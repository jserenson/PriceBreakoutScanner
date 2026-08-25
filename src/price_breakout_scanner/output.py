from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from importlib.resources import as_file, files
from pathlib import Path

from .models import Candidate


def render_table(candidates: Sequence[Candidate]) -> str:
    headers = ("#", "Symbol", "Score", "Action", "Readiness", "Momentum", "Market", "Structure", "20/50/200", "Extension", "6M Quality", "Price", "DI+ 3/5", "DI- 3/5", "Spread 3/5", "ADX", "ADX State", "Ignition", "Deterioration / Reason")
    rows = [
        (
            item.rank or "-", item.symbol, f"{item.score:.2f}", item.review_action,
            item.readiness_state,
            item.momentum_phase, item.market_state,
            item.structure_state, item.long_term_structure, item.extension_state,
            f"{item.trend_quality_6m_pct:.1f}%", f"{item.price:.2f}",
            f"{item.di_plus_slope_3d:.2f}/{item.di_plus_slope_5d:.2f}",
            f"{item.di_minus_slope_3d:.2f}/{item.di_minus_slope_5d:.2f}",
            f"{item.di_spread_slope_3d:.2f}/{item.di_spread_slope_5d:.2f}",
            f"{item.adx:.1f}", item.adx_state,
            item.bars_since_ignition if item.bars_since_ignition is not None else "-",
            item.deterioration_flags or item.rejection_reason or "-",
        )
        for item in candidates
    ]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(str(value)))

    def line(values: Sequence[object]) -> str:
        return "  ".join(str(value).ljust(widths[index]) for index, value in enumerate(values)).rstrip()

    separator = "  ".join("-" * width for width in widths)
    return "\n".join((line(headers), separator, *(line(row) for row in rows)))


def write_export(
    path: str | Path,
    candidates: Sequence[Candidate],
    format_name: str,
    *,
    detail_sheets: bool = False,
) -> Path:
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    records = [candidate.as_dict() for candidate in candidates]
    if format_name == "xlsx":
        _write_xlsx(output, records, detail_sheets=detail_sheets)
    elif format_name == "json":
        output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    else:
        with output.open("w", newline="", encoding="utf-8") as handle:
            if records:
                writer = csv.DictWriter(handle, fieldnames=records[0].keys())
                writer.writeheader()
                writer.writerows(records)
    return output


def _write_xlsx(
    output: Path, records: list[dict[str, object]], *, detail_sheets: bool = False
) -> None:
    node = Path(os.environ.get("PRICE_BREAKOUT_NODE", "/Users/jamesserenson/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"))
    node_modules = Path(os.environ.get("PRICE_BREAKOUT_NODE_MODULES", "/Users/jamesserenson/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"))
    if not node.is_file() or not node_modules.is_dir():
        raise RuntimeError("Excel export runtime unavailable; set PRICE_BREAKOUT_NODE and PRICE_BREAKOUT_NODE_MODULES")
    with tempfile.TemporaryDirectory(prefix="price-breakout-xlsx-") as temp_name:
        temp = Path(temp_name)
        (temp / "node_modules").symlink_to(node_modules, target_is_directory=True)
        data_path = temp / "candidates.json"
        data_path.write_text(json.dumps(records), encoding="utf-8")
        with as_file(files("price_breakout_scanner").joinpath("xlsx_builder.mjs")) as builder:
            completed = subprocess.run(
                [
                    str(node), str(builder), str(data_path), str(output.resolve()),
                    str(temp), "details" if detail_sheets else "summary",
                ],
                text=True, capture_output=True, check=False, cwd=temp,
            )
        if completed.returncode:
            raise RuntimeError(f"Excel export failed: {completed.stderr.strip() or completed.stdout.strip()}")
