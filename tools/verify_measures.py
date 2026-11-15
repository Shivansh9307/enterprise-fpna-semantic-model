#!/usr/bin/env python3
"""Independent check of the Power BI measures against the synthetic CSVs.

The model's DAX results are exported to tests/results/*.csv by tools/run_dax.ps1. This script recomputes the same
numbers with pandas, straight from data/*.csv, and compares them. It shares no logic with the model: the time
logic here is plain month arithmetic.

    .venv/Scripts/python tools/verify_measures.py            # every stage
    .venv/Scripts/python tools/verify_measures.py --stage 3

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
ALL_MONTHS = list(pd.period_range("2024-01", "2026-12", freq="M"))


def load():
    """Line-level frames in GBP, profit-impact sign (revenue positive, costs negative)."""
    gl = pd.read_csv(DATA / "Fact_GL.csv", parse_dates=["PeriodDate", "PostingDate"])
    plan = pd.read_csv(DATA / "Fact_Plan.csv", parse_dates=["PeriodDate"])
    fx = pd.read_csv(DATA / "Dim_FX.csv", parse_dates=["PeriodDate"])
    acc = pd.read_csv(DATA / "Dim_Account.csv")[["AccountKey", "PLGroupL1", "PLGroupL2", "InEBITDA"]]
    ent = pd.read_csv(DATA / "Dim_Entity.csv")[["EntityKey", "EntityCode"]]
    key = ["PeriodDate", "CurrencyCode"]
    last_actual = gl["PeriodDate"].max()

    # rate of the same month one year earlier (missing for 2024)
    prior = fx[key + ["AvgRateToGBP"]].rename(columns={"AvgRateToGBP": "PriorYearRate"})
    prior["PeriodDate"] = prior["PeriodDate"] + pd.DateOffset(years=1)
    # forecast rate: average rate up to the last actual month, then that month's rate held flat
    held = fx[fx.PeriodDate == last_actual].set_index("CurrencyCode")["AvgRateToGBP"]
    fx = fx.merge(prior, on=key, how="left")
    fx["ForecastRate"] = fx["AvgRateToGBP"].where(fx.PeriodDate <= last_actual, fx.CurrencyCode.map(held))

    def enrich(df):
        df = df.merge(fx, on=key).merge(acc, on="AccountKey").merge(ent, on="EntityKey")
        df["month"] = df["PeriodDate"].dt.to_period("M")
        return df

    actual = enrich(gl)
    actual["gbp"] = -actual["AmountLocal"] * actual["AvgRateToGBP"]
    actual["gbp_budget_rate"] = -actual["AmountLocal"] * actual["BudgetRateToGBP"]
    actual["gbp_py_rate"] = -actual["AmountLocal"] * actual["PriorYearRate"]
    budget = enrich(plan[plan.ScenarioKey == 2])
    budget["gbp"] = -budget["AmountLocal"] * budget["BudgetRateToGBP"]
    forecast = enrich(plan[plan.ScenarioKey == 3])
    forecast["gbp"] = -forecast["AmountLocal"] * forecast["ForecastRate"]
    return actual, budget, forecast


def monthly(df, mask=None, col="gbp"):
    d = df if mask is None else df[mask(df)]
    return d.dropna(subset=[col]).groupby("month")[col].sum().to_dict()


def total(series, months):
    vals = [series[m] for m in months if m in series]
    return sum(vals) if vals else None


def minus(a, b):
    return None if a is None and b is None else (a or 0.0) - (b or 0.0)


def ratio(n, d):
    return None if n is None or not d else n / abs(d)


def series_for(frames, mask):
    actual, budget, forecast = frames
    both = lambda extra: (lambda d: (mask(d) if mask else True) & extra(d))
    rev, ebitda = (lambda d: d.PLGroupL1 == "Revenue"), (lambda d: d.InEBITDA == 1)
    sliced = actual if mask is None else actual[mask(actual)]
    return {"a": monthly(actual, mask), "b": monthly(budget, mask), "f": monthly(forecast, mask),
            "a_rev": monthly(actual, both(rev)), "b_rev": monthly(budget, both(rev)),
            "a_ebitda": monthly(actual, both(ebitda)), "b_ebitda": monthly(budget, both(ebitda)),
            "a_budget_rate": monthly(actual, mask, "gbp_budget_rate"), "a_py_rate": monthly(actual, mask, "gbp_py_rate"),
            "posted": sliced.groupby("PostingDate")["gbp"].sum(),
            "first": min(monthly(actual)), "last_actual": max(monthly(actual))}


def posted_mtd(s, last_date):
    window = s["posted"][(s["posted"].index >= last_date.replace(day=1)) & (s["posted"].index <= last_date)]
    return float(window.sum()) if len(window) else None


def stage2_measures(ctx, s):
    """Time intelligence and budget variance for a context given as a list of months."""
    a, b, first = s["a"], s["b"], s["first"]
    closed = [m for m in ctx if m <= s["last_actual"]]
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


def stage3_measures(ctx, s):
    """Forecast, constant currency and posting-date measures for a context given as a list of months."""
    a, b, f, last_actual = s["a"], s["b"], s["f"], s["last_actual"]
    closed = [m for m in ctx if m <= last_actual]
    year = [m for m in ALL_MONTHS if m.year in {c.year for c in ctx}]
    actual, budget_closed = total(a, ctx), total(b, closed)
    prior = total(a, [m - 12 for m in closed])
    out = {"Actual": actual, "Forecast": total(f, ctx), "Forecast FY": total(f, year), "Budget FY": total(b, year)}
    out["Forecast Remaining"] = total(f, [m for m in ctx if m > last_actual])
    parts = [total(a, [m for m in year if m <= last_actual]), total(f, [m for m in year if m > last_actual])]
    out["Actual YTD + Forecast Remaining"] = None if parts == [None, None] else sum(p or 0.0 for p in parts)
    has_forecast = out["Forecast FY"] is not None
    out["Forecast vs Budget FY"] = out["Forecast FY"] - (out["Budget FY"] or 0.0) if has_forecast else None
    out["Forecast vs Budget FY %"] = ratio(out["Forecast vs Budget FY"], out["Budget FY"])
    prior_full_year = total(a, [m - 12 for m in year])
    out["Forecast vs Actual PY %"] = ratio(out["Forecast FY"] - (prior_full_year or 0.0), prior_full_year) if has_forecast else None
    at_budget, at_py = total(s["a_budget_rate"], ctx), total(s["a_py_rate"], ctx)
    out["Actual at Budget Rates"] = at_budget
    out["FX Var to Budget"] = minus(actual, at_budget)
    out["Operational Var to Budget"] = minus(at_budget, budget_closed)
    out["Var to Budget"] = minus(actual, budget_closed)
    out["Actual at PY Rates"] = at_py
    out["YoY CC"] = at_py - prior if at_py is not None and prior is not None else None
    out["YoY % CC"] = ratio(out["YoY CC"], prior)
    out["FX Impact YoY"] = (actual or 0.0) - at_py if at_py is not None else None
    out["YoY"] = actual - prior if actual is not None and prior is not None else None
    out["Posted MTD"] = posted_mtd(s, max(ctx).to_timestamp(how="end").normalize())
    return out


def context(kind, key):
    if kind == "month":
        return [pd.Period(f"{int(key) // 100}-{int(key) % 100:02d}", "M")]
    if kind == "year":
        return [m for m in ALL_MONTHS if m.year == int(key)]
    year, q = str(key).split(" Q")
    return [m for m in ALL_MONTHS if m.year == int(year) and m.quarter == int(q)]


ALL_KEYS = {"month": [m.year * 100 + m.month for m in ALL_MONTHS], "year": [2024, 2025, 2026],
            "quarter": [f"{y} Q{q}" for y in (2024, 2025, 2026) for q in (1, 2, 3, 4)]}
US_REVENUE = lambda d: (d.EntityCode == "US01") & (d.PLGroupL1 == "Revenue")
GRIDS = {  # result file -> (stage, key column, context kind, slice filter)
    "stage2_03_monthly_total": (2, "Year Month Key", "month", None),
    "stage2_04_monthly_revenue": (2, "Year Month Key", "month", lambda d: d.PLGroupL1 == "Revenue"),
    "stage2_05_monthly_us01_ebitda": (2, "Year Month Key", "month", lambda d: (d.EntityCode == "US01") & (d.InEBITDA == 1)),
    "stage2_06_yearly_total": (2, "Year", "year", None),
    "stage2_07_quarterly_de01": (2, "Year Quarter", "quarter", lambda d: d.EntityCode == "DE01"),
    "stage3_01_monthly_total": (3, "Year Month Key", "month", None),
    "stage3_02_monthly_us01_revenue": (3, "Year Month Key", "month", US_REVENUE),
    "stage3_03_yearly_total": (3, "Year", "year", None),
    "stage3_04_yearly_us01_revenue": (3, "Year", "year", US_REVENUE),
    "stage3_05_yearly_ebitda": (3, "Year", "year", lambda d: d.InEBITDA == 1),
}


def differs(name, got, want):
    tol = RATIO_TOL * max(1.0, abs(want or 0.0)) if name.endswith("%") else AMOUNT_TOL
    return (got is None) != (want is None) or (got is not None and abs(got - want) > tol)


def check_grid(name, frames):
    stage, key_col, kind, mask = GRIDS[name]
    fn = stage2_measures if stage == 2 else stage3_measures
    s = series_for(frames, mask)
    dax = pd.read_csv(RESULTS / f"{name}.csv")
    compared = failed = 0
    worst = 0.0
    problems = []
    for _, row in dax.iterrows():
        for m, want in fn(context(kind, row[key_col]), s).items():
            got = None if pd.isna(row[m]) else float(row[m])
            compared += 1
            if differs(m, got, want):
                failed += 1
                problems.append(f"    {row[key_col]} | {m}: model {got} vs pandas {want}")
            elif got is not None and not m.endswith("%"):
                worst = max(worst, abs(got - want))
    present = set(dax[key_col])
    for k in ALL_KEYS[kind]:  # every context pandas can compute must be present in the model output
        if k not in present and any(v is not None for v in fn(context(kind, k), s).values()):
            failed += 1
            problems.append(f"    {k}: row missing from the model output")
    print(f"{'PASS' if not failed else 'FAIL'}  {name}: {len(dax)} rows, {compared} values compared, {failed} failed, largest amount difference {worst:.4f}")
    if problems:
        print("\n".join(problems[:15]))
    return failed


def check_daily_posted(frames):
    name = "stage3_06_daily_posted_mtd"
    s = series_for(frames, None)
    dax = pd.read_csv(RESULTS / f"{name}.csv", parse_dates=["Date"])
    got = dax.set_index("Date")["Posted MTD"]
    days = list(pd.date_range("2025-07-01", "2025-07-31")) + list(pd.date_range("2026-11-01", "2026-11-30"))
    failed, worst, problems = 0, 0.0, []
    for d in days:
        want, g = posted_mtd(s, d), (float(got[d]) if d in got.index and not pd.isna(got[d]) else None)
        if differs("Posted MTD", g, want):
            failed += 1
            problems.append(f"    {d.date()} | Posted MTD: model {g} vs pandas {want}")
        elif g is not None:
            worst = max(worst, abs(g - want))
    print(f"{'PASS' if not failed else 'FAIL'}  {name}: {len(dax)} rows, {len(days)} days compared, {failed} failed, largest amount difference {worst:.4f}")
    if problems:
        print("\n".join(problems[:15]))
    return failed


def check_identities():
    """Reconciliations inside the model's own output."""
    failed = 0
    for name in [n for n, g in GRIDS.items() if g[0] == 3]:
        dax = pd.read_csv(RESULTS / f"{name}.csv").fillna(0.0)
        fx_split = (dax["FX Var to Budget"] + dax["Operational Var to Budget"] - dax["Var to Budget"]).abs().max()
        with_py = dax[dax["Actual at PY Rates"] != 0]
        yoy_split = (with_py["YoY CC"] + with_py["FX Impact YoY"] - with_py["YoY"]).abs().max() if len(with_py) else 0.0
        with_fc = dax[dax["Forecast FY"] != 0]
        outlook = (with_fc["Actual YTD + Forecast Remaining"] - with_fc["Forecast FY"]).abs().max() if len(with_fc) else 0.0
        # the forecast holds January to October as actuals rounded to 2 decimals per entity, account and month, so allow 1 GBP
        ok = fx_split <= AMOUNT_TOL and yoy_split <= AMOUNT_TOL and outlook <= 1.0
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: FX Var + Operational Var = Var to Budget (max gap {fx_split:.4f}); "
              f"YoY CC + FX Impact YoY = YoY (max gap {yoy_split:.4f}); outlook = Forecast FY (max gap {outlook:.4f})")
    return failed


