from __future__ import annotations

import unittest

from price_breakout_scanner.scanner import BreakoutScanner


class StateModelTests(unittest.TestCase):
    def test_repairing_structure_recognizes_synchronized_recovery(self) -> None:
        closes = [9.8, 10.0, 10.2, 10.4, 10.7, 11.0]
        ema8 = [10.1, 10.0, 10.0, 10.1, 10.3, 10.6]
        ema21 = [10.4, 10.3, 10.2, 10.15, 10.2, 10.3]
        ema50 = [10.55, 10.5, 10.45, 10.4, 10.4, 10.4]
        di_plus = [15, 16, 18, 20, 23, 26]
        di_minus = [28, 27, 25, 23, 20, 17]
        adx = [22, 20, 18, 17, 16.9, 17.0]
        trend = [-1, -0.5, -0.1, 0.1, 0.3, 0.6]
        timing = [-0.5, -0.2, 0.1, 0.3, 0.5, 0.8]
        tmo = [-20, -10, -2, 5, 12, 20]
        squeeze = [-2, -1.5, -1, -0.4, 0.1, 0.5]
        self.assertEqual(
            BreakoutScanner._structure_state(
                closes, ema8, ema21, ema50, di_plus, di_minus, adx,
                trend, timing, tmo, squeeze,
            ),
            "REPAIRING",
        )

    def test_extension_is_separate_from_structure(self) -> None:
        ema8 = [10.0, 10.1, 10.2, 10.3, 10.4, 10.5]
        ema21 = [9.8, 9.85, 9.9, 9.95, 10.0, 10.05]
        self.assertEqual(
            BreakoutScanner._extension_state(7.0, 11.0, 2.0, ema8, ema21),
            "EXTENDED",
        )
        self.assertEqual(
            BreakoutScanner._extension_state(1.0, 2.0, 0.5, ema8, ema21),
            "HUGGING_EMA8",
        )

    def test_adx_flattening_after_decline_is_detected(self) -> None:
        self.assertEqual(
            BreakoutScanner._adx_state([25, 22, 19, 17, 16.9, 17.0]),
            "FLATTENING",
        )

    def test_weakening_market_state_is_not_a_confirmed_ranking_state(self) -> None:
        state = BreakoutScanner._market_state(
            "PRIMED", "INTACT", "CONTROLLED",
            [20, 21, 22, 23], [15, 15, 15, 15],
            [5, 6, 7, 8], [20, 19, 18, 17],
        )
        self.assertEqual(state, "WEAKENING")

    def test_six_month_quality_rewards_persistent_bar_by_bar_structure(self) -> None:
        closes = [10 + index * 0.1 for index in range(130)]
        ema8 = [value - 0.1 for value in closes]
        ema21 = [value - 0.2 for value in closes]
        ema50 = [value - 0.3 for value in closes]
        quality, aligned = BreakoutScanner._trend_quality_6m(
            closes, ema8, ema21, ema50
        )
        self.assertEqual(quality, 100.0)
        self.assertEqual(aligned, 126)

    def test_latest_di_rollover_is_reported_even_when_three_day_slope_is_positive(self) -> None:
        flags = BreakoutScanner._deterioration_flags(
            [20, 21, 24, 23], [3, 4, 7, 6],
            [1, 2, 3, 4], [1, 2, 3, 4],
            [1, 2, 3, 4], [1, 2, 3, 4],
        )
        self.assertIn("DI+ rolled over", flags)

    def test_readiness_states_are_explicit_review_buckets(self) -> None:
        self.assertEqual(
            BreakoutScanner._readiness_state("CONFIRMED"),
            "CONFIRMED_NOT_EXTENDED",
        )
        self.assertEqual(
            BreakoutScanner._readiness_state("CONFIRMED_EXTENDED"),
            "CONFIRMED_EXTENDED",
        )
        self.assertEqual(
            BreakoutScanner._readiness_state("PRIMED"),
            "PRIMED_EARLY_EXPANSION",
        )
        self.assertEqual(
            BreakoutScanner._readiness_state("REPAIRING"),
            "REPAIRING_STRUCTURE",
        )
        self.assertEqual(
            BreakoutScanner._readiness_state("WEAKENING"),
            "WATCH_MOMENTUM_NOT_READY",
        )

    def test_ranking_keeps_readiness_buckets_in_review_order(self) -> None:
        states = [
            "CONFIRMED_NOT_EXTENDED", "CONFIRMED_EXTENDED",
            "PRIMED_EARLY_EXPANSION", "REPAIRING_STRUCTURE",
            "WATCH_MOMENTUM_NOT_READY",
        ]
        self.assertEqual(
            [BreakoutScanner._ranking_priority(state) for state in states],
            list(range(5)),
        )


if __name__ == "__main__":
    unittest.main()
