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
    REQUIRED_TABLES = {"symbols"}
    PREFERRED_PRICE_TABLE = "price_history_unadjusted"
    FALLBACK_PRICE_TABLE = "price_history"
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
        if not {self.PREFERRED_PRICE_TABLE, self.FALLBACK_PRICE_TABLE} & tables:
            raise ScannerError("Database is missing a supported price-history table")

    def price_source(self) -> str:
        with closing(self._connect()) as connection:
            return self._price_table(connection)

    def _price_table(self, connection: sqlite3.Connection) -> str:
        tables = self._tables(connection)
        if self.PREFERRED_PRICE_TABLE in tables:
            available = connection.execute(
                f"SELECT EXISTS(SELECT 1 FROM {self.PREFERRED_PRICE_TABLE} LIMIT 1)"
            ).fetchone()[0]
            if available:
                return self.PREFERRED_PRICE_TABLE
        if self.FALLBACK_PRICE_TABLE in tables:
            return self.FALLBACK_PRICE_TABLE
        raise ScannerError("Database is missing a supported price-history table")

    def session_dates(self, limit: int = 10) -> list[tuple[str, int, bool]]:
        """Return recent dates, symbol coverage, and completeness."""
        with closing(self._connect()) as connection:
            price_table = self._price_table(connection)
            rows = connection.execute(
                "SELECT date, COUNT(DISTINCT symbol_id) AS symbols "
                f"FROM {price_table} GROUP BY date ORDER BY date DESC LIMIT ?",
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
            price_table = self._price_table(connection)
            date = date or self.latest_complete_date()
            cutoff = self._history_cutoff(connection, price_table, date)
            histories = self._load_history(
                connection, price_table, cutoff, date, selected_symbols
            )
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

        candidates.sort(
            key=lambda item: (
                self._ranking_priority(item.readiness_state),
                -item.score,
                item.symbol,
            )
        )
        ranked = [candidate.with_rank(index) for index, candidate in enumerate(candidates[:limit], 1)]
        return str(date), ranked

    def _history_cutoff(
        self, connection: sqlite3.Connection, price_table: str, date: str
    ) -> str:
        rows = connection.execute(
            f"SELECT DISTINCT date FROM {price_table} WHERE date <= ? "
            "ORDER BY date DESC LIMIT ?", (date, self.HISTORY_BARS)
        ).fetchall()
        if len(rows) < 60:
            raise ScannerError(f"Insufficient market history through {date}")
        return str(rows[-1][0])

    def _load_history(
        self, connection: sqlite3.Connection, price_table: str,
        cutoff: str, date: str,
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
            FROM {price_table} ph JOIN symbols s ON s.id = ph.symbol_id
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
        # Match the supplied ThinkScript studies used for visual validation.
        macd_trend = indicators.macd_histogram(closes, 24, 52, 9)
        macd_timing = indicators.macd_histogram(closes, 3, 10, 16)
        tmo_series, tmo_signal_series = indicators.chart_tmo(closes, 14, 5, 3)
        squeeze_series, squeeze_on_series, squeeze_count_series = (
            indicators.clean_squeeze_v2(highs, lows, closes, 21, 2.0, 1.5)
        )
        squeeze_released = (
            len(squeeze_on_series) > 1
            and squeeze_on_series[-2]
            and not squeeze_on_series[-1]
        )
        structures = [
            closes[index] > ema20_series[index]
            and ema8_series[index] > ema20_series[index]
            and ema20_series[index] >= ema50_series[index] * 0.98
            for index in range(len(closes))
        ]
        bars_since_di_cross = cls._bars_since_meaningful_di_cross(di_plus, di_minus)
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
        trend_quality_6m, positive_structure_bars = cls._trend_quality_6m(
            closes, ema8_series, ema20_series, ema50_series
        )
        deterioration_flags = cls._deterioration_flags(
            di_plus, di_spread_series, tmo_series, squeeze_series,
            macd_trend, macd_timing,
        )
        structure_state = cls._structure_state(
            closes, ema8_series, ema20_series, ema50_series,
            di_plus, di_minus, adx_series, macd_trend, macd_timing,
            tmo_series, squeeze_series,
        )
        if structure_state == "INTACT" and trend_quality_6m < 50:
            structure_state = "REPAIRING"
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
        if ema_spread < 0.75 and ignition_state not in {"REJECTED", "WEAKENING"}:
            ignition_state = "REPAIRING"
            rejection_reason = "EMA ribbon is still too flat to confirm an upward structure"
        if (
            "DI+ rolled over" in deterioration_flags or len(deterioration_flags) >= 2
        ) and ignition_state in {"CONFIRMED", "PRIMED"}:
            ignition_state = "WEAKENING"
            rejection_reason = "; ".join(deterioration_flags)
        elif deterioration_flags and ignition_state == "CONFIRMED":
            ignition_state = "PRIMED"
            rejection_reason = (
                "; ".join(deterioration_flags)
                + "; awaiting renewed all-lane confirmation"
            )
        market_state = cls._market_state(
            ignition_state, structure_state, extension_state,
            di_plus, di_minus, di_spread_series, adx_series,
        )
        momentum_phase = cls._momentum_phase(
            structure_state, extension_state, bars_since_ignition,
            squeeze_released, di_plus, di_minus, di_spread_series, adx_series,
            tmo_series, squeeze_series, macd_trend, macd_timing,
            runup_60, ema_spread, market_state,
        )
        readiness_state = cls._readiness_state(market_state, momentum_phase)
        score = cls._ignition_score(
            ignition_state, bars_since_di_cross, di_cross_confirmed,
            adx_at_cross, adx_slope, squeeze_series[-1], squeeze_slope, squeeze_turn,
            tmo_series[-1], tmo_signal_series[-1], tmo_slope,
            macd_trend[-1], trend_slope,
            macd_timing[-1], timing_slope, structure_state != "BROKEN", ema_spread,
            move_since_ignition, bars_since_ignition,
            trend_quality_6m, deterioration_flags, di_plus[-1], di_minus[-1],
            di_plus_slope_3, di_spread_slope_3, adx_series[-1], extension_state,
        )
        if market_state == "BROKEN":
            score = 0.0
        elif market_state == "WEAKENING":
            score = min(score, 49.0)
        elif market_state in {"REPAIRING", "REPAIRING_EXTENDED"}:
            score = min(score, 69.0)
        maturity_penalty = cls._maturity_penalty(
            runup_60, ema_spread, bars_since_reset, ignition_state, volume_ratio
        )
        score = max(0.0, score - maturity_penalty * 0.5)
        legacy_score, grade = legacy or (None, None)
        return Candidate(
            rank=None, symbol=symbol, company=clean[-1]["company_name"], date=date,
            score=round(score, 2), setup=ignition_state,
            market_state=market_state, readiness_state=readiness_state,
            momentum_phase=momentum_phase,
            structure_state=structure_state,
            extension_state=extension_state, price=round(close, 2),
            trend_quality_6m_pct=round(trend_quality_6m, 1),
            positive_structure_bars_6m=positive_structure_bars,
            deterioration_flags=", ".join(deterioration_flags) or None,
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
            squeeze_on=squeeze_on_series[-1],
            squeeze_count=squeeze_count_series[-1],
            squeeze_released=squeeze_released,
            tmo=round(tmo_series[-1], 4),
            tmo_signal=round(tmo_signal_series[-1], 4),
            tmo_slope_3d=round(tmo_slope, 4),
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

    @classmethod
    def _bars_since_meaningful_di_cross(
        cls, di_plus: Sequence[float], di_minus: Sequence[float], limit: int = 60
    ) -> int | None:
        """Ignore one-bar DI failures that merely recross inside an active move."""
        first = max(1, len(di_plus) - 1 - limit)
        for index in range(len(di_plus) - 1, first - 1, -1):
            if cls._meaningful_di_cross_at(di_plus, di_minus, index):
                return len(di_plus) - 1 - index
        return None

    @staticmethod
    def _meaningful_di_cross_at(
        di_plus: Sequence[float], di_minus: Sequence[float], index: int
    ) -> bool:
        if index < 1 or not (
            di_plus[index] > di_minus[index]
            and di_plus[index - 1] <= di_minus[index - 1]
        ):
            return False
        prior_start = max(0, index - 5)
        prior = range(prior_start, index)
        # A fresh transition needs actual bearish/neutral control before the
        # cross, not a single marginal DI- tick during an established advance.
        return sum(di_plus[position] <= di_minus[position] for position in prior) >= 3

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
    def _trend_quality_6m(
        closes: Sequence[float], ema8: Sequence[float], ema21: Sequence[float],
        ema50: Sequence[float], bars: int = 126,
    ) -> tuple[float, int]:
        """Summarize every daily bar in roughly six trading months.

        This deliberately rewards persistent, orderly structure instead of
        treating the last bar as if it appeared without a history.
        """
        start = max(1, len(closes) - bars)
        samples = range(start, len(closes))
        aligned = 0
        points = 0.0
        count = max(1, len(closes) - start)
        for index in samples:
            bar_points = sum(
                (
                    closes[index] > ema8[index],
                    ema8[index] > ema21[index],
                    ema21[index] > ema50[index],
                    ema8[index] >= ema8[index - 1],
                    ema21[index] >= ema21[index - 1],
                    ema50[index] >= ema50[index - 1],
                )
            )
            points += bar_points / 6
            if bar_points == 6:
                aligned += 1
        return points / count * 100, aligned

    @staticmethod
    def _deterioration_flags(
        di_plus: Sequence[float], di_spread: Sequence[float],
        tmo: Sequence[float], squeeze: Sequence[float],
        trend: Sequence[float], timing: Sequence[float],
    ) -> list[str]:
        """Describe current loss of slope; a positive value alone is not enough."""
        flags: list[str] = []
        if indicators.slope(di_plus, 1) < 0 and indicators.slope(di_spread, 1) < 0:
            flags.append("DI+ rolled over")
        if indicators.slope(di_plus, 3) <= 0:
            flags.append("DI+ declining 3d")
        if indicators.slope(di_spread, 3) <= 0:
            flags.append("DI spread narrowing")
        if tmo[-1] <= 0 or indicators.slope(tmo, 3) <= 0:
            flags.append("TMO weak")
        if squeeze[-1] <= 0 or indicators.slope(squeeze, 3) <= 0:
            flags.append("squeeze deteriorating")
        if trend[-1] <= 0 or indicators.slope(trend, 3) <= 0:
            flags.append("MACD trend deteriorating")
        if timing[-1] <= 0 or indicators.slope(timing, 3) <= 0:
            flags.append("MACD timing deteriorating")
        elif indicators.slope(timing, 1) < 0:
            flags.append("MACD timing rolled over")
        return flags

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
        if ignition_state == "REPAIRING":
            return "REPAIRING"
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

    @staticmethod
    def _momentum_phase(
        structure_state: str, extension_state: str,
        bars_since_ignition: int | None, squeeze_released: bool,
        di_plus: Sequence[float], di_minus: Sequence[float],
        di_spread: Sequence[float], adx: Sequence[float],
        tmo: Sequence[float], squeeze: Sequence[float],
        trend: Sequence[float], timing: Sequence[float],
        runup_60: float = 0.0, ema8_ema50_spread: float = 0.0,
        market_state: str | None = None,
    ) -> str:
        """Classify the path of the move instead of its latest values alone."""
        if structure_state == "BROKEN" or market_state in {"BROKEN", "WEAKENING"}:
            return "DETERIORATING"
        slopes = (
            indicators.slope(di_plus, 3), indicators.slope(di_spread, 3),
            indicators.slope(tmo, 3), indicators.slope(squeeze, 3),
            indicators.slope(trend, 3), indicators.slope(timing, 3),
        )
        improving = sum(value > 0 for value in slopes)
        weakening = sum(value <= 0 for value in slopes)
        di_control = di_plus[-1] > di_minus[-1]
        di_rollover = (
            indicators.count_declines(di_plus, 3) >= 2
            and indicators.slope(di_plus, 3) < -0.15
            and indicators.slope(di_spread, 3) < -0.15
        )
        energy_rollover = sum(
            indicators.slope(series, 3) <= 0
            for series in (tmo, squeeze, trend, timing)
        )
        if di_rollover and energy_rollover >= 2:
            return "DETERIORATING"
        if extension_state == "EXTENDED":
            return "EXTENDED"
        fresh = bars_since_ignition is not None and bars_since_ignition <= 7
        mature_advance = runup_60 > 25 and ema8_ema50_spread > 6
        adx_constructive = indicators.slope(adx, 3) >= -0.10
        if mature_advance and di_control and improving >= 3:
            return "CONTINUING"
        if (
            structure_state == "INTACT" and fresh and di_control
            and improving >= 4 and (squeeze_released or adx_constructive)
        ):
            return "IGNITING" if market_state in {None, "CONFIRMED"} else "PRIMED"
        if structure_state == "REPAIRING" and di_control and improving >= 4:
            return "PRIMED"
        if structure_state == "REPAIRING":
            return "REPAIRING"
        if di_control and improving >= 4 and extension_state in {"HUGGING_EMA8", "CONTROLLED"}:
            return "PRIMED"
        if di_control and improving >= 3:
            return "CONTINUING"
        if di_control and weakening >= 3:
            return "DIGESTING"
        return "DETERIORATING"

    @staticmethod
    def _readiness_state(market_state: str, momentum_phase: str | None = None) -> str:
        """Put entry readiness in explicit, mutually exclusive review buckets."""
        if momentum_phase is None:
            return {
                "CONFIRMED": "CONFIRMED_NOT_EXTENDED",
                "CONFIRMED_EXTENDED": "CONFIRMED_EXTENDED",
                "PRIMED": "PRIMED_EARLY_EXPANSION",
                "REPAIRING": "REPAIRING_STRUCTURE",
                "REPAIRING_EXTENDED": "REPAIRING_STRUCTURE",
                "WEAKENING": "WATCH_MOMENTUM_NOT_READY",
                "BROKEN": "WATCH_MOMENTUM_NOT_READY",
            }[market_state]
        return {
            "IGNITING": "IGNITING_ENTRY",
            "PRIMED": "PRIMED_ENTRY",
            "CONTINUING": "CONTINUING_NOT_EXTENDED",
            "DIGESTING": "DIGESTING_WAIT",
            "REPAIRING": "REPAIRING_STRUCTURE",
            "EXTENDED": "EXTENDED_WAIT_FOR_RESET",
            "DETERIORATING": "DETERIORATING_NOT_READY",
        }[momentum_phase]

    @staticmethod
    def _ranking_priority(readiness_state: str) -> int:
        """Keep score comparisons inside a readiness bucket, not across buckets."""
        return {
            "IGNITING_ENTRY": 0,
            "PRIMED_ENTRY": 1,
            "CONTINUING_NOT_EXTENDED": 2,
            "DIGESTING_WAIT": 3,
            "REPAIRING_STRUCTURE": 4,
            "EXTENDED_WAIT_FOR_RESET": 5,
            "DETERIORATING_NOT_READY": 6,
            # Keep v1.5.1 labels stable for callers constructing old records.
            "CONFIRMED_NOT_EXTENDED": 0,
            "CONFIRMED_EXTENDED": 5,
            "PRIMED_EARLY_EXPANSION": 1,
            "WATCH_MOMENTUM_NOT_READY": 6,
        }.get(readiness_state, 5)

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
                cls._meaningful_di_cross_at(di_plus, di_minus, cross)
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
        adx_at_cross: float | None, adx_slope: float, squeeze: float, squeeze_slope: float,
        squeeze_turn: bool, tmo: float, tmo_signal: float, tmo_slope: float,
        trend: float,
        trend_slope: float, timing: float, timing_slope: float,
        structure_ok: bool, ema_spread: float, move_since_ignition: float | None,
        bars_since_ignition: int | None,
        trend_quality_6m: float, deterioration_flags: Sequence[str],
        di_plus: float, di_minus: float, di_plus_slope: float,
        di_spread_slope: float, adx: float, extension_state: str,
    ) -> float:
        if state == "REJECTED":
            return 0.0
        # The score is intentionally distributed across structure, DI health,
        # energy confirmation and freshness so no single recent cross can
        # saturate the ranking.
        score = 8.0 if structure_ok else -40.0
        score += min(16.0, trend_quality_6m * 0.16)
        score += 8 if cross_confirmed else -15
        score += 5 if di_plus > di_minus else -15
        score += 4 if di_plus_slope > 0 else -4
        score += 5 if di_spread_slope > 0 else -5
        score += 4 if adx_slope > 0 else 2 if adx_slope >= -0.10 else -3
        score += 3 if adx >= 20 else 2 if adx >= 15 else 1 if adx_slope > 0 else 0
        score += 6 if squeeze_slope > 0 and squeeze > 0 else -3 if squeeze <= 0 else 0
        score += 5 if tmo > 0 and tmo > tmo_signal and tmo_slope > 0 else 2 if tmo > 0 and tmo_slope > 0 else -5 if tmo <= 0 else 0
        score += 7 if trend > 0 and trend_slope > 0 else -5 if trend <= 0 else 0
        score += 7 if timing > 0 and timing_slope > 0 else -5 if timing <= 0 else 0
        score += {"CONFIRMED": 8, "PRIMED": 6, "REPAIRING": 2,
                  "EXTENDED": 2, "WEAKENING": -8}.get(state, 0)
        if bars_since_ignition is not None:
            score += 6 if bars_since_ignition <= 7 else 4 if bars_since_ignition <= 12 else 1
        if bars_since_cross is not None:
            score += 4 if bars_since_cross <= 7 else 2 if bars_since_cross <= 12 else 0
        score += 3 if ema_spread <= 6 else 1 if ema_spread <= 9 else -5
        score -= 4 * len(deterioration_flags)
        if extension_state == "HUGGING_EMA8":
            score += 3
        elif extension_state == "EXTENDED":
            score -= 10
        if move_since_ignition is not None and move_since_ignition > 20:
            score -= 15
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
