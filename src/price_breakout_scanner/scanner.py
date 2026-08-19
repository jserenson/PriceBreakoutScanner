from __future__ import annotations

import math
import sqlite3
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from contextlib import closing
from pathlib import Path

from . import indicators
from .models import Candidate


class ScannerError(RuntimeError):
    """Raised when the database cannot provide scanner results."""


class BreakoutScanner:
    REQUIRED_TABLES = {"symbols", "price_history"}
    HISTORY_BARS = 180
    COMPLETE_COVERAGE = 0.95

    def __init__(self, database: str | Path):
        self.database = Path(database).expanduser()

    def _connect(self) -> sqlite3.Connection:
        if not self.database.is_file():
            raise ScannerError(f"Database not found: {self.database}")
        try:
            connection = sqlite3.connect(
                f"file:{self.database.resolve()}?mode=ro", uri=True, timeout=30
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            return connection
        except sqlite3.Error as exc:
            raise ScannerError(f"Cannot open database: {exc}") from exc

    def validate(self) -> None:
        with closing(self._connect()) as connection:
            tables = self._tables(connection)
        missing = self.REQUIRED_TABLES - tables
        if missing:
            raise ScannerError(
                "Database is missing required tables: " + ", ".join(sorted(missing))
            )

    def session_dates(self, limit: int = 10) -> list[tuple[str, int, bool]]:
        """Return recent dates, symbol coverage, and completeness."""
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT date, COUNT(DISTINCT symbol_id) AS symbols "
                "FROM price_history GROUP BY date ORDER BY date DESC LIMIT ?",
                (max(limit + 10, 20),),
            ).fetchall()
        if not rows:
            return []
        baseline_counts = [int(row["symbols"]) for row in rows[1:11]] or [int(rows[0]["symbols"])]
        baseline = statistics.median(baseline_counts)
        threshold = baseline * self.COMPLETE_COVERAGE
        return [
            (str(row["date"]), int(row["symbols"]), int(row["symbols"]) >= threshold)
            for row in rows[:limit]
        ]

    def available_dates(self, limit: int = 10) -> list[str]:
        return [date for date, _, complete in self.session_dates(limit + 5) if complete][:limit]

    def latest_complete_date(self) -> str:
        sessions = self.session_dates(20)
        for date, _, complete in sessions:
            if complete:
                return date
        raise ScannerError("No complete price-history session is available")

    def scan(
        self,
        *,
        date: str | None = None,
        min_score: float = 55.0,
        grades: Iterable[str] = (),
        min_dollar_volume: int = 1_000_000,
        require_liquidity: bool = True,
        require_bullish_structure: bool = False,
        archetypes: Iterable[str] = (),
        transitions: Iterable[str] = (),
        symbols: Iterable[str] = (),
        limit: int = 20,
    ) -> tuple[str, list[Candidate]]:
        """Rank price-action setups; legacy arguments remain CLI-compatible.

        `grades` is the only legacy argument that filters results. Archetype,
        transition, and bullish-structure flags are accepted for v1 CLI
        compatibility but intentionally do not drive the price-action model.
        """
        del require_bullish_structure, archetypes, transitions
        if limit < 1:
            raise ScannerError("Limit must be at least 1")
        selected_symbols = tuple(sorted({value.upper() for value in symbols}))
        grade_values = tuple(sorted({value.upper() for value in grades}))

        with closing(self._connect()) as connection:
            date = date or self.latest_complete_date()
            cutoff = self._history_cutoff(connection, date)
            histories = self._load_history(connection, cutoff, date, selected_symbols)
            legacy = self._load_legacy(connection, date)
            stored_stages = self._load_stages(connection, date)

        candidates: list[Candidate] = []
        for symbol, bars in histories.items():
            candidate = self._analyze(symbol, bars, date, legacy.get(symbol), stored_stages.get(symbol))
            if candidate is None or candidate.score < min_score:
                continue
            if require_liquidity and candidate.dollar_volume_20d < min_dollar_volume:
                continue
            if grade_values and (candidate.grade or "").upper() not in grade_values:
                continue
            candidates.append(candidate)

        candidates.sort(key=lambda item: (-item.score, item.symbol))
        ranked = [candidate.with_rank(index) for index, candidate in enumerate(candidates[:limit], 1)]
        return str(date), ranked

    def _history_cutoff(self, connection: sqlite3.Connection, date: str) -> str:
        rows = connection.execute(
            "SELECT DISTINCT date FROM price_history WHERE date <= ? "
            "ORDER BY date DESC LIMIT ?", (date, self.HISTORY_BARS)
        ).fetchall()
        if len(rows) < 60:
            raise ScannerError(f"Insufficient market history through {date}")
        return str(rows[-1][0])

    def _load_history(
        self, connection: sqlite3.Connection, cutoff: str, date: str,
        symbols: tuple[str, ...],
    ) -> dict[str, list[sqlite3.Row]]:
        clauses = ["ph.date BETWEEN ? AND ?", "s.active = 1"]
        parameters: list[object] = [cutoff, date]
        if symbols:
            clauses.append(f"UPPER(s.symbol) IN ({','.join('?' for _ in symbols)})")
            parameters.extend(symbols)
        rows = connection.execute(
            f"""
            SELECT s.symbol, s.company_name, ph.date, ph.open, ph.high, ph.low,
                   ph.close, ph.volume
            FROM price_history ph JOIN symbols s ON s.id = ph.symbol_id
            WHERE {' AND '.join(clauses)}
            ORDER BY s.symbol, ph.date
            """, parameters
        )
        histories: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            histories[str(row["symbol"])].append(row)
        return histories

    def _load_legacy(self, connection: sqlite3.Connection, date: str) -> dict[str, tuple[float | None, str | None]]:
        if not {"trade_selections", "symbol_analysis"}.issubset(self._tables(connection)):
            return {}
        rows = connection.execute(
            """
            SELECT s.symbol, ts.TradeScore, ts.TradeGrade
            FROM trade_selections ts JOIN symbols s ON s.id=ts.symbol_id
            WHERE ts.date=?
            """, (date,)
        )
        return {str(row[0]): (row[1], row[2]) for row in rows}

    def _load_stages(self, connection: sqlite3.Connection, date: str) -> dict[str, int]:
        if "weinstein_stages" not in self._tables(connection):
            return {}
        rows = connection.execute(
            """
            SELECT symbol, stage FROM weinstein_stages ws
            WHERE date=(SELECT MAX(date) FROM weinstein_stages WHERE date<=?)
            """, (date,)
        )
        return {str(row[0]): int(row[1]) for row in rows if row[1] is not None}

    @classmethod
    def _analyze(
        cls, symbol: str, bars: Sequence[sqlite3.Row], date: str,
        legacy: tuple[float | None, str | None] | None,
        stored_stage: int | None,
    ) -> Candidate | None:
        clean = [bar for bar in bars if all(bar[key] is not None for key in ("high", "low", "close", "volume"))]
        if len(clean) < 160 or str(clean[-1]["date"]) != date:
            return None
        closes = [float(bar["close"]) for bar in clean]
        highs = [float(bar["high"]) for bar in clean]
        lows = [float(bar["low"]) for bar in clean]
        volumes = [float(bar["volume"]) for bar in clean]
        close = closes[-1]
        if close <= 0:
            return None

        resistance = max(highs[-21:-1])
        breakout_pct = cls._pct(close, resistance)
        distance = cls._pct(resistance, close)
        range_10 = cls._range_pct(highs[-10:], lows[-10:], close)
        range_40 = cls._range_pct(highs[-40:], lows[-40:], close)
        tightening = range_10 / range_40 if range_40 else 1.0
        prior_low = min(lows[-20:-10])
        recent_low = min(lows[-10:])
        higher_low = cls._pct(recent_low, prior_low)
        avg_volume_20 = statistics.fmean(volumes[-21:-1])
        avg_volume_5 = statistics.fmean(volumes[-6:-1])
        volume_ratio = volumes[-1] / avg_volume_20 if avg_volume_20 else 0.0
        contraction = avg_volume_5 / avg_volume_20 if avg_volume_20 else 0.0
        momentum_5 = cls._pct(close, closes[-6])
        momentum_20 = cls._pct(close, closes[-21])
        sma20 = statistics.fmean(closes[-20:])
        sma50 = statistics.fmean(closes[-50:])
        sma150 = statistics.fmean(closes[-150:])
        prior_sma150 = statistics.fmean(closes[-170:-20])
        stage_slope = cls._pct(sma150, prior_sma150)
        computed_stage = cls._weinstein_stage(close, sma150, stage_slope)
        stage = stored_stage or computed_stage
        stage_source = "stored" if stored_stage is not None else "computed"
        extension = cls._pct(close, sma20)
        ema8_series = cls._ema(closes, 8)
        ema20_series = cls._ema(closes, 21)
        ema50_series = cls._ema(closes, 50)
        ema_spread = cls._pct(ema8_series[-1], ema50_series[-1])
        price_ema8_distance = cls._pct(close, ema8_series[-1])
        price_ema21_distance = cls._pct(close, ema20_series[-1])
        price_ema50_distance = cls._pct(close, ema50_series[-1])
        ema8_ema21_spread = cls._pct(ema8_series[-1], ema20_series[-1])
        runup_60 = cls._pct(close, min(lows[-60:]))
        bars_since_reset = cls._bars_since_reset(closes, ema8_series, ema20_series, ema50_series)
        dollar_volume = int(close * statistics.fmean(volumes[-20:]))

        di_plus, di_minus, adx_series = indicators.dmi_adx(highs, lows, closes)
        atr_series = indicators.average_true_range(highs, lows, closes)
        price_ema8_atr = (close - ema8_series[-1]) / atr_series[-1] if atr_series[-1] else 0.0
        di_spread_series = [plus - minus for plus, minus in zip(di_plus, di_minus)]
        di_plus_slope_3 = indicators.slope(di_plus, 3)
        di_plus_slope_5 = indicators.slope(di_plus, 5)
        di_minus_slope_3 = indicators.slope(di_minus, 3)
        di_minus_slope_5 = indicators.slope(di_minus, 5)
        di_spread_slope_3 = indicators.slope(di_spread_series, 3)
        di_spread_slope_5 = indicators.slope(di_spread_series, 5)
        macd_trend = indicators.macd_histogram(closes, 12, 26, 9)
        macd_timing = indicators.macd_histogram(closes, 5, 13, 4)
        tmo_series = indicators.true_momentum(closes)
        squeeze_series = indicators.squeeze_momentum(highs, lows, closes)
        structures = [
            closes[index] > ema20_series[index]
            and ema8_series[index] > ema20_series[index]
            and ema20_series[index] >= ema50_series[index] * 0.98
            for index in range(len(closes))
        ]
        bars_since_di_cross = indicators.bars_since_cross(di_plus, di_minus)
        di_cross_confirmed = cls._di_cross_confirmed(di_plus, di_minus, bars_since_di_cross)
        bars_since_structure = cls._bars_since_transition(structures)
        bars_since_ignition = cls._bars_since_synchronized_ignition(
            closes, ema8_series, structures, di_plus, di_minus,
            macd_trend, macd_timing, tmo_series, squeeze_series,
        )
        move_since_ignition = (
            cls._pct(close, closes[-1 - bars_since_ignition])
            if bars_since_ignition is not None else None
        )
        adx_at_cross = (
            adx_series[-1 - bars_since_di_cross]
            if bars_since_di_cross is not None else None
        )
        adx_slope = indicators.slope(adx_series, 5)
        squeeze_slope = indicators.slope(squeeze_series, 3)
        squeeze_turn = indicators.recent_slope_turn(squeeze_series)
        tmo_slope = indicators.slope(tmo_series, 3)
        trend_slope = indicators.slope(macd_trend, 3)
        timing_slope = indicators.slope(macd_timing, 3)
        structure_state = cls._structure_state(
            closes, ema8_series, ema20_series, ema50_series,
            di_plus, di_minus, adx_series, macd_trend, macd_timing,
            tmo_series, squeeze_series,
        )
        extension_state = cls._extension_state(
            price_ema8_distance, price_ema21_distance, price_ema8_atr,
            ema8_series, ema20_series,
        )
        adx_state = cls._adx_state(adx_series)
        energy_lanes = sum(
            (
                adx_slope > 0,
                squeeze_slope > 0,
                tmo_slope > 0,
                macd_trend[-1] > 0 and trend_slope > 0,
                macd_timing[-1] > 0 and timing_slope > 0,
            )
        )
        macd_improving = (
            macd_trend[-1] > 0 and trend_slope > 0
        ) or (
            macd_timing[-1] > 0 and timing_slope > 0
        )
        ignition_state, rejection_reason = cls._ignition_state(
            structure_state, extension_state, bars_since_di_cross, di_cross_confirmed,
            bars_since_ignition, move_since_ignition, ema_spread,
            ema8_series, ema20_series, energy_lanes, macd_improving,
            di_plus, di_minus, di_spread_series, adx_series,
        )
        market_state = cls._market_state(
            ignition_state, structure_state, extension_state,
            di_plus, di_minus, di_spread_series, adx_series,
        )
        score = cls._ignition_score(
            ignition_state, bars_since_di_cross, di_cross_confirmed,
            adx_at_cross, adx_slope, squeeze_slope, squeeze_turn,
            tmo_series[-1], tmo_slope, macd_trend[-1], trend_slope,
            macd_timing[-1], timing_slope, structure_state != "BROKEN", ema_spread,
            move_since_ignition, bars_since_ignition,
        )
        maturity_penalty = cls._maturity_penalty(
            runup_60, ema_spread, bars_since_reset, ignition_state, volume_ratio
        )
        legacy_score, grade = legacy or (None, None)
        return Candidate(
            rank=None, symbol=symbol, company=clean[-1]["company_name"], date=date,
            score=round(score, 2), setup=ignition_state,
            market_state=market_state, structure_state=structure_state,
            extension_state=extension_state, price=round(close, 2),
            resistance=round(resistance, 2), distance_to_resistance_pct=round(distance, 2),
            breakout_pct=round(breakout_pct, 2), range_10d_pct=round(range_10, 2),
            tightening_ratio=round(tightening, 3), higher_low_pct=round(higher_low, 2),
            volume_ratio=round(volume_ratio, 2), volume_contraction_ratio=round(contraction, 2),
            momentum_5d_pct=round(momentum_5, 2), momentum_20d_pct=round(momentum_20, 2),
            extension_20d_pct=round(extension, 2), runup_60d_pct=round(runup_60, 2),
            ema8_ema50_spread_pct=round(ema_spread, 2),
            price_ema8_distance_pct=round(price_ema8_distance, 2),
            price_ema21_distance_pct=round(price_ema21_distance, 2),
            price_ema50_distance_pct=round(price_ema50_distance, 2),
            price_ema8_distance_atr=round(price_ema8_atr, 2),
            ema8_ema21_spread_pct=round(ema8_ema21_spread, 2),
            bars_since_reset=bars_since_reset,
            maturity_penalty=round(maturity_penalty, 2), ignition_state=ignition_state,
            bars_since_di_cross=bars_since_di_cross, di_cross_confirmed=di_cross_confirmed,
            di_plus=round(di_plus[-1], 2), di_minus=round(di_minus[-1], 2),
            di_plus_slope_3d=round(di_plus_slope_3, 3),
            di_plus_slope_5d=round(di_plus_slope_5, 3),
            di_minus_slope_3d=round(di_minus_slope_3, 3),
            di_minus_slope_5d=round(di_minus_slope_5, 3),
            di_spread=round(di_spread_series[-1], 2),
            di_spread_slope_3d=round(di_spread_slope_3, 3),
            di_spread_slope_5d=round(di_spread_slope_5, 3),
            adx=round(adx_series[-1], 2), adx_slope_5d=round(adx_slope, 3),
            adx_state=adx_state,
            adx_at_cross=round(adx_at_cross, 2) if adx_at_cross is not None else None,
            squeeze_momentum=round(squeeze_series[-1], 3),
            squeeze_slope_3d=round(squeeze_slope, 3), squeeze_recent_turn=squeeze_turn,
            tmo=round(tmo_series[-1], 2), tmo_slope_3d=round(tmo_slope, 3),
            macd_trend_hist=round(macd_trend[-1], 4),
            macd_trend_slope_3d=round(trend_slope, 4),
            macd_timing_hist=round(macd_timing[-1], 4),
            macd_timing_slope_3d=round(timing_slope, 4),
            bars_since_structure_restored=bars_since_structure,
            bars_since_ignition=bars_since_ignition,
            move_since_ignition_pct=round(move_since_ignition, 2) if move_since_ignition is not None else None,
            event_risk="UNKNOWN", rejection_reason=rejection_reason,
            weinstein_stage=stage,
            stage_source=stage_source, dollar_volume_20d=dollar_volume,
            legacy_score=round(float(legacy_score), 2) if legacy_score is not None else None,
            grade=str(grade) if grade is not None else None,
        )

    @staticmethod
    def _di_cross_confirmed(
        di_plus: Sequence[float], di_minus: Sequence[float], bars_since_cross: int | None
    ) -> bool:
        if bars_since_cross is None or not di_plus[-1] > di_minus[-1]:
            return False
        start = len(di_plus) - 1 - bars_since_cross
        observations = [di_plus[index] > di_minus[index] for index in range(start, len(di_plus))]
        recent = observations[-min(3, len(observations)) :]
        return all(recent) and sum(observations) / len(observations) >= 0.70

    @staticmethod
    def _bars_since_transition(states: Sequence[bool], limit: int = 60) -> int | None:
        for bars_ago in range(0, min(limit, len(states) - 1) + 1):
            index = len(states) - 1 - bars_ago
            if states[index] and (index == 0 or not states[index - 1]):
                return bars_ago
        return None

    @staticmethod
    def _structure_state(
        closes: Sequence[float], ema8: Sequence[float], ema21: Sequence[float],
        ema50: Sequence[float], di_plus: Sequence[float], di_minus: Sequence[float],
        adx: Sequence[float], trend: Sequence[float], timing: Sequence[float],
        tmo: Sequence[float], squeeze: Sequence[float],
    ) -> str:
        """Classify intact structure and synchronized repair without a Boolean cliff."""
        intact = (
            closes[-1] > ema8[-1] > ema21[-1] >= ema50[-1]
            and indicators.slope(ema21, 5) >= 0
            and indicators.slope(ema50, 10) >= 0
        )
        if intact:
            return "INTACT"
        repair_signals = sum(
            (
                closes[-1] > ema8[-1],
                closes[-1] > ema21[-1],
                ema8[-1] > ema21[-1],
                indicators.slope(ema8, 3) > 0,
                indicators.slope(ema21, 5) >= 0,
                ema21[-1] >= ema50[-1] * 0.98,
                di_plus[-1] > di_minus[-1] and indicators.slope(di_plus, 3) > 0,
                indicators.slope(di_minus, 3) < 0,
                indicators.slope(adx, 3) >= -0.10,
                tmo[-1] > 0 and indicators.slope(tmo, 3) > 0,
                trend[-1] > 0 and indicators.slope(trend, 3) > 0,
                timing[-1] > 0 and indicators.slope(timing, 3) > 0,
                indicators.slope(squeeze, 3) > 0,
            )
        )
        return "REPAIRING" if repair_signals >= 8 else "BROKEN"

    @staticmethod
    def _extension_state(
        price_ema8_pct: float, price_ema21_pct: float, price_ema8_atr: float,
        ema8: Sequence[float], ema21: Sequence[float],
    ) -> str:
        if price_ema8_pct < -1 or price_ema21_pct < -2:
            return "BELOW_RIBBON"
        if price_ema8_atr >= 1.75 or price_ema8_pct >= 6 or price_ema21_pct >= 10:
            return "EXTENDED"
        if price_ema8_atr <= 0.65 and abs(price_ema8_pct) <= 2.5:
            return "HUGGING_EMA8"
        if indicators.slope(ema8, 3) > 0 and indicators.slope(ema21, 5) >= 0:
            return "CONTROLLED"
        return "NEUTRAL"

    @staticmethod
    def _adx_state(adx: Sequence[float]) -> str:
        slope_1 = indicators.slope(adx, 1)
        slope_3 = indicators.slope(adx, 3)
        slope_5 = indicators.slope(adx, 5)
        if slope_3 > 0.10 and slope_5 > 0:
            return "RISING"
        if abs(slope_3) <= 0.10 or (slope_5 < 0 and slope_1 >= 0):
            return "FLATTENING"
        return "FALLING" if slope_3 < 0 else "TURNING_UP"

    @staticmethod
    def _market_state(
        ignition_state: str, structure_state: str, extension_state: str,
        di_plus: Sequence[float], di_minus: Sequence[float],
        di_spread: Sequence[float], adx: Sequence[float],
    ) -> str:
        if ignition_state == "REJECTED":
            return "BROKEN"
        if ignition_state == "WEAKENING":
            return "WEAKENING"
        if extension_state == "EXTENDED":
            return "CONFIRMED_EXTENDED" if structure_state == "INTACT" else "REPAIRING_EXTENDED"
        if structure_state == "REPAIRING":
            return "PRIMED" if ignition_state == "PRIMED" else "REPAIRING"
        if (
            di_plus[-1] > di_minus[-1]
            and indicators.slope(di_spread, 3) > 0
            and indicators.slope(adx, 3) >= -0.10
        ):
            return "CONFIRMED" if ignition_state == "CONFIRMED" else "PRIMED"
        return "WEAKENING"

    @classmethod
    def _bars_since_synchronized_ignition(
        cls, closes: Sequence[float], ema8: Sequence[float], structures: Sequence[bool],
        di_plus: Sequence[float], di_minus: Sequence[float], trend: Sequence[float],
        timing: Sequence[float], tmo: Sequence[float], squeeze: Sequence[float],
        limit: int = 60,
    ) -> int | None:
        first_index = max(6, len(closes) - 1 - limit)
        for index in range(len(closes) - 1, first_index - 1, -1):
            recent_cross = any(
                di_plus[cross] > di_minus[cross]
                and di_plus[cross - 1] <= di_minus[cross - 1]
                for cross in range(max(1, index - 5), index + 1)
            )
            confirmations = sum(
                (
                    closes[index] > ema8[index],
                    trend[index] > 0 and indicators.slope(trend, 3, index) > 0,
                    timing[index] > 0 and indicators.slope(timing, 3, index) > 0,
                    indicators.slope(tmo, 3, index) > 0,
                    indicators.slope(squeeze, 3, index) > 0,
                )
            )
            if recent_cross and structures[index] and confirmations >= 4:
                return len(closes) - 1 - index
        return None

    @staticmethod
    def _ignition_state(
        structure_state: str, extension_state: str,
        bars_since_cross: int | None, cross_confirmed: bool,
        bars_since_ignition: int | None, move_since_ignition: float | None,
        ema_spread: float, ema8: Sequence[float], ema20: Sequence[float],
        energy_lanes: int, macd_improving: bool,
        di_plus: Sequence[float], di_minus: Sequence[float],
        di_spread: Sequence[float], adx: Sequence[float],
    ) -> tuple[str, str | None]:
        di_improving = (
            di_plus[-1] > di_minus[-1]
            and indicators.slope(di_plus, 3) > 0
            and indicators.slope(di_plus, 5) >= 0
            and indicators.slope(di_spread, 3) > 0
            and indicators.slope(di_spread, 5) > 0
            and indicators.count_declines(di_plus, 3) < 2
        )
        adx_constructive = indicators.slope(adx, 3) >= -0.10 or indicators.slope(adx, 1) > 0
        if structure_state == "BROKEN":
            return "REJECTED", "structure broken with no synchronized repair"
        if bars_since_cross is not None and bars_since_cross <= 10 and not cross_confirmed:
            return "REJECTED", "unconfirmed DI+ cross"
        if bars_since_ignition is not None and bars_since_ignition > 30:
            return "REJECTED", "stale ignition"
        if move_since_ignition is not None and move_since_ignition > 20:
            return "EXTENDED", "move mature; wait for EMA8/EMA21 reset"
        if extension_state == "EXTENDED":
            return "EXTENDED", "strong structure but price is stretched above its EMA ribbon"
        if structure_state == "REPAIRING":
            if di_improving and adx_constructive and energy_lanes >= 3:
                return "PRIMED", "structure repair is synchronizing but EMA50 confirmation is incomplete"
            return "REPAIRING", "structure is improving; awaiting wider momentum confirmation"
        if not di_improving:
            return "WEAKENING", "DI+ slope or DI spread has deteriorated"
        if (
            bars_since_ignition is not None and bars_since_ignition <= 12
            and cross_confirmed and ema_spread <= 8
            and energy_lanes >= 3 and macd_improving
            and indicators.slope(adx, 3) > 0.10
        ):
            return "CONFIRMED", None
        if bars_since_ignition is not None and bars_since_ignition <= 12:
            return "PRIMED", "recent ignition is awaiting full multi-lane confirmation"
        if (
            bars_since_ignition is not None and bars_since_ignition <= 30
            and cross_confirmed and ema_spread <= 10
            and indicators.slope(adx, 3) > 0.10
        ):
            return "CONFIRMED", None
        return "PRIMED", "bullish structure and DI trajectory are present without synchronized ignition"

    @staticmethod
    def _ignition_score(
        state: str, bars_since_cross: int | None, cross_confirmed: bool,
        adx_at_cross: float | None, adx_slope: float, squeeze_slope: float,
        squeeze_turn: bool, tmo: float, tmo_slope: float, trend: float,
        trend_slope: float, timing: float, timing_slope: float,
        structure_ok: bool, ema_spread: float, move_since_ignition: float | None,
        bars_since_ignition: int | None,
    ) -> float:
        if state == "REJECTED":
            return 0.0
        score = 0.0
        score += {
            "CONFIRMED": 16,
            "PRIMED": 13,
            "REPAIRING": 8,
            "EXTENDED": 5,
            "WEAKENING": -10,
        }.get(state, 0)
        if bars_since_ignition is not None:
            score += 22 if bars_since_ignition <= 3 else 18 if bars_since_ignition <= 7 else 14 if bars_since_ignition <= 12 else 8
        if bars_since_cross is not None:
            score += 10 if bars_since_cross <= 3 else 8 if bars_since_cross <= 7 else 5 if bars_since_cross <= 12 else 0
        score += 5 if cross_confirmed else -20
        if adx_at_cross is not None:
            score += 4 if adx_at_cross < 20 else 3 if adx_at_cross <= 30 else 0 if adx_at_cross <= 40 else -3
        score += 3 if adx_slope > 0 else 0
        score += 5 if squeeze_slope > 0 else 0
        score += 2 if squeeze_turn else 0
        score += 4 if tmo_slope > 0 else 0
        score += 2 if -20 <= tmo <= 70 else -2 if tmo > 85 else 0
        score += 4 if trend > 0 and trend_slope > 0 else 0
        score += 4 if timing > 0 and timing_slope > 0 else 0
        score += 2 if trend > 0 and timing > 0 else 0
        score += 8 if structure_ok else -40
        score += 6 if ema_spread <= 4 else 4 if ema_spread <= 6 else 0 if ema_spread <= 9 else -6
        if move_since_ignition is not None:
            score += 6 if move_since_ignition <= 5 else 3 if move_since_ignition <= 12 else 0 if move_since_ignition <= 20 else -20
        if state == "WEAKENING":
            score = min(score, 49)
        elif state == "REPAIRING":
            score = min(score, 69)
        elif state == "PRIMED":
            score = min(score, 84)
        elif state == "EXTENDED":
            score = min(score, 74)
        return max(0.0, min(100.0, score))

    @staticmethod
    def _score(
        range_10: float, tightening: float, higher_low: float,
        distance: float, breakout: float, volume_ratio: float, contraction: float,
        momentum_5: float, momentum_20: float, above_sma20: bool,
        sma20_above_sma50: bool, stage: int, extension: float,
    ) -> float:
        score = 0.0
        score += 12 if tightening <= 0.55 else 8 if tightening <= 0.75 else 4 if tightening <= 1.0 else 0
        score += 8 if range_10 <= 8 else 5 if range_10 <= 12 else 2 if range_10 <= 18 else 0
        score += 15 if higher_low >= 0 else 8 if higher_low >= -2 else 0
        if 0 <= breakout <= 5:
            score += 20
        elif 0 <= distance <= 3:
            score += 18
        elif distance <= 7:
            score += 12
        elif distance <= 12:
            score += 5
        score += 15 if volume_ratio >= 1.5 else 11 if volume_ratio >= 1.2 else 10 if contraction <= 0.75 else 7 if contraction <= 0.9 else 2
        score += 8 if momentum_5 > 0 and momentum_5 > momentum_20 / 4 else 4 if momentum_5 > 0 else 0
        score += 4 if above_sma20 else 0
        score += 3 if sma20_above_sma50 else 0
        score += {1: 8, 2: 15, 3: 2, 4: -5}.get(stage, 0)
        if extension > 15:
            score -= 15
        elif extension > 10:
            score -= 10
        elif extension > 7:
            score -= 5
        if breakout > 8:
            score -= 10
        return max(0.0, min(100.0, score))

    @staticmethod
    def _maturity_penalty(
        runup_60: float, ema_spread: float, bars_since_reset: int | None,
        setup: str, volume_ratio: float,
    ) -> float:
        """Penalize mature trends while retaining confirmed breakouts for review."""
        penalty = 22 if runup_60 > 50 else 15 if runup_60 > 35 else 8 if runup_60 > 25 else 0
        penalty += 18 if ema_spread > 12 else 12 if ema_spread > 9 else 6 if ema_spread > 6 else 0
        if bars_since_reset is None or bars_since_reset > 40:
            penalty += 12
        elif bars_since_reset > 25:
            penalty += 8
        if setup != "BREAKOUT" and runup_60 > 30 and ema_spread > 9:
            penalty += 10
        if setup == "BREAKOUT" and volume_ratio >= 1.2:
            penalty = min(penalty, 20)
        return float(penalty)

    @staticmethod
    def _ema(values: Sequence[float], period: int) -> list[float]:
        alpha = 2 / (period + 1)
        result = [values[0]]
        for value in values[1:]:
            result.append(alpha * value + (1 - alpha) * result[-1])
        return result

    @classmethod
    def _bars_since_reset(
        cls, closes: Sequence[float], ema8: Sequence[float],
        ema20: Sequence[float], ema50: Sequence[float],
    ) -> int | None:
        """Bars since price and the fast EMA ribbon last compressed near trend."""
        for bars_ago in range(0, min(61, len(closes))):
            index = len(closes) - 1 - bars_ago
            spread = cls._pct(ema8[index], ema50[index])
            if closes[index] <= ema20[index] * 1.02 and spread <= 6:
                return bars_ago
        return None

    @staticmethod
    def _setup_label(distance: float, breakout: float, volume: float, tightening: float, range_10: float) -> str:
        if 0 <= breakout <= 5 and volume >= 1.2:
            return "BREAKOUT"
        if 0 <= distance <= 3:
            return "READY"
        if tightening <= 0.75 and range_10 <= 12:
            return "TIGHTENING"
        return "WATCH"

    @staticmethod
    def _weinstein_stage(close: float, sma150: float, slope: float) -> int:
        distance = BreakoutScanner._pct(close, sma150)
        if close > sma150 and slope > 1:
            return 2
        if abs(slope) <= 2 and abs(distance) <= 10:
            return 1
        if close >= sma150:
            return 3
        return 4

    @staticmethod
    def _range_pct(highs: Sequence[float], lows: Sequence[float], close: float) -> float:
        return (max(highs) - min(lows)) / close * 100 if close else math.inf

    @staticmethod
    def _pct(current: float, prior: float) -> float:
        return (current / prior - 1) * 100 if prior else 0.0

    @staticmethod
    def _tables(connection: sqlite3.Connection) -> set[str]:
        return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
