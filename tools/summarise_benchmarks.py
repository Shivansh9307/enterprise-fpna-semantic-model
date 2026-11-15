#!/usr/bin/env python3
"""Summarise the dscmd benchmark files in tests/perf/results into one table, slowest first.

    python tools/summarise_benchmarks.py              # print the table
    python tools/summarise_benchmarks.py --markdown   # the same as a Markdown table

Each benchmark file holds several cold-cache and warm-cache runs of one query. The table shows the median and the
maximum of the cold runs, the median of the warm runs, and the storage engine share. Timings are from one machine
on synthetic data: use them to rank queries, not as absolute figures.
"""
from __future__ import annotations

import argparse
import csv
import io
import statistics
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "tests" / "perf" / "results"


def read(path: Path):
    text = path.read_text(encoding="utf-8-sig")
    if "Sequence,Cache" not in text:
        return None  # not a benchmark file
    runs = list(csv.DictReader(io.StringIO(text.split("# Summary")[0].strip())))
    cold = [r for r in runs if r["Cache"] == "Cold"]
    warm = [r for r in runs if r["Cache"] == "Warm"]
    num = lambda rows, key: [float(r[key]) for r in rows]
    return {
        "query": path.stem,
        "cold_median": statistics.median(num(cold, "TotalDuration_ms")),
        "cold_max": max(num(cold, "TotalDuration_ms")),
        "warm_median": statistics.median(num(warm, "TotalDuration_ms")),
        "se_queries": max(num(cold, "StorageEngineQueryCount")),
        "se_ms": statistics.median(num(cold, "StorageEngineDuration_ms")),
        "fe_ms": statistics.median(num(cold, "FormulaEngineDuration_ms")),
        "rows": int(float(runs[0]["RowCount"])),
        "runs": f"{len(cold)}+{len(warm)}",
        "errors": sum(1 for r in runs if r.get("Error")),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--top", type=int, default=0, help="show only the slowest N")
    ap.add_argument("--prefix", default="", help="only files whose name starts with this")
    args = ap.parse_args()
    rows = [r for r in (read(p) for p in sorted(RESULTS.glob(f"{args.prefix}*.csv"))) if r]
    rows.sort(key=lambda r: -r["cold_median"])
    if args.top:
        rows = rows[: args.top]
    head = ["query", "cold median ms", "cold max ms", "warm median ms", "FE ms", "SE ms", "SE queries", "rows", "runs", "errors"]
    body = [[r["query"], f"{r['cold_median']:.0f}", f"{r['cold_max']:.0f}", f"{r['warm_median']:.0f}", f"{r['fe_ms']:.0f}",
             f"{r['se_ms']:.0f}", f"{r['se_queries']:.0f}", f"{r['rows']:,}", r["runs"], str(r["errors"])] for r in rows]
    if args.markdown:
        print("| " + " | ".join(head) + " |")
        print("|" + "|".join(["---"] + ["---:"] * (len(head) - 1)) + "|")
        for b in body:
            print("| " + " | ".join(b) + " |")
    else:
        widths = [max(len(x) for x in col) for col in zip(head, *body)]
        for line in [head] + body:
            print("  ".join(x.ljust(w) if i == 0 else x.rjust(w) for i, (x, w) in enumerate(zip(line, widths))))
    print(f"\n{len(rows)} queries")


if __name__ == "__main__":
    main()
