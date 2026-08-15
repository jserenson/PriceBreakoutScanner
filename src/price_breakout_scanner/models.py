from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any


@dataclass(frozen=True, slots=True)
class Candidate:
    rank: int | None
    symbol: str
    company: str | None
    date: str
    score: float
    setup: str
    price: float
    resistance: float
    distance_to_resistance_pct: float
    breakout_pct: float
    range_10d_pct: float
    tightening_ratio: float
    higher_low_pct: float
    volume_ratio: float
    volume_contraction_ratio: float
    momentum_5d_pct: float
    momentum_20d_pct: float
    extension_20d_pct: float
    weinstein_stage: int
    stage_source: str
    dollar_volume_20d: int
    legacy_score: float | None = None
    grade: str | None = None

    def with_rank(self, rank: int) -> "Candidate":
        return replace(self, rank=rank)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

