from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .output import render_table, write_export
from .scanner import BreakoutScanner, ScannerError

DEFAULT_DATABASE = Path(
    "/Users/jamesserenson/Documents/AnacondaProjects/Atlas-Runs/PriceBreakoutScanner.db"
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="price-breakout-scanner",
        description="Rank Atlas breakout candidates without modifying the source database.",
    )
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    result.add_argument(
        "--db", type=Path,
        default=Path(os.environ.get("PRICE_BREAKOUT_DB", DEFAULT_DATABASE)),
        help="SQLite database (or set PRICE_BREAKOUT_DB)",
    )
    result.add_argument("--date", help="Trading date in YYYY-MM-DD form; defaults to latest")
    result.add_argument("--dates", action="store_true", help="List recent available dates and exit")
    result.add_argument("--min-score", type=float, default=70.0)
    result.add_argument("--grades", default="A,B", help="Comma-separated grades; empty means all")
    result.add_argument("--min-dollar-volume", type=int, default=1_000_000)
    result.add_argument("--allow-illiquid", action="store_true")
    result.add_argument("--allow-nonbullish", action="store_true")
    result.add_argument("--archetype", action="append", default=[])
    result.add_argument("--transition", action="append", default=[])
    result.add_argument("--symbol", action="append", default=[])
    result.add_argument("--limit", type=int, default=20)
    result.add_argument("--export", type=Path, help="Write results to a .csv or .json file")
    result.add_argument("--format", choices=("csv", "json"), help="Export format override")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    scanner = BreakoutScanner(args.db)
    try:
        scanner.validate()
        if args.dates:
            print("\n".join(scanner.available_dates()))
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

    print(f"PriceBreakoutScanner v{__version__} | {selected_date} | {len(candidates)} candidates")
    if candidates:
        print(render_table(candidates))
    else:
        print("No candidates matched the selected filters.")

    if args.export:
        format_name = args.format or args.export.suffix.lower().lstrip(".")
        if format_name not in {"csv", "json"}:
            print("error: export must use .csv/.json or --format", file=sys.stderr)
            return 2
        output = write_export(args.export, candidates, format_name)
        print(f"Exported: {output.resolve()}")
    return 0


def _csv_values(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())

