from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

from . import __version__
from .output import render_table, write_export
from .scanner import BreakoutScanner, ScannerError

DEFAULT_DATABASE = Path(
    "/Users/jamesserenson/Documents/AnacondaProjects/Stage5_SymbolDatabase/symbols.db"
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="price-breakout-scanner",
        description="Detect recent synchronized price-action ignitions from read-only market history.",
    )
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    result.add_argument(
        "--db", type=Path,
        default=Path(os.environ.get("PRICE_BREAKOUT_DB", DEFAULT_DATABASE)),
        help="SQLite database (or set PRICE_BREAKOUT_DB)",
    )
    result.add_argument("--date", help="Trading date in YYYY-MM-DD form; defaults to latest")
    result.add_argument("--dates", action="store_true", help="List recent session coverage and exit")
    result.add_argument("--min-score", type=float, default=55.0, help="Minimum recent-ignition score")
    result.add_argument("--grades", default="", help="Optional legacy Atlas grades; empty means all")
    result.add_argument("--min-dollar-volume", type=int, default=1_000_000)
    result.add_argument("--allow-illiquid", action="store_true")
    result.add_argument("--allow-nonbullish", action="store_true", help=argparse.SUPPRESS)
    result.add_argument("--archetype", action="append", default=[], help=argparse.SUPPRESS)
    result.add_argument("--transition", action="append", default=[], help=argparse.SUPPRESS)
    result.add_argument("--symbol", action="append", default=[])
    result.add_argument("--limit", type=int, default=20)
    result.add_argument("--export", type=Path, help="Write results to a .csv, .json, or .xlsx file")
    result.add_argument("--format", choices=("csv", "json", "xlsx"), help="Export format override")
    result.add_argument("--quiet", action="store_true", help="Suppress scanner heartbeat messages")
    return result


class Heartbeat:
    """Show that a long scan is alive without mixing status into its results."""

    def __init__(self, *, interval: float = 5.0, stream: TextIO = sys.stderr):
        self.interval = interval
        self.stream = stream
        self.status = "starting"
        self.started = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "Heartbeat":
        self.started = time.monotonic()
        print("Scanner started — heartbeat active", file=self.stream, flush=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def update(self, status: str) -> None:
        self.status = status

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(1.0, self.interval * 2))
        elapsed = time.monotonic() - self.started
        outcome = "stopped" if exc_type else "finished"
        print(f"Scanner {outcome} after {elapsed:.1f}s", file=self.stream, flush=True)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            elapsed = time.monotonic() - self.started
            print(
                f"Scanner running — {elapsed:.0f}s — {self.status}",
                file=self.stream,
                flush=True,
            )


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    scanner = BreakoutScanner(args.db)
    try:
        scanner.validate()
        if args.dates:
            for session_date, count, complete in scanner.session_dates():
                print(f"{session_date}  {count:>5} symbols  {'complete' if complete else 'partial'}")
            return 0
        heartbeat = None if args.quiet else Heartbeat()
        if heartbeat:
            with heartbeat:
                selected_date, candidates = _scan(scanner, args, heartbeat.update)
        else:
            selected_date, candidates = _scan(scanner, args, None)
    except ScannerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"PriceBreakoutScanner v{__version__} | {selected_date} | "
        f"{len(candidates)} candidates | {scanner.price_source()}"
    )
    if candidates:
        print(render_table(candidates))
    else:
        print("No candidates matched the selected filters.")

    if args.export:
        format_name = args.format or args.export.suffix.lower().lstrip(".")
        if format_name not in {"csv", "json", "xlsx"}:
            print("error: export must use .csv/.json/.xlsx or --format", file=sys.stderr)
            return 2
        try:
            if not args.quiet:
                print(f"Exporting {format_name.upper()} report…", file=sys.stderr, flush=True)
            output = write_export(args.export, candidates, format_name)
        except (OSError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"Exported: {output.resolve()}")
    return 0


def _scan(
    scanner: BreakoutScanner,
    args: argparse.Namespace,
    progress: Callable[[str], None] | None,
) -> tuple[str, list]:
    return scanner.scan(
        date=args.date,
        min_score=args.min_score,
        grades=_csv_values(args.grades),
        min_dollar_volume=args.min_dollar_volume,
        require_liquidity=not args.allow_illiquid,
        require_bullish_structure=not args.allow_nonbullish,
        archetypes=args.archetype,
        transitions=args.transition,
        symbols=args.symbol,
        limit=args.limit,
        progress=progress,
    )


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
