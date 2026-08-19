from __future__ import annotations

import math
from collections.abc import Sequence


def ema(values: Sequence[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def slope(values: Sequence[float], bars: int = 3, index: int = -1) -> float:
    resolved = index if index >= 0 else len(values) + index
    prior = resolved - bars
    if prior < 0:
        return 0.0
    return (float(values[resolved]) - float(values[prior])) / bars


def macd_histogram(
    closes: Sequence[float], fast: int, slow: int, signal: int
) -> list[float]:
    fast_line = ema(closes, fast)
    slow_line = ema(closes, slow)
    macd = [fast_value - slow_value for fast_value, slow_value in zip(fast_line, slow_line)]
    signal_line = ema(macd, signal)
    return [value - signal_value for value, signal_value in zip(macd, signal_line)]


def dmi_adx(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> tuple[list[float], list[float], list[float]]:
    true_ranges = [float(highs[0]) - float(lows[0])]
    plus_dm = [0.0]
    minus_dm = [0.0]
    for index in range(1, len(closes)):
        up = float(highs[index]) - float(highs[index - 1])
        down = float(lows[index - 1]) - float(lows[index])
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        true_ranges.append(
            max(
                float(highs[index]) - float(lows[index]),
                abs(float(highs[index]) - float(closes[index - 1])),
                abs(float(lows[index]) - float(closes[index - 1])),
            )
        )
    atr = _wilder(true_ranges, period)
    plus_smooth = _wilder(plus_dm, period)
    minus_smooth = _wilder(minus_dm, period)
    di_plus = [100 * value / tr if tr else 0.0 for value, tr in zip(plus_smooth, atr)]
    di_minus = [100 * value / tr if tr else 0.0 for value, tr in zip(minus_smooth, atr)]
    dx = [
        100 * abs(plus - minus) / (plus + minus) if plus + minus else 0.0
        for plus, minus in zip(di_plus, di_minus)
    ]
    return di_plus, di_minus, _wilder(dx, period)


def average_true_range(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 14
) -> list[float]:
    """Wilder average true range, aligned one-for-one with the input bars."""
    true_ranges = [float(highs[0]) - float(lows[0])]
    for index in range(1, len(closes)):
        true_ranges.append(
            max(
                float(highs[index]) - float(lows[index]),
                abs(float(highs[index]) - float(closes[index - 1])),
                abs(float(lows[index]) - float(closes[index - 1])),
            )
        )
    return _wilder(true_ranges, period)


def count_declines(values: Sequence[float], bars: int = 3, index: int = -1) -> int:
    """Count falling one-bar changes in the trailing window."""
    resolved = index if index >= 0 else len(values) + index
    start = max(1, resolved - bars + 1)
    return sum(values[position] < values[position - 1] for position in range(start, resolved + 1))


def true_momentum(closes: Sequence[float], lookback: int = 14) -> list[float]:
    """TMO approximation: smoothed sum of 14 pairwise close comparisons."""
    raw: list[float] = []
    for index in range(len(closes)):
        score = 0
        for offset in range(1, min(lookback, index) + 1):
            score += 1 if closes[index] > closes[index - offset] else -1
        denominator = min(lookback, index)
        raw.append(100 * score / denominator if denominator else 0.0)
    return ema(ema(raw, 5), 3)


def squeeze_momentum(
    highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int = 20
) -> list[float]:
    """LazyBear-style momentum: regression of close minus range/SMA midpoint."""
    result = [0.0] * len(closes)
    for index in range(period - 1, len(closes)):
        start = index - period + 1
        highest = max(highs[start : index + 1])
        lowest = min(lows[start : index + 1])
        average = sum(closes[start : index + 1]) / period
        midpoint = ((highest + lowest) / 2 + average) / 2
        values = [float(close) - midpoint for close in closes[start : index + 1]]
        result[index] = _linear_regression_endpoint(values)
    return result


def bars_since_cross(positive: Sequence[float], negative: Sequence[float], limit: int = 60) -> int | None:
    for bars_ago in range(0, min(limit, len(positive) - 1) + 1):
        index = len(positive) - 1 - bars_ago
        if index > 0 and positive[index] > negative[index] and positive[index - 1] <= negative[index - 1]:
            return bars_ago
    return None


def recent_slope_turn(values: Sequence[float], lookback: int = 5) -> bool:
    slopes = [slope(values, 1, index) for index in range(max(1, len(values) - lookback), len(values))]
    return any(slopes[index] > 0 and slopes[index - 1] <= 0 for index in range(1, len(slopes)))


def _wilder(values: Sequence[float], period: int) -> list[float]:
    alpha = 1 / period
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1 - alpha) * result[-1])
    return result


def _linear_regression_endpoint(values: Sequence[float]) -> float:
    count = len(values)
    x_mean = (count - 1) / 2
    y_mean = sum(values) / count
    denominator = sum((index - x_mean) ** 2 for index in range(count))
    if math.isclose(denominator, 0):
        return float(values[-1])
    slope_value = sum((index - x_mean) * (value - y_mean) for index, value in enumerate(values)) / denominator
    intercept = y_mean - slope_value * x_mean
    return intercept + slope_value * (count - 1)
