"""build_i18n.py — language layer for the AutomationCost (/automation/) build.

Phase 1 (DE pilot). Generates the /<lang>/automation/ mirror of the funnel from
translations in data/i18n/<lang>.json:
  • generated pricing pages → render_pricing_page(lang=…, tr=…, editorial=merged)
  • manual pages (calculator/compare/index) → data-i18n localization pass
  • per-language sitemap.xml
  • static assets copied into the lang folder (relative links keep working)

EN stays the source at the site root (x-default). Frozen content (prices, tool
names, numbers) comes from tools.json / the cost engine identically for every
language — translation files never contain it.

check=True compares the would-be output against what's on disk and returns the
list of out-of-date files (folded into `build.py --check`, so the guard's build
drift check covers /de/ too — no hand-editing of generated pages).

Chrome-block injection (hreflang + language switcher between HTML markers) is
shared with build.py via inject_chrome_blocks(): build.py fills the EN manual
pages, build_i18n fills the localized copies.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import build_pricing
from build_hosting import expand_hosting_variants
from i18n_util import (
    make_tr, load_i18n, site_langs, lang_prefix, page_url,
    hreflang_links, lang_switcher,
)

ROOT = Path(__file__).resolve().parent          # …/automation
REPO_ROOT = ROOT.parent                          # …/wizardcost (site root)

# Manual (hand-written) funnel pages localized via data-i18n annotations.
MANUAL_PAGES = ["index.html", "calculator.html", "compare.html"]
# Page → i18n slug (must match the data-i18n="pages.<slug>.*" keys in the HTML,
# so the <meta description> lookup uses the same namespace as the body copy).
PAGE_SLUG = {"index.html": "hub", "calculator.html": "calc", "compare.html": "compare"}
# Static assets a localized page references relatively — copied into each lang dir.
STATIC_ASSETS = ["app.css", "app.js", "favicon.svg", "og-image.png", "og-image.svg"]
STATIC_DIRS = ["assets"]

# Chrome-block markers (mirror the DATA:* injection pattern already in the repo).
HREFLANG_START, HREFLANG_END = "<!-- HREFLANG:START -->", "<!-- HREFLANG:END -->"
LANGSWITCH_START, LANGSWITCH_END = "<!-- LANGSWITCH:START -->", "<!-- LANGSWITCH:END -->"
# Client-side JS-i18n dict (for content the page renders in JS, where data-i18n can't reach).
ACI18N_START, ACI18N_END = "<!-- AC_I18N:START -->", "<!-- AC_I18N:END -->"


def lang_dir(lang: str) -> Path:
    """Output dir for a language's automation mirror (EN = automation/ itself)."""
    return ROOT if lang == "en" else REPO_ROOT / lang / "automation"


def _rel_for(page: str) -> str:
    """Sitemap/canonical rel for a manual page. index.html → '' (folder index)."""
    return "" if page == "index.html" else page


# ── shared chrome-block injection (used for EN by build.py, for <lang> here) ──
def _replace_marked(html: str, start: str, end: str, inner: str) -> str:
    i = html.find(start)
    j = html.find(end)
    if i == -1 or j == -1 or j < i:
        return html  # markers absent (page not annotated yet) → no-op
    return html[: i + len(start)] + inner + html[j:]


def inject_chrome_blocks(html: str, *, lang: str, langs: list[str], site: dict,
                         rel: str) -> str:
    """Fill the HREFLANG + LANGSWITCH marker blocks for one page/locale.

    Deterministic (same input → same output) so it's safe under --check. The
    language switcher is omitted when only one language is configured.
    """
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "")
    hl = ("\n" + hreflang_links(domain, base_path, rel, langs, indent="  ") + "\n  ") if len(langs) > 1 else ""
    html = _replace_marked(html, HREFLANG_START, HREFLANG_END, hl)
    if len(langs) > 1:
        sw = "\n    " + lang_switcher(base_path, rel, langs, lang) + "\n    "
    else:
        sw = ""
    html = _replace_marked(html, LANGSWITCH_START, LANGSWITCH_END, sw)
    return html


