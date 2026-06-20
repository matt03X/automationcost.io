"""verify_i18n.py — automated checker for the i18n translation files.

The owner doesn't read every target language, so this guards translations
DETERMINISTICALLY (no LLM, no deps) — it catches the dangerous, mechanical
failure modes that break the build or silently corrupt facts:

  • JSON validity + reviewed flag surfaced
  • placeholder parity — every {name}/{prices}/{vol}/{cmp_vol}… in the EN source
    must survive in the translation (a dropped placeholder loses a price or 400s
    the .format() call)
  • markup parity — same HTML tags (<strong>/<em>/<a …>) and entities (&times;…)
  • frozen-price-leak guard — a translation must NOT bake in a literal $/€/Kč
    amount (prices come from the engine; a baked "$73.5" goes stale)
  • pricing editorial structure — whenWorthIt/faq keep their length and the
    `tier` (good/warn/bad) is frozen (it drives the verdict colour/meaning)
  • coverage report per namespace

EN source of truth is collected by RENDERING the EN pages with a tracing
translator (captures every tr(key, default) actually used) + parsing the
data-i18n annotations in the manual pages — so it can't drift from the code.

Optional `--llm`: back-translate the REVIEW-flagged editorial (meta/pricing/
pages) to Czech via the Anthropic API so the owner can verify *meaning* in a
language he reads. Needs ANTHROPIC_API_KEY; degrades gracefully without it.
Raw HTTPS (stdlib urllib) is used deliberately so the static-site repo keeps
zero Python dependencies.

Exit 1 on any hard violation; 0 otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import build_pricing
import build_i18n
from build_hosting import expand_hosting_variants, apply_fx

ROOT = Path(__file__).resolve().parent
I18N_DIR = ROOT / "data" / "i18n"
EDITORIAL = ROOT / "data" / "pricing-editorial.json"

PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[^}]*)?\}")
TAG_RE = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)")
ENTITY_RE = re.compile(r"&[a-zA-Z]+;|&#\d+;")
PRICE_LEAK_RE = re.compile(r"[$€]\s?\d|\d\s?Kč")  # baked currency amount (must come from the engine)

DEFAULT_LLM_MODEL = "claude-opus-4-8"  # skill default; pass --model claude-haiku-4-5 for cheaper


def _ph(s):     return sorted(PLACEHOLDER_RE.findall(s))
def _tags(s):   return sorted(TAG_RE.findall(s.lower()))
def _ents(s):   return sorted(ENTITY_RE.findall(s))


# ── EN source of truth ────────────────────────────────────────────────────────
def collect_en_defaults() -> dict[str, str]:
    """Render the EN pages with a tracing tr + parse manual data-i18n → {key: EN}."""
    seen: dict[str, str] = {}

    def tracer(key, default):
        seen.setdefault(key, default)
        return default

    site = json.loads((ROOT / "data" / "site.json").read_text(encoding="utf-8"))
    data = json.loads(build_pricing.DATA.read_text(encoding="utf-8"))
    tools = data["tools"]
    apply_fx(tools)
    editorial = json.loads(EDITORIAL.read_text(encoding="utf-8"))
    engine = build_pricing._root_engine()
    vbb: dict[str, list[dict]] = {}
    for v in expand_hosting_variants(tools):
        vbb.setdefault(v.get("variantOf", v["slug"]), []).append(v)
    for slug in build_pricing.PRICING_SLUGS:
        if slug in editorial.get("tools", {}):
            build_pricing.render_pricing_page(slug, tools, vbb, editorial, site,
                                              data.get("_meta", {}), engine,
                                              lang="en", langs=["en", "de"], tr=tracer)

    # manual pages: data-i18n inner text + <meta name=description>
    for page in build_i18n.MANUAL_PAGES:
        p = ROOT / page
        if not p.exists():
            continue
        html = p.read_text(encoding="utf-8")
        for m in build_i18n._DATA_I18N_RE.finditer(html):
            seen.setdefault(m.group(3), m.group(4))
        md = re.search(r'<meta name="description"[^>]*\scontent="([^"]*)"', html)
        if md:
            pkey = build_i18n.PAGE_SLUG.get(page, page[:-5] if page.endswith(".html") else page)
            seen.setdefault(f"pages.{pkey}.metadesc", md.group(1))
    return seen


def flatten(d: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key))
        elif isinstance(v, str):
            out[key] = v
    return out


# ── checks ────────────────────────────────────────────────────────────────────
def verify(lang: str):
    errors: list[str] = []
    warns: list[str] = []
    en = collect_en_defaults()
    path = I18N_DIR / f"{lang}.json"
    if not path.exists():
        return [f"{lang}.json not found"], [], {}
    dej = json.loads(path.read_text(encoding="utf-8"))
    meta = dej.get("_meta", {})
    flat = flatten({k: v for k, v in dej.items() if k != "_meta"})

    # 1. frozen-price leak (any value)
    for k, v in flat.items():
        if PRICE_LEAK_RE.search(v):
            errors.append(f"[price-leak] {k}: baked currency amount in translation → {v!r}")

    # 2. placeholder + markup parity vs EN default (chrome/meta/pages keys)
    for k, v in flat.items():
        if k in en:
            ed = en[k]
            if _ph(ed) != _ph(v):
                errors.append(f"[placeholder] {k}: EN {_ph(ed)} ≠ {lang.upper()} {_ph(v)}")
            if _tags(ed) != _tags(v):
                errors.append(f"[markup] {k}: EN tags {_tags(ed)} ≠ {lang.upper()} {_tags(v)}")
            if _ents(ed) != _ents(v):
                warns.append(f"[entity] {k}: EN {_ents(ed)} ≠ {lang.upper()} {_ents(v)}")
        elif not k.startswith(("pricing.", "js.")):  # pricing.* checked structurally; js.* is client-side (can't trace)
            warns.append(f"[orphan] {k}: key not used by the EN build (stale or typo?)")

    # 3. pricing editorial structure (whenWorthIt/faq length + frozen tier + markup)
    en_tools = json.loads(EDITORIAL.read_text(encoding="utf-8")).get("tools", {})
    for slug, ded in (dej.get("pricing") or {}).items():
        een = en_tools.get(slug, {})
        for fld in ("whenWorthIt", "faq"):
            if fld not in ded:
                continue
            de_list, en_list = ded[fld], een.get(fld, [])
            if len(de_list) != len(en_list):
                errors.append(f"[count] pricing.{slug}.{fld}: {lang.upper()} {len(de_list)} ≠ EN {len(en_list)}")
                continue
            for i, (dit, eit) in enumerate(zip(de_list, en_list)):
                if fld == "whenWorthIt" and dit.get("tier") != eit.get("tier"):
                    errors.append(f"[frozen-tier] pricing.{slug}.whenWorthIt[{i}]: "
                                  f"tier {dit.get('tier')!r} ≠ EN {eit.get('tier')!r}")
                for sub in ("q", "a", "case", "verdict"):
                    if sub in dit and sub in eit and isinstance(dit[sub], str):
                        if _tags(eit[sub]) != _tags(dit[sub]):
                            errors.append(f"[markup] pricing.{slug}.{fld}[{i}].{sub}")
                        if _ph(eit[sub]) != _ph(dit[sub]):
                            errors.append(f"[placeholder] pricing.{slug}.{fld}[{i}].{sub}")

    coverage = {
        "total EN keys": len(en),
        "translated": sum(1 for k in en if k in flat),
        "reviewed": meta.get("reviewed"),
    }
    return errors, warns, coverage


# ── optional LLM back-translation (Czech) ─────────────────────────────────────
REVIEW_PREFIXES = ("meta.", "pricing.", "pages.")


def _anthropic(messages, model, max_tokens=4096):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps({"model": model, "max_tokens": max_tokens, "messages": messages}).encode("utf-8"),
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        body = json.loads(r.read().decode("utf-8"))
    return "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")


def llm_backtranslate(lang: str, model: str):
    en = collect_en_defaults()
    dej = json.loads((I18N_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    flat = flatten({k: v for k, v in dej.items() if k != "_meta"})
    items = [{"key": k, "en": en.get(k, "(EN from data)"), lang: v}
             for k, v in flat.items() if k.startswith(REVIEW_PREFIXES)]
    if not items:
        print("(no review-flagged editorial strings)")
        return
    prompt = (
        f"You are an i18n reviewer. For each item below, the '{lang}' field is a {lang.upper()} "
        "translation of the 'en' English source. Back-translate the "
        f"{lang.upper()} into CZECH, then judge whether it faithfully conveys the same MEANING "
        "and FACTS as the English (prices, tool names, claims). Output a Markdown table: "
        "key | česky (zpětný překlad) | OK / ⚠ rozdíl (krátce co). Keep tool names and prices as-is.\n\n"
        + json.dumps(items, ensure_ascii=False, indent=2)
    )
    out = _anthropic([{"role": "user", "content": prompt}], model, max_tokens=8000)
    if out is None:
        print("⚠ --llm vyžaduje ANTHROPIC_API_KEY (export ANTHROPIC_API_KEY=…). Přeskočeno.")
        print(f"   K manuální revizi: {len(items)} editorial řetězců (meta/pricing/pages).")
        return
    print(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify i18n translation files.")
    ap.add_argument("lang", nargs="?", default="de", help="language code (default: de)")
    ap.add_argument("--llm", action="store_true", help="LLM back-translation to Czech (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--model", default=DEFAULT_LLM_MODEL, help=f"LLM model (default {DEFAULT_LLM_MODEL}; haiku is cheaper)")
    args = ap.parse_args()

    errors, warns, coverage = verify(args.lang)
    print(f"=== verify_i18n: {args.lang}.json ===")
    print(f"coverage: {coverage}")
    for w in warns:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    if not errors:
        print(f"[verify_i18n] OK — {args.lang} je mechanicky v pořádku "
              f"({coverage.get('translated')}/{coverage.get('total EN keys')} klíčů, "
              f"reviewed={coverage.get('reviewed')}).")

    if args.llm:
        print(f"\n=== LLM zpětný překlad do češtiny ({args.model}) ===")
        llm_backtranslate(args.lang, args.model)

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
