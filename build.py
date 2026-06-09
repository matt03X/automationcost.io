#!/usr/bin/env python3
"""build.py — vstříkne kanonická data z data/tools.json do statických stránek.

Jediný zdroj pravdy = data/tools.json. Tento skript z něj vygeneruje `const TOOLS`
blok pro calculator.html (pole, jen ocenitelné plány) a compare.html (objekt, všechny
plány + bohatší pole) a nahradí obsah mezi markery:

    /* DATA:TOOLS:START */ … /* DATA:TOOLS:END */

Build-time injekce (ne runtime fetch) → ceny zůstávají v HTML pro crawlery, žádná latence.

Spuštění:
    python build.py            # přegeneruje calculator.html + compare.html
    python build.py --check    # selže (exit 1), pokud by build něco změnil (CI guard)

Konvence v tools.json:
    opsIncluded / workflowLimit == null  → Infinity (unlimited)
    monthlyUsd == null                   → custom (calculator plán přeskočí, compare = null)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "tools.json"

START = "/* DATA:TOOLS:START */"
END = "/* DATA:TOOLS:END */"
WARN = "/* generováno build.py z data/tools.json — needituj ručně */"


# ---------------------------------------------------------------------------
# Pomocníci pro formátování hodnot do JS literálů
# ---------------------------------------------------------------------------

def js_str(s: str) -> str:
    """Bezpečný JS string literál (json.dumps řeší escaping uvozovek atd.)."""
    return json.dumps(s, ensure_ascii=False)


def js_bool(b: bool) -> str:
    return "true" if b else "false"


def js_limit(v) -> str:
    """null v datech = Infinity v JS (neomezeno)."""
    return "Infinity" if v is None else str(v)


def js_money(v) -> str:
    """null = custom (zůstává null v JS), jinak číslo."""
    return "null" if v is None else str(v)


def js_overage(ov) -> str:
    if ov is None:
        return "null"
    return f"{{ per: {ov['per']}, usd: {ov['usd']} }}"


# ---------------------------------------------------------------------------
# Render plánu
# ---------------------------------------------------------------------------

def render_plan(plan: dict, *, include_note: bool) -> str:
    parts = [
        f'name: {js_str(plan["name"])}',
        f'monthlyUsd: {js_money(plan.get("monthlyUsd"))}',
        f'opsIncluded: {js_limit(plan.get("opsIncluded"))}',
        f'workflowLimit: {js_limit(plan.get("workflowLimit"))}',
    ]
    if plan.get("selfHostOnly"):
        parts.append("selfHostOnly: true")
    if include_note and plan.get("note"):
        parts.append(f'note: {js_str(plan["note"])}')
    return "{ " + ", ".join(parts) + " }"


# ---------------------------------------------------------------------------
# Projektor: calculator.html  (pole; jen plány s konkrétní cenou; s note)
# ---------------------------------------------------------------------------

def render_calculator(tools: list[dict]) -> str:
    lines = ["const TOOLS = ["]
    for t in tools:
        priced = [p for p in t["plans"] if p.get("monthlyUsd") is not None]
        lines.append("  {")
        lines.append(
            f'    slug: {js_str(t["slug"])}, name: {js_str(t["name"])}, '
            f'selfHostable: {js_bool(t["selfHostable"])}, aiFeatures: {js_bool(t["aiFeatures"])}, '
            f'integrations: {t["integrations"]},'
        )
        lines.append(
            f'    homepage: {js_str(t["homepage"])}, affiliateUrl: {js_str(t["affiliateUrl"])}, '
            f'hasAffiliate: {js_bool(t["hasAffiliate"])},'
        )
        lines.append("    plans: [")
        for p in priced:
            lines.append("      " + render_plan(p, include_note=True) + ",")
        lines.append(f"    ], overage: {js_overage(t.get('overage'))} }},")
    lines.append("];")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Projektor: compare.html  (objekt; všechny plány; bez note; bohatší pole)
# ---------------------------------------------------------------------------

def render_compare(tools: list[dict]) -> str:
    lines = ["const TOOLS = {"]
    for t in tools:
        lines.append(f'  {js_str(t["slug"])}: {{')
        lines.append(f'    slug: {js_str(t["slug"])}, name: {js_str(t["name"])},')
        lines.append(f'    tagline: {js_str(t["tagline"])},')
        lines.append(
            f'    selfHostable: {js_bool(t["selfHostable"])}, '
            f'aiFeatures: {js_bool(t["aiFeatures"])}, integrations: {t["integrations"]},'
        )
        lines.append(f'    license: {js_str(t["license"])},')
        lines.append(
            f'    freeOps: {js_str(t["freeOps"])}, freeWorkflows: {js_str(t["freeWorkflows"])}, '
            f'maxSteps: {js_str(t["maxSteps"])},'
        )
        lines.append(
            f'    timeout: {js_str(t["timeout"])}, logHistory: {js_str(t["logHistory"])}, '
            f'gdprFriendly: {js_bool(t["gdprFriendly"])},'
        )
        lines.append(
            f'    multiUser: {js_bool(t["multiUser"])}, apiAccess: {js_bool(t["apiAccess"])}, '
            f'webhooks: {js_bool(t["webhooks"])}, codeSteps: {js_bool(t["codeSteps"])},'
        )
        lines.append(f'    homepage: {js_str(t["homepage"])},')
        lines.append(f'    affiliateUrl: {js_str(t["affiliateUrl"])},')
        lines.append(f'    hasAffiliate: {js_bool(t["hasAffiliate"])},')
        lines.append("    plans: [")
        for p in t["plans"]:
            lines.append("      " + render_plan(p, include_note=False) + ",")
        lines.append("    ],")
        lines.append(f"    overage: {js_overage(t.get('overage'))},")
        lines.append(f'    pros: [{", ".join(js_str(x) for x in t["pros"])}],')
        lines.append(f'    cons: [{", ".join(js_str(x) for x in t["cons"])}],')
        lines.append("  },")
    lines.append("};")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Injekce mezi markery
# ---------------------------------------------------------------------------

def inject(path: Path, generated: str) -> bool:
    """Nahradí obsah mezi START/END markery. Vrací True, pokud se soubor změnil."""
    text = path.read_text(encoding="utf-8")
    if START not in text or END not in text:
        raise SystemExit(
            f"CHYBA: v {path.name} chybí markery {START} … {END}. "
            "Obal `const TOOLS = …;` těmito markery (jednorázově ručně)."
        )
    pre, rest = text.split(START, 1)
    _, post = rest.split(END, 1)

    # zachovej odsazení markeru (mezery před START na jeho řádku)
    indent = pre[pre.rfind("\n") + 1:]
    block = f"{START} {WARN}\n{generated}\n{indent}{END}"
    new_text = pre + block + post

    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject data/tools.json into static pages.")
    parser.add_argument("--check", action="store_true",
                        help="Selže (exit 1), pokud by build něco změnil — bez zápisu.")
    args = parser.parse_args()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    tools = data["tools"]

    targets = {
        ROOT / "calculator.html": render_calculator(tools),
        ROOT / "compare.html": render_compare(tools),
    }

    if args.check:
        dirty = []
        for path, generated in targets.items():
            text = path.read_text(encoding="utf-8")
            pre, rest = text.split(START, 1)
            _, post = rest.split(END, 1)
            indent = pre[pre.rfind("\n") + 1:]
            block = f"{START} {WARN}\n{generated}\n{indent}{END}"
            if pre + block + post != text:
                dirty.append(path.name)
        if dirty:
            print(f"[build --check] OUT OF DATE: {', '.join(dirty)} — spusť `python build.py`.")
            return 1
        print("[build --check] OK — stránky jsou aktuální vůči data/tools.json.")
        return 0

    changed = []
    for path, generated in targets.items():
        if inject(path, generated):
            changed.append(path.name)
    if changed:
        print(f"[build] aktualizováno: {', '.join(changed)}")
    else:
        print("[build] beze změny (stránky už byly aktuální).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
