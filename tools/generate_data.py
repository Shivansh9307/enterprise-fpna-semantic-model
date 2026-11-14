#!/usr/bin/env python3
"""Synthetic FP&A dataset for the powerbi_datagoblin test project.

EVERYTHING HERE IS FICTIONAL. "Halcyon Group" does not exist; no figure is a real company's data.

Usage:  python tools/generate_data.py --out data [--seed N] [--scale 1.0]
Scale multiplies the number of customers and journal lines (use 3-5 for a performance-tuning stress test).
The run is deterministic for a given seed and scale.

GL sign convention: debit positive, credit negative, so profit = -SUM(AmountLocal) over P&L accounts.
The ledger holds P&L accounts only. Journals are not balanced double entry (there is no balance sheet side).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

MONTHS = pd.date_range("2024-01-01", "2026-12-01", freq="MS")  # 36 months: FY2024 to FY2026
LAST_ACTUAL = pd.Timestamp("2026-10-01")  # actuals run to Oct 2026; Nov-Dec 2026 exist only in Budget and Forecast
ACT_MONTHS = MONTHS[MONTHS <= LAST_ACTUAL]

ENTITIES = [  # key, code, name, country, currency, region, revenue share
    (1, "UK01", "Halcyon UK Ltd", "United Kingdom", "GBP", "EMEA", 0.35),
    (2, "US01", "Halcyon US Inc", "United States", "USD", "Americas", 0.40),
    (3, "DE01", "Halcyon GmbH", "Germany", "EUR", "EMEA", 0.15),
    (4, "IN01", "Halcyon India Pvt Ltd", "India", "INR", "APAC", 0.10),
]
ENT_SHARE = {e[0]: e[6] for e in ENTITIES}
ENT_CCY = {e[0]: e[4] for e in ENTITIES}

DEPTS = {  # department -> entity keys that have a cost centre for it
    "Revenue": [1, 2, 3, 4],
    "Sales": [1, 2, 3],
    "Marketing": [1, 2, 3],
    "Engineering": [1, 2, 4],
    "Product": [1, 2],
    "Customer Support": [1, 2, 4],
    "Professional Services": [1, 2, 3],
    "Hosting": [1, 2],
    "Finance": [1, 2, 3, 4],
    "People and Operations": [1, 2, 3, 4],
}
DEPT_FUNCTION = {
    "Revenue": "Revenue", "Sales": "Sales and Marketing", "Marketing": "Sales and Marketing",
    "Engineering": "Research and Development", "Product": "Research and Development",
    "Customer Support": "Cost of Sales", "Professional Services": "Cost of Sales", "Hosting": "Cost of Sales",
    "Finance": "General and Administrative", "People and Operations": "General and Administrative",
}

# code, name, L1, L2, department, natural sign (+1 debit nature, -1 credit nature), in EBITDA, monthly GBP at Jan-2024,
# growth kind, seasonality, journal lines per entity-month, noise sigma, budget bias
ACCOUNTS = [
    (4010, "Subscription Revenue", "Revenue", "Recurring Revenue", "Revenue", -1, True, 1_900_000, "rev", "none", 0, 0.015, 1.06),
    (4020, "Usage Revenue", "Revenue", "Recurring Revenue", "Revenue", -1, True, 350_000, "rev", "none", 0, 0.05, 1.06),
    (4110, "Implementation Services", "Revenue", "Services Revenue", "Revenue", -1, True, 450_000, "rev", "svc", 0, 0.08, 1.06),
    (4120, "Consulting Services", "Revenue", "Services Revenue", "Revenue", -1, True, 300_000, "rev", "svc", 0, 0.10, 1.06),
    (4210, "Training Revenue", "Revenue", "Services Revenue", "Revenue", -1, True, 80_000, "rev", "svc", 0, 0.12, 1.06),
    (5010, "Hosting and Infrastructure", "Cost of Sales", "Hosting", "Hosting", 1, True, 330_000, "opx", "none", 40, 0.04, 0.95),
    (5020, "Third-party Licences", "Cost of Sales", "Hosting", "Hosting", 1, True, 140_000, "opx", "none", 12, 0.04, 0.98),
    (5110, "Support Staff Costs", "Cost of Sales", "Delivery Staff", "Customer Support", 1, True, 220_000, "sal", "none", 4, 0.02, 0.97),
    (5120, "Professional Services Staff", "Cost of Sales", "Delivery Staff", "Professional Services", 1, True, 420_000, "sal", "none", 4, 0.02, 0.97),
    (5130, "Delivery Contractors", "Cost of Sales", "Delivery Staff", "Professional Services", 1, True, 90_000, "opx", "none", 15, 0.10, 0.98),
    (6010, "Sales Salaries", "Operating Expenses", "Sales and Marketing", "Sales", 1, True, 420_000, "sal", "none", 4, 0.02, 0.97),
    (6020, "Sales Commissions", "Operating Expenses", "Sales and Marketing", "Sales", 1, True, 150_000, "sal", "comm", 6, 0.08, 0.98),
    (6030, "Marketing Programmes", "Operating Expenses", "Sales and Marketing", "Marketing", 1, True, 220_000, "opx", "events", 40, 0.08, 0.98),
    (6040, "Events and Travel", "Operating Expenses", "Sales and Marketing", "Marketing", 1, True, 90_000, "opx", "events", 60, 0.12, 0.98),
    (6110, "Engineering Salaries", "Operating Expenses", "Research and Development", "Engineering", 1, True, 520_000, "sal", "none", 5, 0.02, 0.97),
    (6120, "Product Salaries", "Operating Expenses", "Research and Development", "Product", 1, True, 140_000, "sal", "none", 3, 0.02, 0.97),
    (6130, "Cloud Development Environments", "Operating Expenses", "Research and Development", "Engineering", 1, True, 70_000, "opx", "none", 20, 0.06, 0.98),
    (6140, "R&D Contractors", "Operating Expenses", "Research and Development", "Engineering", 1, True, 90_000, "opx", "none", 15, 0.10, 0.98),
    (6210, "Finance and Admin Salaries", "Operating Expenses", "General and Administrative", "Finance", 1, True, 180_000, "sal", "none", 3, 0.02, 0.97),
    (6220, "Rent and Facilities", "Operating Expenses", "General and Administrative", "People and Operations", 1, True, 120_000, "opx", "none", 6, 0.02, 1.00),
    (6230, "Professional Fees", "Operating Expenses", "General and Administrative", "Finance", 1, True, 70_000, "opx", "none", 10, 0.15, 0.98),
    (6240, "Insurance", "Operating Expenses", "General and Administrative", "Finance", 1, True, 25_000, "opx", "none", 2, 0.02, 1.00),
    (6250, "Software and IT", "Operating Expenses", "General and Administrative", "Finance", 1, True, 60_000, "opx", "none", 15, 0.05, 0.98),
    (6260, "Bad Debt Expense", "Operating Expenses", "General and Administrative", "Finance", 1, True, 25_000, "opx", "baddebt", 3, 0.20, 1.00),
    (7010, "Depreciation", "Depreciation and Amortisation", "Depreciation and Amortisation", "Finance", 1, False, 150_000, "flat", "none", 1, 0.01, 1.00),
    (7020, "Amortisation", "Depreciation and Amortisation", "Depreciation and Amortisation", "Finance", 1, False, 60_000, "flat", "none", 1, 0.01, 1.00),
    (7110, "Interest Income", "Finance Items", "Finance Items", "Finance", -1, False, 20_000, "flat", "none", 1, 0.10, 1.00),
    (7120, "Interest Expense", "Finance Items", "Finance Items", "Finance", 1, False, 45_000, "flat", "none", 1, 0.05, 1.00),
    (7210, "FX Gains and Losses", "Finance Items", "Finance Items", "Finance", 1, False, 15_000, "flat", "fx", 2, 1.00, 1.00),
    (8010, "Corporation Tax", "Tax", "Tax", "Finance", 1, False, 40_000, "opx", "none", 1, 0.10, 1.00),
]
ACC_COLS = ["code", "name", "l1", "l2", "dept", "nat", "ebitda", "base", "growth", "season", "nlines", "sigma", "bias"]
GROWTH = {
    "rev": {2024: 0.28, 2025: 0.24, 2026: 0.20},
    "sal": {2024: 0.12, 2025: 0.10, 2026: 0.09},
    "opx": {2024: 0.10, 2025: 0.09, 2026: 0.08},
    "flat": {2024: 0.0, 2025: 0.0, 2026: 0.0},
}
SEASON = {
    "none": [1] * 12,
    "svc": [0.92, 0.95, 1.0, 1.0, 1.02, 1.03, 0.98, 0.90, 1.05, 1.05, 1.08, 1.14],
    "events": [0.8, 0.9, 1.6, 0.9, 0.9, 1.0, 0.7, 0.6, 1.6, 1.1, 0.9, 0.6],
    "comm": [0.7, 0.7, 1.6, 0.8, 0.8, 1.5, 0.8, 0.8, 1.5, 0.8, 0.8, 1.9],
    "baddebt": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1.2, 1.6],
    "fx": [1] * 12,
}
SEASON = {k: np.array(v, dtype=float) / np.mean(v) for k, v in SEASON.items()}
SOURCE = {"Revenue": "Billing", "Customer Support": "Payroll", "Professional Services": "Payroll", "Sales": "Payroll",
          "Engineering": "Payroll", "Product": "Payroll"}
VENDORS = ["Northlane Cloud", "Brightwater Systems", "Kestrel Partners", "Ardent Media", "Copperline Travel", "Mosaic Advisory",
           "Tidewell Facilities", "Ironbark Software", "Lumen Events", "Fernhill Legal"]
TEAMS = ["Team A", "Team B", "Team C", "Team D", "Team E", "Team F"]


def month_index(ts: pd.Timestamp) -> int:
    return (ts.year - 2024) * 12 + ts.month - 1


def level_index(kind: str) -> np.ndarray:
    """Cumulative growth index per month (1.0 in Jan 2024), compounding each year's rate monthly."""
    out, cur = [], 1.0
    for m in MONTHS:
        out.append(cur)
        cur *= (1 + GROWTH[kind][m.year]) ** (1 / 12)
    return np.array(out)


