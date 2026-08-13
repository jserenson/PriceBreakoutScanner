from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path

from .models import Candidate


def render_table(candidates: Sequence[Candidate]) -> str:
    headers = ("#", "Symbol", "Score", "Grade", "Price", "Confidence", "Setup", "Signal")
    rows = [
        (
            candidate.rank if candidate.rank is not None else "-",
            candidate.symbol,
            f"{candidate.score:.2f}",
            candidate.grade or "-",
            f"{candidate.price:.2f}" if candidate.price is not None else "-",
            f"{candidate.confidence:.0f}%" if candidate.confidence is not None else "-",
            candidate.archetype or "-",
            _signal(candidate),
        )
        for candidate in candidates
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
    if format_name == "json":
        output.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    else:
        with output.open("w", newline="", encoding="utf-8") as handle:
            if records:
                writer = csv.DictWriter(handle, fieldnames=records[0].keys())
                writer.writeheader()
                writer.writerows(records)
            else:
                handle.write("")
    return output


def _signal(candidate: Candidate) -> str:
    signals = []
    if candidate.rank1_ignition:
        signals.append("ignition")
    if candidate.momentum_recovering:
        signals.append("recovering")
    if candidate.pullback_completing:
        signals.append("pullback")
    return ",".join(signals) or candidate.description or "-"

