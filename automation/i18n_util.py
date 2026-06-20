"""i18n utilities for the AutomationCost build — Phase 1 (DE pilot).

Design principles (see plan: krok-0-sync):
  • EN is the *implicit* source. Translation lookups fall back to the inline
    English default, so the EN build stays byte-identical → no regression and
    `build.py --check` stays green. Only overrides live in <lang>.json.
  • URL scheme is lang-first: EN at root (x-default), other langs mirrored under
    /<lang>/…  e.g. /de/automation/zapier-pricing.html.
  • Prices, tool/brand names and numbers are FROZEN — they never appear in the
    translation files; they come from tools.json / the cost engine identically
    for every language.

Translation files: automation/data/i18n/<lang>.json  (namespaced: ui / meta /
pages / pricing / vs). Missing key → English default (page is partially
translated, build never fails).
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
I18N_DIR = HERE / "data" / "i18n"

# Endonyms shown in the language switcher (frozen — language names aren't translated).
LANG_NAMES: dict[str, str] = {
    "en": "English",
    "de": "Deutsch",
    "fr": "Français",
    "cs": "Čeština",
    "es": "Español",
    "pt-br": "Português (BR)",
    "it": "Italiano",
    "pl": "Polski",
}

# Inline globe icon for the switcher button (matches nav SVG stroke styling).
GLOBE_SVG = (
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/>'
    '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 '
    '15.3 15.3 0 0 1 4-10z"/></svg>'
)
_CHEVRON_SVG = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>'
)


# ── config ──────────────────────────────────────────────────────────────────
def site_langs(site: dict) -> list[str]:
    """Languages to build, EN first. Defaults to EN-only when unset."""
    langs = list(site.get("languages") or ["en"])
    if "en" not in langs:
        langs = ["en"] + langs
    return langs


def load_i18n(lang: str) -> dict:
    """Translation dict for a language ({} for EN or a missing file)."""
    if lang == "en":
        return {}
    p = I18N_DIR / f"{lang}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def make_tr(i18n: dict):
    """Return tr(dotted_key, english_default) → translation or the default.

    The English default is always passed at the call site, so EN (empty dict)
    and any missing key both render the original English verbatim.
    """
    def tr(key: str, default: str) -> str:
        cur: object = i18n
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur if isinstance(cur, str) else default

    return tr


# ── URL helpers ───────────────────────────────────────────────────────────────
def lang_prefix(domain: str, base_path: str, lang: str) -> str:
    """Absolute site prefix incl. the language segment (no trailing slash).

    EN → https://domain/<base_path>   ·   DE → https://domain/de/<base_path>
    """
    bp = (base_path or "").strip("/")
    seg = "" if lang == "en" else lang
    tail = "/".join(p for p in (seg, bp) if p)
    return f"https://{domain}/{tail}".rstrip("/") if tail else f"https://{domain}"


def page_url(domain: str, base_path: str, lang: str, rel: str) -> str:
    """Absolute URL of a page. rel='' → folder index (keeps trailing slash)."""
    prefix = lang_prefix(domain, base_path, lang)
    rel = rel.lstrip("/")
    return f"{prefix}/" if rel == "" else f"{prefix}/{rel}"


def _abs_path(base_path: str, lang: str, rel: str) -> str:
    """Root-absolute path (for cross-folder switcher links). rel='' → folder index."""
    bp = (base_path or "").strip("/")
    seg = "" if lang == "en" else lang
    rel = rel.lstrip("/")
    parts = [p for p in (seg, bp) if p]
    head = "/" + "/".join(parts) if parts else ""
    return f"{head}/" if rel == "" else f"{head}/{rel}"


# ── head + nav fragments ──────────────────────────────────────────────────────
def hreflang_links(domain: str, base_path: str, rel: str, langs: list[str],
                   indent: str = "  ") -> str:
    """<link rel=alternate hreflang> for every lang + x-default → EN."""
    out = [
        f'{indent}<link rel="alternate" hreflang="{lg}" '
        f'href="{page_url(domain, base_path, lg, rel)}">'
        for lg in langs
    ]
    out.append(
        f'{indent}<link rel="alternate" hreflang="x-default" '
        f'href="{page_url(domain, base_path, "en", rel)}">'
    )
    return "\n".join(out)


def lang_switcher(base_path: str, rel: str, langs: list[str], current: str) -> str:
    """Globe dropdown markup (reuses the shared .ac-dd component).

    Only languages in `langs` are offered, so a page is never linked to a locale
    that wasn't generated for it. Cross-folder links are root-absolute.
    """
    items = "\n".join(
        f'        <a href="{_abs_path(base_path, lg, rel)}" hreflang="{lg}"'
        + (' aria-current="true"' if lg == current else "")
        + f">{LANG_NAMES.get(lg, lg)}</a>"
        for lg in langs
    )
    return (
        '<div class="ac-dd ac-lang">\n'
        '      <button class="ac-dd-btn" aria-expanded="false" aria-haspopup="true" '
        f'aria-label="Language / Sprache">{GLOBE_SVG}{_CHEVRON_SVG}</button>\n'
        '      <div class="ac-dd-menu ac-lang-menu">\n'
        f"{items}\n"
        "      </div>\n"
        "    </div>"
    )