RLS_CASES = {  # case -> (roles, user); must match tools/run_rls_tests.ps1
    "group_cfo": (["Group Finance"], "cfo@halcyon.example"),
    "entity_cfo": (["Entity Finance"], "cfo@halcyon.example"),
    "entity_controller": (["Entity Finance"], "controller@halcyon.example"),
    "entity_uk": (["Entity Finance"], "uk.fpa@halcyon.example"),
    "entity_us": (["Entity Finance"], "us.fpa@halcyon.example"),
    "entity_de": (["Entity Finance"], "de.fpa@halcyon.example"),
    "entity_in": (["Entity Finance"], "in.fpa@halcyon.example"),
    "entity_unmapped": (["Entity Finance"], "nobody@halcyon.example"),
    "emea_uk": (["EMEA Finance"], "uk.fpa@halcyon.example"),
    "emea_unmapped": (["EMEA Finance"], "nobody@halcyon.example"),
    "entity_emea_us": (["Entity Finance", "EMEA Finance"], "us.fpa@halcyon.example"),  # roles add up: US01 plus EMEA
}
# FY2025 EBITDA by entity as supplied by the project owner, a second reference besides the pandas recomputation
OWNER_EBITDA = {"entity_uk": -781112.52, "entity_us": -925483.09, "entity_de": 3333287.55, "entity_in": 3091822.01}


