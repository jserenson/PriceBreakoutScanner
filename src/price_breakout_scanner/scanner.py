from __future__ import annotations

import math
import sqlite3
import statistics
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path

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
        with self._connect() as connection:
            tables = self._tables(connection)
        missing = self.REQUIRED_TABLES - tables
        if missing:
            raise ScannerError(
                "Database is missing required tables: " + ", ".join(sorted(missing))
            )

    def session_dates(self, limit: int = 10) -> list[tuple[str, int, bool]]:
        """Return recent dates, symbol coverage, and completeness."""
        with self._connect() as connection:
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

        with self._connect() as connection:
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
        ema20_series = cls._ema(closes, 20)
        ema50_series = cls._ema(closes, 50)
        ema_spread = cls._pct(ema8_series[-1], ema50_series[-1])
        runup_60 = cls._pct(close, min(lows[-60:]))
        bars_since_reset = cls._bars_since_reset(closes, ema8_series, ema20_series, ema50_series)
        dollar_volume = int(close * statistics.fmean(volumes[-20:]))

        setup = cls._setup_label(distance, breakout_pct, volume_ratio, tightening, range_10)
        raw_score = cls._score(
            range_10, tightening, higher_low, distance, breakout_pct,
            volume_ratio, contraction, momentum_5, momentum_20,
            close > sma20, sma20 > sma50, stage, extension,
        )
        maturity_penalty = cls._maturity_penalty(
            runup_60, ema_spread, bars_since_reset, setup, volume_ratio
        )
        score = max(0.0, raw_score - maturity_penalty)
        legacy_score, grade = legacy or (None, None)
        return Candidate(
            rank=None, symbol=symbol, company=clean[-1]["company_name"], date=date,
            score=round(score, 2), setup=setup, price=round(close, 2),
            resistance=round(resistance, 2), distance_to_resistance_pct=round(distance, 2),
            breakout_pct=round(breakout_pct, 2), range_10d_pct=round(range_10, 2),
            tightening_ratio=round(tightening, 3), higher_low_pct=round(higher_low, 2),
            volume_ratio=round(volume_ratio, 2), volume_contraction_ratio=round(contraction, 2),
            momentum_5d_pct=round(momentum_5, 2), momentum_20d_pct=round(momentum_20, 2),
            extension_20d_pct=round(extension, 2), runup_60d_pct=round(runup_60, 2),
            ema8_ema50_spread_pct=round(ema_spread, 2), bars_since_reset=bars_since_reset,
            maturity_penalty=round(maturity_penalty, 2), weinstein_stage=stage,
            stage_source=stage_source, dollar_volume_20d=dollar_volume,
            legacy_score=round(float(legacy_score), 2) if legacy_score is not None else None,
            grade=str(grade) if grade is not None else None,
        )

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
