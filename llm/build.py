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

    if args.check:
        dirty = [p.name for p in targets
                 if render_block(p.read_text(encoding="utf-8"), generated, START, END, WARN)
                 != p.read_text(encoding="utf-8")]
        if dirty:
            print(f"[llm build --check] OUT OF DATE: {', '.join(dirty)} — spusť `python llm/build.py`.")
            return 1
        print("[llm build --check] OK — stránky jsou aktuální vůči data/models.json.")
        return 0

    changed = [p.name for p in targets if inject(p, generated)]

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
