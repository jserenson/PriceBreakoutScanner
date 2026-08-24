from __future__ import annotations

import io
import time
import unittest

from price_breakout_scanner import __version__
from price_breakout_scanner.cli import Heartbeat, parser


class CliTests(unittest.TestCase):
    def test_release_version_is_current(self) -> None:
        self.assertEqual(__version__, "1.5.2.1")

    def test_heartbeat_reports_current_phase_and_completion(self) -> None:
        output = io.StringIO()
        with Heartbeat(interval=0.01, stream=output) as heartbeat:
            heartbeat.update("analyzing 100 of 5,000 symbols")
            time.sleep(0.03)
        text = output.getvalue()
        self.assertIn("Scanner started", text)
        self.assertIn("analyzing 100 of 5,000 symbols", text)
        self.assertIn("Scanner finished", text)

    def test_quiet_option_suppresses_heartbeat(self) -> None:
        self.assertTrue(parser().parse_args(["--quiet"]).quiet)

    def test_watchlist_accepts_comma_separated_tickers(self) -> None:
        args = parser().parse_args(["--watchlist", "AAPL,MSFT,NVDA"])
        self.assertEqual(args.watchlist, "AAPL,MSFT,NVDA")


if __name__ == "__main__":
    unittest.main()
