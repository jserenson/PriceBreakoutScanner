from __future__ import annotations

import argparse
import csv
import sqlite3
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .cli import DEFAULT_DATABASE


@dataclass(frozen=True)
class PilotEvent:
    symbol: str
    signal_date: str
    entry_close: float
    price_vs_ema8_pct: float
    di_plus: float
    di_minus: float
    di_plus_slope_5d: float
    adx: float
    timing_hist: float
    timing_slope_5d: float
    weinstein_stage: str
    weekly_ma30: float | None
    weekly_ma30_slope_5w_pct: float | None
    price_vs_weekly_ma30_pct: float | None
    runup_20d_pct: float
    entry_classification: str
    outcome_status: str
    return_5d_pct: float | None
    return_10d_pct: float | None
    return_20d_pct: float | None
    max_gain_20d_pct: float | None
    max_drawdown_20d_pct: float | None
    hit_5pct_date: str | None
    hit_10pct_date: str | None
    hit_minus5pct_date: str | None
    first_5pct_outcome: str | None


class PilotStudy:
    """Historical proof-of-concept for one mechanically defined setup.

    Candidate timing remains intentionally broad. Each event is then classified
    using a weekly Weinstein regime and extension derived only from price
    history and independently calculated indicators.
    """

    REQUIRED_ANALYSIS_COLUMNS = {
        "symbol_id", "date", "BullishStructure", "DIPlus", "DIMinus", "ADX",
        "Close", "EMA8", "EMA21", "MACDTimingHist", "DIPlus_Slope_5D",
        "MACDTimingHist_Slope_5D",
    }
    HORIZON = 20

    def __init__(self, database: str | Path):
        self.database = Path(database).expanduser()

    def run(self, symbol: str, *, cooldown: int = 10) -> list[PilotEvent]:
        if cooldown < 0:
            raise ValueError("cooldown cannot be negative")
        symbol = symbol.upper().strip()
        with self._connect() as connection:
            self._validate(connection)
            rows = connection.execute(
                """
                SELECT sa.date, sa.Close, sa.EMA8, sa.EMA21, sa.DIPlus,
                       sa.DIMinus, sa.ADX, sa.DIPlus_Slope_5D,
                       sa.MACDTimingHist, sa.MACDTimingHist_Slope_5D,
                       sa.BullishStructure
                FROM symbol_analysis sa
                JOIN symbols s ON s.id = sa.symbol_id
                WHERE UPPER(s.symbol) = ? ORDER BY sa.date
                """, (symbol,),
            ).fetchall()
            bars = connection.execute(
                """
                SELECT ph.date, ph.high, ph.low, ph.close
                FROM price_history ph JOIN symbols s ON s.id = ph.symbol_id
                WHERE UPPER(s.symbol) = ? ORDER BY ph.date
                """, (symbol,),
            ).fetchall()
        if not rows or not bars:
            raise ValueError(f"No analysis and price history found for {symbol}")

        bar_index = {str(row["date"]): index for index, row in enumerate(bars)}
        weekly_regimes = self._weekly_regimes(bars)
        events: list[PilotEvent] = []
        previous_qualified = False
        last_event_bar = -cooldown - 1
        for row in rows:
            qualified = self._qualifies(row)
            index = bar_index.get(str(row["date"]))
            is_new_episode = qualified and not previous_qualified
            if index is not None and is_new_episode and index - last_event_bar > cooldown:
                events.append(self._measure(
                    symbol, row, bars, index, weekly_regimes.get(str(row["date"])),
                ))
                last_event_bar = index
            previous_qualified = qualified
        return events

    def _connect(self) -> sqlite3.Connection:
        if not self.database.is_file():
            raise ValueError(f"Database not found: {self.database}")
        connection = sqlite3.connect(f"file:{self.database.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def _validate(self, connection: sqlite3.Connection) -> None:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(symbol_analysis)")
        }
        missing = self.REQUIRED_ANALYSIS_COLUMNS - columns
        if missing:
            raise ValueError("symbol_analysis is missing: " + ", ".join(sorted(missing)))

    @staticmethod
    def _weekly_regimes(bars: list[sqlite3.Row]) -> dict[str, tuple[str, float, float, float]]:
        """Calculate a no-look-ahead 30-week regime for every daily bar."""
        weeks: OrderedDict[tuple[int, int], tuple[str, float]] = OrderedDict()
        result: dict[str, tuple[str, float, float, float]] = {}
        stage2_start_week: tuple[int, int] | None = None
        for bar in bars:
            day = date.fromisoformat(str(bar["date"]))
            iso = day.isocalendar()
            week_key = (iso.year, iso.week)
            weeks[week_key] = (str(bar["date"]), float(bar["close"]))
            weekly_values = list(weeks.values())
            closes = [value[1] for value in weekly_values]
            if len(closes) < 35:
                continue
            ma30 = sum(closes[-30:]) / 30.0
            ma30_five_weeks_ago = sum(closes[-35:-5]) / 30.0
            slope = 100.0 * (ma30 / ma30_five_weeks_ago - 1.0)
            distance = 100.0 * (float(bar["close"]) / ma30 - 1.0)

            raw_stage2 = distance > 2.0 and slope > 0.0
            if raw_stage2 and stage2_start_week is None:
                stage2_start_week = week_key
            elif not raw_stage2:
                stage2_start_week = None

            if distance < -2.0 and slope < -1.0:
                stage = "STAGE4"
            elif raw_stage2:
                stage = "EARLY_STAGE2" if distance <= 20.0 else "STAGE2_EXTENDED"
            elif distance >= 0.0 and slope >= -1.0:
                stage = "STAGE1_TO_2"
            elif abs(distance) <= 10.0 and abs(slope) <= 1.5:
                stage = "STAGE1"
            elif distance >= 0.0 and slope < 0.0:
                stage = "STAGE3"
            else:
                stage = "UNFAVORABLE"
            result[str(bar["date"])] = (stage, ma30, slope, distance)
        return result

    @staticmethod
    def _entry_classification(
        regime: tuple[str, float, float, float] | None,
        price_vs_ema8: float,
        runup_20d: float,
    ) -> str:
        if regime is None:
            return "INSUFFICIENT_WEEKLY_HISTORY"
        stage, _, _, weekly_extension = regime
        if stage not in {"STAGE1_TO_2", "EARLY_STAGE2"}:
            return "REJECT_STAGE" if stage != "STAGE2_EXTENDED" else "EXTENDED"
        if weekly_extension > 20.0 or price_vs_ema8 > 6.0 or runup_20d > 25.0:
            return "EXTENDED"
        return "TRANSITION_CANDIDATE" if stage == "STAGE1_TO_2" else "EARLY_STAGE2_CANDIDATE"

    @staticmethod
    def _qualifies(row: sqlite3.Row) -> bool:
        required = (
            "Close", "EMA8", "EMA21", "DIPlus", "DIMinus",
            "DIPlus_Slope_5D", "MACDTimingHist", "MACDTimingHist_Slope_5D",
        )
        if any(row[name] is None for name in required) or not row["EMA8"]:
            return False
        price_vs_ema8 = 100.0 * (float(row["Close"]) / float(row["EMA8"]) - 1.0)
        return (
            str(row["BullishStructure"]).strip().upper() in {"1", "TRUE", "BULL", "BULLISH"}
            and float(row["EMA8"]) >= float(row["EMA21"])
            and float(row["DIPlus"]) > float(row["DIMinus"])
            and float(row["DIPlus_Slope_5D"]) > 0
            and float(row["MACDTimingHist"]) > 0
            and float(row["MACDTimingHist_Slope_5D"]) > 0
            and -1.0 <= price_vs_ema8 <= 4.0
        )

    @staticmethod
    def _measure(
        symbol: str, signal: sqlite3.Row, bars: list[sqlite3.Row], index: int,
        regime: tuple[str, float, float, float] | None,
    ) -> PilotEvent:
        entry = float(signal["Close"])
        price_vs_ema8 = 100.0 * (entry / float(signal["EMA8"]) - 1.0)
        prior_20 = [float(bar["low"]) for bar in bars[max(0, index - 19):index + 1]
                    if bar["low"] is not None]
        runup_20d = 100.0 * (entry / min(prior_20) - 1.0) if prior_20 else 0.0
        future = bars[index + 1:index + 1 + PilotStudy.HORIZON]

        def close_return(day: int) -> float | None:
            if len(future) < day or future[day - 1]["close"] is None:
                return None
            return round(100.0 * (float(future[day - 1]["close"]) / entry - 1.0), 2)

        valid = [row for row in future if row["high"] is not None and row["low"] is not None]
        max_gain = max((100.0 * (float(row["high"]) / entry - 1.0) for row in valid), default=None)
        max_loss = min((100.0 * (float(row["low"]) / entry - 1.0) for row in valid), default=None)

        def first_hit(multiplier: float, field: str, comparison: str) -> str | None:
            for bar in valid:
                value = float(bar[field])
                if (comparison == "ge" and value >= entry * multiplier) or (
                    comparison == "le" and value <= entry * multiplier
                ):
                    return str(bar["date"])
            return None

        hit_5 = first_hit(1.05, "high", "ge")
        hit_10 = first_hit(1.10, "high", "ge")
        hit_minus5 = first_hit(0.95, "low", "le")
        if hit_5 and hit_minus5:
            first_outcome = "TARGET_FIRST" if hit_5 < hit_minus5 else (
                "STOP_FIRST" if hit_minus5 < hit_5 else "SAME_DAY_AMBIGUOUS"
            )
        elif hit_5:
            first_outcome = "TARGET_FIRST"
        elif hit_minus5:
            first_outcome = "STOP_FIRST"
        else:
            first_outcome = "NEITHER"

        complete = len(future) >= PilotStudy.HORIZON
        weekly_stage, weekly_ma, weekly_slope, weekly_distance = regime or (
            "UNKNOWN", None, None, None,
        )
        return PilotEvent(
            symbol=symbol,
            signal_date=str(signal["date"]),
            entry_close=round(entry, 4),
            price_vs_ema8_pct=round(price_vs_ema8, 2),
            di_plus=round(float(signal["DIPlus"]), 2),
            di_minus=round(float(signal["DIMinus"]), 2),
            di_plus_slope_5d=round(float(signal["DIPlus_Slope_5D"]), 3),
            adx=round(float(signal["ADX"]), 2) if signal["ADX"] is not None else 0.0,
            timing_hist=round(float(signal["MACDTimingHist"]), 4),
            timing_slope_5d=round(float(signal["MACDTimingHist_Slope_5D"]), 4),
            weinstein_stage=weekly_stage,
            weekly_ma30=round(weekly_ma, 4) if weekly_ma is not None else None,
            weekly_ma30_slope_5w_pct=(
                round(weekly_slope, 2) if weekly_slope is not None else None
            ),
            price_vs_weekly_ma30_pct=(
                round(weekly_distance, 2) if weekly_distance is not None else None
            ),
            runup_20d_pct=round(runup_20d, 2),
            entry_classification=PilotStudy._entry_classification(
                regime, price_vs_ema8, runup_20d,
            ),
            outcome_status="COMPLETE" if complete else "OPEN",
            return_5d_pct=close_return(5),
            return_10d_pct=close_return(10),
            return_20d_pct=close_return(20),
            max_gain_20d_pct=round(max_gain, 2) if max_gain is not None else None,
            max_drawdown_20d_pct=round(max_loss, 2) if max_loss is not None else None,
            hit_5pct_date=hit_5,
            hit_10pct_date=hit_10,
            hit_minus5pct_date=hit_minus5,
            first_5pct_outcome=first_outcome,
        )


def write_csv(path: str | Path, events: list[PilotEvent]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = list(PilotEvent.__dataclass_fields__)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(asdict(event) for event in events)
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a one-symbol historical ignition study")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--cooldown", type=int, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    events = PilotStudy(args.db).run(args.symbol, cooldown=args.cooldown)
    if args.output:
        print(write_csv(args.output, events).resolve())
    else:
        for event in events:
            print(asdict(event))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
