# Data dictionary (synthetic)

**All data is fictional.** "Halcyon Group" and its customers, people and figures do not exist. Rebuild with
`python tools/generate_data.py --out data` (seed 20261114, scale 1.0). `--scale 3` or higher gives a larger model for performance testing.
`data/expected.json` holds headline numbers computed independently with pandas; the Power BI model must reproduce them.

## Shape
A four-entity software and services group reporting in GBP. Actuals Jan 2024 to Oct 2026; Budget Jan 2024 to Dec 2026; Forecast FY2026
(Jan to Oct equal actuals, Nov and Dec projected). Local currencies GBP, USD, EUR, INR.

| Table | Rows (seed 20261114) | Grain |
|---|---|---|
| Fact_GL | 307,697 | one journal line (P&L accounts only) |
| Fact_Plan | 4,992 | month x scenario x entity x account x cost centre (Budget and Forecast) |
| Dim_Account | 30 | chart of accounts with P&L hierarchy |
| Dim_CostCentre | 31 | department x entity |
| Dim_Entity | 4 | legal entity |
| Dim_Customer | 2,500 | customer (revenue lines only) |
| Dim_FX | 144 | month x currency |
| Dim_Scenario | 3 | Actual, Budget, Forecast |
| Dim_UserEntityMap | 12 | fictional user x entity, for row-level security tests |

There is no date CSV: build the date table in the model (a `CALENDAR` over 2024 to 2026 with fiscal fields).

## Columns that need explaining
- **AmountLocal** (Fact_GL, Fact_Plan): local currency, GL convention: debit positive, credit negative. Profit = -SUM(AmountLocal).
  `Dim_Account[NaturalSign]` is -1 for credit-nature accounts (revenue, interest income) and +1 otherwise. Revenue is therefore negative in the ledger.
- **PeriodDate** vs **PostingDate** (Fact_GL): the accounting period is `PeriodDate` (first of month). About 1.5% of lines are late adjustments
  posted in the following month for a prior period. Report by `PeriodDate`.
- **IsAdjustment**: late adjustments, and reversal and rebook pairs (which net to zero).
- **Dim_FX**: rates are local to GBP. Actuals convert at `AvgRateToGBP` of the period. Budget converts at `BudgetRateToGBP`, fixed at the January
  rate of each year, so constant-currency and FX variance can be built. `CloseRateToGBP` is there for completeness (the ledger has no balance sheet).
- **Forecast rate** (not a column in the CSV): Forecast converts at `AvgRateToGBP` of the period up to the last month that has actuals
  (Oct 2026), then at that month's rate held flat. The generator builds the Nov and Dec 2026 forecast amounts at the Oct 2026 average rate,
  so the simulated Nov and Dec 2026 rows of `AvgRateToGBP` must not be used for the forecast. The model derives this rate in Power Query
  as `Forecast Rate To GBP`.
- **Dim_Account[InEBITDA]**: 1 for revenue, cost of sales and operating expenses; 0 for depreciation, amortisation, finance items and tax.
- **Dim_Customer[StartMonth]**: first month the customer appears in the data (customers that predate 2024 show Jan 2024).
- **Dim_UserEntityMap**: `cfo@` and `controller@` map to all four entities; each `xx.fpa@` maps to one. All on the reserved `halcyon.example` domain.

## Known limits (do not hide these in the report)
- P&L only. Journals are not balanced double entry and there is no balance sheet or cash flow.
- Tax is a smoothed placeholder, not a tax computation. FX gains and losses are random noise around zero.
- No headcount table: salary lines are generated per team, not per employee.
- Budget is generated from the same underlying plan as the actuals with a bias, so variances are plausible but synthetic.

## Planted stories (for the dashboard narrative; each is visible in the data)
1. Hosting and Infrastructure runs about 30% over plan from Jun to Aug 2025.
2. Germany revenue dips about 15% in Q3 2025, then recovers.
3. A large third-party licence renewal in Mar 2026 (about 1.8x the normal month).
4. India engineering salaries run about 30% under plan from Apr to Jun 2026 (vacancies).
5. A one-off bad debt charge in Dec 2025 (about 4x normal).
6. A USD shock of about -6% at the start of FY2026, which opens a gap between reported and constant-currency results **year on year**
   (FY2026 actuals converted at FY2025 rates). It does not show against budget rates: the FY2026 budget rate is the January 2026 rate,
   which is already after the shock. Tested in the model for US01 revenue, Jan to Oct 2026 against Jan to Oct 2025 (synthetic GBP):
   reported growth 3,716,026, constant-currency growth 5,457,467, FX impact -1,741,441; FX variance to budget only +152,186.
7. Budget revenue is about 6% optimistic against actuals, so revenue variance is negative throughout.
