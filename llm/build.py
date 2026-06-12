#!/usr/bin/env python3
"""llm/build.py — vstříkne kanonická data z data/models.json do stránek /llm/ subsite.

Jediný zdroj pravdy = data/models.json (ceny ověřené proti oficiálním ceníkům,
audit dumpy v calc-test/llm-pricing-dumps/). Generuje `const MODELS` blok mezi:

    /* DATA:MODELS:START */ … /* DATA:MODELS:END */

Dále: sitemap.xml subsite, GA4 + Cloudflare analytics injektory (vzor automation).
Changelog + feedy z git historie models.json přijdou ve Fázi 2.

Spuštění:
    python build.py            # přegeneruje stránky
    python build.py --check    # CI guard (exit 1 při zastaralých blocích)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "models.json"
SITE = ROOT / "data" / "site.json"

START = "/* DATA:MODELS:START */"
END = "/* DATA:MODELS:END */"
WARN = "/* generováno build.py z data/models.json — needituj ručně */"

AN_START = "<!-- ANALYTICS (build.py) -->"
AN_END = "<!-- /ANALYTICS -->"
GA_START = "<!-- GA4 (build.py) -->"
GA_END = "<!-- /GA4 -->"


def js_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def js_num(v) -> str:
    return "null" if v is None else str(v)


def render_models(data: dict) -> str:
    """const MODELS pro index.html (+ budoucí compare). Pole per model:
    n (name), p (provider name), pslug, t (tier), i/o (USD za 1M in/out),
    cached (USD za 1M cached input; null = bez cache), batch (násobitel; null),
    ctx (context window v tokenech; null)."""
    lines = ["const MODELS = ["]
    for prov in data["providers"]:
        for m in prov["models"]:
            lines.append(
                "  { "
                f'n: {js_str(m["name"])}, p: {js_str(prov["name"])}, pslug: {js_str(prov["slug"])}, '
                f't: {js_str(m["tier"])}, i: {js_num(m["inputPerM"])}, o: {js_num(m["outputPerM"])}, '
                f'cached: {js_num(m.get("cachedInputPerM"))}, batch: {js_num(m.get("batchDiscount"))}, '
                f'ctx: {js_num(m.get("contextWindow"))} }},'
            )
    lines.append("];")
    lines.append(f'const MODELS_REVIEWED = {js_str(data["_meta"].get("last_reviewed") or "")};')
    return "\n".join(lines)


# ── changelog z git historie models.json (vzor automation/build.py) ─────────

CLOG_START = "/* DATA:CHANGELOG:START */"
CLOG_END = "/* DATA:CHANGELOG:END */"
CLOG_WARN = "/* generováno build.py z git historie data/models.json — needituj ručně */"


def _fmt_perM(v) -> str:
    return "n/a" if v is None else f"${v}/1M"


def _fmt_batch(v) -> str:
    return "none" if v is None else f"−{round((1 - v) * 100)}%"


def _fmt_ctx(v) -> str:
    if v is None:
        return "n/a"
    return f"{v // 1000000}M tokens" if v >= 1000000 else f"{v // 1000}k tokens"


def models_history() -> list[tuple[str, dict]]:
    """[(date, parsed models.json)] pro každý commit, od nejstaršího (--follow)."""
    import subprocess
    repo = ROOT.parent
    rel = str(DATA.relative_to(repo)).replace("\\", "/")
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--follow", "--format=%H %ad", "--date=short",
         "--name-only", "--", rel], capture_output=True, text=True)
    if log.returncode != 0:
        return []
    commits, sha_date = [], None
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
    commits.reverse()
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


def diff_models(old: dict, new: dict, date: str) -> list[dict]:
    """Cenově relevantní rozdíly verzí models.json → changelog záznamy.
    Nové modely/provideři se nehlásí (růst katalogu ≠ změna ceny).
    Tier změny = editorial re-sort → hlásí se jako info, ale NEpatří do alertů."""
    entries = []
    old_models = {}
    for p in old.get("providers", []):
        for m in p.get("models", []):
            old_models[m["id"]] = m
    for p in new.get("providers", []):
        for m in p.get("models", []):
            q = old_models.get(m["id"])
            if q is None:
                continue
            add = lambda item, a, b, d: entries.append(
                {"d": date, "tool": m["id"], "name": m["name"], "pslug": p["slug"],
                 "item": item, "old": a, "neu": b, "dir": d})
            # POZOR: přechod null→hodnota = backfill NAŠÍ verifikace (doplnili
            # jsme ověřený údaj), NE změna vendora → do changelogu nepatří.
            # Záznam vzniká jen při změně hodnota→hodnota.
            for key, label in (("inputPerM", "input price"), ("outputPerM", "output price"),
                               ("cachedInputPerM", "cached input price")):
                a, b = q.get(key), m.get(key)
                if a != b and a is not None and b is not None:
                    add(label, _fmt_perM(a), _fmt_perM(b), "up" if b > a else "down")
            a, b = q.get("batchDiscount"), m.get("batchDiscount")
            if a != b and a is not None and b is not None:
                add("batch discount", _fmt_batch(a), _fmt_batch(b), "info")
            a, b = q.get("contextWindow"), m.get("contextWindow")
            if a != b and a is not None and b is not None:
                add("context window", _fmt_ctx(a), _fmt_ctx(b), "info")
            a, b = q.get("tier"), m.get("tier")
            if a != b and a is not None and b is not None:
                add("tier (editorial)", a, b, "info")
    return entries


def changelog_entries() -> tuple[list[dict], str | None]:
    hist = models_history()
    entries = []
    for (_, older), (date, newer) in zip(hist, hist[1:]):
        entries.extend(diff_models(older, newer, date))
    entries.sort(key=lambda e: e["d"], reverse=True)
    return entries, (hist[0][0] if hist else None)


def render_changelog(data: dict, entries: list[dict], genesis: str | None) -> str:
    lines = ["const CHANGELOG = ["]
    for e in entries:
        lines.append(
            f'  {{ d: {js_str(e["d"])}, tool: {js_str(e["tool"])}, name: {js_str(e["name"])}, '
            f'pslug: {js_str(e["pslug"])}, '
            f'item: {js_str(e["item"])}, old: {js_str(e["old"])}, neu: {js_str(e["neu"])}, dir: {js_str(e["dir"])} }},')
    lines.append("];")
    import datetime as _dt
    if genesis:
        y, m, _ = genesis.split("-")
        genesis_month = _dt.date(int(y), int(m), 1).strftime("%B %Y")
    else:
        genesis_month = "June 2026"
    n_providers = len(data.get("providers", []))
    n_models = sum(len(p.get("models", [])) for p in data.get("providers", []))
    lines.append(f'const CLOG_GENESIS = {js_str(f"Tracking started {genesis_month} · {n_providers} providers · {n_models} models")};')
    return "\n".join(lines)


def _is_alert_entry(e: dict) -> bool:
    """Email alerty slibují 'price-change alerts only' → tier re-sort (editorial)
    do alerts.xml NEpatří; ceny, batch a context window (limit) ano."""
    return "tier" not in e["item"]


def _alert_meta(e: dict) -> str:
    import datetime as _dt
    kind = "Price change" if e["dir"] in ("up", "down") else (
        "Limit change" if "context" in e["item"] else "Pricing structure change")
    dt = _dt.datetime.strptime(e["d"], "%Y-%m-%d")
    return f"{kind} · verified {dt:%B} {dt.day}, {dt.year}"


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _feed_xml(prefix: str, self_name: str, title: str, channel_desc: str,
              entries: list[dict], alert_style: bool = False) -> str:
    import datetime as _dt
    page = f"{prefix}/changelog.html"
    items = []
    for e in entries[:50]:
        item_title = f'{e["name"]} — {e["item"]}: {e["old"]} → {e["neu"]}'
        desc = (_alert_meta(e) if alert_style
                else f'{_alert_meta(e)}. Full history in the WizardCost LLM changelog.')
        pub = _dt.datetime.strptime(e["d"], "%Y-%m-%d").strftime("%a, %d %b %Y 00:00:00 GMT")
        guid = f'{e["d"]}-{e["tool"]}-{e["item"].replace(" ", "-")}'
        items.append(
            "  <item>\n"
            f"    <title>{_xml_escape(item_title)}</title>\n"
            f"    <link>{page}</link>\n"
            f'    <guid isPermaLink="false">{_xml_escape(guid)}</guid>\n'
            f"    <pubDate>{pub}</pubDate>\n"
            f"    <description>{_xml_escape(desc)}</description>\n"
            "  </item>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
            f"  <title>{_xml_escape(title)}</title>\n  <link>{page}</link>\n"
            f"  <description>{_xml_escape(channel_desc)}</description>\n  <language>en</language>\n"
            f'  <atom:link href="{prefix}/{self_name}" rel="self" type="application/rss+xml"/>\n'
            + ("\n".join(items) + "\n" if items else "") + "</channel>\n</rss>\n")


def build_feeds(domain: str, base_path: str, entries: list[dict]) -> list[str]:
    """feed.xml = plný LLM changelog; alerts.xml = jen ceny/limity (zdroj
    budoucí email kampaně — NIKDY na něj nemířit plný feed, slib disclosure)."""
    prefix = _site_prefix(domain, base_path)
    feeds = [
        ("feed.xml", "WizardCost — LLM API Pricing Changelog",
         "Every dated price and limit change recorded across OpenAI, Anthropic, Gemini, "
         "DeepSeek, xAI and Mistral APIs — sourced from official pricing pages.", entries),
        ("alerts.xml", "WizardCost — LLM Price-Change Alerts",
         "Price and limit changes only — the feed behind WizardCost LLM email alerts.",
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


# ── injekce mezi markery (vzor automation/build.py) ─────────────────────────

def render_block(text: str, generated: str, start: str, end: str, warn: str) -> str:
    if start not in text or end not in text:
        raise SystemExit(f"CHYBA: chybí markery {start} … {end}.")
    pre, rest = text.split(start, 1)
    _, post = rest.split(end, 1)
    indent = pre[pre.rfind("\n") + 1:]
    return pre + f"{start} {warn}\n{generated}\n{indent}{end}" + post


def inject(path: Path, generated: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text = render_block(text, generated, START, END, WARN)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False


# ── site-wide artefakty (vzor automation/build.py) ───────────────────────────

def load_site() -> dict:
    return json.loads(SITE.read_text(encoding="utf-8"))


def public_pages(exclude: list[str]) -> list[Path]:
    skip = set(exclude or [])
    return sorted(p for p in ROOT.glob("*.html")
                  if p.name not in skip and not p.name.startswith("_"))


def _site_prefix(domain: str, base_path: str) -> str:
    bp = (base_path or "").strip("/")
    return f"https://{domain}/{bp}".rstrip("/") if bp else f"https://{domain}"


def build_sitemap(domain: str, base_path: str, pages: list[Path]) -> bool:
    prefix = _site_prefix(domain, base_path)
    urls = []
    for p in pages:
        loc = f"{prefix}/" if p.name == "index.html" else f"{prefix}/{p.name}"
        urls.append(f"  <url><loc>{loc}</loc></url>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           + "\n".join(urls) + "\n</urlset>\n")
    out = ROOT / "sitemap.xml"
    if not out.exists() or out.read_text(encoding="utf-8") != xml:
        out.write_text(xml, encoding="utf-8")
        return True
    return False


def _apply_snippet(pages: list[Path], start: str, end: str, snippet: str) -> list[str]:
    """Idempotentní vložení/odebrání snippetu před </head> (vzor automation)."""
    import re as _re
    block_re = _re.compile(_re.escape(start) + r".*?" + _re.escape(end) + r"\n?\s*", _re.S)
    changed = []
    for p in pages:
        text = p.read_text(encoding="utf-8")
        cleaned = block_re.sub("", text)
        new = cleaned.replace("</head>", snippet + "</head>", 1) if snippet and "</head>" in cleaned else cleaned
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed.append(p.name)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Inject data/models.json into /llm/ pages.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    site = load_site()
    data = json.loads(DATA.read_text(encoding="utf-8"))
    generated = render_models(data)
    targets = [p for p in (ROOT / "index.html", ROOT / "compare.html") if p.exists()]

    # changelog: generovaný z git historie models.json (sdílí ho i feedy)
    clog_entries, clog_genesis = changelog_entries()
    clog_page = ROOT / "changelog.html"
    clog_jobs = []
    if clog_page.exists() and CLOG_START in clog_page.read_text(encoding="utf-8"):
        clog_jobs.append((clog_page, render_changelog(data, clog_entries, clog_genesis),
                          CLOG_START, CLOG_END, CLOG_WARN))

    if args.check:
        dirty = [p.name for p in targets
                 if render_block(p.read_text(encoding="utf-8"), generated, START, END, WARN)
                 != p.read_text(encoding="utf-8")]
        dirty += [p.name for p, gen, s, e, w in clog_jobs
                  if render_block(p.read_text(encoding="utf-8"), gen, s, e, w)
                  != p.read_text(encoding="utf-8")]
        if dirty:
            print(f"[llm build --check] OUT OF DATE: {', '.join(dirty)} — spusť `python llm/build.py`.")
            return 1
        print("[llm build --check] OK — stránky jsou aktuální vůči data/models.json.")
        return 0

    changed = [p.name for p in targets if inject(p, generated)]
    for p, gen, s, e, w in clog_jobs:
        text = p.read_text(encoding="utf-8")
        new_text = render_block(text, gen, s, e, w)
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            changed.append(p.name)
    changed += build_feeds(site.get("domain", "wizardcost.com"),
                           site.get("base_path", "/llm"), clog_entries)

    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "/llm")
    pages = public_pages(site.get("sitemap_exclude", ["404.html"]))
    if build_sitemap(domain, base_path, pages):
        changed.append("sitemap.xml")

    token = site.get("cloudflare_analytics_token", "")
    an = (f'{AN_START}\n  <script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
          f'data-cf-beacon=\'{{"token": "{token}"}}\'></script>\n  {AN_END}\n  ') if token else ""
    changed += _apply_snippet(pages, AN_START, AN_END, an)

    ga = site.get("ga4_measurement_id", "")
    ga_snip = (f'{GA_START}\n  <script async src="https://www.googletagmanager.com/gtag/js?id={ga}"></script>\n'
               f'  <script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}'
               f'gtag("js",new Date());gtag("config","{ga}");</script>\n  {GA_END}\n  ') if ga else ""
    changed += _apply_snippet(pages, GA_START, GA_END, ga_snip)

    print(f"[llm build] aktualizováno: {', '.join(changed)}" if changed else "[llm build] beze změny.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
