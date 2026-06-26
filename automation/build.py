#!/usr/bin/env python3
"""build.py — vstříkne kanonická data z data/tools.json do statických stránek.

Jediný zdroj pravdy = data/tools.json. Tento skript z něj vygeneruje `const TOOLS`
blok pro calculator.html (pole, všechny plány vč. custom tier) a compare.html (objekt, všechny
plány + bohatší pole) a nahradí obsah mezi markery:

    /* DATA:TOOLS:START */ … /* DATA:TOOLS:END */

Build-time injekce (ne runtime fetch) → ceny zůstávají v HTML pro crawlery, žádná latence.

Spuštění:
    python build.py            # přegeneruje calculator.html + compare.html
    python build.py --check    # selže (exit 1), pokud by build něco změnil (CI guard)

Konvence v tools.json:
    opsIncluded / workflowLimit == null  → Infinity (unlimited)
    monthlyUsd == null                   → custom (calculator cenu odhadne za běhu, compare = "Custom")
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_hosting import expand_hosting_variants, apply_fx  # noqa: E402
from build_pricing import build_pricing_pages, build_seo_pages, _page_graph_ld, _iso_date, _clamp_title, _clamp_desc, _seo_breadcrumb_ld  # noqa: E402
from build_catalog import build_catalog_pages  # noqa: E402
from build_integrations import build_integrations_page  # noqa: E402
import integration_counts as ic  # noqa: E402  — jediný zdroj počtů integrací + typové labely
import build_i18n  # noqa: E402  — language layer (/de/ … mirror, hreflang, switcher)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "tools.json"
SITE = ROOT / "data" / "site.json"

START = "/* DATA:TOOLS:START */"
END = "/* DATA:TOOLS:END */"
WARN = "/* generováno build.py z data/tools.json — needituj ručně */"

CLOG_START = "/* DATA:CHANGELOG:START */"
CLOG_END = "/* DATA:CHANGELOG:END */"
CLOG_WARN = "/* generováno build.py z git historie data/tools.json — needituj ručně */"

# GEO:LD — Org+WebSite+WebPage @graph injektovaný do <head> statických stránek
# (živý dateModified z last_reviewed). Markery jsou HTML komentáře → warn prázdný
# (jinak by se text vykreslil mimo komentář).
GEO_LD_START = "<!-- GEO:LD:START -->"
GEO_LD_END = "<!-- GEO:LD:END -->"
GEO_LD_WARN = ""

SCORING = ROOT / "data" / "scoring-model.json"
SCORING_START = "/* DATA:SCORING:START */"
SCORING_END = "/* DATA:SCORING:END */"
SCORING_WARN = "/* generováno build.py z data/scoring-model.json — needituj ručně, edituj JSON */"

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
    """selfHostHw = stupňovité VPS prahy podle objemu (upTo == null → Infinity).
    Chybí-li klíč, vrací 'null' (tool nemá self-host nebo používá fixní plán)."""
    if not tiers:
        return "null"
    cells = ", ".join(
        f"{{ upTo: {js_limit(t.get('upTo'))}, usd: {t['usd']}" +
        (f", home: {t['home']}" if t.get('home') is not None else "") +
        (f", hwOneOff: {t['hwOneOff']}" if t.get('hwOneOff') is not None else "") +
        (f", spec: {js_str(t['spec'])}" if t.get('spec') else "") + " }"
        for t in tiers)
    return f"[{cells}]"


def js_creditbands(bands) -> str:
    """creditBands = [[upTo, perCredit], …] tarifní tabulka (Pipedream).
    upTo == null → Infinity (poslední neomezené pásmo). Pole dvojic."""
    return "[" + ", ".join(f"[{js_limit(upto)}, {pc}]" for upto, pc in bands) + "]"


# ---------------------------------------------------------------------------
# Render plánu
# ---------------------------------------------------------------------------

def render_plan(plan: dict, *, include_note: bool) -> str:
    parts = []
    if plan.get("monthlyUsd") is None:
        # custom / contact-sales tier — calculator.html estimates its price at
        # runtime (calcCost), compare.html renders "Custom"
        parts.append("custom: true")
    parts += [
        f'name: {js_str(plan["name"])}',
        f'monthlyUsd: {js_money(plan.get("monthlyUsd"))}',
        f'opsIncluded: {js_limit(plan.get("opsIncluded"))}',
        f'workflowLimit: {js_limit(plan.get("workflowLimit"))}',
    ]
    # reálná roční cena (billed-annually $/mo) — engine ji použije při billing=annual;
    # chybí-li (pipedream/activepieces zatím nescrapováno) → annual = monthly (žádná vymyšlená sleva)
    if isinstance(plan.get("annualUsd"), (int, float)):
        parts.append(f'annualUsd: {plan["annualUsd"]}')
    # per-active-flow billing (Activepieces cloud): cost = max(0, flows - freeFlows) * pricePerFlowUsd
    if plan.get("pricePerFlowUsd"):
        parts.append(f'pricePerFlowUsd: {plan["pricePerFlowUsd"]}')
    if plan.get("freeFlows") is not None:
        parts.append(f'freeFlows: {plan["freeFlows"]}')
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
# Projektor: calculator.html  (pole; všechny plány — custom tier s flagem
# `custom: true`, jehož cenu calcCost odhaduje za běhu; s note)
# ---------------------------------------------------------------------------

def render_calculator(tools: list[dict]) -> str:
    lines = ["const TOOLS = ["]
    for t in tools:
        priced = t["plans"]
        lines.append("  {")
        lines.append(
            f'    slug: {js_str(t["slug"])}, name: {js_str(t["name"])}, '
            f'unitModel: {js_str(t.get("unitModel", "runs"))}, annualFactor: {t.get("annualFactor", 1)}, '
            f'selfHostable: {js_bool(t["selfHostable"])}, aiFeatures: {js_bool(t["aiFeatures"])}, '
            f'integrations: {t["integrations"]}, integrationType: {js_str(ic.count_type(t["slug"]))},'
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
    # expanze hosting variant (Cloud / VPS / vlastní server) — compare ukazuje
    # každou variantu jako samostatný "tool" (n8n 3×, atd.). Viz build_hosting.py.
    lines = ["const TOOLS = {"]
    for t in expand_hosting_variants(tools):
        lines.append(f'  {js_str(t["slug"])}: {{')
        lines.append(f'    slug: {js_str(t["slug"])}, name: {js_str(t["name"])}, unitModel: {js_str(t.get("unitModel", "runs"))}, annualFactor: {t.get("annualFactor", 1)},')
        lines.append(f'    hostingKind: {js_str(t.get("hostingKind", "saas"))}, variantOf: {js_str(t.get("variantOf", t["slug"]))},')
        lines.append(f'    tagline: {js_str(t["tagline"])},')
        lines.append(
            f'    selfHostable: {js_bool(t["selfHostable"])}, '
            f'aiFeatures: {js_bool(t["aiFeatures"])}, integrations: {t["integrations"]}, '
            f'integrationType: {js_str(ic.count_type(t.get("variantOf", t["slug"])))},'
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
# Changelog: git historie data/tools.json → veřejný cenový changelog
# ---------------------------------------------------------------------------

def _fmt_money(v) -> str:
    return "Custom" if v is None else f"${v}/mo"


def _fmt_count(v) -> str:
    """Hodnoty limitů BEZ jednotky — jednotku nese název pole („included ops",
    „workflow limit"), opakovat ji ve hodnotách je duplicitní (feedback designu)."""
    return "Unlimited" if v is None else f"{v:,}"


def _fmt_overage(ov) -> str:
    return "none" if ov is None else f"${ov['usd']}/{ov['per']:,} runs"


def tools_history() -> list[tuple[str, dict]]:
    """[(date, parsed tools.json)] pro každý commit měnící data/tools.json,
    od nejstaršího. Sleduje přejmenování (--follow). Bez gitu vrací []."""
    import subprocess
    repo = ROOT.parent
    rel = str(DATA.relative_to(repo)).replace("\\", "/")
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--follow", "--format=%H %ad", "--date=short",
         "--name-only", "--", rel],
        capture_output=True, text=True)
    if log.returncode != 0:
        return []
    commits = []  # (sha, date, path_at_commit)
    sha_date = None
    for raw in log.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) == 2 and len(parts[0]) == 40:
            sha_date = (parts[0], parts[1])
        elif sha_date and line.endswith(".json"):
            commits.append((sha_date[0], sha_date[1], line))
            sha_date = None
    commits.reverse()  # git log dává nejnovější první
    hist = []
    for sha, date, path in commits:
        show = subprocess.run(["git", "-C", str(repo), "show", f"{sha}:{path}"],
                              capture_output=True, text=True)
        if show.returncode != 0:
            continue
        try:
            hist.append((date, json.loads(show.stdout)))
        except json.JSONDecodeError:
            continue
    return hist


def diff_tools(old: dict, new: dict, date: str) -> list[dict]:
    """Cenově relevantní rozdíly dvou verzí tools.json → changelog záznamy.
    Ignoruje _meta, texty, affiliate URL apod. Nové nástroje/plány nehlásí
    (přírůstek katalogu není změna ceny)."""
    entries = []
    olds = {t["slug"]: t for t in old.get("tools", [])}
    for t in new.get("tools", []):
        o = olds.get(t["slug"])
        if o is None:
            continue
        add = lambda item, a, b, d: entries.append(
            {"d": date, "tool": t["slug"], "name": t["name"], "item": item, "old": a, "neu": b, "dir": d})
        # Počty integrací NEhlásíme do (cenového) changelogu: jsou audit/matrix-sourced
        # evidence (integrations/index.json), ne cenový event. Auto-entry typu
        # „n8n 1,868 → 572" by navíc bez metodického kontextu vypadal jako propad.
        if o.get("overage") != t.get("overage"):
            add("Overage", _fmt_overage(o.get("overage")), _fmt_overage(t.get("overage")), "info")
        old_plans = {p["name"]: p for p in o.get("plans", [])}
        for p in t.get("plans", []):
            q = old_plans.get(p["name"])
            if q is None:
                continue
            a, b = q.get("monthlyUsd"), p.get("monthlyUsd")
            if a != b:
                direction = "info" if (a is None or b is None) else ("up" if b > a else "down")
                add(p["name"], _fmt_money(a), _fmt_money(b), direction)
            if q.get("opsIncluded") != p.get("opsIncluded"):
                add(f"{p['name']} — included runs", _fmt_count(q.get("opsIncluded")), _fmt_count(p.get("opsIncluded")), "info")
            if q.get("workflowLimit") != p.get("workflowLimit"):
                add(f"{p['name']} — workflow limit", _fmt_count(q.get("workflowLimit")), _fmt_count(p.get("workflowLimit")), "info")
    return entries


