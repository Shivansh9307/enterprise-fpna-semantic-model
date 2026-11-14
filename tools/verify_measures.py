#!/usr/bin/env python3
"""Independent check of the Power BI measures against the synthetic CSVs.

The model's DAX results are exported to tests/results/*.csv by tools/run_dax.ps1. This script recomputes the same
numbers with pandas, straight from data/*.csv, and compares them. It shares no logic with the model: the time
logic here is plain month arithmetic.

    .venv/Scripts/python tools/verify_measures.py            # every check that has a result file
    .venv/Scripts/python tools/verify_measures.py --stage 2

All figures are synthetic (fictional Halcyon Group). Exit code 1 if any comparison fails.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA, RESULTS = ROOT / "data", ROOT / "tests" / "results"
# Amounts within 0.01 GBP. Ratios within one part in a million of their size: the model stores local amounts as
# fixed decimals (4 places) while pandas uses floats, which moves ratios in about the ninth significant digit.
AMOUNT_TOL, RATIO_TOL = 0.01, 1e-6


def load():
    gl = pd.read_csv(DATA / "Fact_GL.csv", parse_dates=["PeriodDate"])
    plan = pd.read_csv(DATA / "Fact_Plan.csv", parse_dates=["PeriodDate"])
    fx = pd.read_csv(DATA / "Dim_FX.csv", parse_dates=["PeriodDate"])
    acc = pd.read_csv(DATA / "Dim_Account.csv")[["AccountKey", "PLGroupL1", "PLGroupL2", "InEBITDA"]]
    ent = pd.read_csv(DATA / "Dim_Entity.csv")[["EntityKey", "EntityCode"]]
    key = ["PeriodDate", "CurrencyCode"]
    actual = gl.merge(fx, on=key).merge(acc, on="AccountKey").merge(ent, on="EntityKey")
    actual["gbp"] = -actual["AmountLocal"] * actual["AvgRateToGBP"]  # profit-impact sign
    budget = plan[plan.ScenarioKey == 2].merge(fx, on=key).merge(acc, on="AccountKey").merge(ent, on="EntityKey")
    budget["gbp"] = -budget["AmountLocal"] * budget["BudgetRateToGBP"]
    for df in (actual, budget):
        df["month"] = df["PeriodDate"].dt.to_period("M")
    return actual, budget


def monthly(df, mask=None):
    d = df if mask is None else df[mask(df)]
    return d.groupby("month")["gbp"].sum().to_dict()


def total(series, months):
    vals = [series[m] for m in months if m in series]
    return sum(vals) if vals else None


def minus(a, b):
    return None if a is None and b is None else (a or 0.0) - (b or 0.0)


def ratio(n, d):
    return None if n is None or not d else n / abs(d)


def measures(ctx, s, first, last_actual):
    """All stage 2 measures for a context given as a list of months. s holds monthly series for the slice."""
    a, b = s["a"], s["b"]
    closed = [m for m in ctx if m <= last_actual]
    last = max(closed) if closed else None
    ytd = [m for m in pd.period_range(first, last) if m.year == last.year] if last else []
    qtd = [m for m in ytd if m.quarter == last.quarter]
    out = {"Actual": total(a, ctx), "Budget": total(b, ctx), "Budget (Closed Periods)": total(b, closed)}
    out["Actual MTD"] = total(a, [last]) if last else None
    out["Actual QTD"] = total(a, qtd)
    out["Actual YTD"] = total(a, ytd)
    out["Actual PY"] = total(a, [m - 12 for m in closed])
    out["Actual PY YTD"] = total(a, [m - 12 for m in ytd])
    both = out["Actual"] is not None and out["Actual PY"] is not None
    out["YoY"] = out["Actual"] - out["Actual PY"] if both else None
    out["YoY %"] = ratio(out["YoY"], out["Actual PY"])
    out["YTD YoY %"] = ratio(minus(out["Actual YTD"], out["Actual PY YTD"]), out["Actual PY YTD"])
    out["Actual R12M"] = total(a, list(pd.period_range(last - 11, last))) if last and last - 11 >= first else None
    out["Actual R12M PY"] = total(a, list(pd.period_range(last - 23, last - 12))) if last and last - 23 >= first else None
    out["Budget YTD"] = total(b, ytd)
    out["Budget PY"] = total(b, [m - 12 for m in ctx])
    out["Var to Budget"] = minus(out["Actual"], out["Budget (Closed Periods)"])
    out["Var to Budget %"] = ratio(out["Var to Budget"], out["Budget (Closed Periods)"])
    out["Var to Budget YTD"] = minus(out["Actual YTD"], out["Budget YTD"])
    out["Var to Budget YTD %"] = ratio(out["Var to Budget YTD"], out["Budget YTD"])
    out["Revenue Var to Budget"] = minus(total(s["a_rev"], ctx), total(s["b_rev"], closed))
    out["EBITDA Var to Budget"] = minus(total(s["a_ebitda"], ctx), total(s["b_ebitda"], closed))
    return out


def context(kind, key):
    if kind == "month":
        return [pd.Period(f"{int(key) // 100}-{int(key) % 100:02d}", "M")]
    if kind == "year":
        return list(pd.period_range(f"{int(key)}-01", f"{int(key)}-12", freq="M"))
    year, q = str(key).split(" Q")
    return [m for m in pd.period_range(f"{year}-01", f"{year}-12", freq="M") if m.quarter == int(q)]


GRIDS = {  # result file -> (key column, context kind, slice filter)
    "stage2_03_monthly_total": ("Year Month Key", "month", None),
    "stage2_04_monthly_revenue": ("Year Month Key", "month", lambda d: d.PLGroupL1 == "Revenue"),
    "stage2_05_monthly_us01_ebitda": ("Year Month Key", "month", lambda d: (d.EntityCode == "US01") & (d.InEBITDA == 1)),
    "stage2_06_yearly_total": ("Year", "year", None),
    "stage2_07_quarterly_de01": ("Year Quarter", "quarter", lambda d: d.EntityCode == "DE01"),
}


def check_grid(name, actual, budget):
    key_col, kind, mask = GRIDS[name]
    both = lambda extra: (lambda d: (mask(d) if mask else True) & extra(d))
    s = {"a": monthly(actual, mask), "b": monthly(budget, mask),
         "a_rev": monthly(actual, both(lambda d: d.PLGroupL1 == "Revenue")), "b_rev": monthly(budget, both(lambda d: d.PLGroupL1 == "Revenue")),
         "a_ebitda": monthly(actual, both(lambda d: d.InEBITDA == 1)), "b_ebitda": monthly(budget, both(lambda d: d.InEBITDA == 1))}
    first, last_actual = min(monthly(actual)), max(monthly(actual))
    dax = pd.read_csv(RESULTS / f"{name}.csv")
    compared = failed = 0
    worst = 0.0
    problems = []
    for _, row in dax.iterrows():
        want = measures(context(kind, row[key_col]), s, first, last_actual)
        for m, w in want.items():
            got = None if pd.isna(row[m]) else float(row[m])
            compared += 1
            tol = RATIO_TOL * max(1.0, abs(w or 0.0)) if m.endswith("%") else AMOUNT_TOL
            if (got is None) != (w is None) or (got is not None and abs(got - w) > tol):
                failed += 1
                problems.append(f"    {row[key_col]} | {m}: model {got} vs pandas {w}")
            elif got is not None and not m.endswith("%"):
                worst = max(worst, abs(got - w))
    # every context pandas can compute must be present in the model output
    all_keys = {"month": [m.year * 100 + m.month for m in pd.period_range("2024-01", "2026-12", freq="M")],
                "year": [2024, 2025, 2026],
                "quarter": [f"{y} Q{q}" for y in (2024, 2025, 2026) for q in (1, 2, 3, 4)]}[kind]
    missing = [k for k in all_keys if k not in set(dax[key_col])
               and any(v is not None for v in measures(context(kind, k), s, first, last_actual).values())]
    for k in missing:
        failed += 1
        problems.append(f"    {k}: row missing from the model output")
    print(f"{'PASS' if not failed else 'FAIL'}  {name}: {len(dax)} rows, {compared} values compared, {failed} failed, largest amount difference {worst:.4f}")
    print("\n".join(problems[:15]))
    return failed


HEADLINES = ["revenue_gbp", "cost_of_sales_gbp", "gross_profit_gbp", "gross_margin_pct", "ebitda_gbp", "ebitda_margin_pct"]


def check_expected(stage):
    exp = json.loads((DATA / "expected.json").read_text())
    pairs = []  # (label, model value, expected value)

    def headline(file, block):
        row = pd.read_csv(RESULTS / f"{file}.csv").iloc[0]
        pairs.extend((f"{block}.{k}", float(row[k]), exp[block][k]) for k in HEADLINES)

    def by_group(file, key_col, value_col, expected, label):
        got = pd.read_csv(RESULTS / f"{file}.csv").set_index(key_col)[value_col]
        pairs.extend((f"{label}.{k}", float(got[k]), v) for k, v in expected.items())

    if stage == 1:
        headline("stage1_02_fy2025_actual", "fy2025_actual")
        headline("stage1_03_fy2025_budget", "fy2025_budget")
        by_group("stage1_04_fy2025_opex_by_l2", "P&L Group L2", "actual_opex_gbp", exp["fy2025_actual"]["opex_by_l2_gbp"], "fy2025_actual.opex")
        by_group("stage1_04_fy2025_opex_by_l2", "P&L Group L2", "budget_opex_gbp", exp["fy2025_budget"]["opex_by_l2_gbp"], "fy2025_budget.opex")
        by_group("stage1_05_fy2025_revenue_by_entity", "Entity Code", "revenue_gbp", exp["fy2025_actual_revenue_by_entity_gbp"], "fy2025_revenue_by_entity")
        counts = pd.read_csv(RESULTS / "stage1_01_row_counts.csv").iloc[0]
        for k, v in exp["row_counts"].items():
            if k in counts.index:
                pairs.append((f"row_counts.{k}", float(counts[k]), v + (1 if k == "Dim_Customer" else 0)))  # +1: the -1 "No customer" row
    else:
        headline("stage2_01_ytd_oct2026_expected", "ytd_oct2026_actual")
        by_group("stage2_02_ytd_oct2026_opex_by_l2", "P&L Group L2", "actual_opex_ytd_gbp", exp["ytd_oct2026_actual"]["opex_by_l2_gbp"], "ytd_oct2026_actual.opex")
    failed = 0
    for label, got, want in pairs:
        tol = 0.00005 if label.endswith("_pct") else 0.005  # expected.json is rounded to 4 and 2 decimals
        ok = abs(got - want) <= tol
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  expected.json {label}: model {got:,.4f} vs expected {want:,.4f}")
    return failed


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", type=int, choices=[1, 2], help="check one stage only")
    args = ap.parse_args()
    failed = 0
    for stage in ([args.stage] if args.stage else [1, 2]):
        print(f"--- stage {stage}: data/expected.json (synthetic GBP)")
        failed += check_expected(stage)
        if stage == 2:
            print("--- stage 2: pandas recomputation of time intelligence and budget variance")
            actual, budget = load()
            for name in GRIDS:
                failed += check_grid(name, actual, budget)
    print(f"\n{'ALL CHECKS PASSED' if not failed else str(failed) + ' CHECK(S) FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
