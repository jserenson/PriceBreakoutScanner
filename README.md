# PriceBreakoutScanner 1.5.1

PriceBreakoutScanner is a **bar-by-bar trend-state and synchronized-ignition
detector**. It prefers dividend-unadjusted end-of-day
`price_history_unadjusted`, evaluates roughly six
trading months of structure, and looks for the transition from repair into a
newly confirmed bullish move without confusing an extended or deteriorating
chart with a fresh setup.

Atlas TradeScore and TradeGrade remain optional comparison columns and do not
drive default selection. SQLite is opened read-only. The default nightly source
is:

```text
/Users/jamesserenson/Documents/AnacondaProjects/Stage5_SymbolDatabase/symbols.db
```

Production scans use `price_history_unadjusted` and retain adjusted close only
as reference data. Small legacy and unit-test databases may fall back to
`price_history`; the CLI prints the selected source on every scan.

## Run

In VS Code select **Run PriceBreakoutScanner** and press `F5`. Select **Export
PriceBreakoutScanner Excel** to create `reports/latest.xlsx`.

Terminal equivalents:

```bash
PYTHONPATH=src python3 -m price_breakout_scanner
PYTHONPATH=src python3 -m price_breakout_scanner --limit 100 --export reports/latest.xlsx
PYTHONPATH=src python3 -m price_breakout_scanner --dates
```

The newest session is used only when its symbol coverage is at least 95% of the
recent-session median. Defaults are score >=55, 20-day dollar volume >=$1
million, and 20 rows. `--min-score 0 --symbol VRTX` exposes rejected/watch
diagnostics for research.

## Indicator definitions

All signals use data through the selected date—there is no look-ahead.

- **DI+/DI-/ADX:** Wilder 14. `bars_since_di_cross` starts when DI+ crosses
  above DI-. Confirmation requires DI+ to remain above DI- on the most recent
  bars and at least 70% of bars since the cross. ADX is sampled at the cross;
  low ADX is allowed because chart research showed it may strengthen later.
- **Clean Squeeze + Momentum v2:** exact supplied ThinkScript parameters:
  length 21, population standard deviation 2.0, simple 21-bar average true
  range 1.5, and Mobius-style Inertia momentum using EMA21 in the midpoint.
  Momentum, squeeze state, squeeze count, release, and 3-bar slope are reported.
- **Chart TMO:** `close - close[14]`, smoothed by EMA5 twice, with an EMA3 signal.
  Main value, signal value, and 3-bar slope are reported.
- **MACD Trend:** chart 24/52/9 histogram and 3-bar slope.
- **MACD Timing:** chart 3/10/16 histogram and 3-bar slope.
- **Bullish structure:** close > EMA20, EMA8 > EMA20, and EMA20 at least 98% of
  EMA50. The scanner records when this structure was most recently restored.
- **EMA separation:** `(EMA8 / EMA50 - 1) * 100`.
- **Six-month structure quality:** every one of the latest 126 trading bars is
  scored for price above EMA8, EMA8 above EMA21, EMA21 above EMA50, and positive
  one-bar slopes in all three EMAs. The report includes the resulting percentage
  and the number of fully aligned bars.
- **Deterioration:** the latest bar is checked separately so a still-positive
  +DI, TMO, Squeeze, or MACD histogram cannot hide that it has rolled over.

These formulas are locally reproducible versions of the supplied ThinkScript.
Small platform differences may remain from initialization or rounding; the
scanner therefore reports the underlying values and slopes.

## Synchronized ignition and states

A synchronized ignition requires a DI+ cross in the preceding five bars,
bullish structure, and at least four of these five confirmations:

1. Price above EMA8.
2. MACD Trend positive and rising.
3. MACD Timing positive and rising.
4. TMO rising.
5. Squeeze momentum rising.

Current lifecycle states are **REPAIRING**, **PRIMED**, **CONFIRMED**,
**CONFIRMED_EXTENDED**, **WEAKENING**, and **BROKEN**. Structure and entry risk
remain separate: a chart may retain excellent EMA structure while being marked
extended, and a positive DI crossover is downgraded when +DI and its spread roll
over on the newest bar. Flat EMA ribbons remain repairing rather than receiving
full trend credit.

Results are presented in five entry-readiness buckets, in this order:
**CONFIRMED_NOT_EXTENDED**, **CONFIRMED_EXTENDED**,
**PRIMED_EARLY_EXPANSION**, **REPAIRING_STRUCTURE**, and
**WATCH_MOMENTUM_NOT_READY**. Scores rank charts only within that review order,
so a short-term momentum burst in a repairing structure cannot displace a
fully aligned confirmed setup. Distance above EMA8/EMA21 remains visible and
drives the extended bucket and its score penalty.

This design intentionally rejects stale/current strong-stock false positives.
CAT, CMI, DE, GE, IR, ITW, NVO, and ROK are rejected on the 2026-08-14 review
date. MRK is an established continuation; EMR, PFE, PH, and VRTX are watches
without current multi-lane confirmation. All are excluded by the default score
threshold.

## Historical validation

Chart-research anchors are approximate visual dates, so nearby trading sessions
are reviewed rather than tuned as exact labels. Confirmed examples include:

- ETN around 2026-04-13: `EMERGING`.
- GE around 2026-06-01: `EMERGING`.
- ITW around 2026-02-02: `EMERGING`, including the observed low-ADX ignition.
- EMR transitions into a fresh ignition shortly after the approximate 12/29
  chart anchor (2026-01-05 in the database).
- HON’s post-6/15 cross fails by 2026-06-23 and is rejected without using future
  bars in the 6/23 calculation.

ETN around 2026-01-12 and GE around 2025-12-08 do not qualify under the current
OHLC-derived structure rule on those exact database dates. They remain recorded
as unresolved validation differences rather than being force-fit.

### One-symbol outcome pilot

Before turning visual chart observations into elimination rules, run the
mechanical early-ignition pilot on one symbol. It records only the first day of
each qualifying episode, then measures 5/10/20-session returns, maximum
favorable and adverse excursion, and whether +5%, +10%, or -5% was reached.

```bash
PYTHONPATH=src python3 -m price_breakout_scanner.pilot_study \
  --symbol WTI --output reports/WTI-pilot-events.csv
```

The source database remains read-only. The latest event can be marked `OPEN`
when 20 future sessions do not yet exist and is excluded from completed-event
conclusions.

The pilot also derives a no-look-ahead Weinstein regime from weekly closes and
the 30-week moving average. Entry classification uses that regime plus price
extension. All daily indicators are calculated independently from raw OHLCV;
`symbol_analysis` and `Stage5Active` are deliberately not used to identify or
validate entries.

The timing trigger uses the current bar plus the three-day MACD Timing slope.
The five-day slope remains in the diagnostic output but is not a gate because
an older spike can keep it negative after the current histogram has turned up.
The WTI chart reviewed on 2026-08-19 is therefore represented by its latest
completed session, 2026-08-18 ($3.83 close). It is detected while the rejected
2025-07-30 and 2025-08-26 signals remain excluded.

## Event-risk limitation

The current database has no earnings or corporate-event calendar. `event_risk`
is therefore always `UNKNOWN`. The scanner does not imply that any candidate is
safe to hold through earnings. Other limitations include no intraday timing,
benchmark-relative strength, broad-market regime, fundamentals, or news model.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