def changelog_entries() -> tuple[list[dict], str | None]:
    """Záznamy changelogu z git historie (nejnovější první) + datum prvního
    commitu tools.json (genesis). Sdílí je changelog.html i RSS feed.

    Filtr baseline (data/changelog-overrides.json, klíč `baseline_until`):
    diffy s datem <= baseline jsou BOOTSTRAP OPRAVY našich výchozích dat, ne
    vendor změny (prokázáno Wayback auditem 2026-06-12 — viz _meta v overrides)
    → do changelogu ani alertů nepatří. Stejný princip jako llm backfill guard."""
    hist = tools_history()
    entries = []
    for (_, older), (date, newer) in zip(hist, hist[1:]):
        entries.extend(diff_tools(older, newer, date))
    overrides_path = DATA.parent / "changelog-overrides.json"
    if overrides_path.exists():
        baseline = json.loads(overrides_path.read_text(encoding="utf-8")).get("baseline_until")
        if baseline:
            entries = [e for e in entries if e["d"] > baseline]
    entries.sort(key=lambda e: e["d"], reverse=True)
    return entries, (hist[0][0] if hist else None)


def render_changelog(tools: list[dict], entries: list[dict], genesis: str | None) -> str:
    lines = ["const CHANGELOG = ["]
    for e in entries:
        lines.append(
            f'  {{ d: {js_str(e["d"])}, tool: {js_str(e["tool"])}, name: {js_str(e["name"])}, '
            f'item: {js_str(e["item"])}, old: {js_str(e["old"])}, neu: {js_str(e["neu"])}, dir: {js_str(e["dir"])} }},')
    lines.append("];")

    import datetime as _dt
    if genesis:
        y, m, _ = genesis.split("-")
        genesis_month = _dt.date(int(y), int(m), 1).strftime("%B %Y")
    else:
        genesis_month = "June 2026"
    n_plans = sum(len(t.get("plans", [])) for t in tools)
    lines.append(f'const CLOG_GENESIS = {js_str(f"Tracking started {genesis_month} · {len(tools)} tools · {n_plans} plans")};')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# X-vs-Y stránky: tools.json (čísla z enginu) + data/pairs.json (editorial)
# → automation/<a>-vs-<b>.html. Šablona portovaná z automation/_vs-example.html
# (design 2026-06-11). Verdikt/stripNote/whyLoser se vkládají DOSLOVNĚ.
# ---------------------------------------------------------------------------

PAIRS = ROOT / "data" / "pairs.json"
PRICE_HISTORY = ROOT / "data" / "price-history.json"


