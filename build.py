#!/usr/bin/env python3
"""build.py — root (umbrella) build pro wizardcost.com.

Homepage: vygeneruje `const DEMO` blok hero price-dema z automation/data/tools.json
(jediný zdroj pravdy cen) a nahradí obsah mezi markery:

    /* DATA:DEMO:START */ … /* DATA:DEMO:END */

Cenová logika kopíruje cost engine z automation/calculator.html (calcCost):
monthly billing, self-host povolen, workflows=3, custom tier odhad exponentem 0.7
nad největším veřejným cloud plánem. Při změně enginu změň i `cheapest_monthly`
níže — shodu hlídá calc-test/verify-demo.js.

Dále: sitemap.xml, robots.txt, GA4/analytics snippety. TOOLS injekce pro
calculator/compare tu zůstává jen pro případ, že by stránky ležely v rootu
(v tomhle repu žijí v /automation/ s vlastním build.py).

Spuštění:
    python build.py            # přegeneruje index.html (DEMO) + site artefakty
    python build.py --check    # selže (exit 1), pokud by build něco změnil (CI guard)

Konvence v tools.json:
    opsIncluded / workflowLimit == null  → Infinity (unlimited)
    monthlyUsd == null                   → custom (cena se odhaduje)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "tools.json"
AUTOMATION_DATA = ROOT / "automation" / "data" / "tools.json"
SITE = ROOT / "data" / "site.json"

START = "/* DATA:TOOLS:START */"
END = "/* DATA:TOOLS:END */"
WARN = "/* generováno build.py z data/tools.json — needituj ručně */"

DEMO_START = "/* DATA:DEMO:START */"
DEMO_END = "/* DATA:DEMO:END */"
DEMO_WARN = "/* generováno build.py z automation/data/tools.json — needituj ručně */"

# Hero demo: které objemy (RUNS/mo) a nástroje homepage ukazuje. DEMO_STEPS =
# předpokládané kroky/workflow pro převod runs → vendorova jednotka (musí sedět
# s verify-demo.js, který volá JS calcCost se stejnými steps).
DEMO_VOLUMES = [1000, 5000, 20000, 100000]
DEMO_TOOLS = [("n8n", "n8n"), ("make", "Make"), ("pipedream", "Pipedream"), ("zapier", "Zapier")]
DEMO_WORKFLOWS = 3
DEMO_STEPS = 3
DEMO_FOOT_TEXT = "*self-hosted = server hardware, not a tool fee · units differ per tool (we convert runs→each vendor's unit) · ~ estimated custom tier"

AN_START = "<!-- ANALYTICS (build.py) -->"
AN_END = "<!-- /ANALYTICS -->"

GA_START = "<!-- GA4 (build.py) -->"
GA_END = "<!-- /GA4 -->"


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


def js_selfhosthw(tiers) -> str:
    """selfHostHw = stupňovité VPS prahy podle objemu (upTo == null → Infinity)."""
    if not tiers:
        return "null"
    cells = ", ".join(f"{{ upTo: {js_limit(t.get('upTo'))}, usd: {t['usd']} }}" for t in tiers)
    return f"[{cells}]"


def js_creditbands(bands) -> str:
    """creditBands = [[upTo, perCredit], …] tarifní tabulka (Pipedream).
    upTo == null → Infinity (poslední neomezené pásmo)."""
    return "[" + ", ".join(f"[{js_limit(upto)}, {pc}]" for upto, pc in bands) + "]"


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
    if "overage" in plan:
        # per-plan override tool-level overage; null = plán nemá pay-as-you-go
        parts.append(f'overage: {js_overage(plan["overage"])}')
    if plan.get("creditBands"):
        parts.append(f'creditBands: {js_creditbands(plan["creditBands"])}')
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
            f'unitModel: {js_str(t.get("unitModel", "runs"))}, annualFactor: {t.get("annualFactor", 1)}, '
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
        lines.append(f"    ], overage: {js_overage(t.get('overage'))}, "
                     f"selfHostHw: {js_selfhosthw(t.get('selfHostHw'))} }},")
    lines.append("];")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Projektor: compare.html  (objekt; všechny plány; bez note; bohatší pole)
# ---------------------------------------------------------------------------

def render_compare(tools: list[dict]) -> str:
    lines = ["const TOOLS = {"]
    for t in tools:
        lines.append(f'  {js_str(t["slug"])}: {{')
        lines.append(f'    slug: {js_str(t["slug"])}, name: {js_str(t["name"])}, unitModel: {js_str(t.get("unitModel", "runs"))}, annualFactor: {t.get("annualFactor", 1)},')
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
        lines.append(f"    selfHostHw: {js_selfhosthw(t.get('selfHostHw'))},")
        lines.append(f'    pros: [{", ".join(js_str(x) for x in t["pros"])}],')
        lines.append(f'    cons: [{", ".join(js_str(x) for x in t["cons"])}],')
        lines.append("  },")
    lines.append("};")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hero price demo (homepage) — Python port calcCost z automation/calculator.html
# ---------------------------------------------------------------------------

def self_host_hw_cost(tool: dict, ops: int):
    """VPS cena pro daný objem (selfHostHw prahy, upTo=None → neomezeno).
    Zrcadlí JS selfHostHwCost(). None = tool nemá self-host hardware škálu."""
    tiers = tool.get("selfHostHw")
    if not tiers:
        return None
    for t in tiers:
        if t.get("upTo") is None or ops <= t["upTo"]:
            return t["usd"]
    return tiers[-1]["usd"]


def vendor_units(tool: dict, runs: int, steps: int) -> int:
    """runs×steps → billable jednotka vendora. Zrcadlí JS vendorUnits().
    runs (n8n exec, Pipedream credit/běh), modules=runs×steps (Make), actions
    (Zapier: trigger+filtry zdarma → runs×(steps−1)×0.8)."""
    s = max(1, steps)
    model = tool.get("unitModel", "runs")
    if model == "modules":
        return runs * s
    if model == "actions":
        return round(runs * max(1, s - 1) * 0.8)
    return runs


def cheapest_monthly(tool: dict, runs: int, steps: int = DEMO_STEPS, workflows: int = DEMO_WORKFLOWS) -> dict | None:
    """Nejlevnější měsíční cena nástroje při daném objemu (hostPref=any, monthly).

    runs = běhy workflow/měsíc, steps = kroky na workflow → engine přepočítá na
    vendorovu jednotku (vendor_units) a teprve pak počítá cenu. Zrcadlí calcCost():
    - plány s monthlyUsd=None (custom) se přeskočí a ocení odhadem níže
    - overage: ceil((ops - included) / per) * usd; creditBands flat-per-band
    - custom odhad: kotva = největší veřejný cloud plán; exponent 0.7
    - shoda ceny: pro label preferuj placený plán bez overage (Core, ne Free+ops)
    """
    ops = vendor_units(tool, runs, steps)
    best = None  # (cost, label_pref, plan, overage_usd)
    for p in tool["plans"]:
        if p.get("monthlyUsd") is None:
            continue
        wl = p.get("workflowLimit")
        if wl is not None and wl < workflows:
            continue
        # čistě open-source self-host plán ($8 placeholder): reálná cena = VPS,
        # který škáluje s objemem. Placené self-host licence (n8n Business $667)
        # si drží vlastní cenu. Zrcadlí JS hwPlan větev v calcCost().
        hw_plan = p.get("selfHostOnly") and p["monthlyUsd"] <= 8 and tool.get("selfHostHw")
        cost = self_host_hw_cost(tool, ops) if hw_plan else p["monthlyUsd"]
        over = 0
        inc = p.get("opsIncluded")  # None = unlimited
        if not p.get("selfHostOnly") and inc is not None and ops > inc:
            if p.get("creditBands"):
                # Pipedream: base + (kredity nad included) × sazba pásma. Zrcadlí
                # JS creditBandRate: pásmo s upTo (None=Infinity) >= ops. Flat-per-band.
                rate = p["creditBands"][-1][1]
                for upto, pc in p["creditBands"]:
                    if upto is None or ops <= upto:
                        rate = pc
                        break
                over = (ops - inc) * rate
                cost = round(cost + over, 2)
            else:
                # per-plan overage přebíjí tool-level; null = plán nemá pay-as-you-go
                ov = p["overage"] if "overage" in p else tool.get("overage")
                if not ov:
                    continue
                over = math.ceil((ops - inc) / ov["per"]) * ov["usd"]
                cost = round(cost + over, 2)  # na centy — zrcadlí JS ($19.99 + $25 ≠ 44.9899…)
        # při shodě ceny preferuj pro label placený plán bez overage, pak placený
        # s overage, až nakonec free tier ("Core +ops" čitelnější než "Free +ops")
        if over == 0 and p["monthlyUsd"] > 0:
            label_pref = 0
        elif p["monthlyUsd"] > 0:
            label_pref = 1
        else:
            label_pref = 2
        if best is None or (cost, label_pref) < (best[0], best[1]):
            best = (cost, label_pref, p, over)

    custom = next((p for p in tool["plans"] if p.get("monthlyUsd") is None), None)
    if custom:
        anchors = [p for p in tool["plans"]
                   if p.get("monthlyUsd") and not p.get("selfHostOnly") and p.get("opsIncluded") is not None]
        if anchors:
            max_inc = max(p["opsIncluded"] for p in anchors)
            anchor = min((p for p in anchors if p["opsIncluded"] == max_inc), key=lambda p: p["monthlyUsd"])
            if ops > anchor["opsIncluded"]:
                est = anchor["monthlyUsd"] * max(1.3, (ops / anchor["opsIncluded"]) ** 0.7)
                est = max(5, int(est / 5 + 0.5) * 5)
                beyond_public = ops > anchor["opsIncluded"] * 2
                if best is None or (beyond_public and est < best[0]):
                    return {"cost": est, "label": custom["name"], "est": True}

    if best is None:
        return None
    cost, _, plan, over = best
    if plan.get("selfHostOnly"):
        label = "self-hosted*"
    else:
        label = plan["name"] + (" +ops" if over > 0 else "")
    return {"cost": cost, "label": label, "est": False}


def render_demo(tools: list[dict]) -> str:
    by_slug = {t["slug"]: t for t in tools}
    lines = ["const DEMO = {"]
    for vol in DEMO_VOLUMES:
        rows = []
        for slug, display in DEMO_TOOLS:
            r = cheapest_monthly(by_slug[slug], vol)
            if r is None:
                raise SystemExit(f"CHYBA: {slug} nemá ocenitelný plán pro {vol} ops — uprav DEMO_TOOLS/DEMO_VOLUMES.")
            row = f'{{n:{js_str(display)}, c:{r["cost"]}, note:{js_str(r["label"])}'
            if r["est"]:
                row += ", est:1"
            rows.append(row + "}")
        lines.append(f"  {vol}: [ " + ", ".join(rows) + " ],")
    lines.append("};")
    lines.append(f"const DEMO_FOOT = {js_str(DEMO_FOOT_TEXT)};")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Injekce mezi markery
# ---------------------------------------------------------------------------

def render_block(text: str, generated: str, start: str, end: str, warn: str) -> str:
    """Vrátí text s nahrazeným obsahem mezi markery (beze změny souboru)."""
    if start not in text or end not in text:
        raise SystemExit(
            f"CHYBA: chybí markery {start} … {end}. "
            "Obal generovaný blok těmito markery (jednorázově ručně)."
        )
    pre, rest = text.split(start, 1)
    _, post = rest.split(end, 1)
    # zachovej odsazení markeru (mezery před START na jeho řádku)
    indent = pre[pre.rfind("\n") + 1:]
    return pre + f"{start} {warn}\n{generated}\n{indent}{end}" + post


def inject(path: Path, generated: str, start: str = START, end: str = END, warn: str = WARN) -> bool:
    """Nahradí obsah mezi markery. Vrací True, pokud se soubor změnil."""
    text = path.read_text(encoding="utf-8")
    new_text = render_block(text, generated, start, end, warn)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


# ---------------------------------------------------------------------------
# Site-wide artefakty: sitemap.xml, robots.txt, analytics snippet
# ---------------------------------------------------------------------------

def load_site() -> dict:
    if SITE.exists():
        return json.loads(SITE.read_text(encoding="utf-8"))
    return {"domain": "automationcost.io", "cloudflare_analytics_token": "", "sitemap_exclude": ["404.html"]}


def public_pages(exclude: list[str]) -> list[Path]:
    """Veřejné HTML stránky (seřazené), bez vyloučených a bez pomocných `_*`."""
    skip = set(exclude or [])
    return sorted(
        p for p in ROOT.glob("*.html")
        if p.name not in skip and not p.name.startswith("_")
    )


def _site_prefix(domain: str, base_path: str) -> str:
    """https://domain  +  optional /base_path  (no trailing slash)."""
    bp = (base_path or "").strip("/")
    return f"https://{domain}/{bp}".rstrip("/") if bp else f"https://{domain}"