def check_rls(frames):
    """Each role and user case against what pandas says that role should see. FY2025, synthetic GBP."""
    actual, budget, _ = frames
    ent = pd.read_csv(DATA / "Dim_Entity.csv")
    umap = pd.read_csv(DATA / "Dim_UserEntityMap.csv")
    cust = pd.read_csv(DATA / "Dim_Customer.csv")
    cc = pd.read_csv(DATA / "Dim_CostCentre.csv")
    plan = pd.read_csv(DATA / "Fact_Plan.csv")
    code = ent.set_index("EntityKey")["EntityCode"]
    fy = lambda d: d.PeriodDate.dt.year == 2025
    blank = lambda v: v if v else None  # the model returns blank, not zero, when nothing is visible
    money = lambda v: "blank" if v is None else f"{v:,.2f}"
    failed = 0
    for case, (roles, user) in RLS_CASES.items():
        keys, map_rows = set(), 0
        mine = umap[umap.UserPrincipalName.str.lower() == user.lower()]
        for role in roles:
            if role == "Group Finance":
                keys |= set(ent.EntityKey)
                map_rows = len(umap)
            elif role == "Entity Finance":
                keys |= set(mine.EntityKey)
                map_rows = max(map_rows, len(mine))
            elif role == "EMEA Finance":
                keys |= set(ent[ent.Region == "EMEA"].EntityKey)
        a, b = actual[actual.EntityKey.isin(keys)], budget[budget.EntityKey.isin(keys)]
        want = {
            "entities": ",".join(sorted(code[k] for k in keys)) or None,
            "revenue_gbp": blank(a[fy(a) & (a.PLGroupL1 == "Revenue")].gbp.sum()),
            "ebitda_gbp": blank(a[fy(a) & (a.InEBITDA == 1)].gbp.sum()),
            "budget_ebitda_gbp": blank(b[fy(b) & (b.InEBITDA == 1)].gbp.sum()),
            "gl_rows": blank(len(a)),
            "plan_rows": blank(int(plan.EntityKey.isin(keys).sum())),
            "customers": 1 + int(cust.EntityKey.isin(keys).sum()),  # the -1 "No customer" row is always visible
            "cost_centres": blank(int(cc.EntityKey.isin(keys).sum())),
            "map_rows": blank(map_rows),
        }
        row = pd.read_csv(RESULTS / f"stage4_01_role_check_{case}.csv").iloc[0]
        problems = []
        if str(row["upn"]).lower() != user.lower():
            problems.append(f"upn: model ran as {row['upn']}, not {user}")
        for k, w in want.items():
            g = None if pd.isna(row[k]) else row[k]
            if k == "entities":
                bad = g != w
            else:
                g = None if g is None else float(g)
                bad = differs(k, g, None if w is None else float(w))
            if bad:
                problems.append(f"{k}: model {g} vs pandas {w}")
        if case in OWNER_EBITDA and abs(float(row["ebitda_gbp"]) - OWNER_EBITDA[case]) > 0.005:
            problems.append(f"ebitda_gbp: model {row['ebitda_gbp']} vs owner figure {OWNER_EBITDA[case]}")
        failed += bool(problems)
        print(f"{'PASS' if not problems else 'FAIL'}  {case}: [{', '.join(roles)}] {user} sees {want['entities'] or 'nothing'}; "
              f"revenue {money(want['revenue_gbp'])}, EBITDA {money(want['ebitda_gbp'])}, budget EBITDA {money(want['budget_ebitda_gbp'])}, "
              f"customers {want['customers']}, cost centres {want['cost_centres'] or 0}, map rows {want['map_rows'] or 0}")
        for pr in problems:
            print("    " + pr)
    return failed


