from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from price_breakout_scanner.output import write_export
from price_breakout_scanner.scanner import BreakoutScanner, ScannerError


class BreakoutScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "scanner.db"
        with sqlite3.connect(self.database) as connection:
            connection.executescript(
                """
                CREATE TABLE symbols (
                    id INTEGER PRIMARY KEY, symbol TEXT, company_name TEXT
                );
                CREATE TABLE symbol_analysis (
                    id INTEGER PRIMARY KEY, symbol_id INTEGER, date TEXT,
                    Price REAL, Confidence REAL, PrimaryRank INTEGER,
                    SecondaryRank INTEGER, Transition TEXT, Archetype TEXT,
                    DollarVolume50 INTEGER, LiquidityPass INTEGER,
                    BullishStructure TEXT, Rank1Ignition INTEGER,
                    MomentumRecovering INTEGER, PullbackCompleting INTEGER
                );
                CREATE TABLE trade_selections (
                    id INTEGER PRIMARY KEY, analysis_id INTEGER, symbol_id INTEGER,
                    date TEXT, TradeScore REAL, TradeGrade TEXT, TradeRank INTEGER,
                    TradeDescription TEXT
                );
                INSERT INTO symbols VALUES
                    (1, 'AAA', 'Alpha Inc'), (2, 'BBB', 'Beta Inc'),
                    (3, 'CCC', 'Charlie Inc');
                INSERT INTO symbol_analysis VALUES
                    (10, 1, '2026-08-12', 25, 95, 1, 1, 'IGNITION', 'EXPANSION',
                     50000000, 1, '1', 1, 0, 0),
                    (20, 2, '2026-08-12', 30, 80, 2, 2, 'RECOVERY', 'PULLBACK',
                     40000000, 1, '1', 0, 1, 1),
                    (30, 3, '2026-08-12', 5, 90, 1, 1, 'IGNITION', 'EXPANSION',
                     200000, 0, '1', 1, 0, 0);
                INSERT INTO trade_selections VALUES
                    (100, 10, 1, '2026-08-12', 88, 'A', 1, 'Breakout'),
                    (200, 20, 2, '2026-08-12', 75, 'B', 2, 'Pullback'),
                    (300, 30, 3, '2026-08-12', 90, 'A', 3, 'Illiquid'),
                    (400, 10, 1, '2026-08-11', 60, 'C', 1, 'Old');
                """
            )
        self.scanner = BreakoutScanner(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_scan_uses_latest_date_and_filters_liquidity(self) -> None:
        date, candidates = self.scanner.scan()
        self.assertEqual(date, "2026-08-12")
        self.assertEqual([candidate.symbol for candidate in candidates], ["AAA", "BBB"])
        self.assertTrue(candidates[0].rank1_ignition)

    def test_symbol_and_archetype_filters(self) -> None:
        _, candidates = self.scanner.scan(symbols=["bbb"], archetypes=["PULLBACK"])
        self.assertEqual([candidate.symbol for candidate in candidates], ["BBB"])

    def test_explicit_date_can_return_no_matches(self) -> None:
        date, candidates = self.scanner.scan(date="2026-08-11")
        self.assertEqual(date, "2026-08-11")
        self.assertEqual(candidates, [])

    def test_csv_export(self) -> None:
        _, candidates = self.scanner.scan()
        destination = Path(self.temporary.name) / "output.csv"
        write_export(destination, candidates, "csv")
        with destination.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["symbol"], "AAA")

    def test_missing_database_has_clear_error(self) -> None:
        with self.assertRaisesRegex(ScannerError, "Database not found"):
            BreakoutScanner(Path(self.temporary.name) / "missing.db").validate()


if __name__ == "__main__":
    unittest.main()