# ── data-i18n swap (manual pages) ─────────────────────────────────────────────
# Matches <tag … data-i18n="key" …>inner</tag> for a leaf-ish element (inner must
# not contain a nested element of the SAME tag). The data-i18n key is a dotted
# path resolved against the whole <lang>.json (so shared chrome reuses nav.* etc.;
# page-specific copy lives under pages.*). The EN inner is the fallback → only
# differing strings need a translation, build never breaks on a missing key.
_DATA_I18N_RE = re.compile(r'(<(\w+)[^>]*\bdata-i18n="([^"]+)"[^>]*>)(.*?)(</\2>)', re.DOTALL)


def _swap_data_i18n(html: str, tr) -> str:
    def repl(m: re.Match) -> str:
        open_tag, _tag, key, inner, close = m.groups()
        return open_tag + tr(key, inner) + close
    return _DATA_I18N_RE.sub(repl, html)


# ── localizers ────────────────────────────────────────────────────────────────
def _merge_editorial(editorial: dict, i18n: dict) -> dict:
    """Editorial dict with <lang>.json['pricing'][slug] shallow-merged over EN.

    Strings (h1/intro/warn) and whole lists (whenWorthIt/faq) replace EN per key;
    missing keys keep English (partial translation never breaks the build)."""
    merged = copy.deepcopy(editorial)
    for slug, tr_ed in (i18n.get("pricing") or {}).items():
        if slug in merged.get("tools", {}) and isinstance(tr_ed, dict):
            merged["tools"][slug].update(tr_ed)
    return merged


def localize_pricing(lang: str, tr, i18n: dict, tools: list[dict], site: dict,
                     tools_meta: dict, langs: list[str], *, check: bool) -> list[str]:
    if not build_pricing.EDITORIAL.exists():
        return []
    editorial = _merge_editorial(
        json.loads(build_pricing.EDITORIAL.read_text(encoding="utf-8")), i18n)
    engine = build_pricing._root_engine()
    by_slug = {t["slug"]: t for t in tools}
    variants_by_base: dict[str, list[dict]] = {}
    for v in expand_hosting_variants(tools):
        variants_by_base.setdefault(v.get("variantOf", v["slug"]), []).append(v)

    out_dir = lang_dir(lang)
    out: list[str] = []
    for slug in build_pricing.PRICING_SLUGS:
        if slug not in by_slug or slug not in editorial.get("tools", {}):
            continue
        rendered = build_pricing.render_pricing_page(
            slug, tools, variants_by_base, editorial, site, tools_meta, engine,
            lang=lang, langs=langs, tr=tr)
        out += _emit(out_dir / f"{slug}-pricing.html", rendered, check)
    return out


def localize_manual(lang: str, tr, i18n: dict, page: str, site: dict,
                    langs: list[str], *, check: bool) -> list[str]:
    src_path = ROOT / page
    if not src_path.exists():
        return []
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "")
    rel = _rel_for(page)
    en_url = page_url(domain, base_path, "en", rel)
    lang_url = page_url(domain, base_path, lang, rel)
    en_img = f"{lang_prefix(domain, base_path, 'en')}/og-image.png"
    lang_img = f"{lang_prefix(domain, base_path, lang)}/og-image.png"

    # Strip analytics/GA blocks → localized copy is deterministic, independent of
    # build.py's post-generation analytics injection (DE analytics is phase 2).
    tr = make_tr(i18n)
    pkey = PAGE_SLUG.get(page, page[:-5] if page.endswith(".html") else page)
    html = build_pricing._strip_injected(src_path.read_text(encoding="utf-8"))
    html = re.sub(r'(<html lang=")[^"]*(")', rf"\g<1>{lang}\g<2>", html, count=1)
    html = re.sub(r'(<link rel="canonical" href=")[^"]*(">)',
                  lambda m: m.group(1) + lang_url + m.group(2), html, count=1)
    html = re.sub(r'(<meta property="og:url" content=")[^"]*(">)',
                  lambda m: m.group(1) + lang_url + m.group(2), html, count=1)
    html = html.replace(en_img, lang_img)
    # <meta name=description> is an attribute → translate via a per-page key (EN = fallback).
    # Tolerant of extra attributes (e.g. id="page-desc" on compare.html); swaps only the
    # content value so the surrounding tag (and any id the page JS targets) is preserved.
    md = re.search(r'(<meta name="description"[^>]*\scontent=")([^"]*)("[^>]*>)', html)
    if md:
        de_desc = tr(f"pages.{pkey}.metadesc", md.group(2))
        if de_desc != md.group(2):
            html = html[:md.start()] + md.group(1) + de_desc + md.group(3) + html[md.end():]
    html = inject_chrome_blocks(html, lang=lang, langs=langs, site=site, rel=rel)
    html = _swap_data_i18n(html, tr)
    # JS-i18n dict for content the page renders client-side (t(key, fallback) reads it)
    js_dict = i18n.get("js") or {}
    if js_dict:
        payload = "<script>window.AC_I18N=" + json.dumps(js_dict, ensure_ascii=False) + ";</script>"
        html = _replace_marked(html, ACI18N_START, ACI18N_END, payload)
    return _emit(lang_dir(lang) / page, html, check)


