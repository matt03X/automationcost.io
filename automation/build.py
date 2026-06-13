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

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "tools.json"
SITE = ROOT / "data" / "site.json"

START = "/* DATA:TOOLS:START */"
END = "/* DATA:TOOLS:END */"
WARN = "/* generováno build.py z data/tools.json — needituj ručně */"

CLOG_START = "/* DATA:CHANGELOG:START */"
CLOG_END = "/* DATA:CHANGELOG:END */"
CLOG_WARN = "/* generováno build.py z git historie data/tools.json — needituj ručně */"

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
    cells = ", ".join(f"{{ upTo: {js_limit(t.get('upTo'))}, usd: {t['usd']} }}" for t in tiers)
    return f"[{cells}]"


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
    if plan.get("selfHostOnly"):
        parts.append("selfHostOnly: true")
    if "overage" in plan:
        # per-plan override tool-level overage; null = plán nemá pay-as-you-go
        parts.append(f'overage: {js_overage(plan["overage"])}')
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
    return "none" if ov is None else f"${ov['usd']}/{ov['per']:,} ops"


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
        if o.get("integrations") != t.get("integrations"):
            add("Integrations", f"{o.get('integrations'):,}", f"{t.get('integrations'):,}", "info")
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
                add(f"{p['name']} — included ops", _fmt_count(q.get("opsIncluded")), _fmt_count(p.get("opsIncluded")), "info")
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


