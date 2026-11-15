# Report pages and checks (stage 6)

**All data is synthetic** (fictional Halcyon Group). Every page carries a header line that says so, with the fiscal year,
the last month with actuals, the entities in scope and the currency. The report was built with the `pbir` CLI (0.9.33);
no report file was edited by hand.

## Brief

- **Reader:** a CFO or FP&A reviewer doing the monthly P&L review.
- **Questions:** are we on track against budget; which lines and entities drive the gap; how much is FX; where will FY2026 land.
- **Tone:** restrained. One blue for actuals, grey for the comparison series.
- **Signature:** variance colour. Blue is favourable, orange is adverse, on every page, set once in the theme. The pair stays
  distinguishable for red-green colour-blind readers.
- **Filters:** Year (default 2026) and Entity at report level, in the filter pane.

## Pages (1280 x 720)

| Page | Answers | Visuals |
|---|---|---|
| Overview | Are we on track against budget? | Four KPIs (revenue, gross profit, EBITDA, net profit, year to date against budget), monthly EBITDA actual and budget, EBITDA variance by entity, variance by P&L group, entity table |
| P&L Statement | What does the P&L look like line by line? | Statement from revenue to net profit with actual, budget, variance, variance % and prior year; margins by month; actuals by entity |
| Variance Drivers | Which lines drive the gap, and when? | Variance % by P&L group and month (heat matrix), variance by P&L group and by department, accounts ranked by adverse variance |
| Forecast and FX | Where will the year land, and how much is FX? | Full-year forecast KPIs against budget, monthly EBITDA outlook, reported against constant-currency revenue growth, entity table splitting growth and budget variance into FX and operations |

The KPI and trend visuals use the generic measures (`Actual YTD`, `Budget YTD`, `Forecast FY`, `Actual`, `Budget`) with a
visual-level filter on the account group. That keeps the model free of one measure per line and per time view.

## Checks

| Check | Result |
|---|---|
| `pbir validate --all` (structure, schema, fields against the model, layout) | Passes, no errors. 26 warnings, all listed below as deliberate |
| `pbir bpa run` (report best-practice analysis) | 83 findings before fixes, 35 after, no errors |
| Screenshots of all four pages, captured from Power BI Desktop through `pbir desktop screenshot` | Reviewed against the checked numbers, below |

Fixed after the first best-practice run: alt text added to all 30 visuals (26 findings), drop shadows switched off in the
theme (22 findings).

Left as they are, on purpose:

| Finding | Count | Reason |
|---|---:|---|
| Visual undersized | 12 | The KPIs are 124 px high so that four fit above the charts. They render without clipping in the screenshots |
| Visual-level filters | 10 | The design choice described above: generic measures filtered per visual |
| Missing title | 4 | The header line on each page is a card without a title; it has alt text |
| Oversized card | 4 | The same header line, deliberately wide |
| Too many fields | 4 | The detail tables |
| Hard-coded colour | 1 | White as the midpoint of the variance heat gradient |

## Screenshot review against the checked numbers (FY2026, synthetic GBP)

| Page | Figure on the page | Checked value |
|---|---|---|
| Overview | Revenue year to date 52.1M against budget 55.2M, -6% | 52,093,805 and 55,245,333 (`expected.json`, statement check) |
| Overview | EBITDA year to date 9.3M against budget 13.9M, -33% | 9,280,475 and 13,877,002 |
| Overview | Net profit year to date 6.4M against budget 11.0M, -42% | 6,409,505 and 11,025,681 |
| Overview | Entity table total: revenue 52,093,805, revenue variance -3,151,529, EBITDA 9,280,475, EBITDA variance -4,596,528 | Same values in the stage 2 yearly grid |
| P&L Statement | All eleven lines, five columns | Equal to `tests/results/stage6_01_statement_yearly.csv`, which matches pandas |
| Variance Drivers | Hosting -30.3% in March | Planted story 3, the large licence renewal in March 2026 |
| Variance Drivers | Account table total: 6,409,505 actual, 11,025,681 budget, -4,616,176 variance | Same values in the stage 2 yearly grid |
| Forecast and FX | EBITDA full-year forecast 12.1M against budget 17.8M, -32% | 12,106,346 and 17,820,807 (stage 3 yearly EBITDA grid) |
| Forecast and FX | Net profit full-year forecast 8.7M against budget 14.4M | 8,656,328 and 14,396,793 |
| Forecast and FX | US01 revenue: growth 21.6%, at constant currency 31.7%, FX impact -1,741,441, FX variance 152,186, operational variance -1,317,730 | Same values in the stage 3 US01 revenue grid (planted story 6) |

Screenshots are written to `screenshots/`, which is not committed.

## Not run

- The report in the Power BI service (not published), on a phone layout, or with a screen reader.
- The pages under each security role. Row-level security was tested by DAX queries in stage 4, not by viewing the pages as a role.
- Other years than 2026. The pages work for any year, but only the 2026 view was reviewed. Forecast visuals are blank for years without a forecast.
- Timings of the real visuals. Stage 5 timed stand-in queries before the pages existed.
