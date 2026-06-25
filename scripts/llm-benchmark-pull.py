#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm-benchmark-pull.py — pull REAL LLM benchmark scores from Epoch AI (CC-BY)
and write llm/data/benchmarks.json. Replaces the editorial capabilityBand estimate
in the recommendation engine with sourced {value, source, asof} numbers.

GOVERNANCE
  - ONLY Epoch AI Benchmarking Hub (CC-BY, programmatic reuse permitted with attribution).
  - Artificial Analysis is BANNED and never touched.
  - No fabrication: a model with no Epoch match is left out (engine falls back to
    the editorial capabilityBand / tier via the coverage guard in llm/build.py).
  - Every value carries {value, source, asof, variant}. asof = Epoch "Release date".

Run:  python scripts/llm-benchmark-pull.py            (writes llm/data/benchmarks.json)
      python scripts/llm-benchmark-pull.py --check    (report coverage, write nothing)
"""
import csv, io, json, re, sys, urllib.request, zipfile
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "llm" / "data" / "models.json"
OUT = ROOT / "llm" / "data" / "benchmarks.json"
EPOCH_ZIP = "https://epoch.ai/data/benchmark_data.zip"
ATTRIBUTION = ("Epoch AI, 'AI Benchmarking Hub'. Published online at epoch.ai. "
               "Retrieved from 'https://epoch.ai/benchmarks/use-this-data'")

# Epoch CSV -> our benchmark metric key + score column
SOURCES = {
    "eci":                   ("epoch_capabilities_index.csv", "ECI Score"),
    "gpqa_diamond":          ("gpqa_diamond.csv", "mean_score"),
    "mmlu":                  ("mmlu_external.csv", "mean_score"),
    "swe_bench_verified":    ("swe_bench_verified.csv", "mean_score"),
    "terminal_bench":        ("terminalbench_external.csv", "mean_score"),
}
# explicit aliases where normalisation alone wouldn't match (our id -> epoch base)
ALIAS = {"grok-4.3": "grok-4-3"}
DATESUF = re.compile(r"-20\d\d-\d\d-\d\d$|-20\d{6}$")  # -YYYY-MM-DD or -YYYYMMDD


def norm(name: str) -> str:
    """Canonical key for matching: drop effort/context variant suffix + trailing date,
    '.'/'_'/' ' -> '-'. Epoch uses '_' for variants (grok-4.3_high, …_16K)."""
    s = name.strip()
    s = s.split("_")[0] if "_" in s else s          # drop variant (grok-4.3_high, haiku…_16K)
    s = DATESUF.sub("", s)                           # drop trailing date (both formats)
    s = s.lower().replace(".", "-").replace("_", "-").replace(" ", "-")
    return re.sub(r"-+", "-", s).strip("-")


def load_csv(z, fname):
    match = [n for n in z.namelist() if n.endswith(fname)]
    if not match:
        return []
    return list(csv.DictReader(io.StringIO(z.read(match[0]).decode("utf-8", "replace"))))


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    check = "--check" in sys.argv
    data = json.loads(MODELS.read_text(encoding="utf-8"))
    our = [(m["id"], m["name"]) for p in data["providers"] for m in p["models"]]

    print(f"downloading {EPOCH_ZIP} ...")
    req = urllib.request.Request(EPOCH_ZIP, headers={"User-Agent": "Mozilla/5.0 (WizardCost benchmark pull)"})
    blob = urllib.request.urlopen(req, timeout=40).read()
    z = zipfile.ZipFile(io.BytesIO(blob))

    # build per-metric index: norm(base) -> list of (value, variant, release_date, accessibility)
    idx = {}
    accessibility = {}  # norm -> "Open weights..." etc (from ECI csv)
    for metric, (fname, col) in SOURCES.items():
        rows = load_csv(z, fname)
        for r in rows:
            mv = r.get("Model version") or ""
            val = to_float(r.get(col))
            if not mv or val is None:
                continue
            key = norm(mv)
            idx.setdefault(metric, {}).setdefault(key, []).append(
                (val, mv, r.get("Release date") or "", r.get("Model accessibility") or ""))
            if metric == "eci" and r.get("Model accessibility"):
                accessibility[key] = r["Model accessibility"]

    out_models, coverage = {}, []
    for mid, mname in our:
        key = ALIAS.get(mid, norm(mid))
        bm = {}
        for metric in SOURCES:
            cand = idx.get(metric, {}).get(key)
            if not cand:
                continue
            val, variant, rel, _ = max(cand, key=lambda t: t[0])  # best-scoring variant
            bm[metric] = {"value": round(val, 4), "source": "Epoch AI", "asof": rel, "variant": variant}
        if bm:
            acc = accessibility.get(key)
            entry = {"benchmarks": bm}
            if acc:
                entry["openWeights"] = acc.lower().startswith("open")
            out_models[mid] = entry
        coverage.append((mname, sorted(bm.keys())))

    print(f"\n=== coverage ({sum(1 for _, b in coverage if b)}/{len(our)} models matched) ===")
    for name, mets in coverage:
        print(f"  {name:24} {', '.join(mets) if mets else 'NO MATCH (editorial fallback)'}")

    payload = {
        "_meta": {
            "source": "Epoch AI Benchmarking Hub",
            "url": "https://epoch.ai/data/benchmark_data.zip",
            "license": "CC-BY",
            "attribution": ATTRIBUTION,
            "pulled": str(date.today()),
            "note": ("REAL benchmark scores (no fabrication). Models without an Epoch match are "
                     "omitted -> engine falls back to editorial capabilityBand/tier. eci = Epoch "
                     "Capabilities Index (composite). Variant = exact Epoch 'Model version' (best effort). "
                     "Artificial Analysis NOT used."),
            "metrics": {
                "eci": "Epoch Capabilities Index (composite capability score; drives the 'frontier' dimension)",
                "gpqa_diamond": "GPQA Diamond accuracy (hard science reasoning)",
                "mmlu": "MMLU accuracy (broad knowledge)",
                "swe_bench_verified": "SWE-bench Verified resolve rate (agentic coding)",
                "terminal_bench": "Terminal-Bench score (CLI/agentic)",
            },
        },
        "models": out_models,
    }
    if check:
        print("\n[--check] wrote nothing.")
        return 0
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT.relative_to(ROOT)} ({len(out_models)} models with benchmarks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