def _root_engine():
    """Importuje root build.py kvůli cheapest_monthly — JEDINÁ kopie cost logiky
    (parita s JS hlídá verify-landing.js); třetí port by se rozjel."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rootbuild", ROOT.parent / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _fmt_usd(cost, est: bool) -> str:
    body = f"{cost:,.2f}".rstrip("0").rstrip(".") if isinstance(cost, float) else f"{cost:,}"
    return ("~$" if est else "$") + body


def _month_year(tools_meta: dict) -> str:
    import datetime as _dt
    lr = (tools_meta or {}).get("last_reviewed")
    if lr:
        try:
            return _dt.date(*[int(x) for x in lr.split("-")]).strftime("%B %Y")
        except ValueError:
            pass
    return "June 2026"


def _logo(slug: str) -> str:
    domain = {"n8n": "n8n.io", "make": "make.com", "pipedream": "pipedream.com",
              "zapier": "zapier.com", "activepieces": "activepieces.com",
              "automatisch": "automatisch.io", "node-red": "nodered.org"}[slug]
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


def _timeout_minutes(s: str):
    """'15 min' → 15, '40 min' → 40, 'No limit*' → inf, jinak None (nesrovnatelné)."""
    import re
    if "no limit" in s.lower():
        return float("inf")
    m = re.match(r"^(\d+)\s*(min|sec)", s.lower())
    if not m:
        return None
    return int(m.group(1)) / (60 if m.group(2) == "sec" else 1)


def _overage_rate(ov):
    return ov["usd"] / ov["per"] if ov else None


# (label, formátovací fce, winner fce → 'a'|'b'|None; None = bez zvýraznění)
def _vs_features():
    def fmt_overage(t):
        ov = t.get("overage")
        return f"+${ov['usd']} per {ov['per']:,} runs" if ov else "none — upgrade only"

    def win_overage(ta, tb):
        ra, rb = _overage_rate(ta.get("overage")), _overage_rate(tb.get("overage"))
        if ra is None or rb is None or ra == rb:
            return None  # bez PAYG vs s PAYG = nejednoznačné (může být dobré i špatné)
        return "a" if ra < rb else "b"

    def win_timeout(ta, tb):
        ma, mb = _timeout_minutes(ta["timeout"]), _timeout_minutes(tb["timeout"])
        if ma is None or mb is None or ma == mb:
            return None
        return "a" if ma > mb else "b"

    def bool_cell(v):
        return '<span class="check">✓</span>' if v else '<span class="cross">✗</span>'

    def win_bool(key):
        return lambda ta, tb: ("a" if ta[key] else "b") if ta[key] != tb[key] else None

    return [
        # Počet integrací s typovým labelem (různá metodika per nástroj). Vítěz se NEvyhlašuje,
        # když mají nástroje jinou bázi (n8n „official nodes" vs Node-RED „community modules" =
        # jablka/hrušky → žádné zavádějící „X > Y").
        ("Integrations", lambda t: ic.label(t["slug"]),
         lambda ta, tb: None if not ic.same_basis(ta["slug"], tb["slug"])
         else (None if ic.count(ta["slug"]) == ic.count(tb["slug"])
               else ("a" if ic.count(ta["slug"]) > ic.count(tb["slug"]) else "b"))),
        ("Free tier", lambda t: f"{t['freeOps']} · {t['freeWorkflows']}", lambda ta, tb: None),
        ("Overage model", fmt_overage, win_overage),
        ("Steps per workflow", lambda t: t["maxSteps"],
         lambda ta, tb: ("a" if ta["maxSteps"].lower().startswith("unlimited") else "b")
         if (ta["maxSteps"].lower().startswith("unlimited") != tb["maxSteps"].lower().startswith("unlimited")) else None),
        ("Execution timeout", lambda t: t["timeout"], win_timeout),
        ("Log history", lambda t: t["logHistory"], lambda ta, tb: None),
        ("EU data residency", lambda t: bool_cell(t["gdprFriendly"]), win_bool("gdprFriendly")),
        ("Self-hosting", lambda t: bool_cell(t["selfHostable"]), win_bool("selfHostable")),
        ("AI features", lambda t: bool_cell(t["aiFeatures"]), win_bool("aiFeatures")),
        ("Multi-user", lambda t: bool_cell(t["multiUser"]), win_bool("multiUser")),
        ("API access", lambda t: bool_cell(t["apiAccess"]), win_bool("apiAccess")),
        ("Webhooks", lambda t: bool_cell(t["webhooks"]), win_bool("webhooks")),
        ("Code steps", lambda t: bool_cell(t["codeSteps"]), win_bool("codeSteps")),
        ("License", lambda t: t["license"], lambda ta, tb: None),
    ]


def _vs_auto_faq(pair, ta, tb, costs, volumes):
    """Standardní FAQ z dat (použité, když pár nemá ruční override `faq`)."""
    a_name, b_name = ta["name"], tb["name"]
    wins = [("a" if ca["cost"] < cb["cost"] else ("b" if cb["cost"] < ca["cost"] else "tie"))
            for ca, cb in costs]
    uniform = wins[0] if all(w == wins[0] and w != "tie" for w in wins) else None
    faq = []
    if uniform:
        wt, lt_ = (ta, tb) if uniform == "a" else (tb, ta)
        (w0, l0), (wN, lN) = (costs[0], costs[-1]) if uniform == "a" else (costs[0][::-1], costs[-1][::-1])
        faq.append({
            "q": f"How do {a_name} and {b_name} compare on price?",
            "a": (f"From published pricing, {wt['name']} is the lower-cost option across the volumes we track — "
                  f"{_fmt_usd(w0['cost'], w0['est'])} vs {_fmt_usd(l0['cost'], l0['est'])} at {volumes[0]:,} runs/mo, "
                  f"and {_fmt_usd(wN['cost'], wN['est'])} vs {_fmt_usd(lN['cost'], lN['est'])} at {volumes[-1]:,}. "
                  "Figures include overage where it applies — see the table above. Price is one factor; the "
                  "feature and trade-off sections cover the rest.")})
    elif not any(w != "tie" for w in wins):
        # úplná shoda na všech objemech (typicky self-host vs self-host — stejná
        # VPS škála): cena není rozhodující, rozdíl je ve funkcích
        faq.append({
            "q": f"How do {a_name} and {b_name} compare on price?",
            "a": (f"They come out to the same cost across the volumes we track — both are free "
                  f"to self-host, so the figure is just your server bill (see the table above). "
                  "Price isn't the deciding factor here; the feature and trade-off sections below "
                  "cover what separates them.")})
    else:
        parts = [f"{volumes[i]:,} runs: {(ta if w == 'a' else tb)['name']}"
                 for i, w in enumerate(wins) if w != "tie"]
        faq.append({
            "q": f"How do {a_name} and {b_name} compare on price?",
            "a": "It depends on volume — the lower-cost option changes: " + " · ".join(parts)
                 + ". Check the table above for your usage level."})
    od = (pair_tools := pair.get("_tools_meta", {}))  # naplněno v render_vs_page
    faq.append({"q": "What counts as an operation on each?",
                "a": f"{od.get(ta['slug'], '')} {od.get(tb['slug'], '')}".strip()})
    sa, sb = ta["selfHostable"], tb["selfHostable"]
    if sa and sb:
        sh = f"Yes — both {a_name} and {b_name} can be self-hosted, which caps the real cost at your server bill."
    elif sa or sb:
        x, y = (ta, tb) if sa else (tb, ta)
        sh = (f"{x['name']} yes — self-hosting makes it nearly free at any volume. "
              f"{y['name']} is cloud-only.")
    else:
        sh = ("No — both are cloud-only. If self-hosting matters to you (cost control, GDPR, "
              "data residency), look at n8n or Activepieces instead — see the "
              '<a href="compare.html">compare tool</a>.')
    faq.append({"q": "Can I self-host either of them?", "a": sh})
    other = tb if pair.get("winner") == ta["slug"] else ta
    if pair.get("whyLoser"):
        faq.append({"q": f"When is {other['name']} the better fit?", "a": pair["whyLoser"]})
    faq.append({"q": "How accurate are these prices?",
                "a": "Taken from official pricing pages and verified "
                     f"{pair.get('_month_year', 'June 2026')}. Values marked ~ are estimates for "
                     'custom enterprise tiers. Every change we record lands in the '
                     '<a href="changelog.html">price changelog</a>.'})
    return faq


def render_vs_page(pair: dict, tools_by_slug: dict, pairs_data: dict, site: dict,
                   tools_meta: dict, engine) -> str:
    ta, tb = tools_by_slug[pair["a"]], tools_by_slug[pair["b"]]
    a_name, b_name = ta["name"], tb["name"]
    volumes = pairs_data["_meta"].get("volumes", [1000, 5000, 20000, 100000])
    month_year = _month_year(tools_meta)
    prefix = _site_prefix(site.get("domain", "wizardcost.com"), site.get("base_path", ""))
    slug = f'{pair["a"]}-vs-{pair["b"]}'

    # ceny z enginu (3 workflows, monthly — stejné assumptions jako homepage DEMO)
    costs = []
    for vol in volumes:
        ra, rb = engine.cheapest_monthly(ta, vol), engine.cheapest_monthly(tb, vol)
        if ra is None or rb is None:
            raise SystemExit(f"CHYBA: {slug} — nástroj nemá ocenitelný plán pro {vol} runs.")
        costs.append((ra, rb))
    wins = [("a" if ca["cost"] < cb["cost"] else ("b" if cb["cost"] < ca["cost"] else "tie"))
            for ca, cb in costs]
    uniform = wins[0] if all(w == wins[0] and w != "tie" for w in wins) else None

    # FAQ: ruční override, jinak auto z dat
    pair = dict(pair)
    pair["_tools_meta"] = {s: d.get("opDef", "") for s, d in pairs_data.get("tools", {}).items()}
    pair["_month_year"] = month_year
    faq = pair.get("faq") or _vs_auto_faq(pair, ta, tb, costs, volumes)

    # vs-strip: VŽDY neutrální "A vs B" (žádný winner "<" — fair-competition neutralita 2026-06-16)
    strip = (f'<span class="who"><img src="{_logo(ta["slug"])}" alt="{a_name} logo">{a_name}</span>\n'
             f'      <span class="lt">vs</span>\n'
             f'      <span class="who"><img src="{_logo(tb["slug"])}" alt="{b_name} logo">{b_name}</span>')

    # cenová tabulka — td.cheap per řádek (vítěz se může mezi objemy přehoupnout)
    rows = []
    any_selfhost_star = False
    for vol, (ra, rb), w in zip(volumes, costs, wins):
        cells = []
        for r, side in ((ra, "a"), (rb, "b")):
            label = r["label"] + (" (estimate)" if r["est"] else "")
            if "self-hosted*" in r["label"]:
                any_selfhost_star = True
            cheap = ' class="cheap"' if w == side else ""
            ok = ' <span class="ok">✓</span>' if w == side else ""
            cells.append(f'<td{cheap}><span class="price">{_fmt_usd(r["cost"], r["est"])}{ok}'
                         f'<small>{label}</small></span></td>')
        rows.append(f'          <tr>\n            <td class="vol">{vol:,}</td>\n'
                    f'            {cells[0]}\n            {cells[1]}\n          </tr>')
    tbl_note = ("~ = estimated custom-tier pricing (vendor quotes individually; calibrated against "
                "public list prices). Assumes 3 workflows, monthly billing, cheapest qualifying plan. "
                f"Prices verified {month_year} — see the <a href=\"changelog.html\">price changelog</a>.")
    if any_selfhost_star:
        tbl_note += (" * self-hosted = free to run yourself; the figure is the server "
                     "infrastructure (VPS + DB, not a tool fee), ~$8/mo small to ~$150/mo at "
                     "high volume — assumes light workflows and excludes your ops time.")

    # feature diff — jen rozdílové řádky; shody do věty pod tabulkou
    diff_rows, same = [], []
    for label, fmt, winner_fn in _vs_features():
        va, vb = fmt(ta), fmt(tb)
        if va == vb:
            same.append(label.lower())
            continue
        w = winner_fn(ta, tb)
        ca = f'<span class="diff-win">{va}</span>' if w == "a" else va
        cb = f'<span class="diff-win">{vb}</span>' if w == "b" else vb
        diff_rows.append(f"          <tr><td>{label}</td><td>{ca}</td><td>{cb}</td></tr>")
    diff_same = ("Same on both: " + " · ".join(same) + ".") if same else ""

    # pros/cons z tools.json (top-level)
    def pc_card(t):
        pros = "\n".join(f'          <li class="pro">{p}</li>' for p in t["pros"])
        cons = "\n".join(f'          <li class="con">{c}</li>' for c in t["cons"])
        return (f'      <div class="pc-card">\n        <div class="pc-head">'
                f'<img src="{_logo(t["slug"])}" alt="{t["name"]} logo">{t["name"]}</div>\n'
                f'        <ul>\n{pros}\n        </ul>\n        <div class="pc-divider"></div>\n'
                f'        <ul>\n{cons}\n        </ul>\n      </div>')

    # outbound CTA — affiliate jen s hasAffiliate (sponsored + ?pc v affiliateUrl)
    def out_card(t):
        blurb = pairs_data.get("tools", {}).get(t["slug"], {}).get("ctaBlurb", "")
        if t["hasAffiliate"]:
            btn = (f'<a href="{t["affiliateUrl"]}" target="_blank" rel="noopener sponsored" '
                   f'class="out-btn aff">Visit {t["name"]} (affiliate) →</a>\n'
                   f'        <span class="aff-note">We earn a commission if you sign up via this link — it never affects the comparison (rankings come purely from public pricing).</span>')
        else:
            btn = (f'<a href="{t["homepage"]}" target="_blank" rel="noopener" '
                   f'class="out-btn plain">Visit {t["name"]} →</a>')
        return (f'      <div class="out-card">\n        <div class="out-head">'
                f'<img src="{_logo(t["slug"])}" alt="{t["name"]} logo">{t["name"]}</div>\n'
                f'        <p>{blurb}</p>\n        {btn}\n      </div>')
    out_cards = [ta, tb]  # rovnocenné pořadí (žádná "winner" karta) — fair-competition neutralita

    # cross-linky: pricing obou + compare + limits + až 3 nejbližší publikované páry
    xlinks = [f'<a class="xlink" href="{ta["slug"]}-pricing.html">{a_name} pricing in detail</a>',
              f'<a class="xlink" href="{tb["slug"]}-pricing.html">{b_name} pricing in detail</a>',
              f'<a class="xlink" href="{ta["slug"]}-alternatives.html">{a_name} alternatives</a>',
              f'<a class="xlink" href="{tb["slug"]}-alternatives.html">{b_name} alternatives</a>',
              '<a class="xlink" href="compare.html">Compare all 7 tools</a>',
              '<a class="xlink" href="limits.html">Plan limits &amp; run caps</a>']
    for other in pairs_data["pairs"]:
        oslug = f'{other["a"]}-vs-{other["b"]}'
        if oslug == slug or len(xlinks) >= 8:
            continue
        if {other["a"], other["b"]} & {pair["a"], pair["b"]}:
            on_a, on_b = tools_by_slug[other["a"]]["name"], tools_by_slug[other["b"]]["name"]
            xlinks.append(f'<a class="xlink" href="{oslug}.html">{on_a} vs {on_b}</a>')

    # FAQPage JSON-LD — 1:1 se zněním na stránce
    faq_ld = json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": f["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq],
    }, ensure_ascii=False, indent=2)
    # breadcrumb JSON-LD (SERP breadcrumbs + topická struktura)
    _home_url = f"https://{site.get('domain', 'wizardcost.com')}/"
    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": _home_url},
            {"@type": "ListItem", "position": 2, "name": "Automation tools", "item": f"{prefix}/tools.html"},
            {"@type": "ListItem", "position": 3, "name": f"{a_name} vs {b_name}", "item": f"{prefix}/{slug}.html"},
        ],
    }, ensure_ascii=False, indent=2)
    faq_html = "\n".join(
        f'      <div class="faq-item">\n        <button class="faq-q" onclick="toggleFaq(this)">{f["q"]}</button>\n'
        f'        <div class="faq-a">{f["a"]}</div>\n      </div>' for f in faq)

    # seo_title override (set per-pair in pairs.json to tune without changing the template default)
    title = (pair.get("seo_title")
             or f"{a_name} vs {b_name}: Pricing &amp; Cost Comparison 2026 | WizardCost")
    desc = (f"{a_name} vs {b_name} priced at " + " / ".join(f"{v:,}" for v in volumes)
            + " runs per month — real plans, overage math, feature differences and how the "
              "pricing compares for your usage.")
    canonical = f"{prefix}/{slug}.html"

    # WebPage + Organization + WebSite graf (GEO/AI-citace: dateModified freshness +
    # identita vydavatele). Bez Product/Offer ceny (stop-and-confirm).
    page_ld = _page_graph_ld(site.get("domain", "wizardcost.com"), canonical,
                             f"{a_name} vs {b_name}: Pricing & Cost Comparison 2026",
                             desc, _iso_date(tools_meta))

    css = _VS_CSS  # sdílená šablona stylů (port z _vs-example.html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build.py z data/tools.json + data/pairs.json — needituj ručně -->
  <title>{_clamp_title(title)}</title>
  <meta name="description" content="{_html_escape(_clamp_desc(desc))}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="AutomationCost.io">
  <meta property="og:title" content="{_html_escape(f'{a_name} vs {b_name}: Pricing & Cost Comparison 2026')}">
  <meta property="og:description" content="{_html_escape(desc)}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{prefix}/og-image.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{prefix}/og-image.png">
  <script type="application/ld+json">
{faq_ld}
  </script>
  <script type="application/ld+json">
{breadcrumb_ld}
  </script>
  <script type="application/ld+json">
{page_ld}
  </script>
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
{css}
  </style>
  <link rel="stylesheet" href="app.css">
</head>
<body class="ac anim">

<div id="ac-progress"></div>

<nav class="ac-nav">
  <a href="/automation/" class="logo">
    <svg class="logo-icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs><linearGradient id="acmk" x1="14" y1="10" x2="30" y2="38" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#2fe39c"></stop><stop offset="1" stop-color="#0ea66e"></stop></linearGradient></defs>
      <path d="M28.5 10.5 L13.5 24 L28.5 37.5" stroke="url(#acmk)" stroke-width="6.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M 36.5 17.8 Q 37.864 22.636 42.7 24 Q 37.864 25.364 36.5 30.2 Q 35.136 25.364 30.3 24 Q 35.136 22.636 36.5 17.8 Z" fill="#eafff5"></path>
    </svg>
    Automation<span>Cost</span><span class="io" style="font-size:0.72em; margin-left:7px;">by WizardCost</span>
  </a>
  <div class="ac-links">
    <a href="compare.html" class="active ac-hide-sm">Compare</a>
    <a href="limits.html" class="ac-hide-sm">Pricing</a>
    <div class="ac-dd">
      <button class="ac-dd-btn" aria-expanded="false" aria-haspopup="true">More
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="ac-dd-menu">
        <a href="index.html">AutomationCost home</a>
        <a href="tools.html">Tools</a>
        <a href="app-finder.html">App finder</a>
        <a href="changelog.html">Changelog</a>
        <a href="price-history.html">Price history</a>
        <div class="ac-dd-sep">Pricing guides</div>
        <a href="n8n-pricing.html"><img src="https://www.google.com/s2/favicons?domain=n8n.io&sz=32" alt="">n8n Pricing</a>
        <a href="make-pricing.html"><img src="https://www.google.com/s2/favicons?domain=make.com&sz=32" alt="">Make Pricing</a>
        <a href="zapier-pricing.html"><img src="https://www.google.com/s2/favicons?domain=zapier.com&sz=32" alt="">Zapier Pricing</a>
        <a href="pipedream-pricing.html"><img src="https://www.google.com/s2/favicons?domain=pipedream.com&sz=32" alt="">Pipedream Pricing</a>
        <a href="activepieces-pricing.html"><img src="https://www.google.com/s2/favicons?domain=activepieces.com&sz=32" alt="">Activepieces Pricing</a>
        <a href="automatisch-pricing.html"><img src="https://www.google.com/s2/favicons?domain=automatisch.io&sz=32" alt="">Automatisch Pricing</a>
        <a href="node-red-pricing.html"><img src="https://www.google.com/s2/favicons?domain=nodered.org&sz=32" alt="">Node-RED Pricing</a>
        <div class="ac-dd-sep">Other wizards</div>
        <a href="/llm/">LLMCost <span class="ac-dd-tag">Live</span></a>
        <span class="ac-dd-soon">EmailCost <span class="ac-dd-tag soon">Soon</span></span>
        <span class="ac-dd-soon">CRMCost <span class="ac-dd-tag soon">Soon</span></span>
      </div>
    </div>
    <a href="calculator.html" class="ac-cta">Calculator
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8"><polyline points="9 18 15 12 9 6"/></svg>
    </a>
  </div>
</nav>

<div class="wrap">

  <!-- 1 ── Hero verdict -->
  <div class="hero" data-screen-label="VS hero">
    <div class="hero-badge">prices verified {month_year.lower()} · 3 workflows · monthly billing</div>
    <h1>{a_name} vs {b_name} — <em>pricing &amp; features compared</em></h1>
    <div class="vs-strip">
      {strip}
    </div>
    <div class="verdict">
      {pair["verdict"]}
    </div>
  </div>

  <!-- 2 ── Price by volume -->
  <div class="section" data-screen-label="Price by volume">
    <div class="section-label">Price by volume</div>
    <h2>What you'd pay per month</h2>
    <p class="section-sub">Cheapest qualifying plan for each tool, including overage, at four typical volumes.</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>runs / month</th><th>{a_name}</th><th>{b_name}</th></tr>
        </thead>
        <tbody>
{chr(10).join(rows)}
        </tbody>
      </table>
    </div>
    <p class="tbl-note">{tbl_note}</p>
  </div>

  <!-- 3 ── Calculator CTA -->
  <div class="calc-cta" data-screen-label="Calculator CTA">
    <div class="calc-cta-text">
      <h2>Get the number for <em style="font-style:normal; color:var(--accent-br);">your</em> exact volume.</h2>
      <p>30 seconds, no signup — your runs, your workflows, all 7 tools ranked.</p>
    </div>
    <a href="calculator.html" class="btn-primary-lg">Open the calculator →</a>
  </div>

  <!-- 4 ── Feature diff -->
  <div class="section" data-screen-label="Feature differences">
    <div class="section-label">Where they differ</div>
    <h2>Feature differences that matter</h2>
    <p class="section-sub">Only the rows where {a_name} and {b_name} actually differ — identical capabilities are left out.</p>
    <div class="table-wrap">
      <table class="diff-table">
        <thead><tr><th>Feature</th><th>{a_name}</th><th>{b_name}</th></tr></thead>
        <tbody>
{chr(10).join(diff_rows)}
        </tbody>
      </table>
    </div>
    <p class="diff-same">{diff_same}</p>
  </div>

  <!-- 5 ── Pros / cons -->
  <div class="section" data-screen-label="Pros and cons">
    <div class="section-label">Trade-offs</div>
    <h2>Pros &amp; cons</h2>
    <div class="pc-grid" style="margin-top:18px;">
{pc_card(ta)}
{pc_card(tb)}
    </div>
  </div>

  <!-- EMAILCAP:HTML:START — price-drop alerts (vs copy variant, generováno).
       Disclosure text schválen ownerem 2026-06-11 — NEMĚNIT bez jeho OK. -->
  <!-- price-drop alerts e-mail form disabled 2026-06-16 — compliance: no e-mail collection while the project stays faceless (no MailerLite signup, no consent banner needed). Previous markup is in git history; re-enable by restoring the price-alerts section + EMAILCAP_ACTION. -->
  <!-- EMAILCAP:HTML:END -->

  <!-- 6 ── FAQ -->
  <div class="section" data-screen-label="FAQ">
    <div class="section-label">FAQ</div>
    <h2>Common questions</h2>
    <div class="faq" style="margin-top:16px;">
{faq_html}
    </div>
  </div>

  <!-- 7 ── Outbound CTAs -->
  <div class="section" data-screen-label="Outbound CTAs">
    <div class="section-label">Try them</div>
    <h2>Both have free tiers — test with your real workflow</h2>
    <div class="out-grid" style="margin-top:18px;">
{out_card(out_cards[0])}
{out_card(out_cards[1])}
    </div>
    <p class="tbl-note">An objective cost comparison from each vendor's public pricing pages ({month_year}) — not a recommendation; rankings reflect price only, so verify current pricing before deciding. We run an affiliate link for Make (the only one of these tools with a public referral program); the others don't offer one, so those are plain links — affiliate status never affects the comparison. See our <a href="affiliate.html">affiliate disclosure</a>.</p>
  </div>

  <!-- 8 ── Cross-links -->
  <div class="section" data-screen-label="Related pages">
    <div class="section-label">Keep digging</div>
    <div class="xlinks">
      {chr(10) + "      ".join(xlinks)}
    </div>
  </div>

</div>

<!-- 9 ── Footer -->
<footer>
  AutomationCost · part of WizardCost · Prices verified {month_year} · <a href="methodology.html">Methodology</a> · <a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> · <a href="affiliate.html">Affiliate Disclosure</a>
</footer>

<script>
function toggleFaq(el) {{ el.parentElement.classList.toggle("open"); }}

/* ── EMAILCAP:JS:START — wire every .price-alerts form on the page ── */
(function () {{
  var OK_MSG  = 'Check your inbox to confirm your subscription.';
  var ERR_MSG = 'Something went wrong — please try again.';
  var OK_ICON  = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
  var ERR_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
  function show(msgEl, ok, text) {{
    msgEl.className = 'pa-msg show ' + (ok ? 'ok' : 'err');
    msgEl.innerHTML = (ok ? OK_ICON : ERR_ICON) + '<span>' + text + '</span>';
  }}
  document.querySelectorAll('.price-alerts form.pa-form').forEach(function (form) {{
    form.addEventListener('submit', function (e) {{
      e.preventDefault();
      var card  = form.closest('.price-alerts');
      var input = form.querySelector('.pa-input');
      var btn   = form.querySelector('.pa-btn');
      var msgEl = card.querySelector('.pa-msg');
      if (!input.value || input.validity.typeMismatch || input.value.indexOf('@') < 1) {{
        show(msgEl, false, 'Please enter a valid email address.');
        input.focus();
        return;
      }}
      btn.disabled = true;
      btn.textContent = 'Subscribing…';
      fetch(form.action, {{ method: 'POST', body: new FormData(form) }})
        .then(function (r) {{ if (!r.ok) throw new Error(r.status); }})
        .then(function () {{ card.classList.add('subscribed'); show(msgEl, true, OK_MSG); }})
        .catch(function () {{
          btn.disabled = false;
          btn.textContent = 'Get price alerts';
          show(msgEl, false, ERR_MSG);
        }});
    }});
  }});
}})();
/* ── EMAILCAP:JS:END ── */
</script>

<script src="app.js"></script>
</body>
</html>
"""