def build_sitemap(domain: str, base_path: str, pages: list[Path]) -> bool:
    prefix = _site_prefix(domain, base_path)
    urls = []
    for p in pages:
        loc = f"{prefix}/" if p.name == "index.html" else f"{prefix}/{p.name}"
        urls.append(f"  <url><loc>{loc}</loc></url>")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls) + "\n</urlset>\n"
    )
    out = ROOT / "sitemap.xml"
    if not out.exists() or out.read_text(encoding="utf-8") != xml:
        out.write_text(xml, encoding="utf-8")
        return True
    return False


def build_robots(domain: str, base_path: str, extra_sitemaps: list[str] | None = None) -> bool:
    """robots.txt only belongs at the domain root. In a sub-folder build
    (base_path set) we skip it — the root build owns the canonical robots.txt.
    extra_sitemaps lists additional sitemap URLs (e.g. per-section /automation/
    sitemaps) so crawlers discover every section from the one root robots.txt."""
    if (base_path or "").strip("/"):
        return False
    sitemaps = [f"https://{domain}/sitemap.xml", *(extra_sitemaps or [])]
    lines = "\n".join(f"Sitemap: {s}" for s in sitemaps)
    txt = f"User-agent: *\nAllow: /\n\n{lines}\n"
    out = ROOT / "robots.txt"
    if not out.exists() or out.read_text(encoding="utf-8") != txt:
        out.write_text(txt, encoding="utf-8")
        return True
    return False


