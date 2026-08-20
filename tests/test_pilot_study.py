from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from price_breakout_scanner.pilot_study import PilotStudy


class PilotStudyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "study.db"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript(
                """
                CREATE TABLE symbols (id INTEGER PRIMARY KEY, symbol TEXT);
                CREATE TABLE price_history (
                    symbol_id INTEGER, date TEXT, high REAL, low REAL, close REAL
                );
                CREATE TABLE symbol_analysis (
                    symbol_id INTEGER, date TEXT, BullishStructure INTEGER,
                    DIPlus REAL, DIMinus REAL, ADX REAL, Close REAL, EMA8 REAL,
                    EMA21 REAL, MACDTimingHist REAL, DIPlus_Slope_5D REAL,
                    MACDTimingHist_Slope_5D REAL
                );
                INSERT INTO symbols VALUES (1, 'ONE');
                """
            )
            for day in range(1, 32):
                date = f"2026-01-{day:02d}"
                close = 100.0 if day == 1 else 100.0 + day * .2
                high = 106.0 if day == 4 else close + .5
                connection.execute(
                    "INSERT INTO price_history VALUES (?,?,?,?,?)",
                    (1, date, high, close - .5, close),
                )
                connection.execute(
                    "INSERT INTO symbol_analysis VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (1, date, 1, 30, 15, 18, close, close / 1.01, close / 1.02,
                     .2, 1 if day <= 2 else -1, .1 if day <= 2 else -1),
                )
            connection.commit()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_detects_episode_once_and_measures_forward_target(self) -> None:
        events = PilotStudy(self.database).run("ONE")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].signal_date, "2026-01-01")
        self.assertEqual(events[0].hit_5pct_date, "2026-01-04")
        self.assertEqual(events[0].first_5pct_outcome, "TARGET_FIRST")
        self.assertEqual(events[0].outcome_status, "COMPLETE")


if __name__ == "__main__":
    unittest.main()