def _vs_strip_injected(text: str) -> str:
    """Odstraní GA4/ANALYTICS bloky (vkládané až po generování) pro porovnání."""
    import re as _re
    for s, e in ((GA_START, GA_END), (AN_START, AN_END)):
        text = _re.sub(_re.escape(s) + r".*?" + _re.escape(e) + r"\n?\s*", "", text, flags=_re.S)
    return text


def build_vs_pages(tools: list[dict], site: dict, tools_meta: dict, *, check: bool) -> list[str]:
    """Vygeneruje <a>-vs-<b>.html pro každý pár v pairs.json. V check módu vrací
    seznam zastaralých souborů (porovnává bez GA4/analytics bloků)."""
    if not PAIRS.exists():
        return []
    pairs_data = json.loads(PAIRS.read_text(encoding="utf-8"))
    if not pairs_data.get("pairs"):
        return []
    engine = _root_engine()
    by_slug = {t["slug"]: t for t in tools}
    out = []
    for pair in pairs_data["pairs"]:
        slug = f'{pair["a"]}-vs-{pair["b"]}'
        target = ROOT / f"{slug}.html"
        rendered = render_vs_page(pair, by_slug, pairs_data, site, tools_meta, engine)
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        dirty = existing is None or _vs_strip_injected(existing) != rendered
        if check:
            if dirty:
                out.append(target.name)
        elif dirty:
            target.write_text(rendered, encoding="utf-8")
            out.append(target.name)
    return out