def _root_engine():
    """Importuje root build.py kvůli cheapest_monthly — JEDINÁ kopie cost logiky
    (parita s JS hlídá verify-demo.js); třetí port by se rozjel."""
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
        return f"+${ov['usd']} per {ov['per']:,} ops" if ov else "none — upgrade only"

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
        ("Integrations", lambda t: f"{t['integrations']:,}+",
         lambda ta, tb: None if ta["integrations"] == tb["integrations"]
         else ("a" if ta["integrations"] > tb["integrations"] else "b")),
        ("Free tier", lambda t: f"{t['freeOps']} · {t['freeWorkflows']}", lambda ta, tb: None),
        ("Overage model", fmt_overage, win_overage),
        ("Steps per workflow", lambda t: t["maxSteps"],
         lambda ta, tb: ("a" if ta["maxSteps"].lower().startswith("unlimited") else "b")
         if (ta["maxSteps"].lower().startswith("unlimited") != tb["maxSteps"].lower().startswith("unlimited")) else None),
        ("Execution timeout", lambda t: t["timeout"], win_timeout),
        ("Log history", lambda t: t["logHistory"], lambda ta, tb: None),
        ("GDPR-friendly", lambda t: bool_cell(t["gdprFriendly"]), win_bool("gdprFriendly")),
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
            "q": f"Is {wt['name']} cheaper than {lt_['name']}?",
            "a": (f"At every volume we track, yes — from {_fmt_usd(w0['cost'], w0['est'])} vs "
                  f"{_fmt_usd(l0['cost'], l0['est'])} at {volumes[0]:,} ops/mo to "
                  f"{_fmt_usd(wN['cost'], wN['est'])} vs {_fmt_usd(lN['cost'], lN['est'])} at "
                  f"{volumes[-1]:,}. Prices include overage where it applies — see the table above.")})
    else:
        parts = [f"{volumes[i]:,} ops: {(ta if w == 'a' else tb)['name']}"
                 for i, w in enumerate(wins) if w != "tie"]
        faq.append({
            "q": f"Which is cheaper, {a_name} or {b_name}?",
            "a": "It depends on volume — the cheaper pick flips: " + " · ".join(parts)
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
    loser = tb if pair.get("winner") == ta["slug"] else ta
    if pair.get("whyLoser"):
        faq.append({"q": f"Why would anyone pick {loser['name']}, then?", "a": pair["whyLoser"]})
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
            raise SystemExit(f"CHYBA: {slug} — nástroj nemá ocenitelný plán pro {vol} ops.")
        costs.append((ra, rb))
    wins = [("a" if ca["cost"] < cb["cost"] else ("b" if cb["cost"] < ca["cost"] else "tie"))
            for ca, cb in costs]
    uniform = wins[0] if all(w == wins[0] and w != "tie" for w in wins) else None

    # FAQ: ruční override, jinak auto z dat
    pair = dict(pair)
    pair["_tools_meta"] = {s: d.get("opDef", "") for s, d in pairs_data.get("tools", {}).items()}
    pair["_month_year"] = month_year
    faq = pair.get("faq") or _vs_auto_faq(pair, ta, tb, costs, volumes)

    # vs-strip: jednoznačný vítěz → "W < L (+ stripNote)"; jinak neutrální "A vs B"
    if uniform:
        w, l = (ta, tb) if uniform == "a" else (tb, ta)
        strip = (f'<span class="who"><img src="{_logo(w["slug"])}" alt="{w["name"]} logo">{w["name"]}</span>\n'
                 f'      <span class="lt">&lt;</span>\n'
                 f'      <span class="who"><img src="{_logo(l["slug"])}" alt="{l["name"]} logo">{l["name"]}</span>')
        if pair.get("stripNote"):
            strip += f'\n      <span style="color:var(--muted); font-weight:500;">{pair["stripNote"]}</span>'
    else:
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
        tbl_note += (" * self-hosted = free open-source software; the figure is the server "
                     "hardware (your VPS, not a tool fee), scaling ~$8–66/mo with volume.")

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
        winner_cls = " winner" if t["slug"] == pair.get("winner") else ""
        blurb = pairs_data.get("tools", {}).get(t["slug"], {}).get("ctaBlurb", "")
        if t["hasAffiliate"]:
            btn = (f'<a href="{t["affiliateUrl"]}" target="_blank" rel="noopener sponsored" '
                   f'class="out-btn aff">Try {t["name"]} free →</a>\n'
                   f'        <span class="aff-note">Affiliate link — never affects our rankings.</span>')
        else:
            btn = (f'<a href="{t["homepage"]}" target="_blank" rel="noopener" '
                   f'class="out-btn plain">Visit {t["name"]} →</a>')
        return (f'      <div class="out-card{winner_cls}">\n        <div class="out-head">'
                f'<img src="{_logo(t["slug"])}" alt="{t["name"]} logo">{t["name"]}</div>\n'
                f'        <p>{blurb}</p>\n        {btn}\n      </div>')
    # winner karta první
    out_cards = sorted([ta, tb], key=lambda t: t["slug"] != pair.get("winner"))

    # cross-linky: pricing obou + compare + až 3 nejbližší publikované páry
    xlinks = [f'<a class="xlink" href="{ta["slug"]}-pricing.html">{a_name} pricing in detail</a>',
              f'<a class="xlink" href="{tb["slug"]}-pricing.html">{b_name} pricing in detail</a>',
              '<a class="xlink" href="compare.html">Compare all 7 tools</a>']
    for other in pairs_data["pairs"]:
        oslug = f'{other["a"]}-vs-{other["b"]}'
        if oslug == slug or len(xlinks) >= 6:
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
    faq_html = "\n".join(
        f'      <div class="faq-item">\n        <button class="faq-q" onclick="toggleFaq(this)">{f["q"]}</button>\n'
        f'        <div class="faq-a">{f["a"]}</div>\n      </div>' for f in faq)

    title = f"{a_name} vs {b_name}: Pricing &amp; Cost Comparison 2026 | AutomationCost.io"
    desc = (f"{a_name} vs {b_name} priced at " + " / ".join(f"{v:,}" for v in volumes)
            + " ops per month — real plans, overage math, feature differences and which one is "
              "cheaper for your usage.")
    canonical = f"{prefix}/{slug}.html"

    css = _VS_CSS  # sdílená šablona stylů (port z _vs-example.html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build.py z data/tools.json + data/pairs.json — needituj ručně -->
  <title>{title}</title>
  <meta name="description" content="{_html_escape(desc)}">
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
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
{css}
  </style>
</head>
<body>

<header>
  <div class="nav-top">
    <a href="/" class="logo">
      <svg class="logo-icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs><linearGradient id="acmk" x1="14" y1="10" x2="30" y2="38" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#2fe39c"></stop><stop offset="1" stop-color="#0ea66e"></stop></linearGradient></defs>
        <path d="M28.5 10.5 L13.5 24 L28.5 37.5" stroke="url(#acmk)" stroke-width="6.8" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M 36.5 17.8 Q 37.864 22.636 42.7 24 Q 37.864 25.364 36.5 30.2 Q 35.136 25.364 30.3 24 Q 35.136 22.636 36.5 17.8 Z" fill="#eafff5"></path>
      </svg>
      Automation<span>Cost</span><span class="io" style="font-size:0.72em; margin-left:7px;">by WizardCost</span>
    </a>
    <span class="nav-badge">Updated {month_year} · Real pricing data</span>
  </div>
  <nav class="nav-bottom">
    <a href="index.html">Home</a>
    <a href="calculator.html">Calculator</a>
    <a href="compare.html" class="active">Compare</a>
    <a href="limits.html">Pricing & Limits</a>
    <a href="tools.html">Tools</a>
    <a href="changelog.html">Changelog</a>
  </nav>
</header>

<div class="wrap">

  <!-- 1 ── Hero verdict -->
  <div class="hero" data-screen-label="VS hero">
    <div class="hero-badge">prices verified {month_year.lower()} · 3 workflows · monthly billing</div>
    <h1>{a_name} vs {b_name} — <em>which costs less?</em></h1>
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
          <tr><th>ops / month</th><th>{a_name}</th><th>{b_name}</th></tr>
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
      <p>30 seconds, no signup — your ops, your workflows, all 7 tools ranked.</p>
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
  <section class="price-alerts" id="price-alerts" data-screen-label="Price-drop alerts">
    <div class="pa-label">Price-drop alerts</div>
    <div class="pa-title">Get an email when {a_name} or {b_name} changes pricing.</div>
    <p class="pa-sub">Every change is verified by hand and published to the <a href="changelog.html">changelog</a> — you get one email per confirmed change.</p>
    <form class="pa-form" id="pa-form" action="{EMAILCAP_ACTION}" method="post" novalidate>
      <label for="pa-email" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);">Email address</label>
      <input class="pa-input" id="pa-email" name="fields[email]" type="email" inputmode="email" autocomplete="email" required placeholder="you@company.com">
      <input type="hidden" name="ml-submit" value="1"><input type="hidden" name="anticsrf" value="true"><button class="pa-btn" id="pa-btn" type="submit">Get price alerts</button>
    </form>
    <div class="pa-msg" id="pa-msg" role="status" aria-live="polite"></div>
    <p class="pa-note">Price-change alerts only. No newsletter, unsubscribe anytime. <a href="privacy.html">Privacy</a></p>
  </section>
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
  AutomationCost · part of WizardCost · Prices verified {month_year} · <a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> · <a href="affiliate.html">Affiliate Disclosure</a>
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
    if "included ops" in item or "workflow limit" in item:
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
    kind = "Plan limit change" if ("included ops" in item or "workflow limit" in item) else "Price change"
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

    if args.check:
        dirty = []
        for path, generated, start, end, warn in jobs:
            text = path.read_text(encoding="utf-8")
            if render_block(text, generated, start, end, warn) != text:
                dirty.append(path.name)
        if DATA.exists():
            dirty += build_vs_pages(data["tools"], site, data.get("_meta", {}), check=True)
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
