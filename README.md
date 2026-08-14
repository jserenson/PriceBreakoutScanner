# PriceBreakoutScanner 1.0

PriceBreakoutScanner turns Atlas nightly analysis into a short, ranked list of
trade candidates. It reads the source SQLite database in read-only mode and does
not recalculate or modify Atlas scores.

## Quick start

The default database is:

```text
/Users/jamesserenson/Documents/AnacondaProjects/Atlas-Runs/PriceBreakoutScanner.db
```

Run directly from this checkout:

```bash
PYTHONPATH=src python -m price_breakout_scanner
```

Or install the command into the existing virtual environment:

```bash
myvenv.nosync/bin/python -m pip install -e .
myvenv.nosync/bin/price-breakout-scanner
```

The default scan selects the newest date, requires an Atlas trade score of at
least 70, grade A or B, passing liquidity, bullish structure, and at least $1
million in average 50-day dollar volume. Results are ordered by score.

## Common scans

```bash
# Show recent dates
PYTHONPATH=src python -m price_breakout_scanner --dates

# Scan a historical session
PYTHONPATH=src python -m price_breakout_scanner --date 2026-08-07

# Raise quality threshold and show 10 rows
PYTHONPATH=src python -m price_breakout_scanner --min-score 80 --limit 10

# Inspect selected symbols
PYTHONPATH=src python -m price_breakout_scanner --symbol IDCC --symbol ULTA

# Export a larger result set
PYTHONPATH=src python -m price_breakout_scanner --limit 100 --export reports/latest.csv
PYTHONPATH=src python -m price_breakout_scanner --limit 100 --export reports/latest.json
PYTHONPATH=src python -m price_breakout_scanner --limit 100 --export reports/latest.xlsx
```

Excel exports use Menlo Regular at 16 points, freeze the top row, enable table
filters, and size the columns to their contents (with sensible caps for long text).

Use `--help` for all filters, including archetype, transition, grade, liquidity,
and bullish-structure overrides.

## Database updates

The Atlas nightly job currently uses the legacy `Atlas-Runs.db` path, which is a
symbolic link to `PriceBreakoutScanner.db`. Consequently each nightly run updates
the scanner's canonical database without a copy or synchronization step. The
scanner opens it with SQLite's read-only URI mode.

To use a different database without changing code:

```bash
PRICE_BREAKOUT_DB=/path/to/database.db PYTHONPATH=src python -m price_breakout_scanner
```

## Tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```
