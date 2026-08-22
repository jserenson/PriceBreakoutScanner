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
    market_state: str
    readiness_state: str
    structure_state: str
    extension_state: str
    trend_quality_6m_pct: float
    positive_structure_bars_6m: int
    deterioration_flags: str | None
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
    runup_60d_pct: float
    ema8_ema50_spread_pct: float
    price_ema8_distance_pct: float
    price_ema21_distance_pct: float
    price_ema50_distance_pct: float
    price_ema8_distance_atr: float
    ema8_ema21_spread_pct: float
    bars_since_reset: int | None
    maturity_penalty: float
    ignition_state: str
    bars_since_di_cross: int | None
    di_cross_confirmed: bool
    di_plus: float
    di_minus: float
    di_plus_slope_3d: float
    di_plus_slope_5d: float
    di_minus_slope_3d: float
    di_minus_slope_5d: float
    di_spread: float
    di_spread_slope_3d: float
    di_spread_slope_5d: float
    adx: float
    adx_slope_5d: float
    adx_state: str
    adx_at_cross: float | None
    squeeze_momentum: float
    squeeze_slope_3d: float
    squeeze_recent_turn: bool
    squeeze_on: bool
    squeeze_count: int
    squeeze_released: bool
    tmo: float
    tmo_signal: float
    tmo_slope_3d: float
    macd_trend_hist: float
    macd_trend_slope_3d: float
    macd_timing_hist: float
    macd_timing_slope_3d: float
    bars_since_structure_restored: int | None
    bars_since_ignition: int | None
    move_since_ignition_pct: float | None
    event_risk: str
    rejection_reason: str | None
    weinstein_stage: int
    stage_source: str
    dollar_volume_20d: int
    legacy_score: float | None = None
    grade: str | None = None

    def with_rank(self, rank: int) -> "Candidate":
        return replace(self, rank=rank)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