# CSS šablona vs-stránek — port z automation/_vs-example.html (design 2026-06-11).
_VS_CSS = """    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0a0e17; --surface: #111827; --surface2: #1a2236;
      --border: #1f2d45; --text: #e8edf5; --muted: #6b7a99;
      --accent: #10b981; --accent-br: #16d18c; --accent-dim: rgba(16,185,129,0.09); --ink: #04130d; --link: #6f9bff; --border2: #27375a; --text2: #a8b4cc;
      --green: #10b981; --yellow: #f59e0b; --red: #ef4444; --radius: 14px; --radius-sm: 9px;
      --font: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; --display: 'Hanken Grotesk', 'Plus Jakarta Sans', sans-serif; --mono: 'JetBrains Mono', ui-monospace, monospace;
    }
    body {
      background: var(--bg);
      background-image: radial-gradient(ellipse 70% 50% at 50% -8%, rgba(16,185,129,0.20), transparent 60%), radial-gradient(ellipse 60% 50% at 100% 0%, rgba(16,185,129,0.08), transparent 50%);
      background-repeat: no-repeat; background-attachment: fixed;
      color: var(--text); font-family: var(--font); font-size: 15.5px; line-height: 1.7; letter-spacing: 0.01em; min-height: 100vh; -webkit-font-smoothing: antialiased;
      padding-top: 100px;
    }
    a { color: var(--link); text-decoration: none; }
    a:hover { color: #9fbcff; }
    h1, h2, h3 { font-family: var(--display); letter-spacing: -0.02em; text-wrap: balance; }
    header { position: fixed; top: 0; left: 0; right: 0; z-index: 100; background: rgba(10,14,23,0.86); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border-bottom: 1px solid var(--border); }
    .nav-top { padding: 0 32px; height: 56px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }
    .nav-bottom { border-bottom: 2px solid var(--border); padding: 0 32px; display: flex; gap: 0; overflow-x: auto; scrollbar-width: none; }
    .nav-bottom::-webkit-scrollbar { display: none; }
    .nav-bottom a { padding: 12px 20px; font-size: 14px; color: var(--muted); text-decoration: none; white-space: nowrap; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: color 0.15s, border-color 0.15s; flex-shrink: 0; }
    .nav-bottom a:hover { color: var(--text); }
    .nav-bottom a.active { color: var(--text); font-weight: 700; border-bottom-color: var(--accent); }
    .logo { display: flex; align-items: center; gap: 0; font-family: var(--display); font-weight: 800; font-size: 1.08rem; color: var(--text); letter-spacing: -0.01em; text-decoration: none; }
    .logo span { color: var(--accent); }
    .logo .io { color: var(--muted); font-weight: 600; }
    .logo-icon { width: 28px; height: 28px; flex-shrink: 0; margin-right: 9px; }
    .nav-badge { font-family: var(--mono); font-size: 11px; background: var(--surface2); border: 1px solid var(--border2); border-radius: 20px; padding: 4px 12px; color: var(--muted); display: flex; align-items: center; gap: 7px; letter-spacing: 0.01em; }
    .nav-badge::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 7px var(--accent); }
    .wrap { max-width: 880px; margin: 0 auto; padding: 0 32px; }
    .hero { padding: 60px 0 8px; }
    .hero-badge { display: inline-flex; align-items: center; gap: 8px; background: var(--surface2); border: 1px solid var(--border2); border-radius: 100px; font-family: var(--mono); font-size: 11.5px; color: var(--text2); padding: 6px 15px; margin-bottom: 22px; letter-spacing: 0.02em; }
    .hero h1 { font-size: clamp(2rem, 4vw, 3rem); font-weight: 800; line-height: 1.1; letter-spacing: -0.02em; margin-bottom: 22px; }
    .hero h1 em { font-style: normal; color: var(--accent); }
    .vs-strip { display: inline-flex; align-items: center; gap: 13px; font-family: var(--mono); font-size: 15px; font-weight: 700; background: var(--surface); border: 1px solid var(--border); border-radius: 99px; padding: 10px 22px; margin-bottom: 22px; }
    .vs-strip img { width: 22px; height: 22px; border-radius: 5px; background: #fff; padding: 2px; object-fit: contain; }
    .vs-strip .lt { color: var(--accent-br); font-size: 17px; }
    .vs-strip .who { display: inline-flex; align-items: center; gap: 8px; }
    .verdict { background: linear-gradient(160deg, rgba(16,185,129,0.10), var(--surface) 65%); border: 1px solid rgba(16,185,129,0.35); border-radius: var(--radius); padding: 22px 26px; font-size: 1.06rem; line-height: 1.65; color: var(--text2); margin-bottom: 14px; }
    .verdict b { color: var(--text); }
    .verdict .win { color: var(--accent-br); font-weight: 700; }
    .section { margin: 44px 0 0; }
    .section-label { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.14em; margin-bottom: 8px; }
    .section h2 { font-size: 1.5rem; font-weight: 800; margin-bottom: 8px; }
    .section-sub { color: var(--text2); font-size: 14.5px; margin-bottom: 20px; max-width: 620px; }
    .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-sm); }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th { background: var(--surface2); color: var(--muted); font-family: var(--mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; padding: 12px 16px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
    td { padding: 13px 16px; border-bottom: 1px solid var(--border); background: var(--surface); vertical-align: middle; }
    tr:last-child td { border-bottom: none; }
    td.vol { font-family: var(--mono); font-weight: 700; white-space: nowrap; }
    .price { font-family: var(--mono); font-weight: 700; white-space: nowrap; }
    .price small { font-weight: 500; color: var(--muted); font-size: 11.5px; display: block; }
    td.cheap { background: rgba(16,185,129,0.07); }
    td.cheap .price { color: var(--accent-br); }
    td.cheap .price .ok { font-size: 11px; }
    .tbl-note { font-family: var(--mono); font-size: 11.5px; color: var(--muted); margin-top: 10px; line-height: 1.7; }
    .calc-cta { background: linear-gradient(160deg, rgba(16,185,129,0.10), var(--surface) 65%); border: 1px solid rgba(16,185,129,0.35); border-radius: var(--radius); padding: 26px 30px; margin-top: 44px; display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
    .calc-cta-text { flex: 1 1 320px; }
    .calc-cta h2 { font-size: 1.3rem; font-weight: 800; margin-bottom: 5px; }
    .calc-cta p { color: var(--text2); font-size: 14px; line-height: 1.6; }
    .btn-primary-lg { background: var(--accent); color: var(--ink); border-radius: var(--radius-sm); padding: 14px 26px; font-family: var(--font); font-size: 15px; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; gap: 9px; box-shadow: 0 0 0 1px rgba(16,185,129,0.4), 0 10px 30px rgba(16,185,129,0.28); transition: transform 0.15s; white-space: nowrap; }
    .btn-primary-lg:hover { transform: translateY(-1px); color: var(--ink); }
    .diff-table td:first-child { font-weight: 700; font-size: 13.5px; white-space: nowrap; }
    .diff-table td { font-size: 13.5px; }
    .diff-win { color: var(--accent-br); font-weight: 700; }
    .check { color: var(--green); font-weight: 700; }
    .cross { color: var(--red); }
    .diff-same { font-family: var(--mono); font-size: 12px; color: var(--muted); margin-top: 10px; }
    .pc-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
    .pc-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px 24px; }
    .pc-head { display: flex; align-items: center; gap: 10px; font-family: var(--display); font-weight: 800; font-size: 1.05rem; margin-bottom: 14px; }
    .pc-head img { width: 24px; height: 24px; border-radius: 5px; background: #fff; padding: 2px; object-fit: contain; }
    .pc-card ul { list-style: none; }
    .pc-card li { font-size: 13.5px; color: var(--text2); padding: 5px 0 5px 24px; position: relative; line-height: 1.55; }
    .pc-card li.pro::before { content: "+"; position: absolute; left: 4px; color: var(--green); font-weight: 800; }
    .pc-card li.con::before { content: "−"; position: absolute; left: 4px; color: var(--red); font-weight: 800; }
    .pc-divider { border-top: 1px solid var(--border); margin: 10px 0; }
    .faq { margin-top: 8px; }
    .faq-item { border-bottom: 1px solid var(--border); padding: 18px 0; }
    .faq-item:first-child { border-top: 1px solid var(--border); }
    .faq-q { font-weight: 700; font-size: 15px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; gap: 16px; width: 100%; background: none; border: none; color: var(--text); font-family: var(--font); text-align: left; padding: 0; }
    .faq-q::after { content: "+"; color: var(--muted); font-size: 1.2rem; flex-shrink: 0; }
    .faq-item.open .faq-q::after { content: "−"; }
    .faq-a { color: var(--muted); font-size: 14px; line-height: 1.7; display: none; margin-top: 10px; }
    .faq-item.open .faq-a { display: block; }
    .out-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
    .out-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; display: flex; flex-direction: column; gap: 10px; }
    .out-card.winner { border-color: rgba(16,185,129,0.4); }
    .out-head { display: flex; align-items: center; gap: 10px; font-family: var(--display); font-weight: 800; font-size: 1.05rem; }
    .out-head img { width: 24px; height: 24px; border-radius: 5px; background: #fff; padding: 2px; object-fit: contain; }
    .out-card p { font-size: 13.5px; color: var(--text2); line-height: 1.6; }
    .out-btn { align-self: flex-start; border-radius: var(--radius-sm); padding: 12px 22px; font-size: 14px; font-weight: 700; text-decoration: none; display: inline-block; margin-top: 4px; }
    .out-btn.aff { background: var(--accent); color: var(--ink); box-shadow: 0 0 0 1px rgba(16,185,129,0.4), 0 8px 24px rgba(16,185,129,0.25); }
    .out-btn.aff:hover { color: var(--ink); transform: translateY(-1px); }
    .out-btn.plain { background: var(--surface2); color: var(--text2); border: 1px solid var(--border2); }
    .out-btn.plain:hover { border-color: var(--accent); color: var(--text); }
    .aff-note { font-family: var(--mono); font-size: 11px; color: var(--muted); }
    .xlinks { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
    .xlink { font-family: var(--mono); font-size: 12.5px; background: var(--surface); border: 1px solid var(--border); border-radius: 99px; padding: 8px 16px; color: var(--text2); transition: border-color 0.15s, color 0.15s; }
    .xlink:hover { border-color: var(--accent); color: var(--text); }
    footer { border-top: 1px solid var(--border); padding: 40px 24px; text-align: center; font-family: var(--display); font-size: 12.5px; color: var(--muted); line-height: 1.85; margin-top: 64px; }
    footer a { color: var(--muted); }
    @media (max-width: 760px) {
      .wrap { padding-left: 18px; padding-right: 18px; }
      .nav-top { padding-left: 18px; padding-right: 18px; }
      .nav-bottom { padding-left: 8px; padding-right: 8px; }
      .nav-bottom a { padding: 13px 14px; }
    }
    @media (max-width: 620px) {
      .nav-badge { display: none; }
      th, td { padding: 10px 9px; }
      td.vol { font-size: 12px; }
      .price { font-size: 13px; white-space: normal; }
      .price small { white-space: normal; font-size: 10.5px; line-height: 1.35; }
      .vs-strip { font-size: 13px; gap: 9px; padding: 9px 16px; flex-wrap: wrap; }
    }
    @media (max-width: 520px) {
      .calc-cta, .out-card { flex-direction: column; align-items: stretch; }
      .btn-primary-lg, .out-btn { text-align: center; align-self: stretch; }
    }
    /* ── EMAILCAP:CSS:START ── price-drop alerts capture block (reusable) ── */
    .price-alerts { background: var(--surface); border: 1px solid var(--border2); border-radius: var(--radius); padding: 24px 28px; margin: 44px 0 0; }
    .pa-label { font-family: var(--mono); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.14em; color: var(--accent); margin-bottom: 8px; }
    .pa-title { font-family: var(--display); font-size: 17px; font-weight: 800; letter-spacing: -0.01em; }
    .pa-sub { font-size: 13.5px; color: var(--text2); margin-top: 5px; line-height: 1.55; max-width: 560px; }
    .pa-form { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
    .pa-input { flex: 1 1 240px; min-width: 0; background: var(--bg); border: 1px solid var(--border2); border-radius: var(--radius-sm); padding: 12px 16px; font-family: var(--font); font-size: 14.5px; color: var(--text); transition: border-color 0.15s, box-shadow 0.15s; }
    .pa-input::placeholder { color: var(--muted); }
    .pa-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(16,185,129,0.20); }
    .pa-btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; background: var(--accent); color: var(--ink); border: 0; cursor: pointer; font-family: var(--font); font-weight: 700; font-size: 14px; padding: 12px 22px; border-radius: var(--radius-sm); white-space: nowrap; transition: background 0.15s; }
    .pa-btn:hover { background: var(--accent-br); }
    .pa-btn:disabled { opacity: 0.6; cursor: default; }
    .pa-note { font-size: 12.5px; color: var(--muted); margin-top: 12px; line-height: 1.55; }
    .pa-note a { color: var(--muted); text-decoration: underline; text-underline-offset: 2px; }
    .pa-note a:hover { color: var(--text2); }
    .pa-msg { display: none; margin-top: 14px; font-size: 14px; line-height: 1.55; }
    .pa-msg.show { display: flex; align-items: flex-start; gap: 9px; }
    .pa-msg svg { flex-shrink: 0; margin-top: 3px; }
    .pa-msg.ok { color: var(--green); }
    .pa-msg.err { color: var(--red); }
    .price-alerts.subscribed .pa-form, .price-alerts.subscribed .pa-note { display: none; }
    @media (max-width: 520px) {
      .price-alerts { padding: 20px 18px; }
      .pa-form { flex-direction: column; }
      .pa-btn { width: 100%; min-height: 44px; }
    }
    /* ── EMAILCAP:CSS:END ── */"""