def apply_analytics(token: str, pages: list[Path]) -> list[str]:
    """Vloží/odebere Cloudflare Web Analytics snippet před </head> všech stránek.
    Idempotentní: nejdřív smaže starý ANALYTICS blok, pak (je-li token) vloží čerstvý.
    Prázdný token = jen úklid (žádné tracking)."""
    snippet = ""
    if token:
        snippet = (
            f'{AN_START}\n'
            f'  <script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
            f'data-cf-beacon=\'{{"token": "{token}"}}\'></script>\n'
            f'  {AN_END}\n  '
        )
    changed = []
    import re as _re
    block_re = _re.compile(_re.escape(AN_START) + r".*?" + _re.escape(AN_END) + r"\n?\s*", _re.S)
    for p in pages:
        text = p.read_text(encoding="utf-8")
        cleaned = block_re.sub("", text)
        if token:
            if "</head>" not in cleaned:
                continue
            new = cleaned.replace("</head>", snippet + "</head>", 1)
        else:
            new = cleaned
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed.append(p.name)
    return changed


def apply_ga4(measurement_id: str, pages: list[Path]) -> list[str]:
    """Vloží/odebere GA4 snippet před </head> všech stránek. Idempotentní."""
    snippet = ""
    if measurement_id:
        snippet = (
            f'{GA_START}\n'
            f'  <script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>\n'
            f'  <script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}'
            f'gtag("js",new Date());gtag("config","{measurement_id}");</script>\n'
            f'  {GA_END}\n  '
        )
    changed = []
    import re as _re
    block_re = _re.compile(_re.escape(GA_START) + r".*?" + _re.escape(GA_END) + r"\n?\s*", _re.S)
    for p in pages:
        text = p.read_text(encoding="utf-8")
        cleaned = block_re.sub("", text)
        if measurement_id:
            if "</head>" not in cleaned:
                continue
            new = cleaned.replace("</head>", snippet + "</head>", 1)
        else:
            new = cleaned
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed.append(p.name)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject data/tools.json into static pages.")
    parser.add_argument("--check", action="store_true",
                        help="Selže (exit 1), pokud by build něco změnil — bez zápisu.")
    args = parser.parse_args()

    site = load_site()

    # jobs: (path, generated, start, end, warn)
    jobs: list[tuple[Path, str, str, str, str]] = []

    # TOOLS injection only applies to pages that actually carry the markers.
    # An umbrella/homepage build (no calculator.html / compare.html present)
    # simply skips it and still does sitemap / robots / analytics.
    if DATA.exists():
        data = json.loads(DATA.read_text(encoding="utf-8"))
        tools = data["tools"]
        candidates = {
            ROOT / "calculator.html": render_calculator,
            ROOT / "compare.html": render_compare,
        }
        jobs += [(p, fn(tools), START, END, WARN) for p, fn in candidates.items() if p.exists()]

    # Hero price demo na homepage — čte kanonická data z automation/data/tools.json
    index_page = ROOT / "index.html"
    demo_src = AUTOMATION_DATA if AUTOMATION_DATA.exists() else DATA
    if index_page.exists() and demo_src.exists() and DEMO_START in index_page.read_text(encoding="utf-8"):
        demo_tools = json.loads(demo_src.read_text(encoding="utf-8"))["tools"]
        jobs.append((index_page, render_demo(demo_tools), DEMO_START, DEMO_END, DEMO_WARN))

    if args.check:
        dirty = []
        for path, generated, start, end, warn in jobs:
            text = path.read_text(encoding="utf-8")
            if render_block(text, generated, start, end, warn) != text:
                dirty.append(path.name)
        if dirty:
            print(f"[build --check] OUT OF DATE: {', '.join(dirty)} — spusť `python build.py`.")
            return 1
        print("[build --check] OK — stránky jsou aktuální vůči tools.json.")
        return 0

    changed = []
    for path, generated, start, end, warn in jobs:
        if inject(path, generated, start, end, warn):
            changed.append(path.name)

    # site-wide artefakty
    domain = site.get("domain", "automationcost.io")
    base_path = site.get("base_path", "")
    pages = public_pages(site.get("sitemap_exclude", ["404.html"]))
    if build_sitemap(domain, base_path, pages):
        changed.append("sitemap.xml")
    if build_robots(domain, base_path, site.get("extra_sitemaps", [])):
        changed.append("robots.txt")
    an_changed = apply_analytics(site.get("cloudflare_analytics_token", ""), pages)
    changed.extend(an_changed)
    ga_changed = apply_ga4(site.get("ga4_measurement_id", ""), pages)
    changed.extend(ga_changed)

    if changed:
        print(f"[build] aktualizováno: {', '.join(changed)}")
    else:
        print("[build] beze změny (vše aktuální).")
    if not site.get("cloudflare_analytics_token"):
        print("[build] pozn.: cloudflare_analytics_token je prázdný → analytics se nevkládá. "
              "Doplň token v data/site.json a spusť build znovu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
