# Performance and best-practice results (stage 5)

**All data is synthetic** (fictional Halcyon Group, seed 20261114, scale 1.0: 307,697 ledger lines). Everything on this page was
run on one Windows laptop on 2026-11-15 unless it is marked "not run". Timings rank queries against each other; they are not
absolute figures and will differ on other hardware and in the Power BI service.

## Tools

| Job | Tool |
|---|---|
| Model size (VertiPaq Analyzer) | DAX Studio 3.6.2 command line, `dscmd vpax` |
| Query timings | `dscmd benchmark`: 5 cold-cache and 5 warm-cache runs per query, through `tools/run_dax.ps1 -Benchmark` |
| Model best-practice analysis | Tabular Editor 2.29.0, read-only, with Microsoft's rule set (71 rules, `BestPracticeRules/BPARules.json` in the `microsoft/Analysis-Services` repository) |
| Engine | Power BI Desktop 2.159.1231.0 (Store build), local model |

## Result in one paragraph

Nothing in the model is slow at this data size: the slowest of 59 measures takes 84 ms on a cold cache and the slowest
visual-shaped query 197 ms. The work that paid off was on model size and hygiene: switching off attribute hierarchies on
36 hidden columns and removing two unused columns cut the reported model size from 34.3 MB to 24.2 MB and the ledger table
from 8.1 MB to 4.4 MB, and best-practice findings fell from 139 to 40, all of the rest intentional.

## Model size

| | Before | After |
|---|---:|---:|
| Model total | 34.32 MB | 24.15 MB |
| `GL` table | 8.13 MB | 4.41 MB |
| Attribute hierarchies, all columns | 781 KB | 33 KB |
| Column data, all columns | 2.72 MB | 2.72 MB |
| Columns | 76 | 74 |

Read the totals with care: 19 visible text columns each still report a dictionary of about 1.07 MB, which is an allocation the
engine makes when a text column is first loaded, not real content. Hidden columns with attribute hierarchies switched off
report their true dictionary size. The real content of the model is close to 4 MB, nearly all of it in `GL`.

Largest `GL` columns after the changes:

| Column | Size | Note |
|---|---:|---|
| `Amount Local` | 1,231 KB | 133,112 distinct values; the only amount column |
| `Journal ID` | 1,058 KB | 15,137 distinct values; hidden, not used by any measure. Removed after this measurement |
| `Customer Key` | 523 KB | relationship key |
| `Posting Date` | 403 KB | inactive relationship, used by `Posted MTD` |
| `Description` | 50 KB | 407 distinct values; hidden, not used by any measure |

**Decision, `Journal ID` and `Description`:** `Journal ID` (1,058 KB, 24% of the ledger table, used by nothing) was removed after
these measurements; `Description` (50 KB) is kept, hidden. The sizes on this page are from before that removal.

## Query timings

Each measure was timed alone in a typical matrix shape (by month, entity and P&L group; `tests/perf/measure_*.dax`).
Of 59 measures, 45 run in under 30 ms cold; the median is 20 ms. The slowest twelve:

| Measure query | Cold median ms | Cold max ms | Warm median ms | Formula engine ms | Storage engine ms | Storage engine queries | Rows |
|---|---:|---:|---:|---:|---:|---:|---:|
| `P&L Value` (by line, month, entity) | 84 | 97 | 70 | 60 | 19 | 35 | 1,496 |
| `Forecast vs Budget FY %` | 55 | 67 | 44 | 24 | 30 | 31 | 432 |
| `Var to Budget YTD %` | 50 | 55 | 38 | 35 | 9 | 11 | 1,224 |
| `Actual YTD + Forecast Remaining` | 47 | 52 | 31 | 23 | 20 | 29 | 1,296 |
| `Var to Budget YTD` | 47 | 52 | 33 | 36 | 1 | 11 | 1,224 |
| `YoY %` | 44 | 91 | 23 | 26 | 18 | 11 | 792 |
| `Forecast vs Actual PY %` | 43 | 51 | 31 | 26 | 17 | 23 | 432 |
| `Posted MTD` | 42 | 47 | 34 | 23 | 15 | 9 | 1,238 |
| `YTD YoY %` | 40 | 45 | 27 | 27 | 11 | 11 | 792 |
| `Forecast vs Budget FY` | 35 | 40 | 28 | 11 | 21 | 27 | 432 |
| `Budget FY` | 33 | 40 | 27 | 19 | 11 | 15 | 1,296 |
| `Actual YTD` | 31 | 36 | 23 | 22 | 7 | 8 | 1,224 |

Four queries shaped like report visuals (`tests/perf/visual_*.dax`):

| Visual-shaped query | Cold median ms | Cold max ms | Warm median ms | Formula engine ms | Storage engine ms | Storage engine queries | Rows |
|---|---:|---:|---:|---:|---:|---:|---:|
| Revenue and `YoY %` by customer and year | 197 | 233 | 139 | 125 | 59 | 13 | 5,787 |
| P&L statement by month (`P&L Value`) | 60 | 67 | 42 | 40 | 19 | 34 | 374 |
| Rolling 12 months and year to date by month and entity | 45 | 50 | 32 | 30 | 20 | 17 | 136 |
| Variance matrix, nine measures by account and entity | 34 | 39 | 25 | 23 | 9 | 13 | 104 |

