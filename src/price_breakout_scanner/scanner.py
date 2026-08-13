from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from .models import Candidate


class ScannerError(RuntimeError):
    """Raised when the database cannot provide scanner results."""


class BreakoutScanner:
    REQUIRED_TABLES = {"symbols", "symbol_analysis", "trade_selections"}

    def __init__(self, database: str | Path):
        self.database = Path(database).expanduser()

    def _connect(self) -> sqlite3.Connection:
        if not self.database.is_file():
            raise ScannerError(f"Database not found: {self.database}")
        try:
            connection = sqlite3.connect(
                f"file:{self.database.resolve()}?mode=ro", uri=True
            )
            connection.row_factory = sqlite3.Row
            return connection
        except sqlite3.Error as exc:
            raise ScannerError(f"Cannot open database: {exc}") from exc

    def validate(self) -> None:
        with self._connect() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        missing = self.REQUIRED_TABLES - tables
        if missing:
            raise ScannerError(
                "Database is missing required tables: " + ", ".join(sorted(missing))
            )

    def available_dates(self, limit: int = 10) -> list[str]:
        if limit < 1:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT date FROM trade_selections "
                "ORDER BY date DESC LIMIT ?",
                (limit,),
            )
            return [str(row[0]) for row in rows]

    def scan(
        self,
        *,
        date: str | None = None,
        min_score: float = 70.0,
        grades: Iterable[str] = ("A", "B"),
        min_dollar_volume: int = 1_000_000,
        require_liquidity: bool = True,
        require_bullish_structure: bool = True,
        archetypes: Iterable[str] = (),
        transitions: Iterable[str] = (),
        symbols: Iterable[str] = (),
        limit: int = 20,
    ) -> tuple[str, list[Candidate]]:
        if limit < 1:
            raise ScannerError("Limit must be at least 1")

        grade_values = tuple(value.upper() for value in grades)
        archetype_values = tuple(archetypes)
        transition_values = tuple(transitions)
        symbol_values = tuple(value.upper() for value in symbols)

        clauses = ["ts.date = ?", "COALESCE(ts.TradeScore, 0) >= ?"]
        parameters: list[object] = []

        with self._connect() as connection:
            if date is None:
                row = connection.execute("SELECT MAX(date) FROM trade_selections").fetchone()
                date = row[0] if row else None
            if not date:
                raise ScannerError("No trade-selection dates are available")

            parameters.extend((date, min_score))
            self._add_in_filter(clauses, parameters, "ts.TradeGrade", grade_values)
            if min_dollar_volume > 0:
                clauses.append("COALESCE(sa.DollarVolume50, 0) >= ?")
                parameters.append(min_dollar_volume)
            if require_liquidity:
                clauses.append("sa.LiquidityPass = 1")
            if require_bullish_structure:
                clauses.append("sa.BullishStructure = '1'")
            self._add_in_filter(clauses, parameters, "sa.Archetype", archetype_values)
            self._add_in_filter(clauses, parameters, "sa.Transition", transition_values)
            self._add_in_filter(clauses, parameters, "UPPER(s.symbol)", symbol_values)
            parameters.append(limit)

            sql = f"""
                SELECT ts.TradeRank AS rank, s.symbol, s.company_name AS company,
                       ts.date, ts.TradeScore AS score, ts.TradeGrade AS grade,
                       sa.Price AS price, sa.Confidence AS confidence,
                       sa.PrimaryRank AS primary_rank,
                       sa.SecondaryRank AS secondary_rank,
                       sa.Transition AS transition, sa.Archetype AS archetype,
                       ts.TradeDescription AS description,
                       sa.DollarVolume50 AS dollar_volume_50,
                       COALESCE(sa.Rank1Ignition, 0) AS rank1_ignition,
                       COALESCE(sa.MomentumRecovering, 0) AS momentum_recovering,
                       COALESCE(sa.PullbackCompleting, 0) AS pullback_completing
                FROM trade_selections AS ts
                JOIN symbol_analysis AS sa ON sa.id = ts.analysis_id
                JOIN symbols AS s ON s.id = ts.symbol_id
                WHERE {' AND '.join(clauses)}
                ORDER BY ts.TradeScore DESC, ts.TradeRank ASC, s.symbol ASC
                LIMIT ?
            """
            try:
                rows = connection.execute(sql, parameters).fetchall()
            except sqlite3.Error as exc:
                raise ScannerError(f"Scan failed: {exc}") from exc

        return str(date), [self._candidate(row) for row in rows]

    @staticmethod
    def _add_in_filter(
        clauses: list[str], parameters: list[object], column: str, values: tuple[str, ...]
    ) -> None:
        if values:
            clauses.append(f"{column} IN ({','.join('?' for _ in values)})")
            parameters.extend(values)

    @staticmethod
    def _candidate(row: sqlite3.Row) -> Candidate:
        values = dict(row)
        for key in ("rank1_ignition", "momentum_recovering", "pullback_completing"):
            values[key] = bool(values[key])
        return Candidate(**values)