# MailerLite form endpoint — stejná hodnota je hardcoded v calculator.html
# a changelog.html (grep https://assets.mailerlite.com/jsonp/2426816/forms/190009354045359550/subscribe → nahradit na
# 3 místech najednou, pak rebuild).
EMAILCAP_ACTION = "https://assets.mailerlite.com/jsonp/2426816/forms/190009354045359550/subscribe"


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


def _static_geo_ld(text: str, site: dict, tools_meta: dict) -> str:
    """Z <head> statické stránky vytáhne canonical/title/desc a vrátí `<script>` blok
    s Org+WebSite+WebPage @graph (živý dateModified z last_reviewed). Vrací "" když chybí
    canonical. Reuse _page_graph_ld z build_pricing → konzistentní s generovanými stránkami."""
    import re
    mc = re.search(r'<link rel="canonical" href="([^"]+)"', text)
    if not mc:
        return ""
    mt = re.search(r"<title[^>]*>(.*?)</title>", text, re.S)
    md = re.search(r'<meta name="description"[^>]*\scontent="([^"]*)"', text)
    name = (mt.group(1).strip() if mt else "").split(" | ")[0].replace("&amp;", "&")
    desc = (md.group(1) if md else "").replace("&amp;", "&")
    graph = _page_graph_ld(site.get("domain", "wizardcost.com"), mc.group(1), name, desc,
                           _iso_date(tools_meta))
    fname = mc.group(1).rsplit("/", 1)[-1]
    leaf = {"compare.html": "Compare tools", "changelog.html": "Price changelog"}.get(fname, name)
    bc = _seo_breadcrumb_ld(site, mc.group(1).rsplit("/", 1)[0], leaf, mc.group(1))
    return (f'  <script type="application/ld+json">\n{graph}\n  </script>\n'
            f'  <script type="application/ld+json">\n{bc}\n  </script>')


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


# ---------------------------------------------------------------------------
# Price-history stránka: data/price-history.json (kurátorováno z Wayback verdiktů,
# calc-test/wayback/) → automation/price-history.html. CELÉ generované, server-side
# (crawlovatelné + AI-citovatelné — proto NE JS render). CONFIRMED-only; gapy přiznané.
# ---------------------------------------------------------------------------

_PH_CSS = """
    .ph-lead { color: var(--text2); font-size: 1.06rem; max-width: 700px; margin: 14px auto 4px; }
    .ph-tldr { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 22px; margin: 22px 0; }
    .ph-tldr ul { margin: 8px 0 0; padding-left: 20px; }
    .ph-tldr li { margin: 5px 0; color: var(--text2); }
    .ph-tool { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px; margin-bottom: 18px; }
    .ph-tool-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
    .ph-tool-head img { width: 30px; height: 30px; border-radius: 7px; }
    .ph-tool-head h3 { font-size: 1.22rem; }
    .ph-headline { color: var(--accent-br); font-size: 0.85rem; font-weight: 600; display: block; }
    .ph-meta { margin-left: auto; font-family: var(--mono); font-size: 11px; color: var(--muted); }
    .ph-stable { border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 12px 0; margin-bottom: 16px; }
    .ph-row { display: flex; align-items: baseline; gap: 10px; padding: 3px 0; flex-wrap: wrap; }
    .ph-plan { font-weight: 700; min-width: 100px; }
    .ph-price { font-family: var(--mono); color: var(--text); }
    .ph-detail { color: var(--muted); font-size: 0.85rem; }
    .ph-event { border-left: 2px solid var(--border2); padding: 4px 0 14px 16px; margin-left: 4px; position: relative; }
    .ph-event::before { content: ''; position: absolute; left: -5px; top: 8px; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
    .ph-event-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .ph-date { font-family: var(--mono); font-size: 12px; color: var(--text2); }
    .ph-kind { font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 20px; }
    .ph-k-change { background: rgba(245,158,11,0.16); color: #f6ad3c; }
    .ph-k-product { background: rgba(111,155,255,0.16); color: #8fb0ff; }
    .ph-k-pack { background: rgba(168,180,204,0.12); color: #aeb9d0; }
    .ph-k-artifact { background: rgba(107,122,153,0.14); color: #93a0bd; }
    .ph-event-title { font-weight: 600; margin-top: 4px; }
    .ph-event-detail { color: var(--text2); font-size: 0.9rem; margin-top: 3px; }
    .ph-evidence { margin-top: 6px; display: flex; gap: 14px; flex-wrap: wrap; }
    .ph-evidence a { font-size: 12px; font-family: var(--mono); }
    .ph-none { color: var(--muted); font-style: italic; }
    .ph-gap { background: rgba(245,158,11,0.07); border: 1px solid rgba(245,158,11,0.22); border-radius: 9px; padding: 9px 13px; margin-top: 12px; font-size: 0.86rem; color: var(--text2); }
    .ph-fixed-row { display: flex; align-items: baseline; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
    .ph-fixed-row img { width: 20px; height: 20px; }
"""

_PH_KIND = {
    "change": ("Real change", "ph-k-change"),
    "product": ("New product", "ph-k-product"),
    "packaging": ("Repackaging", "ph-k-pack"),
    "artifact": ("Display only", "ph-k-artifact"),
}


def _ph_kind_badge(kind: str) -> str:
    label, cls = _PH_KIND.get(kind, (kind, "ph-k-artifact"))
    return f'<span class="ph-kind {cls}">{label}</span>'


def _ph_tool_card(t: dict) -> str:
    stable = "\n".join(
        f'<div class="ph-row"><span class="ph-plan">{_html_escape(p["plan"])}</span>'
        f'<span class="ph-price">{_html_escape(p["price"])}</span>'
        f'<span class="ph-detail">{_html_escape(p["detail"])} · stable since {_html_escape(p["since"])}</span></div>'
        for p in t.get("stable", []))
    events = []
    for e in t.get("events", []):
        links = " ".join(
            f'<a href="{u}" target="_blank" rel="noopener nofollow">archive {i + 1} ↗</a>'
            for i, u in enumerate(e.get("evidence", [])))
        links = f'<div class="ph-evidence">{links}</div>' if links else ""
        events.append(
            '<div class="ph-event">'
            f'<div class="ph-event-head"><span class="ph-date">{_html_escape(e["date"])}</span>{_ph_kind_badge(e["kind"])}</div>'
            f'<div class="ph-event-title">{_html_escape(e["title"])}</div>'
            f'<p class="ph-event-detail">{_html_escape(e["detail"])}</p>{links}</div>')
    events_html = "\n".join(events) if events else '<p class="ph-none">No price events recorded in this window.</p>'
    gaps = "\n".join(
        f'<div class="ph-gap">⚠ Coverage gap {_html_escape(g["from"])} → {_html_escape(g["to"])}: {_html_escape(g["reason"])}</div>'
        for g in t.get("gaps", []))
    oq = (f'<div class="ph-gap">❓ Open question — {_html_escape(t["open_question"])}</div>'
          if t.get("open_question") else "")
    return (
        f'<div class="ph-tool" id="ph-{t["slug"]}">\n'
        f'      <div class="ph-tool-head"><img src="{_logo(t["slug"])}" alt="{t["name"]} logo" loading="lazy">'
        f'<div><h3>{t["name"]}</h3><span class="ph-headline">{_html_escape(t["headline"])}</span></div>'
        f'<span class="ph-meta">{t["snapshots"]} archived snapshots · {_html_escape(t["range_from"])} → {_html_escape(t["range_to"])}</span></div>\n'
        f'      <div class="ph-stable">{stable}</div>\n'
        f'      <div class="ph-events">{events_html}</div>\n'
        f'      {gaps}{oq}\n    </div>')


