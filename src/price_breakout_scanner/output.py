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
    headers = ("#", "Symbol", "PA Score", "Setup", "Price", "To Res", "10D Range", "Vol", "Mom 5D", "Run 60D", "EMA Gap", "Reset", "Penalty", "Stage", "Legacy")
    rows = [
        (
            item.rank or "-", item.symbol, f"{item.score:.2f}", item.setup,
            f"{item.price:.2f}", f"{item.distance_to_resistance_pct:.1f}%", f"{item.range_10d_pct:.1f}%",
            f"{item.volume_ratio:.2f}x", f"{item.momentum_5d_pct:.1f}%",
            f"{item.runup_60d_pct:.1f}%", f"{item.ema8_ema50_spread_pct:.1f}%",
            item.bars_since_reset if item.bars_since_reset is not None else ">60",
            f"-{item.maturity_penalty:.0f}",
            item.weinstein_stage,
            f"{item.grade or '-'} / {item.legacy_score:.1f}" if item.legacy_score is not None else "-",
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


def write_export(path: str | Path, candidates: Sequence[Candidate], format_name: str) -> Path:
    output = Path(path).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    records = [candidate.as_dict() for candidate in candidates]
    if format_name == "xlsx":
        _write_xlsx(output, records)
    elif format_name == "json":
        output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    else:
        with output.open("w", newline="", encoding="utf-8") as handle:
            if records:
                writer = csv.DictWriter(handle, fieldnames=records[0].keys())
                writer.writeheader()
                writer.writerows(records)
    return output


def _write_xlsx(output: Path, records: list[dict[str, object]]) -> None:
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
                [str(node), str(builder), str(data_path), str(output.resolve()), str(temp)],
                text=True, capture_output=True, check=False, cwd=temp,
            )
        if completed.returncode:
            raise RuntimeError(f"Excel export failed: {completed.stderr.strip() or completed.stdout.strip()}")
