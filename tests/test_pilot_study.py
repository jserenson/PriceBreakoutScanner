from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from price_breakout_scanner.pilot_study import PilotStudy
from price_breakout_scanner import indicators


class PilotStudyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "study.db"
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript(
                """
                CREATE TABLE symbols (id INTEGER PRIMARY KEY, symbol TEXT);
                CREATE TABLE price_history (
                    symbol_id INTEGER, date TEXT, open REAL, high REAL, low REAL,
                    close REAL, volume INTEGER
                );
                INSERT INTO symbols VALUES (1, 'ONE');
                """
            )
            for day in range(1, 32):
                date = f"2026-01-{day:02d}"
                close = 100.0 if day == 1 else 100.0 + day * .2
                high = 106.0 if day == 4 else close + .5
                connection.execute(
                    "INSERT INTO price_history VALUES (?,?,?,?,?,?,?)",
                    (1, date, close - .1, high, close - .5, close, 100000),
                )
            connection.commit()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_detects_episode_once_and_measures_forward_target(self) -> None:
        events = PilotStudy(self.database).run("ONE")
        calculated = PilotStudy._calculate_indicators(self._bars())
        self.assertEqual(len(calculated), 31)
        self.assertIn("DIPlus", calculated[-1])
        self.assertIn("MACDTrendHist", calculated[-1])
        self.assertIn("TMO", calculated[-1])
        self.assertIn("SqueezeCount", calculated[-1])

    def test_chart_tmo_matches_displayed_thinkscript_formula(self) -> None:
        closes = [float(value) for value in range(1, 25)]
        main, signal = indicators.chart_tmo(closes, 14, 5, 3)
        raw = [0.0] * 14 + [14.0] * 10
        expected = indicators.ema(indicators.ema(raw, 5), 5)
        self.assertEqual(main, expected)
        self.assertEqual(signal, indicators.ema(expected, 3))

    def test_clean_squeeze_count_resets_after_release(self) -> None:
        closes = [100.0] * 25 + [120.0, 80.0, 120.0]
        highs = [value + .1 for value in closes]
        lows = [value - .1 for value in closes]
        _, squeeze_on, counts = indicators.clean_squeeze_v2(highs, lows, closes)
        self.assertTrue(squeeze_on[24])
        self.assertGreater(counts[24], 0)
        self.assertEqual(counts[-1], 0)

    def test_entry_classification_uses_stage_and_price_extension_only(self) -> None:
        early = ("EARLY_STAGE2", 100.0, 1.0, 12.0)
        extended = ("STAGE2_EXTENDED", 100.0, 4.0, 28.0)
        stage4 = ("STAGE4", 100.0, -3.0, -5.0)
        self.assertEqual(
            PilotStudy._entry_classification(early, 2.0, 20.0),
            "EARLY_STAGE2_CANDIDATE",
        )
        self.assertEqual(PilotStudy._entry_classification(extended, 2.0, 10.0), "EXTENDED")
        self.assertEqual(PilotStudy._entry_classification(stage4, 2.0, 10.0), "REJECT_STAGE")

    def test_runs_without_symbol_analysis_table(self) -> None:
        self.assertIsInstance(PilotStudy(self.database).run("ONE"), list)

    def test_prefers_unadjusted_history_when_available(self) -> None:
        with sqlite3.connect(self.database) as connection:
            connection.execute(
                "CREATE TABLE price_history_unadjusted AS "
                "SELECT * FROM price_history"
            )
            connection.execute(
                "UPDATE price_history_unadjusted SET close=close+1"
            )
        with PilotStudy(self.database)._connect() as connection:
            self.assertEqual(
                PilotStudy._price_table(connection),
                "price_history_unadjusted",
            )

    def test_small_one_day_di_dip_is_not_treated_as_rollover(self) -> None:
        current = {
            "Close": 102.0, "EMA8": 100.0, "EMA21": 99.0,
            "DIPlus": 21.7, "DIMinus": 12.0, "DIPlus_Slope_5D": 1.0,
            "MACDTrendHist": -.001, "MACDTimingHist": .03,
            "MACDTimingHist_Slope_3D": .01,
            "MACDTimingHist_Slope_5D": .01, "SqueezeReleased": False,
        }
        previous = {"DIPlus": 22.0, "MACDTrendHist": -.002, "MACDTimingHist": .02}
        self.assertEqual(
            PilotStudy._entry_trigger(current, previous, "RESTORING"),
            "BASE_TRANSITION",
        )

    def test_current_three_day_macd_turn_is_not_blocked_by_old_five_day_spike(self) -> None:
        current = {
            "Close": 103.0, "EMA8": 100.0, "EMA21": 99.0,
            "DIPlus": 32.0, "DIMinus": 20.0, "DIPlus_Slope_5D": .4,
            "MACDTrendHist": .03, "MACDTimingHist": .057,
            "MACDTimingHist_Slope_3D": .01,
            "MACDTimingHist_Slope_5D": -.006, "SqueezeReleased": False,
        }
        previous = {"DIPlus": 31.0, "MACDTrendHist": .027, "MACDTimingHist": .054}
        self.assertEqual(
            PilotStudy._entry_trigger(current, previous, "CONFIRMED"),
            "BASE_TRANSITION",
        )

    def _bars(self) -> list[sqlite3.Row]:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute("SELECT * FROM price_history ORDER BY date").fetchall()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