def render_price_history(data: dict, site: dict) -> str:
    meta = data.get("_meta", {})
    prefix = _site_prefix(site.get("domain", "wizardcost.com"), site.get("base_path", ""))
    canonical = f"{prefix}/price-history.html"
    updated = meta.get("updated", "2026-06-20")
    window = f'{meta.get("window_from", "2024-06")} – {meta.get("window_to", "2026-06")}'

    tool_cards = "\n    ".join(_ph_tool_card(t) for t in data.get("tools", []))
    fixed_html = "\n".join(
        f'<div class="ph-fixed-row"><img src="{_logo(f["slug"])}" alt="" loading="lazy">'
        f'<span class="ph-plan">{_html_escape(f["name"])}</span>'
        f'<span class="ph-detail">{_html_escape(f["note"])}</span></div>'
        for f in data.get("fixed", []))

    title = "Automation Tool Pricing History 2024–2026: What Actually Changed | WizardCost"
    desc = ("Two years of Make, Zapier, n8n and Pipedream pricing from the Web Archive. "
            "Core prices barely moved — every confirmed change linked to dated archive evidence.")

    article_ld = json.dumps({
        "@context": "https://schema.org", "@type": "Article",
        "headline": "Automation tool pricing history (2024–2026)",
        "description": desc,
        "datePublished": "2026-06-20", "dateModified": updated,
        "author": {"@type": "Organization", "name": "AutomationCost.io"},
        "publisher": {"@type": "Organization", "name": "WizardCost"},
        "mainEntityOfPage": canonical,
    }, ensure_ascii=False, indent=2)
    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f'https://{site.get("domain", "wizardcost.com")}/'},
            {"@type": "ListItem", "position": 2, "name": "Automation tools", "item": f"{prefix}/tools.html"},
            {"@type": "ListItem", "position": 3, "name": "Pricing history", "item": canonical},
        ],
    }, ensure_ascii=False, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build.py z data/price-history.json — needituj ručně -->
  <title>{_clamp_title(title)}</title>
  <meta name="description" content="{_html_escape(_clamp_desc(desc))}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="AutomationCost.io">
  <meta property="og:title" content="Automation Tool Pricing History 2024–2026">
  <meta property="og:description" content="{_html_escape(desc)}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{prefix}/og-image.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{prefix}/og-image.png">
  <script type="application/ld+json">
{article_ld}
  </script>
  <script type="application/ld+json">
{breadcrumb_ld}
  </script>
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
{_VS_CSS}
{_PH_CSS}
  </style>
  <link rel="stylesheet" href="app.css">
</head>
<body class="ac anim">

<div id="ac-progress"></div>

<nav class="ac-nav">
  <a href="/automation/" class="logo">
    <svg class="logo-icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs><linearGradient id="acmk" x1="14" y1="10" x2="30" y2="38" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#2fe39c"></stop><stop offset="1" stop-color="#0ea66e"></stop></linearGradient></defs>
      <path d="M28.5 10.5 L13.5 24 L28.5 37.5" stroke="url(#acmk)" stroke-width="6.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M 36.5 17.8 Q 37.864 22.636 42.7 24 Q 37.864 25.364 36.5 30.2 Q 35.136 25.364 30.3 24 Q 35.136 22.636 36.5 17.8 Z" fill="#eafff5"></path>
    </svg>
    Automation<span>Cost</span><span class="io" style="font-size:0.72em; margin-left:7px;">by WizardCost</span>
  </a>
  <div class="ac-links">
    <a href="compare.html" class="ac-hide-sm">Compare</a>
    <a href="limits.html" class="ac-hide-sm">Pricing</a>
    <div class="ac-dd">
      <button class="ac-dd-btn" aria-expanded="false" aria-haspopup="true">More
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="ac-dd-menu">
        <a href="index.html">AutomationCost home</a>
        <a href="tools.html">Tools</a>
        <a href="app-finder.html">App finder</a>
        <a href="changelog.html">Changelog</a>
        <a href="price-history.html">Price history</a>
        <div class="ac-dd-sep">Pricing guides</div>
        <a href="n8n-pricing.html"><img src="https://www.google.com/s2/favicons?domain=n8n.io&sz=32" alt="">n8n Pricing</a>
        <a href="make-pricing.html"><img src="https://www.google.com/s2/favicons?domain=make.com&sz=32" alt="">Make Pricing</a>
        <a href="zapier-pricing.html"><img src="https://www.google.com/s2/favicons?domain=zapier.com&sz=32" alt="">Zapier Pricing</a>
        <a href="pipedream-pricing.html"><img src="https://www.google.com/s2/favicons?domain=pipedream.com&sz=32" alt="">Pipedream Pricing</a>
        <div class="ac-dd-sep">Other wizards</div>
        <a href="/llm/">LLMCost <span class="ac-dd-tag">Live</span></a>
      </div>
    </div>
    <a href="calculator.html" class="ac-cta">Calculator
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8"><polyline points="9 18 15 12 9 6"/></svg>
    </a>
  </div>
</nav>

<div class="wrap">

  <div class="hero" data-screen-label="Price history hero">
    <div class="hero-badge">2-year price history · Web Archive evidence · updated {updated}</div>
    <h1>Automation tool pricing — <em>what actually changed, {window}</em></h1>
    <p class="ph-lead">{_html_escape(meta.get("thesis", ""))}</p>
  </div>

  <div class="section" data-screen-label="Summary">
    <div class="ph-tldr">
      <strong>The short version</strong>
      <ul>
        <li><b>Zapier</b> — core plans ($0 / $19.99 / $69) unchanged for 2+ years.</li>
        <li><b>Make</b> — annual prices ($9 / $16 / $29) flat since at least Feb 2025.</li>
        <li><b>n8n</b> — one real overhaul (Aug 2025): workflow limits removed, Business tier added.</li>
        <li><b>Pipedream</b> — Basic / Advanced ($29 / $49) flat; free tier cut 300 → 100 credits.</li>
      </ul>
    </div>
  </div>

  <div class="section" data-screen-label="Per-tool timeline">
    <div class="section-label">The receipts</div>
    <h2>Two years of pricing, tool by tool</h2>
    <p class="section-sub">Each entry links to a dated Web Archive snapshot. Product launches and display changes are labelled as such — only genuine price moves are marked <span class="ph-kind ph-k-change">Real change</span>.</p>
    {tool_cards}
  </div>

  <div class="section" data-screen-label="Fixed / open-source">
    <div class="section-label">Free &amp; open-source</div>
    <h2>The self-hosted tools</h2>
    <p class="section-sub">These have no list-price history to chart — they are free or open-source; the only cost is the server you run them on.</p>
    {fixed_html}
  </div>

  <div class="section" data-screen-label="Methodology">
    <div class="section-label">How we know</div>
    <h2>Method &amp; honest caveats</h2>
    <p class="section-sub">{_html_escape(meta.get("method", ""))}</p>
    <p class="tbl-note">Some windows are coverage gaps (marked ⚠) where a vendor rendered prices client-side, so the archive holds no figures — we don't guess. From here on, our <a href="changelog.html">daily price audit</a> records changes as they happen.</p>
  </div>

  <div class="calc-cta" data-screen-label="Calculator CTA">
    <div class="calc-cta-text">
      <h2>Prices are stable — so pick on <em style="font-style:normal; color:var(--accent-br);">your</em> volume.</h2>
      <p>30 seconds, no signup — your runs, all 7 tools ranked by real cost.</p>
    </div>
    <a href="calculator.html" class="btn-primary-lg">Open the calculator →</a>
  </div>

  <div class="section" data-screen-label="Related pages">
    <div class="section-label">Keep digging</div>
    <div class="xlinks">
      <a class="xlink" href="changelog.html">Live price changelog</a>
      <a class="xlink" href="compare.html">Compare all 7 tools</a>
      <a class="xlink" href="calculator.html">Pricing calculator</a>
    </div>
  </div>

</div>

<footer>
  AutomationCost · part of WizardCost · Pricing history from the Web Archive · updated {updated} · <a href="methodology.html">Methodology</a> · <a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> · <a href="affiliate.html">Affiliate Disclosure</a>
</footer>