STATEMENT_LINES = {  # line key -> (account filter, costs shown positive)
    1: (lambda d: d.PLGroupL1 == "Revenue", False),
    2: (lambda d: d.PLGroupL1 == "Cost of Sales", True),
    3: (lambda d: d.PLGroupL1.isin(["Revenue", "Cost of Sales"]), False),
    4: (lambda d: d.PLGroupL1 == "Operating Expenses", True),
    5: (lambda d: d.InEBITDA == 1, False),
    6: (lambda d: d.PLGroupL1 == "Depreciation and Amortisation", True),
    7: (lambda d: d.PLGroupL1.isin(["Revenue", "Cost of Sales", "Operating Expenses", "Depreciation and Amortisation"]), False),
    8: (lambda d: d.PLGroupL1 == "Finance Items", True),
    9: (lambda d: d.PLGroupL1 != "Tax", False),
    10: (lambda d: d.PLGroupL1 == "Tax", True),
    11: (lambda d: d.PLGroupL1.notna(), False),
}
STATEMENT_FILES = {  # result file -> (context column, context kind, entity filter)
    "stage6_01_statement_yearly": ("Year", "year", None),
    "stage6_02_statement_de01_month": ("Year Month Key", "month", "DE01"),
}


def check_statement(name, frames):
    """P&L statement measures: each line is an account filter, costs shown positive, variance favourable-positive."""
    key_col, kind, entity = STATEMENT_FILES[name]
    dax = pd.read_csv(RESULTS / f"{name}.csv")
    compared = failed = 0
    problems = []
    for line, (accounts, cost) in STATEMENT_LINES.items():
        mask = (lambda d, f=accounts: f(d) & (d.EntityCode == entity)) if entity else accounts
        s = series_for(frames, mask)
        sign = -1.0 if cost else 1.0
        flip = lambda v: None if v is None else sign * v
        for _, row in dax[dax["Line Key"] == line].iterrows():
            m = stage2_measures(context(kind, row[key_col]), s)
            budget = flip(m["Budget (Closed Periods)"])
            want = {"P&L Value": flip(m["Actual"]), "P&L Budget": budget, "P&L Var to Budget": m["Var to Budget"],
                    "P&L Var to Budget %": ratio(m["Var to Budget"], budget), "P&L Actual PY": flip(m["Actual PY"])}
            for k, w in want.items():
                got = None if pd.isna(row[k]) else float(row[k])
                compared += 1
                if differs(k, got, w):
                    failed += 1
                    problems.append(f"    line {line} {row['Line']} | {row[key_col]} | {k}: model {got} vs pandas {w}")
    expected_rows = len(STATEMENT_LINES) * 3
    if len(dax) != expected_rows:
        failed += 1
        problems.append(f"    {len(dax)} rows in the model output, expected {expected_rows}")
    print(f"{'PASS' if not failed else 'FAIL'}  {name}: {len(dax)} rows, {compared} values compared, {failed} failed")
    if problems:
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
    ap.add_argument("--stage", type=int, choices=[1, 2, 3, 4, 6], help="check one stage only")
    args = ap.parse_args()
    stages = [args.stage] if args.stage else [1, 2, 3, 4, 6]
    frames = load() if set(stages) & {2, 3, 4, 6} else None
    failed = 0
    for stage in stages:
        if stage in (1, 2):
            print(f"--- stage {stage}: data/expected.json (synthetic GBP)")
            failed += check_expected(stage)
        if stage in (2, 3):
            print(f"--- stage {stage}: pandas recomputation (synthetic GBP)")
            for name in [n for n, g in GRIDS.items() if g[0] == stage]:
                failed += check_grid(name, frames)
        if stage == 3:
            failed += check_daily_posted(frames)
            print("--- stage 3: reconciliations inside the model output")
            failed += check_identities()
        if stage == 4:
            print("--- stage 4: row-level security, each role and user against pandas (FY2025, synthetic GBP)")
            failed += check_rls(frames)
        if stage == 6:
            print("--- stage 6: P&L statement measures against pandas (synthetic GBP)")
            for name in STATEMENT_FILES:
                failed += check_statement(name, frames)
    print(f"\n{'ALL CHECKS PASSED' if not failed else str(failed) + ' CHECK(S) FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