def build_fx(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    start = {"GBP": 1.0, "USD": 0.79, "EUR": 0.855, "INR": 0.0094}
    drift = {"GBP": 0.0, "USD": 0.0, "EUR": 0.0005, "INR": -0.003}
    vol = {"GBP": 0.0, "USD": 0.008, "EUR": 0.008, "INR": 0.006}
    for ccy, r0 in start.items():
        rate, avg = r0, []
        for m in MONTHS:
            rate *= 1 + drift[ccy] + rng.normal(0, vol[ccy])
            if ccy == "USD" and m == pd.Timestamp("2026-01-01"):
                rate *= 0.94  # planted story: a USD shock at the start of FY2026
            avg.append(rate)
        avg = np.array(avg)
        close = avg * (1 + rng.normal(0, 0.004, len(avg))) if ccy != "GBP" else avg
        for i, m in enumerate(MONTHS):
            first_of_year = avg[month_index(pd.Timestamp(m.year, 1, 1))]
            rows.append((m, ccy, round(avg[i], 6), round(close[i], 6), round(first_of_year, 6)))
    return pd.DataFrame(rows, columns=["PeriodDate", "CurrencyCode", "AvgRateToGBP", "CloseRateToGBP", "BudgetRateToGBP"])


def planted(code: int, ent: int, m: pd.Timestamp) -> float:
    """Planted stories, applied to actuals only, for the dashboard narrative."""
    f = 1.0
    if code == 5010 and pd.Timestamp("2025-06-01") <= m <= pd.Timestamp("2025-08-01"):
        f *= 1.30  # hosting overrun
    if code in (4010, 4020, 4110, 4120, 4210) and ent == 3 and pd.Timestamp("2025-07-01") <= m <= pd.Timestamp("2025-09-01"):
        f *= 0.85  # Germany revenue dip
    if code == 5020 and m == pd.Timestamp("2026-03-01"):
        f *= 1.8  # large licence renewal
    if code == 6110 and ent == 4 and pd.Timestamp("2026-04-01") <= m <= pd.Timestamp("2026-06-01"):
        f *= 0.7  # India engineering vacancies
    if code == 6260 and m == pd.Timestamp("2025-12-01"):
        f *= 4.0  # one-off bad debt write-off
    return f


def split_amount(total: float, n: int, rng: np.random.Generator, alpha: float = 2.0) -> np.ndarray:
    if n <= 1:
        return np.array([round(total, 2)])
    w = rng.dirichlet(np.full(n, alpha))
    parts = np.round(total * w, 2)
    parts[-1] = round(total - parts[:-1].sum(), 2)
    return parts


def build_customers(rng: np.random.Generator, n: int) -> pd.DataFrame:
    adj = ["Bright", "North", "Summit", "Harbour", "Cedar", "Atlas", "Pioneer", "Vertex", "Orchid", "Granite", "Beacon", "Crest"]
    noun = ["Logistics", "Health", "Retail", "Energy", "Capital", "Media", "Foods", "Labs", "Mobility", "Systems", "Learning", "Holdings"]
    industries = ["Retail", "Healthcare", "Logistics", "Financial Services", "Media", "Energy", "Education", "Manufacturing"]
    ent = rng.choice([e[0] for e in ENTITIES], size=n, p=[e[6] for e in ENTITIES])
    seg = rng.choice(["Enterprise", "Mid-Market", "SMB"], size=n, p=[0.06, 0.24, 0.70])
    wt = np.where(seg == "Enterprise", 40.0, np.where(seg == "Mid-Market", 8.0, 1.0)) * rng.lognormal(0, 0.4, n)
    ctry = {1: "United Kingdom", 2: "United States", 3: "Germany", 4: "India"}
    names = [f"{rng.choice(adj)} {rng.choice(noun)} {i + 1:04d}" for i in range(n)]
    pre = rng.random(n) < 0.40  # already a customer before Jan 2024
    start = np.where(pre, 0, rng.integers(1, len(ACT_MONTHS), n))
    churn_p = np.where(seg == "Enterprise", 0.03, np.where(seg == "Mid-Market", 0.05, 0.08)) / 12
    life = rng.geometric(churn_p)
    end = np.minimum(start + life, len(ACT_MONTHS) + 1)  # first month the customer is no longer active
    return pd.DataFrame({
        "CustomerKey": np.arange(1, n + 1), "CustomerName": names, "Segment": seg,
        "Industry": rng.choice(industries, n), "EntityKey": ent, "Country": [ctry[e] for e in ent],
        "StartMonth": [ACT_MONTHS[s] for s in start], "Weight": wt,
        "_start": start, "_end": end, "_pre": pre,
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data")
    ap.add_argument("--seed", type=int, default=20261114)
    ap.add_argument("--scale", type=float, default=1.0)
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(a.seed)

    acc = pd.DataFrame(ACCOUNTS, columns=ACC_COLS)
    acc.insert(0, "AccountKey", np.arange(1, len(acc) + 1))
    idx = {k: level_index(k) for k in GROWTH}
    fx = build_fx(rng)
    fx_avg = fx.set_index(["PeriodDate", "CurrencyCode"])["AvgRateToGBP"]
    fx_bud = fx.set_index(["PeriodDate", "CurrencyCode"])["BudgetRateToGBP"]

    # dimensions
    dim_entity = pd.DataFrame([e[:6] for e in ENTITIES], columns=["EntityKey", "EntityCode", "EntityName", "Country", "Currency", "Region"])
    cc_rows, cc_key = [], {}
    for dept, ents in DEPTS.items():
        for e in ents:
            code = f"CC-{''.join(w[0] for w in dept.split()).upper()}{len(dept) % 10}-{ENTITIES[e - 1][1]}"
            cc_key[(dept, e)] = len(cc_rows) + 1
            cc_rows.append((len(cc_rows) + 1, code, f"{dept} {ENTITIES[e - 1][1]}", dept, DEPT_FUNCTION[dept], e))
    dim_cc = pd.DataFrame(cc_rows, columns=["CostCentreKey", "CostCentreCode", "CostCentreName", "Department", "Function", "EntityKey"])
    assert dim_cc["CostCentreCode"].is_unique
    dim_acc = acc.rename(columns={"code": "AccountCode", "name": "AccountName", "l1": "PLGroupL1", "l2": "PLGroupL2",
                                  "dept": "DefaultDepartment", "nat": "NaturalSign", "ebitda": "InEBITDA"})[
        ["AccountKey", "AccountCode", "AccountName", "PLGroupL1", "PLGroupL2", "DefaultDepartment", "NaturalSign", "InEBITDA"]].copy()
    dim_acc["InEBITDA"] = dim_acc["InEBITDA"].astype(int)
    dim_acc["SortOrder"] = np.arange(1, len(dim_acc) + 1)
    dim_scn = pd.DataFrame({"ScenarioKey": [1, 2, 3], "ScenarioName": ["Actual", "Budget", "Forecast"]})
    n_cust = int(2500 * a.scale)
    cust = build_customers(rng, n_cust)

    # baseline GBP per (account, entity, month): the deterministic plan before noise
    def baseline(r, ent: int, mi: int) -> float:
        ents = DEPTS[r.dept]
        share = ENT_SHARE[ent] / sum(ENT_SHARE[x] for x in ents)
        return r.base * share * idx[r.growth][mi] * SEASON[r.season][MONTHS[mi].month - 1]

    gl_parts, act_totals = [], []  # act_totals: (period, ent, account key, cc key, local amount)
    for r in acc.itertuples():
        for ent in DEPTS[r.dept]:
            ccy = ENT_CCY[ent]
            cck = cc_key[(r.dept, ent)]
            for mi, m in enumerate(ACT_MONTHS):
                tgt_gbp = baseline(r, ent, mi) * planted(r.code, ent, m)
                if r.season == "fx":
                    tgt_gbp = rng.normal(0, r.base * idx["flat"][mi])  # signed gain or loss
                else:
                    tgt_gbp *= rng.lognormal(0, r.sigma)
                tgt_local = tgt_gbp / fx_avg[(m, ccy)] * (r.nat if r.season != "fx" else 1)
                if r.dept == "Revenue":
                    ci = cust[(cust.EntityKey == ent) & (cust._start <= mi) & (cust._end > mi)]
                    if ci.empty:
                        continue
                    k = r.code
                    if k == 4010:
                        sel, lam = ci, 1.4
                    elif k == 4020:
                        sel, lam = ci[rng.random(len(ci)) < 0.65], 5
                    elif k == 4110:
                        sel, lam = ci[(~ci._pre) & (mi - ci._start < 3)], 1.5
                    elif k == 4120:
                        sel, lam = ci[rng.random(len(ci)) < 0.12], 1.5
                    else:
                        sel, lam = ci[rng.random(len(ci)) < 0.05], 1.0
                    if sel.empty:
                        sel = ci.sample(1, random_state=int(rng.integers(1e9)))
                    reps = 1 + rng.poisson(lam - 1 if lam > 1 else 0, len(sel))
                    rows = sel.loc[sel.index.repeat(reps)]
                    w = rows.Weight.to_numpy() * rng.lognormal(0, 0.3, len(rows))
                    amt = np.round(tgt_local * w / w.sum(), 2)
                    amt[-1] = round(tgt_local - amt[:-1].sum(), 2)
                    df = pd.DataFrame({"CustomerKey": rows.CustomerKey.to_numpy(), "AmountLocal": amt})
                else:
                    n = max(1, int(rng.poisson(r.nlines * a.scale))) if r.nlines else 1
                    df = pd.DataFrame({"CustomerKey": pd.NA, "AmountLocal": split_amount(tgt_local, n, rng)})
                df["PeriodDate"], df["EntityKey"], df["AccountKey"], df["CostCentreKey"] = m, ent, r.AccountKey, cck
                df["CurrencyCode"] = ccy
                gl_parts.append(df)
                act_totals.append((m, ent, r.AccountKey, cck, round(df["AmountLocal"].sum(), 2)))

    gl = pd.concat(gl_parts, ignore_index=True)
    n = len(gl)
    acc_by_key = acc.set_index("AccountKey")
    dept_of = gl["AccountKey"].map(acc_by_key["dept"])
    name_of = gl["AccountKey"].map(acc_by_key["name"])
    dim = pd.to_timedelta(rng.integers(0, 28, n), unit="D")
    gl["PostingDate"] = gl["PeriodDate"] + dim
    gl["SourceSystem"] = dept_of.map(SOURCE).fillna("AP")
    gl.loc[gl["AccountKey"].isin(acc.loc[acc.code.isin([7010, 7020]), "AccountKey"]), "SourceSystem"] = "FixedAssets"
    gl.loc[gl["AccountKey"].isin(acc.loc[acc.code.isin([7110, 7120, 7210, 8010]), "AccountKey"]), "SourceSystem"] = "Treasury"
    is_rev = dept_of == "Revenue"
    pick = rng.choice(VENDORS, n)
    gl["Description"] = np.where(is_rev, name_of + " invoice", name_of + " - " + pick)
    gl["Description"] = np.where(dept_of.isin(["Sales", "Engineering", "Product", "Customer Support", "Professional Services"]) & (acc_by_key["growth"].reindex(gl["AccountKey"]).to_numpy() == "sal"),
                                 name_of + " - " + rng.choice(TEAMS, n), gl["Description"])
    gl["IsAdjustment"] = 0
    # late adjusting journals: posted in the following month for a prior period
    late = rng.random(n) < 0.015
    gl.loc[late, "PostingDate"] = gl.loc[late, "PeriodDate"] + pd.offsets.MonthBegin(1) + pd.to_timedelta(rng.integers(0, 5, late.sum()), unit="D")
    gl.loc[late, "IsAdjustment"] = 1
    # reversal and rebook pairs (net zero), to keep filters honest
    pick_idx = np.flatnonzero(rng.random(n) < 0.006)
    base = gl.iloc[pick_idx]
    rev, reb = base.copy(), base.copy()
    rev["AmountLocal"], rev["Description"] = -base["AmountLocal"], "Reversal: " + base["Description"]
    reb["Description"] = "Rebook: " + base["Description"]
    for d in (rev, reb):
        d["IsAdjustment"] = 1
        d["PostingDate"] = np.minimum(d["PostingDate"] + pd.Timedelta(days=2), d["PeriodDate"] + pd.offsets.MonthEnd(0))
    gl = pd.concat([gl, rev, reb], ignore_index=True).sort_values(["PeriodDate", "EntityKey", "AccountKey", "PostingDate"], kind="stable").reset_index(drop=True)
    j = rng.integers(1, 40, len(gl))
    gl["JournalID"] = "J" + gl["PeriodDate"].dt.strftime("%Y%m") + "-" + gl["EntityKey"].astype(str) + "-" + gl["SourceSystem"].str[:2].str.upper() + "-" + pd.Series(j).astype(str).str.zfill(2)
    gl["JournalLine"] = gl.groupby("JournalID").cumcount() + 1
    gl["CustomerKey"] = gl["CustomerKey"].astype("Int64")
    gl = gl[["JournalID", "JournalLine", "PostingDate", "PeriodDate", "EntityKey", "AccountKey", "CostCentreKey", "CustomerKey",
             "CurrencyCode", "AmountLocal", "Description", "SourceSystem", "IsAdjustment"]]

    # plan: budget for all 36 months (fixed budget FX rate); forecast for FY2026
    act_df = pd.DataFrame(act_totals, columns=["PeriodDate", "EntityKey", "AccountKey", "CostCentreKey", "AmountLocal"])
    plan_rows = []
    for r in acc.itertuples():
        for ent in DEPTS[r.dept]:
            ccy, cck = ENT_CCY[ent], cc_key[(r.dept, ent)]
            for mi, m in enumerate(MONTHS):
                gbp = baseline(r, ent, mi) * r.bias * rng.lognormal(0, 0.015) * (1 if r.season != "fx" else 0)
                plan_rows.append((m, 2, ent, r.AccountKey, cck, ccy, round(gbp / fx_bud[(m, ccy)] * r.nat, 2)))
                if m.year == 2026:
                    if m <= LAST_ACTUAL:
                        got = act_df[(act_df.PeriodDate == m) & (act_df.EntityKey == ent) & (act_df.AccountKey == r.AccountKey)]["AmountLocal"].sum()
                        plan_rows.append((m, 3, ent, r.AccountKey, cck, ccy, round(float(got), 2)))
                    else:
                        fgbp = baseline(r, ent, mi) * (0.995 if r.dept == "Revenue" else 1.01) * rng.lognormal(0, 0.01) * (1 if r.season != "fx" else 0)
                        plan_rows.append((m, 3, ent, r.AccountKey, cck, ccy, round(fgbp / fx_avg[(LAST_ACTUAL, ccy)] * r.nat, 2)))
    plan = pd.DataFrame(plan_rows, columns=["PeriodDate", "ScenarioKey", "EntityKey", "AccountKey", "CostCentreKey", "CurrencyCode", "AmountLocal"])

    # security map for RLS testing (fictional users on a reserved domain)
    users = [("cfo@halcyon.example", "Group Finance", e[0]) for e in ENTITIES] + [("controller@halcyon.example", "Group Finance", e[0]) for e in ENTITIES]
    users += [(f"{c.lower()}.fpa@halcyon.example", "Entity Finance", k) for k, c in [(1, "UK"), (2, "US"), (3, "DE"), (4, "IN")]]
    sec = pd.DataFrame(users, columns=["UserPrincipalName", "RoleName", "EntityKey"])

    cust_out = cust[["CustomerKey", "CustomerName", "Segment", "Industry", "EntityKey", "Country", "StartMonth"]]
    tables = {"Dim_Entity": dim_entity, "Dim_CostCentre": dim_cc, "Dim_Account": dim_acc, "Dim_Scenario": dim_scn,
              "Dim_Customer": cust_out, "Dim_FX": fx, "Dim_UserEntityMap": sec, "Fact_GL": gl, "Fact_Plan": plan}
    for name, df in tables.items():
        df.to_csv(out / f"{name}.csv", index=False, date_format="%Y-%m-%d")

    # independent anchors, computed with pandas straight from the CSV-shaped frames
    def pnl_gbp(frame: pd.DataFrame, rate_col: str, ym: tuple[str, str]) -> pd.DataFrame:
        f = frame[(frame.PeriodDate >= ym[0]) & (frame.PeriodDate <= ym[1])].merge(fx[["PeriodDate", "CurrencyCode", rate_col]], on=["PeriodDate", "CurrencyCode"])
        f = f.merge(dim_acc[["AccountKey", "PLGroupL1", "PLGroupL2", "InEBITDA"]], on="AccountKey")
        f["Gbp"] = f["AmountLocal"] * f[rate_col]
        return f

    def summary(f: pd.DataFrame) -> dict:
        rev = -f.loc[f.PLGroupL1 == "Revenue", "Gbp"].sum()
        cogs = f.loc[f.PLGroupL1 == "Cost of Sales", "Gbp"].sum()
        opex = f.loc[f.PLGroupL1 == "Operating Expenses"]
        ebitda = -f.loc[f.InEBITDA == 1, "Gbp"].sum()
        return {"revenue_gbp": round(rev, 2), "cost_of_sales_gbp": round(cogs, 2), "gross_profit_gbp": round(rev - cogs, 2),
                "gross_margin_pct": round((rev - cogs) / rev * 100, 4),
                "opex_by_l2_gbp": {k: round(v, 2) for k, v in opex.groupby("PLGroupL2")["Gbp"].sum().items()},
                "ebitda_gbp": round(ebitda, 2), "ebitda_margin_pct": round(ebitda / rev * 100, 4)}

    gl_f = gl.copy()
    fy25 = pnl_gbp(gl_f, "AvgRateToGBP", ("2025-01-01", "2025-12-01"))
    plan_b = plan[plan.ScenarioKey == 2]
    bud25 = pnl_gbp(plan_b, "BudgetRateToGBP", ("2025-01-01", "2025-12-01"))
    ytd26 = pnl_gbp(gl_f, "AvgRateToGBP", ("2026-01-01", "2026-10-01"))
    ent_rev = {ENTITIES[k - 1][1]: round(-v, 2) for k, v in fy25[fy25.PLGroupL1 == "Revenue"].groupby("EntityKey")["Gbp"].sum().items()}
    expected = {
        "note": "SYNTHETIC DATA. GBP = AmountLocal x AvgRateToGBP (actuals) or BudgetRateToGBP (budget). Profit = -SUM(AmountLocal).",
        "seed": a.seed, "scale": a.scale,
        "row_counts": {k: int(len(v)) for k, v in tables.items()},
        "fy2025_actual": summary(fy25), "fy2025_budget": summary(bud25), "ytd_oct2026_actual": summary(ytd26),
        "fy2025_actual_revenue_by_entity_gbp": ent_rev,
    }
    (out / "expected.json").write_text(json.dumps(expected, indent=2))
    print(json.dumps({"row_counts": expected["row_counts"], "fy2025_actual": {k: v for k, v in expected["fy2025_actual"].items() if k != "opex_by_l2_gbp"},
                      "fy2025_budget_revenue": expected["fy2025_budget"]["revenue_gbp"], "fy2025_budget_ebitda": expected["fy2025_budget"]["ebitda_gbp"]}, indent=2))


if __name__ == "__main__":
    main()
