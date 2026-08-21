from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

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
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    scanner = BreakoutScanner(args.db)
    try:
        scanner.validate()
        if args.dates:
            for session_date, count, complete in scanner.session_dates():
                print(f"{session_date}  {count:>5} symbols  {'complete' if complete else 'partial'}")
            return 0
        selected_date, candidates = scanner.scan(
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
        )
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
            output = write_export(args.export, candidates, format_name)
        except (OSError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"Exported: {output.resolve()}")
    return 0


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
