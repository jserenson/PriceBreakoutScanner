# PriceBreakoutScanner 1.1

PriceBreakoutScanner ranks stocks from raw end-of-day `price_history`. Atlas
TradeScore and TradeGrade are retained as optional comparison columns, but they
do not drive the default ranking or eligibility rules.

The scanner opens SQLite in read-only mode. Its default source is the actively
updated nightly database:

```text
/Users/jamesserenson/Documents/AnacondaProjects/Stage5_SymbolDatabase/symbols.db
```

## Run

```bash
PYTHONPATH=src python3 -m price_breakout_scanner
```

The default scan uses the newest **complete** session, price-action score >=55,
20-day average dollar volume >=$1 million, and the top 20 results. A session is
complete when its distinct-symbol coverage is at least 95% of the median across
recent prior sessions. This prevents a partially loaded current date from being
ranked as if it were final.

```bash
# Show coverage and complete/partial status
PYTHONPATH=src python3 -m price_breakout_scanner --dates

# Validate a known example or scan a completed historical session
PYTHONPATH=src python3 -m price_breakout_scanner --date 2026-08-13 --symbol NET --min-score 0

# Raise the price-action threshold
PYTHONPATH=src python3 -m price_breakout_scanner --min-score 75 --limit 50

# Legacy grade is optional; specify it only when comparison filtering is wanted
PYTHONPATH=src python3 -m price_breakout_scanner --grades A,B

# Export the same ranked records
PYTHONPATH=src python3 -m price_breakout_scanner --limit 100 --export reports/latest.csv
PYTHONPATH=src python3 -m price_breakout_scanner --limit 100 --export reports/latest.json
PYTHONPATH=src python3 -m price_breakout_scanner --limit 100 --export reports/latest.xlsx
```

Excel output uses Menlo Regular at 16 points, freezes the top row, provides
filters and banded rows, sizes columns to content, and includes a Methodology
worksheet.

## Price-action model

The score is capped to 0–100. All calculations use only bars through the selected
date. Resistance explicitly excludes the current bar to avoid look-ahead bias.

| Component | Max | Formula and thresholds |
|---|---:|---|
| Consolidation | 20 | `range10 = (max(high,10)-min(low,10))/close`; `tightening = range10/range40`. Tightening earns 12/8/4 points at <=0.55/0.75/1.00. Range earns 8/5/2 at <=8%/12%/18%. |
| Higher lows | 15 | Compare minimum low over the newest 10 bars with the prior 10. >=0% earns 15; >=-2% earns 8. |
| Resistance | 20 | Resistance is the highest high in the prior 20 bars. A fresh breakout of 0–5% earns 20; distance below resistance of <=3%/7%/12% earns 18/12/5. |
| Volume | 15 | Current volume is compared with the prior 20-day average. >=1.5x/1.2x earns 15/11. Otherwise prior-5-day contraction versus prior-20-day volume earns 10/7 at <=0.75x/0.90x. |
| Momentum/trend | 15 | Improving positive 5-day momentum earns 8 (positive earns 4); close>SMA20 earns 4; SMA20>SMA50 earns 3. |
| Weinstein context | 15 | Stage 2/1/3/4 contributes 15/8/2/-5. Stored `weinstein_stages` is used when available. Otherwise the stage is derived from close vs SMA150 and the 20-day change in SMA150. |
| Overextension | penalty | Close >7%/10%/15% above SMA20 subtracts 5/10/15. More than 8% beyond resistance subtracts another 10. |

### Mature-trend safeguards

Stage 2 alone is not enough. The scanner now measures whether a stock is early
in a move or simply pausing after a long advance:

- `runup_60d_pct = close / minimum(low, 60) - 1`. Run-ups above 25%, 35%, and
  50% subtract 8, 15, and 22 points.
- `ema8_ema50_spread_pct = EMA8 / EMA50 - 1`. Separation above 6%, 9%, and 12%
  subtracts 6, 12, and 18 points.
- A reset bar requires `close <= EMA20 * 1.02` and EMA8/EMA50 separation <=6%.
  More than 25 bars since reset subtracts 8 points; more than 40 bars (or no
  reset within 60 bars) subtracts 12.
- A non-breakout `READY`/`TIGHTENING` candidate with both >30% 60-day run-up and
  >9% EMA separation loses an additional 10 points.
- A confirmed 0–5% breakout with current volume >=1.2x its prior-20-day average
  still carries maturity risk, but the maturity penalty is capped at 20. This
  keeps genuine price/volume confirmation reviewable without allowing a mature
  trend to receive an unqualified top score.

The output exposes the run-up, EMA spread, reset age, and total maturity penalty.
For example, AAMI on 2026-08-14 falls from 93 to 48 because its 36% 60-day
run-up, 11.6% EMA spread, and 30-bar reset age describe a mature trend rather
than an early base. NET on 2026-08-13 remains at the default threshold because
its price/volume breakout is confirmed, but its extension is still visible and
penalized.

Setup labels:

- `BREAKOUT`: 0–5% above prior resistance with volume >=1.2x.
- `READY`: no more than 3% below prior resistance.
- `TIGHTENING`: 10D/40D range ratio <=0.75 and 10-day range <=12%.
- `WATCH`: passes score/liquidity filters but is not in a nearer trigger state.

`NET` on 2026-08-13 is a useful validation example: it is recognized as a
price/volume breakout by the new model even though its optional legacy grade is B.
No other prior winner list exists in this repository's tracked history yet.

## Current limitations

- This is an end-of-day heuristic, not an intraday entry or execution system.
- No market-regime, relative-strength benchmark, earnings/news, fundamentals, or
  event-risk model is included yet.
- Computed Weinstein stages are a daily approximation when the source database
  does not contain the stored stage table.
- The resistance model uses a fixed 20-session window and does not yet detect
  hand-drawn multi-month bases or adjust thresholds by volatility regime.
- Thin or stale securities can still require review even after the dollar-volume
  filter. The output is a research shortlist, not investment advice.

## Configuration and tests

Use a different database without changing code:

```bash
PRICE_BREAKOUT_DB=/path/to/database.db PYTHONPATH=src python3 -m price_breakout_scanner
```

Run tests:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
