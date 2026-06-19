"""Marketing snapshot — spustí konektory (GSC + Cloudflare) a uloží jeden JSON.

Výstup (default --out ./_marketing-out, NIKDY do served tree):
  <out>/<YYYY-MM-DD>.json   = snapshot dne (trend historie)
  <out>/latest.json         = poslední snapshot (rychlé čtení agentem)

Jeden zdroj smí selhat, aniž shodí druhý (status: ok|error per zdroj) — drobné
schéma-chyby u Cloudflare tak nezablokují GSC data.

Spuštění:  python scripts/marketing/snapshot.py [--out DIR]
"""
from __future__ import annotations
import argparse
import datetime
import json
import sys
import traceback
from pathlib import Path

import gsc_pull
import cf_pull

SOURCES = {"gsc": gsc_pull.pull, "cloudflare": cf_pull.pull}


def collect() -> dict:
    out = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "site": "wizardcost.com",
        "sources": {},
    }
    for name, fn in SOURCES.items():
        try:
            out["sources"][name] = {"status": "ok", "data": fn()}
        except SystemExit as e:
            out["sources"][name] = {"status": "error", "error": str(e)}
        except Exception as e:  # noqa: BLE001 — log, neshazuj druhý zdroj
            out["sources"][name] = {"status": "error", "error": f"{e}", "trace": traceback.format_exc()[-800:]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_marketing-out", help="výstupní složka (mimo served tree)")
    args = ap.parse_args()

    snap = collect()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    date = datetime.date.today().isoformat()
    payload = json.dumps(snap, indent=2, ensure_ascii=False)
    (out_dir / f"{date}.json").write_text(payload, encoding="utf-8")
    (out_dir / "latest.json").write_text(payload, encoding="utf-8")

    ok = [n for n, v in snap["sources"].items() if v["status"] == "ok"]
    bad = [n for n, v in snap["sources"].items() if v["status"] != "ok"]
    print(f"snapshot {date}: ok={ok or '—'} error={bad or '—'} → {out_dir}")
    for n in bad:
        print(f"  [{n}] {snap['sources'][n]['error']}", file=sys.stderr)
    # exit 0 i při dílčí chybě — snapshot se uloží; workflow nepadá kvůli jednomu zdroji
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