What the numbers say:

- `P&L Value` is the slowest measure because its `SWITCH` evaluates up to eleven line measures, which shows as 35 storage
  engine queries. It is still well under a tenth of a second for a full statement by month and entity.
- The full-year forecast and budget measures issue more storage engine queries (23 to 31) because they remove the date
  filter and re-apply the year for every row.
- The customer query is slowest simply because it returns the most rows; two thirds of its time is formula engine work.
- Most time everywhere is in the formula engine, as expected for a small model with currency conversion in DAX.

The timings were taken before the hygiene changes below were loaded. Those changes do not alter any measure expression.
The full table is produced by `python tools/summarise_benchmarks.py`; raw runs are in `tests/perf/results`.

## Experiment: currency conversion in DAX against a stored GBP column

The model converts currency in DAX at month x currency grain. The alternative is a GBP amount stored on every ledger line.
`tools/perf_stored_gbp_experiment.ps1` added a temporary stored column to the model in memory, timed the same result both
ways on three shapes, and removed the column again.

| Shape | DAX conversion, cold median ms | Stored column, cold median ms | Storage engine queries (DAX / stored) |
|---|---:|---:|---|
| By month, entity and P&L group (1,224 rows) | 17 | 17 | 3 / 1 |
| By account, cost centre and month (3,536 rows) | 43 | 42 | 3 / 1 |
| By customer and year (5,788 rows) | 77 | 48 | 3 / 1 |

The stored column added 821 KB of column data to `GL`, a 30% increase in the model's column data, for one rate set.

**Decision: keep the conversion in DAX.** The stored column wins only on the customer shape, by 29 ms. The model needs four
rate sets (average, budget, forecast, prior year), so the stored design would need four columns, about 3.3 MB, to save tens
of milliseconds. This holds at scale 1.0; it was not tested on a larger data set (see "Not run").

## Model best-practice analysis

| | Findings |
|---|---:|
| Before | 139 |
| After | 40 |

Fixed:

| Rule | Count | Change |
|---|---:|---|
| Set IsAvailableInMdx to false on non-attribute columns | 38 | Switched off on 36 hidden columns; the other two columns were removed |
| Whole numbers should be formatted with thousands separators | 45 of 48 | Measure format strings changed from `#,##0` to `#,0` (same display, the form the rule expects) |
| Percentages should be formatted with thousands separators and 1 decimal | 11 | Changed to `#,0.0%;-#,0.0%;#,0.0%` |
| Remove unnecessary columns | 2 of 5 | Removed `Account[Natural Sign]` and `User Entity Map[Role Name]` |
| Remove unnecessary measures | 1 | `Last Actual Period` unhidden; it is useful in report titles |
| Add data category for columns | 2 | `Country` on the two country columns |

Left as they are, on purpose:

| Rule | Count | Reason |
|---|---:|---|
| Relationship columns should be of integer data type | 9 | Date and currency-code keys. A date-to-date relationship is the standard for a date table, and the currency code has four values |
| Provide format string for "Date" and "Month" columns | 7 | The rule expects the US form `mm/dd/yyyy`; the model uses `dd mmm yyyy` |
| Do not use floating point data types | 4 | FX rates have six decimals; a fixed decimal type keeps four |
| Reduce usage of calculated tables | 3 | `Date`, `P&L Line` and `_Measures`: a few hundred rows in total |
| Minimize Power Query transformations | 3 | The source is local CSV files, so there is no query folding to protect |
| Remove unnecessary columns | 3 | `GL[Journal ID]` (since removed) and `GL[Description]` (kept by decision); `_Measures[Value]` is the placeholder a measure table needs |
| Remove roles with no members | 3 | Members are assigned in the Power BI service, not in the project files |
| Ensure tables have relationships | 3 | `P&L Line`, `User Entity Map` and `_Measures` are disconnected by design |
| Whole numbers should be formatted with thousands separators | 3 | Two hidden local-currency measures show two decimals; `Last Actual Period` is a date |
| Measures should not be direct references of other measures | 1 | `Net Profit` is a named alias of `Actual` for the statement |
| Hide fact table columns | 1 | False positive on `Date[Year]`, which is not a fact column |

After the changes the model was reloaded and every check from stages 1 to 4 was rerun: 66 of 66 pass.

The analysis was rerun on the final model (75 measures, after `Journal ID` was removed and the statement, customer and
ledger-quality measures were added): 41 findings, the same kinds as above. The one new finding is the text measure
`Report Context`, which has no number format because it returns text.

## Not run

- Report best-practice analysis (`pbir bpa`): the report has no visuals yet. It belongs to stage 6.
- Timings of real report visuals: none exist yet. The four visual-shaped queries stand in for them.
- A larger data set (`--scale 3` or more), to see whether the conversion decision and the rankings hold.
- Query plans and server timing traces for individual measures: nothing was slow enough to need them.
- Anything in the Power BI service.
