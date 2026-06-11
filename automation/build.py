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
# Changelog: git historie data/tools.json → veřejný cenový changelog
# ---------------------------------------------------------------------------

def _fmt_money(v) -> str:
    return "Custom" if v is None else f"${v}/mo"


def _fmt_ops(v) -> str:
    return "Unlimited" if v is None else f"{v:,} ops"


def _fmt_wf(v) -> str:
    return "Unlimited" if v is None else f"{v} workflows"


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
            add("Integrations", str(o.get("integrations")), str(t.get("integrations")), "info")
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
                add(f"{p['name']} — included ops", _fmt_ops(q.get("opsIncluded")), _fmt_ops(p.get("opsIncluded")), "info")
            if q.get("workflowLimit") != p.get("workflowLimit"):
                add(f"{p['name']} — workflow limit", _fmt_wf(q.get("workflowLimit")), _fmt_wf(p.get("workflowLimit")), "info")
    return entries


def changelog_entries() -> tuple[list[dict], str | None]:
    """Záznamy changelogu z git historie (nejnovější první) + datum prvního
    commitu tools.json (genesis). Sdílí je changelog.html i RSS feed."""
    hist = tools_history()
    entries = []
    for (_, older), (date, newer) in zip(hist, hist[1:]):
        entries.extend(diff_tools(older, newer, date))
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


def build_feed(domain: str, base_path: str, entries: list[dict]) -> bool:
    """RSS feed cenového changelogu → feed.xml (max 50 nejnovějších záznamů).
    Stejná data jako changelog.html; prázdný changelog = validní feed bez položek."""
    import datetime as _dt
    prefix = _site_prefix(domain, base_path)
    page = f"{prefix}/changelog.html"
    items = []
    for e in entries[:50]:
        title = f'{e["name"]} — {e["item"]}: {e["old"]} → {e["neu"]}'
        desc = f'{e["name"]} {e["item"]} changed from {e["old"]} to {e["neu"]}.'
        pub = _dt.datetime.strptime(e["d"], "%Y-%m-%d").strftime("%a, %d %b %Y 00:00:00 GMT")
        slug = e["item"].lower().replace(" ", "-")
        guid = f'{e["d"]}-{e["tool"]}-{slug}'
        items.append(
            "  <item>\n"
            f"    <title>{_xml_escape(title)}</title>\n"
            f"    <link>{page}</link>\n"
            f'    <guid isPermaLink="false">{_xml_escape(guid)}</guid>\n'
            f"    <pubDate>{pub}</pubDate>\n"
            f"    <description>{_xml_escape(desc)}</description>\n"
            "  </item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "<channel>\n"
        "  <title>AutomationCost — Automation Tool Price Changelog</title>\n"
        f"  <link>{page}</link>\n"
        "  <description>Every dated price and limit change recorded across n8n, Make, Zapier, "
        "Pipedream and more — sourced from official pricing pages.</description>\n"
        "  <language>en</language>\n"
        f'  <atom:link href="{prefix}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        + ("\n".join(items) + "\n" if items else "")
        + "</channel>\n</rss>\n"
    )
    out = ROOT / "feed.xml"
    if not out.exists() or out.read_text(encoding="utf-8") != xml:
        out.write_text(xml, encoding="utf-8")
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
        if dirty:
            print(f"[build --check] OUT OF DATE: {', '.join(dirty)} — spusť `python build.py`.")
            return 1
        print("[build --check] OK — stránky jsou aktuální vůči data/tools.json.")
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
    if DATA.exists() and build_feed(domain, base_path, clog_entries):
        changed.append("feed.xml")
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
