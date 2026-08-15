from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
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
                    id INTEGER PRIMARY KEY, symbol TEXT, company_name TEXT, active INTEGER
                );
                CREATE TABLE price_history (
                    symbol_id INTEGER, date TEXT, open REAL, high REAL, low REAL,
                    close REAL, volume INTEGER
                );
                CREATE TABLE symbol_analysis (id INTEGER PRIMARY KEY, symbol_id INTEGER, date TEXT);
                CREATE TABLE trade_selections (
                    id INTEGER PRIMARY KEY, analysis_id INTEGER, symbol_id INTEGER,
                    date TEXT, TradeScore REAL, TradeGrade TEXT
                );
                INSERT INTO symbols VALUES
                    (1, 'NET', 'Winner', 1), (2, 'EXT', 'Extended', 1),
                    (3, 'FLAT', 'No Setup', 1), (4, 'MATURE', 'Mature Trend', 1);
                """
            )
            start = date(2026, 1, 1)
            rows = []
            for index in range(180):
                session = (start + timedelta(days=index)).isoformat()
                net = 100 + index * 0.18
                if index >= 160:
                    net = 131 + (index - 160) * 0.12 + ((index % 3) - 1) * 0.25
                if index == 179:
                    net = 134.25
                extended = 60 + index * 0.10
                if index >= 174:
                    extended += (index - 173) * 5
                flat = 50 + ((index % 8) - 4) * 0.8
                mature = 49 if index < 80 else 49 + (index - 79) * 0.43
                for symbol_id, close, volume in (
                    (1, net, 900_000 if index < 179 else 1_500_000),
                    (2, extended, 800_000), (3, flat, 10_000),
                    (4, mature, 500_000),
                ):
                    rows.append((symbol_id, session, close - .2, close + .5, close - .5, close, volume))
            connection.executemany("INSERT INTO price_history VALUES (?,?,?,?,?,?,?)", rows)
            latest = (start + timedelta(days=179)).isoformat()
            connection.execute("INSERT INTO symbol_analysis VALUES (10,1,?)", (latest,))
            connection.execute("INSERT INTO trade_selections VALUES (1,10,1,?,42,'C')", (latest,))
            # Add a deliberately partial next session (one of three symbols).
            partial = (start + timedelta(days=180)).isoformat()
            connection.execute("INSERT INTO price_history VALUES (1,?,?,?,?,?,?)", (partial, 134, 135, 133, 134.5, 500_000))
        self.latest = (date(2026, 1, 1) + timedelta(days=179)).isoformat()
        self.scanner = BreakoutScanner(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_partial_session_is_not_selected(self) -> None:
        self.assertEqual(self.scanner.latest_complete_date(), self.latest)
        sessions = self.scanner.session_dates(2)
        self.assertFalse(sessions[0][2])
        self.assertTrue(sessions[1][2])

    def test_price_action_winner_is_found_without_legacy_grade_filter(self) -> None:
        date_value, candidates = self.scanner.scan(min_score=0, symbols=["NET"])
        self.assertEqual(date_value, self.latest)
        self.assertEqual(candidates[0].symbol, "NET")
        self.assertIn(candidates[0].setup, {"BREAKOUT", "READY"})
        self.assertEqual(candidates[0].grade, "C")

    def test_legacy_grade_is_optional_but_can_filter(self) -> None:
        _, candidates = self.scanner.scan(min_score=0, symbols=["NET"], grades=["A"])
        self.assertEqual(candidates, [])
        _, candidates = self.scanner.scan(min_score=0, symbols=["NET"], grades=[])
        self.assertEqual(len(candidates), 1)

    def test_overextension_penalty_reduces_score(self) -> None:
        _, candidates = self.scanner.scan(min_score=0, symbols=["NET", "EXT"])
        by_symbol = {candidate.symbol: candidate for candidate in candidates}
        self.assertGreater(by_symbol["NET"].score, by_symbol["EXT"].score)
        self.assertGreater(by_symbol["EXT"].extension_20d_pct, 15)

    def test_mature_stage2_trend_without_fresh_base_is_demoted(self) -> None:
        _, candidates = self.scanner.scan(
            min_score=0, symbols=["MATURE"], require_liquidity=False
        )
        mature = candidates[0]
        self.assertGreater(mature.runup_60d_pct, 25)
        self.assertGreater(mature.ema8_ema50_spread_pct, 6)
        self.assertGreaterEqual(mature.maturity_penalty, 20)
        self.assertLess(mature.score, 55)

    def test_liquidity_filter_excludes_thin_symbol(self) -> None:
        _, candidates = self.scanner.scan(min_score=0, symbols=["FLAT"])
        self.assertEqual(candidates, [])
        _, candidates = self.scanner.scan(min_score=0, symbols=["FLAT"], require_liquidity=False)
        self.assertEqual(len(candidates), 1)

    def test_csv_export_preserves_new_metrics(self) -> None:
        _, candidates = self.scanner.scan(min_score=0, symbols=["NET"])
        destination = Path(self.temporary.name) / "output.csv"
        write_export(destination, candidates, "csv")
        with destination.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["symbol"], "NET")
        self.assertIn("tightening_ratio", rows[0])

    def test_missing_database_has_clear_error(self) -> None:
        with self.assertRaisesRegex(ScannerError, "Database not found"):
            BreakoutScanner(Path(self.temporary.name) / "missing.db").validate()


if __name__ == "__main__":
    unittest.main()