def copy_assets(lang: str, *, check: bool) -> list[str]:
    dst_dir = lang_dir(lang)
    out: list[str] = []
    for name in STATIC_ASSETS:
        src = ROOT / name
        if not src.exists():
            continue
        dst = dst_dir / name
        if check:
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                out.append(f"{lang}/automation/{name}")
        else:
            dst_dir.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                shutil.copy2(src, dst)
                out.append(f"{lang}/automation/{name}")
    for dname in STATIC_DIRS:
        src = ROOT / dname
        if src.is_dir() and not check:
            shutil.copytree(src, dst_dir / dname, dirs_exist_ok=True)
    return out


def build_lang_sitemap(lang: str, site: dict, rels: list[str], *, check: bool) -> list[str]:
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "")
    urls = sorted({page_url(domain, base_path, lang, r) for r in rels})
    body = "\n".join(
        f"  <url><loc>{u}</loc></url>" for u in urls)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
           f"{body}\n</urlset>\n")
    return _emit(lang_dir(lang) / "sitemap.xml", xml, check)


def _emit(path: Path, content: str, check: bool) -> list[str]:
    label = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == content:
        return []
    if check:
        return [label]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return [label]


# ── orchestration ─────────────────────────────────────────────────────────────
def run(lang: str, *, site: dict, tools: list[dict], tools_meta: dict,
        langs: list[str], check: bool) -> list[str]:
    """Build (or --check) one language's /automation/ mirror. Returns dirty files."""
    i18n = load_i18n(lang)
    tr = make_tr(i18n)
    out: list[str] = []
    out += localize_pricing(lang, tr, i18n, tools, site, tools_meta, langs, check=check)
    rels = [f"{s}-pricing.html" for s in build_pricing.PRICING_SLUGS]
    for page in MANUAL_PAGES:
        if (ROOT / page).exists():
            out += localize_manual(lang, tr, i18n, page, site, langs, check=check)
            rels.append(_rel_for(page))
    out += copy_assets(lang, check=check)
    out += build_lang_sitemap(lang, site, rels, check=check)
    return out


def inject_en_manual_chrome(site: dict, langs: list[str], *, check: bool) -> list[str]:
    """Fill HREFLANG + LANGSWITCH markers on the EN manual pages in place.

    No-op for pages that don't carry the markers yet (phased rollout). Touches
    only the marker blocks, so the analytics build.py injects afterwards is kept.
    """
    out: list[str] = []
    for page in MANUAL_PAGES:
        src = ROOT / page
        if not src.exists():
            continue
        html = src.read_text(encoding="utf-8")
        if HREFLANG_START not in html and LANGSWITCH_START not in html:
            continue
        new = inject_chrome_blocks(html, lang="en", langs=langs, site=site, rel=_rel_for(page))
        if new == html:
            continue
        if check:
            out.append(f"automation/{page}")
        else:
            src.write_text(new, encoding="utf-8")
            out.append(f"automation/{page}")
    return out


def run_all(site: dict, tools: list[dict], tools_meta: dict, *, check: bool) -> list[str]:
    """Build (or --check) every non-EN language configured in site.json."""
    langs = site_langs(site)
    out: list[str] = []
    # EN manual pages get hreflang + switcher filled in place first, so the
    # localized copies are produced from a chrome-complete source.
    out += inject_en_manual_chrome(site, langs, check=check)
    for lang in langs:
        if lang == "en":
            continue
        out += run(lang, site=site, tools=tools, tools_meta=tools_meta, langs=langs, check=check)
    return out
