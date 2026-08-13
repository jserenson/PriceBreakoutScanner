from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Candidate:
    rank: int | None
    symbol: str
    company: str | None
    date: str
    score: float
    grade: str | None
    price: float | None
    confidence: float | None
    primary_rank: int | None
    secondary_rank: int | None
    transition: str | None
    archetype: str | None
    description: str | None
    dollar_volume_50: int | None
    rank1_ignition: bool
    momentum_recovering: bool
    pullback_completing: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