<script src="app.js"></script>
</body>
</html>
"""


def build_price_history(site: dict, *, check: bool) -> list[str]:
    """Vygeneruje automation/price-history.html z data/price-history.json.
    V check módu vrací seznam zastaralých souborů (porovnává bez GA4/analytics bloků)."""
    if not PRICE_HISTORY.exists():
        return []
    data = json.loads(PRICE_HISTORY.read_text(encoding="utf-8"))
    if not data.get("tools"):
        return []
    target = ROOT / "price-history.html"
    rendered = render_price_history(data, site)
    existing = target.read_text(encoding="utf-8") if target.exists() else None
    dirty = existing is None or _vs_strip_injected(existing) != rendered
    if not dirty:
        return []
    if not check:
        target.write_text(rendered, encoding="utf-8")
    return [target.name]


def build_sitemap(domain: str, base_path: str, pages: list[Path]) -> bool:
    prefix = _site_prefix(domain, base_path)
    urls = []
    for p in pages:
        loc = f"{prefix}/" if p.name == "index.html" else f"{prefix}/{p.name}"
        lastmod = __import__("datetime").date.fromtimestamp(p.stat().st_mtime).isoformat()
        urls.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>")
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


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _entry_kind(e: dict) -> str:
    """Lidský popis typu záznamu pro feed descriptions (žádná vata opakující titulek)."""
    if e["dir"] == "up":
        return "Price increase"
    if e["dir"] == "down":
        return "Price decrease"
    item = e["item"].lower()
    if "integrations" in item:
        return "Catalog update"
    if "included runs" in item or "workflow limit" in item:
        return "Plan limits update"
    if "overage" in item:
        return "Overage pricing update"
    return "Pricing structure update"


def _is_alert_entry(e: dict) -> bool:
    """Email alerty slibují 'price-change alerts only' (disclosure schválená
    ownerem) → do alerts.xml patří jen ceny a limity plánů, NE počty integrací."""
    return e["item"] != "Integrations"


def _alert_meta(e: dict) -> str:
    """Meta řádek email alertů — přesný formát ze specu designu (2026-06-11):
    'Price change · verified June 11, 2026' | 'Plan limit change · verified …'."""
    import datetime as _dt
    item = e["item"].lower()
    kind = "Plan limit change" if ("included runs" in item or "workflow limit" in item) else "Price change"
    dt = _dt.datetime.strptime(e["d"], "%Y-%m-%d")
    return f"{kind} · verified {dt:%B} {dt.day}, {dt.year}"


def _feed_xml(prefix: str, self_name: str, title: str, channel_desc: str, entries: list[dict],
              alert_style: bool = False) -> str:
    import datetime as _dt
    page = f"{prefix}/changelog.html"
    items = []
    for e in entries[:50]:
        item_title = f'{e["name"]} — {e["item"]}: {e["old"]} → {e["neu"]}'
        desc = (_alert_meta(e) if alert_style
                else f'{_entry_kind(e)}, verified {e["d"]}. Full history in the WizardCost price changelog.')
        pub = _dt.datetime.strptime(e["d"], "%Y-%m-%d").strftime("%a, %d %b %Y 00:00:00 GMT")
        slug = e["item"].lower().replace(" ", "-")
        guid = f'{e["d"]}-{e["tool"]}-{slug}'
        items.append(
            "  <item>\n"
            f"    <title>{_xml_escape(item_title)}</title>\n"
            f"    <link>{page}</link>\n"
            f'    <guid isPermaLink="false">{_xml_escape(guid)}</guid>\n'
            f"    <pubDate>{pub}</pubDate>\n"
            f"    <description>{_xml_escape(desc)}</description>\n"
            "  </item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        f"  <title>{_xml_escape(title)}</title>\n"
        f"  <link>{page}</link>\n"
        f"  <description>{_xml_escape(channel_desc)}</description>\n"
        "  <language>en</language>\n"
        f'  <atom:link href="{prefix}/{self_name}" rel="self" type="application/rss+xml"/>\n'
        + ("\n".join(items) + "\n" if items else "")
        + "</channel>\n</rss>\n"
    )


def build_feed(domain: str, base_path: str, entries: list[dict]) -> list[str]:
    """Dva RSS feedy z changelog záznamů (max 50 nejnovějších):
    - feed.xml   = plný changelog (RSS čtečky, autodiscovery na changelog.html)
    - alerts.xml = JEN ceny + limity plánů → zdroj MailerLite RSS kampaně
      (email slib 'price-change alerts only' — počty integrací sem nepatří)."""
    prefix = _site_prefix(domain, base_path)
    feeds = [
        ("feed.xml", "AutomationCost — Automation Tool Price Changelog",
         "Every dated price and limit change recorded across n8n, Make, Zapier, "
         "Pipedream and more — sourced from official pricing pages.", entries),
        ("alerts.xml", "WizardCost — Price-Change Alerts",
         "Price and plan-limit changes only — the feed behind WizardCost email alerts. "
         "Catalog updates (integration counts) live in the full changelog feed.",
         [e for e in entries if _is_alert_entry(e)]),
    ]
    changed = []
    for name, title, desc, ents in feeds:
        xml = _feed_xml(prefix, name, title, desc, ents, alert_style=(name == "alerts.xml"))
        out = ROOT / name
        if not out.exists() or out.read_text(encoding="utf-8") != xml:
            out.write_text(xml, encoding="utf-8")
            changed.append(name)
    return changed


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


def render_scoring(model: dict) -> str:
    """JS const blok ze scoring-model.json (váhy recommendation enginu kalkulačky).
    JSON je nadmnožinou JS object-literálu (klíče v uvozovkách jsou validní JS),
    takže stačí json.dumps. Čísla 0..1 se serializují čistě (0.3, 1.0, …).
    SCORE_W / ROLE_WEIGHTS / TOOL_SCORES čte scoreParts()/computeMatchScore()
    v calculator.html — pořadí mezi top-level consty nehraje roli (užívají se až
    za běhu uvnitř funkcí). Fáze C: research-armáda přepíše hodnoty v JSON."""
    sw = json.dumps(model["scoreWeights"], ensure_ascii=False)
    rw = json.dumps(model["roleWeights"], ensure_ascii=False, indent=2)
    ts = json.dumps(model["toolScores"], ensure_ascii=False, indent=2)
    return (
        f"const SCORE_W = {sw};\n"
        f"const ROLE_WEIGHTS = {rw};\n"
        f"const TOOL_SCORES = {ts};"
    )


def assert_counts_parity(tools: list[dict]) -> None:
    """Tvrdá pojistka: tools.json `integrations` MUSÍ == integrations/index.json `counts`
    (jediný zdroj pravdy pro počty). Při rozjetí build i --check selže s exit≠0 a per-tool diffem."""
    idx_counts = json.loads(
        (ROOT / "data" / "integrations" / "index.json").read_text(encoding="utf-8")
    )["counts"]
    bad = [(t["slug"], t.get("integrations"), idx_counts.get(t["slug"]))
           for t in tools if t.get("integrations") != idx_counts.get(t["slug"])]
    if bad:
        raise SystemExit(
            "CHYBA: tools.json integrations != integrations/index.json counts:\n"
            + "\n".join(f"  {s}: tools.json={a} index.json={b}" for s, a, b in bad)
            + "\nSrovnej tools.json s integrations/index.json (jediný zdroj) a spusť znovu."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject data/tools.json into static pages.")
    parser.add_argument("--check", action="store_true",
                        help="Selže (exit 1), pokud by build něco změnil — bez zápisu.")
    args = parser.parse_args()

    site = load_site()

    # jobs: (path, generated, start, end, warn)
    jobs: list[tuple[Path, str, str, str, str]] = []
    clog_entries: list[dict] = []

    # TOOLS injection only applies to pages that actually carry the markers.
    # An umbrella/homepage build (no calculator.html / compare.html present)
    # simply skips it and still does sitemap / robots / analytics.
    if DATA.exists():
        data = json.loads(DATA.read_text(encoding="utf-8"))
        tools = data["tools"]
        assert_counts_parity(tools)  # tools.json ↔ integrations/index.json counts (jediný zdroj)
        apply_fx(tools)  # n8n (EUR) → USD kurzem z fx.json, než cokoli rendruje/počítá
        candidates = {
            ROOT / "calculator.html": render_calculator,
            ROOT / "compare.html": render_compare,
        }
        jobs += [(p, fn(tools), START, END, WARN) for p, fn in candidates.items() if p.exists()]

        # changelog: generovaný z git historie tools.json (entries sdílí i RSS feed)
        clog_entries, clog_genesis = changelog_entries()
        clog_page = ROOT / "changelog.html"
        if clog_page.exists() and CLOG_START in clog_page.read_text(encoding="utf-8"):
            jobs.append((clog_page, render_changelog(tools, clog_entries, clog_genesis),
                         CLOG_START, CLOG_END, CLOG_WARN))

        # GEO:LD — Org+WebSite+WebPage graf do <head> statických stránek BEZ vlastního
        # WebSite/Org schématu (changelog, compare). Hub/calculator už WebSite/WebApplication
        # mají → ty dostávají jen @id kotvy ručně (žádný duplicitní WebSite node).
        _geo_meta = data.get("_meta", {})
        for _sp in ("changelog.html", "compare.html"):
            _spp = ROOT / _sp
            if _spp.exists() and GEO_LD_START in _spp.read_text(encoding="utf-8"):
                _block = _static_geo_ld(_spp.read_text(encoding="utf-8"), site, _geo_meta)
                if _block:
                    jobs.append((_spp, _block, GEO_LD_START, GEO_LD_END, GEO_LD_WARN))

    # scoring-model injection — recommendation engine weights (calculator.html only).
    # Nezávislé na tools.json: zdroj pravdy pro váhy je data/scoring-model.json.
    if SCORING.exists():
        model = json.loads(SCORING.read_text(encoding="utf-8"))
        calc_page = ROOT / "calculator.html"
        if calc_page.exists() and SCORING_START in calc_page.read_text(encoding="utf-8"):
            jobs.append((calc_page, render_scoring(model),
                         SCORING_START, SCORING_END, SCORING_WARN))

    if args.check:
        dirty = []
        for path, generated, start, end, warn in jobs:
            text = path.read_text(encoding="utf-8")
            if render_block(text, generated, start, end, warn) != text:
                dirty.append(path.name)
        if DATA.exists():
            dirty += build_vs_pages(data["tools"], site, data.get("_meta", {}), check=True)
            dirty += build_pricing_pages(data["tools"], site, data.get("_meta", {}), check=True)
            dirty += build_seo_pages(data["tools"], site, data.get("_meta", {}), check=True)
            dirty += build_catalog_pages(data["tools"], site, data.get("_meta", {}), check=True)
            dirty += build_integrations_page(data["tools"], site, data.get("_meta", {}), check=True)
            dirty += build_i18n.run_all(site, data["tools"], data.get("_meta", {}), check=True)
        dirty += build_price_history(site, check=True)
        if dirty:
            print(f"[build --check] OUT OF DATE: {', '.join(dirty)} — spusť `python build.py`.")
            return 1
        print("[build --check] OK — stránky jsou aktuální vůči data/tools.json.")
        return 0

    changed = []
    for path, generated, start, end, warn in jobs:
        if inject(path, generated, start, end, warn):
            changed.append(path.name)
    if DATA.exists():
        # vs-stránky generovat PŘED sitemap/analytics — nové soubory se tak
        # hned dostanou do sitemapy i GA4 injektoru
        changed += build_vs_pages(data["tools"], site, data.get("_meta", {}), check=False)
        changed += build_pricing_pages(data["tools"], site, data.get("_meta", {}), check=False)
        changed += build_seo_pages(data["tools"], site, data.get("_meta", {}), check=False)
        changed += build_catalog_pages(data["tools"], site, data.get("_meta", {}), check=False)
        changed += build_integrations_page(data["tools"], site, data.get("_meta", {}), check=False)
        changed += build_i18n.run_all(site, data["tools"], data.get("_meta", {}), check=False)

    # price-history je nezávislá na tools.json (vlastní zdroj price-history.json);
    # generovat PŘED sitemap, ať se nová stránka dostane do sitemapy/analytics
    changed += build_price_history(site, check=False)

    # site-wide artefakty
    domain = site.get("domain", "automationcost.io")
    base_path = site.get("base_path", "")
    pages = public_pages(site.get("sitemap_exclude", ["404.html"]))
    if build_sitemap(domain, base_path, pages):
        changed.append("sitemap.xml")
    if build_robots(domain, base_path, site.get("extra_sitemaps", [])):
        changed.append("robots.txt")
    if DATA.exists():
        changed += build_feed(domain, base_path, clog_entries)
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
