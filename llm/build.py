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

import build_seo  # programmatic long-tail SEO stránky (cheapest / alternatives / vs)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "models.json"
SITE = ROOT / "data" / "site.json"
OVERRIDES = ROOT / "data" / "changelog-overrides.json"
EDITORIAL = ROOT / "data" / "pricing-editorial.json"
PRICE_HISTORY = ROOT / "data" / "price-history.json"

START = "/* DATA:MODELS:START */"
END = "/* DATA:MODELS:END */"
WARN = "/* generováno build.py z data/models.json — needituj ručně */"

SC_START = "/* DATA:SCORING:START */"
SC_END = "/* DATA:SCORING:END */"
SC_WARN = "/* generováno build.py z data/scoring-model.json + models.json — needituj ručně */"
SCORING = ROOT / "data" / "scoring-model.json"
# engine USE_CASE (index.html USE_CASES) -> scoring role (scoring-model.json roleWeights)
UC_ROLE = {"chatbot": "chatbot", "rag": "rag", "summarization": "rag",
           "agents": "agents", "extraction": "classification"}

AN_START = "<!-- ANALYTICS (build.py) -->"
AN_END = "<!-- /ANALYTICS -->"
GA_START = "<!-- GA4 (build.py) -->"
GA_END = "<!-- /GA4 -->"

# GEO:LD — Org+WebSite+WebPage @graph do <head> statických /llm/ stránek (živý
# dateModified). HTML komentář markery → warn prázdný (jinak text mimo komentář).
GEO_LD_START = "<!-- GEO:LD:START -->"
GEO_LD_END = "<!-- GEO:LD:END -->"
GEO_LD_WARN = ""


def js_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def js_num(v) -> str:
    return "null" if v is None else str(v)


def js_lc(m: dict) -> str:
    """long-context tier modelu → JS objekt { th, i, o, cached } nebo null.
    Nad prahem `th` (velikost promptu = input tokeny) účtuje provider vyšší sazby
    (Gemini >200k = $4/$18). cached=null → cache se nad prahem neaplikuje."""
    lc = m.get("longContext")
    if not lc:
        return "null"
    return (f'{{ th: {js_num(lc.get("threshold"))}, i: {js_num(lc.get("inputPerM"))}, '
            f'o: {js_num(lc.get("outputPerM"))}, cached: {js_num(lc.get("cachedInputPerM"))} }}')


# Kanonický scénář pro ≈$/mo sloupec compare (MUSÍ sedět s USE_CASES chatbot
# defaulty v index.html a footnote textem na compare — měnit synchronně!).
# Paritu Python↔JS hlídá calc-test/test-llm-engine.js.
CANON = {"req": 100000, "in_tok": 2000, "out_tok": 300, "cache": 0.70}


def canonical_monthly(m: dict) -> float:
    """Python port cost() z index.html pro kanonický scénář (bez batch, reason=1).
    Long-context aware (parita s rates()): nad prahem se použijí lc sazby. Kanonický
    in_tok=2000 < práh → reálně se nikdy nespustí, držíme symetrii s JS enginem."""
    c = CANON["cache"]
    lc = m.get("longContext")
    use_lc = bool(lc) and CANON["in_tok"] > lc["threshold"]
    in_per_m = lc["inputPerM"] if use_lc else m["inputPerM"]
    out_per_m = lc["outputPerM"] if use_lc else m["outputPerM"]
    cached = lc.get("cachedInputPerM") if use_lc else m.get("cachedInputPerM")
    in_rate = in_per_m * (1 - c) + cached * c if cached is not None else in_per_m
    in_cost = CANON["req"] * CANON["in_tok"] / 1e6 * in_rate
    out_cost = CANON["req"] * CANON["out_tok"] / 1e6 * out_per_m
    return round(in_cost + out_cost, 4)


# ── GEO/AI-citace: Org+WebSite+WebPage @graph (freshness + identita) ───────────
# Duplikát z automation/build_pricing._page_graph_ld (subsite je samostatný; vzor
# „kopírovat, neimportovat" jako jinde v repu). Sdílené @id #org/#website konsolidují
# entitu napříč /automation/ i /llm/. Bez Offer ceny — LLM ceny per-token = scénářové.
def _iso_date(data: dict) -> str:
    import datetime as _dt
    lr = (data.get("_meta") or {}).get("last_reviewed")
    if lr:
        try:
            _dt.date(*[int(x) for x in lr.split("-")])
            return lr
        except (ValueError, TypeError):
            pass
    return "2026-06-01"


def _geo_graph_ld(domain: str, canonical: str, name: str, desc: str, iso_date: str) -> str:
    home_url = f"https://{domain}/"
    org_id = f"{home_url}#org"
    return json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "@id": org_id, "name": "WizardCost", "url": home_url,
             "description": ("Independent, data-driven software pricing comparisons. Prices "
                             "verified by hand from official vendor pricing pages and dated "
                             "in a public changelog.")},
            {"@type": "WebSite", "@id": f"{home_url}#website", "name": "WizardCost",
             "url": home_url, "publisher": {"@id": org_id}},
            {"@type": "WebPage", "@id": f"{canonical}#webpage", "url": canonical,
             "name": name, "description": desc, "inLanguage": "en",
             "isPartOf": {"@id": f"{home_url}#website"},
             "publisher": {"@id": org_id}, "dateModified": iso_date},
        ],
    }, ensure_ascii=False, indent=2)


def _static_geo_ld(text: str, domain: str, iso_date: str) -> str:
    """Z <head> statické stránky vytáhne canonical/title/desc → <script> GEO blok ("" když chybí canonical)."""
    import re
    mc = re.search(r'<link rel="canonical" href="([^"]+)"', text)
    if not mc:
        return ""
    mt = re.search(r"<title[^>]*>(.*?)</title>", text, re.S)
    md = re.search(r'<meta name="description"[^>]*\scontent="([^"]*)"', text)
    name = (mt.group(1).strip() if mt else "").split(" | ")[0].replace("&amp;", "&")
    desc = (md.group(1) if md else "").replace("&amp;", "&")
    return (f'  <script type="application/ld+json">\n'
            f'{_geo_graph_ld(domain, mc.group(1), name, desc, iso_date)}\n  </script>')


def render_models(data: dict) -> str:
    """const MODELS pro index.html + compare.html. Pole per model:
    n (name), p (provider name), pslug, t (tier), i/o (USD za 1M in/out),
    cached (USD za 1M cached input; null = bez cache), batch (násobitel; null),
    ctx (context window v tokenech; null), lc (long-context tier { th,i,o,cached }
    nebo null), mo (kanonický ≈$/mo — viz CANON)."""
    lines = ["const MODELS = ["]
    for prov in data["providers"]:
        for m in prov["models"]:
            lines.append(
                "  { "
                f'n: {js_str(m["name"])}, p: {js_str(prov["name"])}, pslug: {js_str(prov["slug"])}, '
                f't: {js_str(m["tier"])}, i: {js_num(m["inputPerM"])}, o: {js_num(m["outputPerM"])}, '
                f'cached: {js_num(m.get("cachedInputPerM"))}, batch: {js_num(m.get("batchDiscount"))}, '
                f'ctx: {js_num(m.get("contextWindow"))}, lc: {js_lc(m)}, mo: {canonical_monthly(m)} }},'
            )
    lines.append("];")
    lines.append(f'const MODELS_REVIEWED = {js_str(data["_meta"].get("last_reviewed") or "")};')
    return "\n".join(lines)


def _model_dims(data: dict) -> dict:
    """Per-model skóre dimenzí DOPOČÍTANÉ z models.json dle scoring-model.json
    dimension_definitions (jeden zdroj pravdy, pokrývá celý lineup). Klíč = name
    (shoda s MODELS blokem). lowPrice řeší priceScore v JS z cost() na profilu."""
    import math
    models = [m for p in data["providers"] for m in p["models"]]
    outs = [m["outputPerM"] for m in models]
    lo_o, hi_o = math.log10(min(outs)), math.log10(max(outs))
    lo_c, hi_c = math.log10(128000), math.log10(1000000)
    tierf = {"frontier": 1.0, "mid": 0.6, "budget": 0.3}
    dims = {}
    for m in models:
        ctx = m.get("contextWindow")
        context = 0.5 if not ctx else min(1.0, max(0.3, 0.5 + 0.5 * (math.log10(ctx) - lo_c) / (hi_c - lo_c)))
        caching = (1 - m["cachedInputPerM"] / m["inputPerM"]) if m.get("cachedInputPerM") is not None else 0.0
        cheap = 0.5 if hi_o == lo_o else min(1.0, max(0.0, 1 - (math.log10(m["outputPerM"]) - lo_o) / (hi_o - lo_o)))
        batch = (1 - m["batchDiscount"]) if m.get("batchDiscount") is not None else 0.0
        dims[m["name"]] = {"context": round(context, 3), "caching": round(caching, 3),
                           "cheapOutput": round(cheap, 3), "batch": round(batch, 3),
                           "frontier": tierf[m["tier"]]}
    return dims


def render_scoring(data: dict) -> str:
    """const SCORE_W / ROLE_WEIGHTS / UC_ROLE / MODEL_SCORES pro recommendation
    engine v index.html. Váhy = editorial (scoring-model.json), dimenze = z dat."""
    sm = json.loads(SCORING.read_text(encoding="utf-8"))
    return "\n".join([
        "const SCORE_W = " + json.dumps(sm["scoreWeights"], ensure_ascii=False) + ";",
        "const ROLE_WEIGHTS = " + json.dumps(sm["roleWeights"], ensure_ascii=False) + ";",
        "const UC_ROLE = " + json.dumps(UC_ROLE, ensure_ascii=False) + ";",
        "const MODEL_SCORES = " + json.dumps(_model_dims(data), ensure_ascii=False) + ";",
    ])


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


def _baseline_until() -> str | None:
    """Datum (YYYY-MM-DD), do kterého se changelog/feed diffy ignorují — bootstrap
    éra + opravy NAŠICH dat ≠ vendor změny (vzor automation changelog-overrides)."""
    if OVERRIDES.exists():
        try:
            return json.loads(OVERRIDES.read_text(encoding="utf-8")).get("baseline_until")
        except json.JSONDecodeError:
            return None
    return None


def changelog_entries() -> tuple[list[dict], str | None]:
    hist = models_history()
    entries = []
    for (_, older), (date, newer) in zip(hist, hist[1:]):
        entries.extend(diff_models(older, newer, date))
    baseline = _baseline_until()
    if baseline:
        entries = [e for e in entries if e["d"] > baseline]
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


# ── provider stránky (CELÉ generované ze šablony — vzor vs-pages automation) ─

TEMPLATE = ROOT / "_provider-template.html"
# MailerLite formulář "LLM price alerts" (id 190087424470157211) → skupina
# price-drop-alerts-llm (id 190087503473018215, env MAILERLITE_GROUP_LLM).
# Stejná action ručně v changelog.html EMAILCAP bloku — měnit synchronně.
EMAILCAP_ACTION_LLM = "https://assets.mailerlite.com/jsonp/2426816/forms/190087424470157211/subscribe"
TIER_ORDER = {"frontier": 0, "mid": 1, "budget": 2}

# Editorial konfigurace per provider. Slugy podle hledanosti (závazné rozhodnutí):
# gemini/grok = produkt vyhrává nad providerem. Fakta v poznámkách (ceny, ratio,
# context windows) se generují z models.json — texty tady jsou jen obálky/výjimky.
PROVIDER_PAGES = {
    "openai": {"page": "openai-pricing.html", "crumb": "openai", "h1": "OpenAI API Pricing",
               "family": "GPT", "vendor": "OpenAI", "cross": "OpenAI pricing", "nav": "OpenAI", "domain": "openai.com"},
    "anthropic": {"page": "anthropic-pricing.html", "crumb": "anthropic", "h1": "Anthropic Claude API Pricing",
                  "family": "Claude", "vendor": "Anthropic", "cross": "Anthropic pricing", "nav": "Anthropic", "domain": "anthropic.com"},
    "google": {"page": "gemini-pricing.html", "crumb": "gemini", "h1": "Google Gemini API Pricing",
               "family": "Gemini", "vendor": "Google", "cross": "Gemini pricing", "nav": "Gemini", "domain": "ai.google.dev",
               "longctx": "Note the long-context surcharge: Gemini 3.1 Pro Preview bills prompts "
                          "over 200k tokens at $4 in / $18 out per 1M — the "
                          "<a href=\"index.html\">calculator</a> applies these rates automatically "
                          "once your input crosses 200k tokens."},
    "deepseek": {"page": "deepseek-pricing.html", "crumb": "deepseek", "h1": "DeepSeek API Pricing",
                 "family": "DeepSeek", "vendor": "DeepSeek", "cross": "DeepSeek pricing", "nav": "DeepSeek", "domain": "deepseek.com",
                 "cache_lead": "DeepSeek publishes the cheapest cache reads we track: "},
    "xai": {"page": "grok-pricing.html", "crumb": "grok", "h1": "xAI Grok API Pricing",
            "family": "Grok", "vendor": "xAI", "cross": "Grok pricing", "nav": "Grok", "domain": "x.ai",
            "source_phrase": "model docs",
            "cache_none": "xAI documents prompt caching but hasn't published a cached-input price "
                          "we could verify — until it does, the calculator charges Grok models the "
                          "full input rate on every token."},
    "mistral": {"page": "mistral-pricing.html", "crumb": "mistral", "h1": "Mistral AI API Pricing",
                "family": "Mistral", "vendor": "Mistral", "cross": "Mistral pricing", "nav": "Mistral", "domain": "mistral.ai"},
}


def nav_dropdown_html(data: dict, active_slug: str | None) -> str:
    """Providers dropdown (1:1 vzor automation „Pricing Guides", magenta přes
    --accent proměnné). Pořadí = pořadí providerů v models.json (= compare),
    labels bez AI/API balastu (rozhodnutí designu 2026-06-12). Stejný markup
    ručně nesou index/compare/changelog (varianta bez active) — měnit synchronně.
    Favicony lokálně z assets/icons/ (launch review: žádný third-party hotlink);
    jednorázový zdroj = google s2 favicons sz=32, při změně lineupu dostáhnout."""
    chev = ('<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>')
    btn_cls = "nav-dropdown-btn active" if active_slug else "nav-dropdown-btn"
    items = []
    for p in data["providers"]:
        c = PROVIDER_PAGES[p["slug"]]
        cls = ' class="active"' if p["slug"] == active_slug else ""
        items.append(f'        <a href="{c["page"]}"{cls}>'
                     f'<img src="assets/icons/{p["slug"]}.png" alt="">'
                     f'{c["nav"]}</a>')
    return ('<div class="nav-dropdown">\n'
            f'      <button class="{btn_cls}" type="button">Providers {chev}</button>\n'
            '      <div class="nav-dropdown-menu">\n'
            + "\n".join(items) + "\n"
            '      </div>\n'
            '    </div>')


def _join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


_NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
              7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}


def _count_word(n: int, cap: bool = False) -> str:
    """Číslovka slovem (1–12), nad rozsah fallback na číslici — provider lineup
    může mít >6 modelů (Mistral), takže pevná mapa {2..6} by spadla."""
    w = _NUM_WORDS.get(n, str(n))
    return w.capitalize() if cap else w


def _usd(v) -> str:
    """Celé dolary bez desetin ($2); zlomkové vždy aspoň 2 místa ($2.50, ne $2.5),
    sub-centová přesnost zůstává celá ($0.0028) — parita s money() v compare."""
    if v == int(v):
        return f"${int(v)}"
    txt = f"{v:.10f}".rstrip("0")
    dec = len(txt.split(".", 1)[1])
    return f"${v:.{max(2, dec)}f}"


def _fmt_mo(v: float) -> str:
    r = round(v, 2)
    if r == int(r):
        return f"${int(r):,}"
    return "$" + f"{r:,.2f}".rstrip("0").rstrip(".")


def _pct(r: float) -> str:
    p = round(r * 100, 1)
    return f"{int(p)}%" if p == int(p) else f"{p}%"


def _verified_month(data: dict) -> str:
    import datetime as _dt
    lr = data["_meta"].get("last_reviewed")
    return _dt.datetime.strptime(lr, "%Y-%m-%d").strftime("%B %Y") if lr else "June 2026"


def _intro(prov: dict, cfg: dict) -> str:
    if "intro" in cfg:
        return cfg["intro"]
    n = len(prov["models"])
    count = _count_word(n, cap=True)
    tiers = [t for t in ("frontier", "mid", "budget") if any(m["tier"] == t for m in prov["models"])]
    tier_phrase = ("all three tiers" if len(tiers) == 3
                   else f"the {tiers[0]} and {tiers[1]} tiers" if len(tiers) == 2
                   else f"the {tiers[0]} tier")
    src = cfg.get("source_phrase", "pricing page")
    return (f'Every {cfg["family"]} model we track, at official per-token rates — verified by hand '
            f'against {cfg["vendor"]}\'s {src}. {count} models across {tier_phrase}.')


def _note_cache(prov: dict, cfg: dict) -> str:
    have = [(m, m["cachedInputPerM"]) for m in prov["models"] if m.get("cachedInputPerM") is not None]
    if not have:
        return cfg["cache_none"]
    missing = [m for m in prov["models"] if m.get("cachedInputPerM") is None]
    ratios = {round(v / m["inputPerM"], 4) for m, v in have}
    if len(ratios) == 1:
        pct = _pct(next(iter(ratios)))
        if missing:
            names = _join([m["name"] for m in missing])
            verb = ("doesn't list one, so the calculator charges it" if len(missing) == 1
                    else "don't list one, so the calculator charges them")
            return (f'Cached input is billed at <b>{pct} of the input rate</b> on every '
                    f'{cfg["family"]} model with a published cache price; {names} {verb} the full '
                    f'input rate. A major lever for chatbots and agents where most of the prompt '
                    f'repeats — the <a href="index.html">calculator</a> models this with your cache share.')
        return (f'Cached input is billed at <b>{pct} of the input rate</b> across all '
                f'{cfg["family"]} models we track — a major lever for chatbots and agents where '
                f'most of the prompt repeats. The <a href="index.html">calculator</a> models this '
                f'with your cache share.')
    lead = cfg.get("cache_lead", "Cache pricing differs per model: ")
    # od nejlevnější — když lead slibuje "cheapest", musí věta začínat nejlevnějším
    parts = "; ".join(f'{m["name"]} at <b>{_usd(v)}/1M</b> ({_pct(v / m["inputPerM"])} of input)'
                      for m, v in sorted(have, key=lambda t: t[1]))
    return f'{lead}{parts}. The <a href="index.html">calculator</a> models this with your cache share.'


def _note_batch(prov: dict, cfg: dict) -> str:
    have = [m for m in prov["models"] if m.get("batchDiscount") is not None]
    if not have:
        return cfg.get("batch_none",
                       f"No verified batch discount published at our last revision — we only list "
                       f'discounts we\'ve confirmed, so the Batch toggle in the '
                       f'<a href="index.html">calculator</a> leaves {cfg["family"]} prices unchanged.')
    ds = {m["batchDiscount"] for m in have}
    scope = ("all models we track" if len(have) == len(prov["models"]) and len(have) > 1
             else _join([m["name"] for m in have]))
    if len(ds) == 1:
        pct = f"−{round((1 - next(iter(ds))) * 100)}%"
        return (f'The Batch API runs asynchronous jobs at a verified <b>{pct} on both input and '
                f'output</b> across {scope} — flip the Batch toggle in the '
                f'<a href="index.html">calculator</a> to model it.')
    return (f'Verified batch discounts apply to {scope} — flip the Batch toggle in the '
            f'<a href="index.html">calculator</a> to model them.')


def _note_ctx(prov: dict, cfg: dict) -> str:
    have = [m for m in prov["models"] if m.get("contextWindow") is not None]
    missing = [m for m in prov["models"] if m.get("contextWindow") is None]
    parts = []
    if have:
        groups: dict[int, list[str]] = {}
        for m in have:
            groups.setdefault(m["contextWindow"], []).append(m["name"])
        sizes = sorted(groups, reverse=True)
        first = groups[sizes[0]]
        s = (f'{_join(first)} {"run" if len(first) > 1 else "runs"} a verified '
             f'<b>{_fmt_ctx(sizes[0]).replace(" tokens", "-token")} context window</b>')
        for size in sizes[1:]:
            names = groups[size]
            s += f'; {_join(names)} {"are" if len(names) > 1 else "is"} {_fmt_ctx(size)}'
        parts.append(s + ".")
        if missing:
            names = _join([m["name"] for m in missing])
            parts.append(f'We haven\'t verified {"a figure" if len(missing) == 1 else "figures"} '
                         f'for {names} yet — {"it shows" if len(missing) == 1 else "they show"} '
                         f'as “—” until we do.')
    else:
        parts.append(cfg.get("ctx_none",
                             f"We haven't verified official context-window figures for the "
                             f'{cfg["family"]} line yet — they\'re listed as “—” until we do.'))
    if "longctx" in cfg:
        parts.append(cfg["longctx"])
    else:
        lc = [m["name"] for m in prov["models"] if m.get("longContextNote")]
        if lc:
            parts.append(f'{_join(lc)} bill{"s" if len(lc) == 1 else ""} higher rates on '
                         f'long-context prompts — this table and the calculator use standard rates.')
    return " ".join(parts)


EDITORIAL_WORTH_CLS = {"good": "tag-yes", "warn": "tag-warn", "bad": "tag-no"}


def load_editorial() -> dict:
    """Per-provider editorial (intro/warn/whenWorthIt/faq) z data/pricing-editorial.json;
    {} když soubor chybí. Texty se vkládají doslovně (owner-approved copy, vzor automation
    pricing-editorial.json) — fakta z models.json, ceny generuje engine."""
    if EDITORIAL.exists():
        try:
            return json.loads(EDITORIAL.read_text(encoding="utf-8")).get("providers", {})
        except json.JSONDecodeError:
            return {}
    return {}


def _ed_warn(ed: dict) -> str:
    w = ed.get("warn")
    return f'\n  <div class="warn-box"><strong>Heads up:</strong> {w}</div>' if w else ""


def _ed_when_worth(ed: dict, family: str) -> str:
    items = ed.get("whenWorthIt") or []
    if not items:
        return ""
    rows = "\n".join(
        f'        <tr><td>{i["case"]}</td>'
        f'<td class="{EDITORIAL_WORTH_CLS.get(i.get("tier"), "tag-no")}">{i["verdict"]}</td></tr>'
        for i in items)
    return (
        '\n  <div class="ed-section" data-screen-label="When worth it">\n'
        f'    <h2 class="sec-h2">When {family} is worth it</h2>\n'
        '    <div class="tbl-card"><table class="worth-table">\n'
        '      <thead><tr><th>Use case</th><th>Verdict</th></tr></thead>\n'
        f'      <tbody>\n{rows}\n      </tbody>\n'
        '    </table></div>\n  </div>')


def _ed_faq_html(ed: dict) -> str:
    faq = ed.get("faq") or []
    if not faq:
        return ""
    items = "\n".join(
        '      <div class="faq-item">\n'
        '        <button class="faq-q" aria-expanded="false" onclick="toggleFaq(this)">' + f["q"]
        + '<svg class="faq-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" '
          'stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></button>\n'
        f'        <div class="faq-a">{f["a"]}</div>\n      </div>' for f in faq)
    return (
        '\n  <div class="ed-section" data-screen-label="FAQ">\n'
        '    <h2 class="sec-h2">Frequently asked questions</h2>\n'
        f'    <div class="faq">\n{items}\n    </div>\n  </div>')


def _ed_jsonld(ed: dict, domain: str, prefix: str, canonical: str, crumb_name: str) -> str:
    blocks = []
    faq = ed.get("faq") or []
    if faq:
        faq_ld = json.dumps({
            "@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": f["q"],
                            "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq],
        }, ensure_ascii=False, indent=2)
        blocks.append(f'  <script type="application/ld+json">\n{faq_ld}\n  </script>')
    bc = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"https://{domain}/"},
            {"@type": "ListItem", "position": 2, "name": "LLM API pricing", "item": f"{prefix}/"},
            {"@type": "ListItem", "position": 3, "name": crumb_name, "item": canonical},
        ],
    }, ensure_ascii=False, indent=2)
    blocks.append(f'  <script type="application/ld+json">\n{bc}\n  </script>')
    return "\n".join(blocks)


def render_provider_page(prov: dict, cfg: dict, data: dict, site: dict, template: str,
                         editorial: dict | None = None) -> str:
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "/llm")
    month = _verified_month(data)
    total = sum(len(p["models"]) for p in data["providers"])
    n = len(prov["models"])
    ed = (editorial or {}).get(prov["slug"], {})

    mos = {m["id"]: canonical_monthly(m) for m in prov["models"]}
    best_id = min(mos, key=mos.get) if n > 1 else None
    rows = []
    for m in sorted(prov["models"], key=lambda m: (TIER_ORDER[m["tier"]], -mos[m["id"]])):
        cached = _usd(m["cachedInputPerM"]) if m.get("cachedInputPerM") is not None else "—"
        batch = (f'−{round((1 - m["batchDiscount"]) * 100)}%'
                 if m.get("batchDiscount") is not None else "—")
        best = ' class="best"' if m["id"] == best_id else ""
        rows.append(
            "        <tr>\n"
            f'          <td><span class="m-name">{m["name"]}</span>'
            f'<span class="m-tier">{m["tier"].upper()}</span></td>\n'
            f'          <td>{_usd(m["inputPerM"])}</td><td>{_usd(m["outputPerM"])}</td>'
            f'<td>{cached}</td><td>{batch}</td><td{best}>{_fmt_mo(mos[m["id"]])}</td>\n'
            "        </tr>")

    have_batch = [m for m in prov["models"] if m.get("batchDiscount") is not None]
    if have_batch and len({m["batchDiscount"] for m in have_batch}) == 1:
        pct = f"−{round((1 - have_batch[0]['batchDiscount']) * 100)}%"
        foot_batch = (f'Batch: the {pct} is {cfg["vendor"]}\'s verified Batch API discount; '
                      f'the ≈ $/mo column is computed without it.')
    elif have_batch:
        foot_batch = "Batch: verified Batch API discounts; the ≈ $/mo column is computed without them."
    else:
        foot_batch = (f'Batch: no verified batch discount published for {cfg["family"]} at our '
                      f"last revision — we only list discounts we've confirmed.")

    cross = [f'    <a href="compare.html">All {total} models →</a>']
    for p in data["providers"]:
        if p["slug"] != prov["slug"]:
            c = PROVIDER_PAGES[p["slug"]]
            cross.append(f'    <a href="{c["page"]}">{c["cross"]} →</a>')
    # long-tail SEO stránky (build_seo.py) — interní linky z nejsilněji rankujících
    # provider stránek na cheapest + alternatives téhož brandu
    cross.append(f'    <a href="{build_seo.SEO[prov["slug"]]["alt"]}.html">'
                 f'{build_seo.SEO[prov["slug"]]["brand"]} alternatives →</a>')
    cross.append('    <a href="cheapest-llm-api.html">Cheapest LLM API →</a>')
    cross.append('    <a href="changelog.html">Price changelog →</a>')

    if n == 1:
        nc_sub = (f'The calculator puts {prov["models"][0]["name"]} next to the other {total - 1} '
                  f'models we track — at your volume, token mix and cache share.')
    else:
        count = _count_word(n)
        nc_sub = (f'The calculator puts these {count} models next to the other {total - n} we '
                  f'track — at your volume, token mix and cache share.')

    names = _join([m["name"] for m in prov["models"]])
    _desc = (f'{names} — {cfg["vendor"]} API prices per 1M tokens, prompt caching and batch '
             f'discounts, verified {month}.')
    _canon = f'{_site_prefix(domain, base_path)}/{cfg["page"]}'
    tokens = {
        "TITLE": f'{cfg["h1"]} ({month}) — WizardCost',
        "DESC": _desc,
        "CANONICAL": _canon,
        "VERIFIED_MONTH": month,
        "CRUMB": cfg["crumb"],
        "H1": cfg["h1"],
        "INTRO": ed.get("intro") or _intro(prov, cfg),
        "ROWS": "\n".join(rows),
        "FOOT_BATCH": foot_batch,
        "NOTE_CACHE": _note_cache(prov, cfg),
        "NOTE_BATCH": _note_batch(prov, cfg),
        "NOTE_CTX": _note_ctx(prov, cfg),
        "NC_TITLE": f'Is {cfg["family"]} the right price for your workload?',
        "NC_SUB": nc_sub,
        "CROSS": "\n".join(cross),
        "CAPTURE_ACTION": EMAILCAP_ACTION_LLM,
        "NAV_DROPDOWN": nav_dropdown_html(data, prov["slug"]),
        "WARN": _ed_warn(ed),
        "WHEN_WORTH": _ed_when_worth(ed, cfg["family"]),
        "FAQ": _ed_faq_html(ed),
        "JSONLD": _ed_jsonld(ed, domain, _site_prefix(domain, base_path),
                             f'{_site_prefix(domain, base_path)}/{cfg["page"]}', cfg["h1"]),
        "PAGE_LD": _geo_graph_ld(domain, _canon, cfg["h1"], _desc, _iso_date(data)),
    }
    page = template
    for k, v in tokens.items():
        page = page.replace("{{" + k + "}}", v)
    if "{{" in page:
        raise SystemExit(f'CHYBA: nevyplněný token v {cfg["page"]} — zkontroluj šablonu.')
    return page


def _strip_injected(text: str) -> str:
    """Odstraní GA4/ANALYTICS bloky (vkládané až po generování) pro porovnání."""
    import re as _re
    for s, e in ((GA_START, GA_END), (AN_START, AN_END)):
        text = _re.sub(_re.escape(s) + r".*?" + _re.escape(e) + r"\n?\s*", "", text, flags=_re.S)
    return text


def build_provider_pages(data: dict, site: dict, *, check: bool) -> list[str]:
    """Vygeneruje <provider>-pricing.html CELÉ ze šablony _provider-template.html
    (nikdy needitovat ručně). V check módu vrací zastaralé soubory — porovnává
    bez GA4/analytics bloků, ty build vkládá až po generování."""
    if not TEMPLATE.exists():
        return []
    template = TEMPLATE.read_text(encoding="utf-8")
    editorial = load_editorial()
    out = []
    for prov in data["providers"]:
        cfg = PROVIDER_PAGES.get(prov["slug"])
        if cfg is None:
            raise SystemExit(f'CHYBA: provider {prov["slug"]} nemá záznam v PROVIDER_PAGES.')
        rendered = render_provider_page(prov, cfg, data, site, template, editorial)
        target = ROOT / cfg["page"]
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        dirty = existing is None or _strip_injected(existing) != rendered
        if check and dirty:
            out.append(cfg["page"])
        elif not check and dirty:
            target.write_text(rendered, encoding="utf-8")
            out.append(cfg["page"])
    return out


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
        lastmod = __import__("datetime").date.fromtimestamp(p.stat().st_mtime).isoformat()
        urls.append(f"  <url><loc>{loc}</loc><lastmod>{lastmod}</lastmod></url>")
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


# ---------------------------------------------------------------------------
# LLM price-history stránka: data/price-history.json (kurátorováno z Wayback
# verdiktů + veřejných oznámení) → llm/price-history.html. CELÉ generované,
# server-side (crawlovatelné + AI-citovatelné). CONFIRMED-only; gapy přiznané.
# Vzor: automation/build.py render_price_history / build_price_history.
# ---------------------------------------------------------------------------

_LLM_PH_CSS = """
    .ph-lead { color: var(--text2); font-size: 1.06rem; max-width: 700px; margin: 14px auto 4px; }
    .ph-tldr { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 22px; margin: 22px 0; }
    .ph-tldr ul { margin: 8px 0 0; padding-left: 20px; }
    .ph-tldr li { margin: 5px 0; color: var(--text2); }
    .ph-tool { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px; margin-bottom: 18px; }
    .ph-tool-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
    .ph-tool-head img { width: 30px; height: 30px; border-radius: 7px; background: #fff; padding: 2px; }
    .ph-tool-head h3 { font-size: 1.22rem; }
    .ph-headline { color: var(--accent-br); font-size: 0.85rem; font-weight: 600; display: block; }
    .ph-meta { margin-left: auto; font-family: var(--mono); font-size: 11px; color: var(--muted); }
    .ph-stable { border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 12px 0; margin-bottom: 16px; }
    .ph-row { display: flex; align-items: baseline; gap: 10px; padding: 3px 0; flex-wrap: wrap; }
    .ph-plan { font-weight: 700; min-width: 140px; }
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
    .section { margin: 44px 0 0; }
    .section-label { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.14em; margin-bottom: 8px; }
    .section h2 { font-size: 1.5rem; font-weight: 800; margin-bottom: 8px; }
    .section-sub { color: var(--text2); font-size: 14.5px; margin-bottom: 20px; max-width: 620px; }
    .tbl-note { font-family: var(--mono); font-size: 11.5px; color: var(--muted); margin-top: 10px; line-height: 1.7; }
    .xlinks { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }
    .xlink { font-family: var(--mono); font-size: 12.5px; background: var(--surface); border: 1px solid var(--border); border-radius: 99px; padding: 8px 16px; color: var(--text2); transition: border-color 0.15s, color 0.15s; text-decoration: none; }
    .xlink:hover { border-color: var(--accent); color: var(--text); }
    .finder-cta { background: linear-gradient(160deg, rgba(217,123,251,0.10), var(--surface) 65%); border: 1px solid rgba(217,123,251,0.35); border-radius: var(--radius); padding: 28px 32px; margin: 52px 0 64px; display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
    .finder-cta-text { flex: 1 1 320px; }
    .finder-cta h2 { font-size: 1.35rem; font-weight: 800; margin-bottom: 6px; }
    .finder-cta p { color: var(--text2); font-size: 14px; line-height: 1.6; }
    .btn-primary-lg { background: var(--accent); color: var(--ink); border-radius: var(--radius-sm); padding: 14px 26px; font-family: var(--font); font-size: 15px; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; gap: 9px; box-shadow: 0 0 0 1px rgba(217,123,251,0.4), 0 10px 30px rgba(217,123,251,0.28); transition: transform 0.15s, box-shadow 0.15s; white-space: nowrap; }
    .btn-primary-lg:hover { transform: translateY(-1px); color: var(--ink); }
"""

_LLM_PH_KIND = {
    "change": ("Real change", "ph-k-change"),
    "product": ("New product", "ph-k-product"),
    "packaging": ("Repackaging", "ph-k-pack"),
    "artifact": ("Display only", "ph-k-artifact"),
}


def _llm_ph_html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _llm_ph_kind_badge(kind: str) -> str:
    label, cls = _LLM_PH_KIND.get(kind, (kind, "ph-k-artifact"))
    return f'<span class="ph-kind {cls}">{label}</span>'


def _llm_ph_logo(slug: str) -> str:
    domain = {
        "openai": "openai.com",
        "anthropic": "anthropic.com",
        "google": "ai.google.dev",
        "deepseek": "deepseek.com",
        "xai": "x.ai",
        "mistral": "mistral.ai",
    }.get(slug, f"{slug}.com")
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=32"


def _llm_ph_tool_card(t: dict) -> str:
    stable = "\n".join(
        f'<div class="ph-row"><span class="ph-plan">{_llm_ph_html_escape(p["plan"])}</span>'
        f'<span class="ph-price">{_llm_ph_html_escape(p["price"])}</span>'
        f'<span class="ph-detail">{_llm_ph_html_escape(p["detail"])} · stable since {_llm_ph_html_escape(p["since"])}</span></div>'
        for p in t.get("stable", []))
    events = []
    for e in t.get("events", []):
        links = " ".join(
            f'<a href="{u}" target="_blank" rel="noopener nofollow">archive {i + 1} ↗</a>'
            for i, u in enumerate(e.get("evidence", [])))
        links = f'<div class="ph-evidence">{links}</div>' if links else ""
        events.append(
            '<div class="ph-event">'
            f'<div class="ph-event-head"><span class="ph-date">{_llm_ph_html_escape(e["date"])}</span>{_llm_ph_kind_badge(e["kind"])}</div>'
            f'<div class="ph-event-title">{_llm_ph_html_escape(e["title"])}</div>'
            f'<p class="ph-event-detail">{_llm_ph_html_escape(e["detail"])}</p>{links}</div>')
    events_html = "\n".join(events) if events else '<p class="ph-none">No price events recorded in this window.</p>'
    gaps = "\n".join(
        f'<div class="ph-gap">Coverage gap {_llm_ph_html_escape(g["from"])} to {_llm_ph_html_escape(g["to"])}: {_llm_ph_html_escape(g["reason"])}</div>'
        for g in t.get("gaps", []))
    oq = (f'<div class="ph-gap">Open question — {_llm_ph_html_escape(t["open_question"])}</div>'
          if t.get("open_question") else "")
    logo = _llm_ph_logo(t["slug"])
    return (
        f'<div class="ph-tool" id="ph-{t["slug"]}">\n'
        f'      <div class="ph-tool-head"><img src="{logo}" alt="{t["name"]} logo" loading="lazy">'
        f'<div><h3>{t["name"]}</h3><span class="ph-headline">{_llm_ph_html_escape(t["headline"])}</span></div>'
        f'<span class="ph-meta">{t["snapshots"]} archived snapshots · {_llm_ph_html_escape(t["range_from"])} to {_llm_ph_html_escape(t["range_to"])}</span></div>\n'
        f'      <div class="ph-stable">{stable}</div>\n'
        f'      <div class="ph-events">{events_html}</div>\n'
        f'      {gaps}{oq}\n    </div>')


def render_llm_price_history(data: dict, site: dict) -> str:
    meta = data.get("_meta", {})
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "/llm")
    prefix = _site_prefix(domain, base_path)
    canonical = f"{prefix}/price-history.html"
    updated = meta.get("updated", "2026-06-20")
    window = f'{meta.get("window_from", "2024-01")} – {meta.get("window_to", "2026-06")}'

    tool_cards = "\n    ".join(_llm_ph_tool_card(t) for t in data.get("tools", []))

    title = "LLM API Pricing History 2024–2026: What Actually Changed | WizardCost"
    desc = ("Two years of OpenAI, Anthropic, Gemini and DeepSeek API pricing. "
            "Major cuts documented — every confirmed event linked to dated evidence.")

    article_ld = json.dumps({
        "@context": "https://schema.org", "@type": "Article",
        "headline": "LLM API pricing history (2024–2026)",
        "description": desc,
        "datePublished": "2026-06-20", "dateModified": updated,
        "author": {"@type": "Organization", "name": "WizardCost"},
        "publisher": {"@type": "Organization", "name": "WizardCost"},
        "mainEntityOfPage": canonical,
    }, ensure_ascii=False, indent=2)
    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"https://{domain}/"},
            {"@type": "ListItem", "position": 2, "name": "LLM Pricing", "item": f"{prefix}/"},
            {"@type": "ListItem", "position": 3, "name": "Pricing history", "item": canonical},
        ],
    }, ensure_ascii=False, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno llm/build.py z data/price-history.json — needituj ručně -->
  <title>{title}</title>
  <meta name="description" content="{_llm_ph_html_escape(desc)}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="WizardCost">
  <meta property="og:title" content="LLM API Pricing History 2024–2026">
  <meta property="og:description" content="{_llm_ph_html_escape(desc)}">
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
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #0a0e17; --surface: #111827; --surface2: #1a2236;
      --border: #1f2d45; --text: #e8edf5; --muted: #6b7a99;
      --accent: #d97bfb; --accent-br: #e98bff; --accent-dim: rgba(217,123,251,0.09); --accent-glow: rgba(217,123,251,0.20); --ink: #1a0524; --link: #6f9bff; --border2: #27375a; --text2: #a8b4cc;
      --green: #10b981; --yellow: #f59e0b; --red: #ef4444; --radius: 14px; --radius-sm: 9px;
      --font: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; --display: 'Hanken Grotesk', 'Plus Jakarta Sans', sans-serif; --mono: 'JetBrains Mono', ui-monospace, monospace;
    }}
    body {{
      background: var(--bg);
      background-image: radial-gradient(ellipse 70% 50% at 50% -8%, rgba(217,123,251,0.20), transparent 60%), radial-gradient(ellipse 60% 50% at 100% 0%, rgba(217,123,251,0.08), transparent 50%);
      background-repeat: no-repeat; background-attachment: fixed;
      color: var(--text); font-family: var(--font); font-size: 15.5px; line-height: 1.7; letter-spacing: 0.01em; min-height: 100vh; -webkit-font-smoothing: antialiased;
      padding-top: 100px;
    }}
    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ color: #9fbcff; }}
    h1, h2, h3 {{ font-family: var(--display); letter-spacing: -0.02em; text-wrap: balance; }}
    header {{ position: fixed; top: 0; left: 0; right: 0; z-index: 100; background: rgba(10,14,23,0.86); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border-bottom: 1px solid var(--border); }}
    .nav-top {{ padding: 0 32px; height: 56px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }}
    .nav-bottom {{ border-bottom: 2px solid var(--border); padding: 0 32px; display: flex; gap: 0; overflow-x: auto; scrollbar-width: none; }}
    .nav-bottom::-webkit-scrollbar {{ display: none; }}
    .nav-bottom a {{ padding: 12px 20px; font-size: 14px; color: var(--muted); text-decoration: none; white-space: nowrap; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: color 0.15s, border-color 0.15s; flex-shrink: 0; }}
    .nav-bottom a:hover {{ color: var(--text); }}
    .nav-bottom a.active {{ color: var(--text); font-weight: 700; border-bottom-color: var(--accent); }}
    .logo {{ display: flex; align-items: center; gap: 0; font-family: var(--display); font-weight: 800; font-size: 1.08rem; color: var(--text); letter-spacing: -0.01em; text-decoration: none; white-space: nowrap; }}
    .logo span {{ color: var(--accent); }}
    .logo .io {{ color: var(--muted); font-weight: 600; }}
    .logo-icon {{ width: 28px; height: 28px; flex-shrink: 0; margin-right: 9px; }}
    .nav-badge {{ font-family: var(--mono); font-size: 11px; background: var(--surface2); border: 1px solid var(--border2); border-radius: 20px; padding: 4px 12px; color: var(--muted); display: flex; align-items: center; gap: 7px; letter-spacing: 0.01em; }}
    .nav-badge::before {{ content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 7px var(--accent); }}
    .nav-dropdown {{ position: relative; display: flex; align-items: center; }}
    .nav-dropdown-btn {{ background: none; border: none; cursor: pointer; color: var(--muted); font-family: var(--font); font-size: 14px; padding: 12px 20px; display: flex; align-items: center; gap: 5px; white-space: nowrap; transition: color 0.15s, border-color 0.15s; margin-bottom: -2px; border-bottom: 2px solid transparent; }}
    .nav-dropdown-btn:hover, .nav-dropdown.open .nav-dropdown-btn {{ color: var(--text); }}
    .nav-dropdown-menu {{ display: none; position: fixed; background: var(--surface); border: 1px solid var(--border2); border-radius: var(--radius); min-width: 214px; z-index: 200; box-shadow: 0 16px 40px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.03); padding: 6px 0; }}
    .nav-dropdown.open .nav-dropdown-menu {{ display: block; }}
    .nav-dropdown-menu a {{ display: flex; align-items: center; gap: 10px; padding: 10px 16px; margin-bottom: 0; font-size: 13px; font-weight: 600; color: var(--text2); transition: background 0.1s, color 0.1s; border-bottom: none !important; }}
    .nav-dropdown-menu a:hover {{ background: var(--surface2); color: var(--text); text-decoration: none; }}
    .nav-dropdown-menu img {{ width: 16px; height: 16px; border-radius: 3px; background: #fff; padding: 1px; }}
    .wrap {{ max-width: 880px; margin: 0 auto; padding: 0 32px; }}
    .hero {{ padding: 64px 0 40px; }}
    .hero-badge {{ display: inline-flex; align-items: center; gap: 8px; background: var(--surface2); border: 1px solid var(--border2); border-radius: 100px; font-family: var(--mono); font-size: 11.5px; color: var(--text2); padding: 6px 15px; margin-bottom: 22px; letter-spacing: 0.02em; }}
    .hero h1 {{ font-size: clamp(2rem, 4vw, 3rem); font-weight: 800; line-height: 1.1; letter-spacing: -0.02em; margin-bottom: 16px; }}
    .hero h1 em {{ font-style: normal; color: var(--accent); }}
    .hero p {{ color: var(--text2); font-size: 1.08rem; max-width: 640px; line-height: 1.7; text-wrap: pretty; }}
    footer {{ border-top: 1px solid var(--border); padding: 40px 24px; text-align: center; font-family: var(--display); font-size: 12.5px; color: var(--muted); line-height: 1.85; margin-top: 24px; }}
    footer a {{ color: var(--muted); }}
    @media (max-width: 760px) {{
      .wrap {{ padding-left: 18px; padding-right: 18px; }}
      .nav-top {{ padding-left: 18px; padding-right: 18px; }}
      .nav-bottom {{ padding-left: 18px; padding-right: 18px; }}
      .nav-bottom a {{ padding: 13px 14px; }}
    }}
    @media (max-width: 620px) {{
      .nav-badge {{ display: none; }}
    }}
    @media (max-width: 520px) {{
      .finder-cta {{ flex-direction: column; align-items: stretch; text-align: left; }}
      .btn-primary-lg {{ justify-content: center; }}
    }}
{_LLM_PH_CSS}
  </style>
</head>
<body>

<header>
  <div class="nav-top">
    <a href="/" class="logo">
      <svg class="logo-icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs><linearGradient id="llmk" x1="14" y1="10" x2="30" y2="38" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#e98bff"></stop><stop offset="1" stop-color="#c44dff"></stop></linearGradient></defs>
        <path d="M28.5 10.5 L13.5 24 L28.5 37.5" stroke="url(#llmk)" stroke-width="6.8" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M 36.5 17.8 Q 37.864 22.636 42.7 24 Q 37.864 25.364 36.5 30.2 Q 35.136 25.364 30.3 24 Q 35.136 22.636 36.5 17.8 Z" fill="#fbeeff"></path>
      </svg>
      LLM<span>Cost</span><span class="io" style="font-size:0.72em; margin-left:7px;">by WizardCost</span>
    </a>
    <span class="nav-badge">LLM API pricing · verified June 2026</span>
  </div>
  <nav class="nav-bottom">
    <a href="./">Calculator</a>
    <a href="compare.html">Compare models</a>
    <div class="nav-dropdown">
      <button class="nav-dropdown-btn" type="button">Providers <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></button>
      <div class="nav-dropdown-menu">
        <a href="openai-pricing.html"><img src="assets/icons/openai.png" alt="">OpenAI</a>
        <a href="anthropic-pricing.html"><img src="assets/icons/anthropic.png" alt="">Anthropic</a>
        <a href="gemini-pricing.html"><img src="assets/icons/gemini.png" alt="">Gemini</a>
        <a href="deepseek-pricing.html"><img src="assets/icons/deepseek.png" alt="">DeepSeek</a>
        <a href="grok-pricing.html"><img src="assets/icons/grok.png" alt="">Grok</a>
        <a href="mistral-pricing.html"><img src="assets/icons/mistral.png" alt="">Mistral</a>
      </div>
    </div>
    <a href="changelog.html">Changelog</a>
    <a href="price-history.html" class="active">Price history</a>
  </nav>
</header>

<div class="wrap">

  <div class="hero" data-screen-label="Price history hero">
    <div class="hero-badge">2-year price history · Web Archive evidence · updated {updated}</div>
    <h1>LLM API pricing — <em>what actually changed, {window}</em></h1>
    <p class="ph-lead">{_llm_ph_html_escape(meta.get("thesis", ""))}</p>
  </div>

  <div class="section" data-screen-label="Summary">
    <div class="ph-tldr">
      <strong>The short version</strong>
      <ul>
        <li><b>OpenAI</b> — GPT-4 launched at $30/$60 per 1M tokens (2023); GPT-4o (2024) cut that to $5/$15; current lineup now starts at $0.20/$1.25 (GPT-5.4 nano).</li>
        <li><b>Anthropic</b> — Claude 3 Haiku ($0.25/$1.25 per 1M) set a cheap-tier anchor in 2024; current Haiku 4.5 is $1/$5 but far more capable.</li>
        <li><b>Google (Gemini)</b> — Flash tier consistently cheapest among frontier providers; Gemini 2.0 Flash shipped free in preview (Dec 2024) before paid pricing.</li>
        <li><b>DeepSeek</b> — R1/V3 launch (Jan 2025) disrupted the market: GPT-4-class quality at 10–30x lower prices than Western competitors.</li>
      </ul>
    </div>
  </div>

  <div class="section" data-screen-label="Per-provider timeline">
    <div class="section-label">The receipts</div>
    <h2>Two years of pricing, provider by provider</h2>
    <p class="section-sub">Each entry links to a dated Web Archive snapshot where available. Product launches and packaging changes are labelled as such — only genuine price moves are marked <span class="ph-kind ph-k-change">Real change</span>. Note: evidence URLs need owner verification before merge.</p>
    {tool_cards}
  </div>

  <div class="section" data-screen-label="Methodology">
    <div class="section-label">How we know</div>
    <h2>Method &amp; honest caveats</h2>
    <p class="section-sub">{_llm_ph_html_escape(meta.get("method", ""))}</p>
    <p class="tbl-note">Some events lack Wayback evidence links (marked in the data) — these are from widely-reported public announcements. From here on, our <a href="changelog.html">live price changelog</a> records changes as they happen, sourced from official pricing pages.</p>
  </div>

  <div class="finder-cta" data-screen-label="CTA">
    <div class="finder-cta-text">
      <h2>Prices changed a lot — check today's best value.</h2>
      <p>The calculator uses current verified prices across all 28 models.</p>
    </div>
    <a href="compare.html" class="btn-primary-lg">Compare all models →</a>
  </div>

  <div class="section" data-screen-label="Related pages">
    <div class="section-label">Keep digging</div>
    <div class="xlinks">
      <a class="xlink" href="changelog.html">Live price changelog →</a>
      <a class="xlink" href="compare.html">Compare all models →</a>
      <a class="xlink" href="./">Pricing calculator →</a>
    </div>
  </div>

</div>

<footer>
  WizardCost LLM Pricing History · Web Archive evidence · updated {updated} · <a href="/automation/privacy.html">Privacy</a> · <a href="/automation/terms.html">Terms</a>
</footer>

<script>
(function () {{
  var dd = document.querySelector(".nav-dropdown");
  if (!dd) return;
  dd.querySelector(".nav-dropdown-btn").addEventListener("click", function (e) {{
    e.stopPropagation();
    var r = this.getBoundingClientRect(), m = dd.querySelector(".nav-dropdown-menu");
    m.style.left = Math.max(8, Math.min(r.left, window.innerWidth - 224)) + "px";
    m.style.top = (r.bottom + 8) + "px";
    dd.classList.toggle("open");
  }});
  document.addEventListener("click", function () {{ dd.classList.remove("open"); }});
}})();
</script>
</body>
</html>
"""


def build_llm_price_history(site: dict, *, check: bool) -> list[str]:
    """Vygeneruje llm/price-history.html z data/price-history.json.
    V check módu vrací seznam zastaralých souborů (porovnává bez GA4/analytics bloků)."""
    if not PRICE_HISTORY.exists():
        return []
    data = json.loads(PRICE_HISTORY.read_text(encoding="utf-8"))
    if not data.get("tools"):
        return []
    target = ROOT / "price-history.html"
    rendered = render_llm_price_history(data, site)
    existing = target.read_text(encoding="utf-8") if target.exists() else None
    dirty = existing is None or _strip_injected(existing) != rendered
    if not dirty:
        return []
    if not check:
        target.write_text(rendered, encoding="utf-8")
    return [target.name]


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
    # scoring blok (recommendation engine) — jen index.html
    idx = ROOT / "index.html"
    if idx.exists() and SCORING.exists() and SC_START in idx.read_text(encoding="utf-8"):
        clog_jobs.append((idx, render_scoring(data), SC_START, SC_END, SC_WARN))

    # GEO:LD graf do <head> /llm/ stránek BEZ vlastního WebSite/Org (compare, changelog).
    # index.html má WebApplication → ponechán (žádný duplicitní WebSite node).
    _geo_iso = _iso_date(data)
    _geo_domain = site.get("domain", "wizardcost.com")
    geo_jobs = []
    for _sp in ("compare.html", "changelog.html"):
        _spp = ROOT / _sp
        if _spp.exists() and GEO_LD_START in _spp.read_text(encoding="utf-8"):
            _blk = _static_geo_ld(_spp.read_text(encoding="utf-8"), _geo_domain, _geo_iso)
            if _blk:
                geo_jobs.append((_spp, _blk, GEO_LD_START, GEO_LD_END, GEO_LD_WARN))

    if args.check:
        dirty = [p.name for p in targets
                 if render_block(p.read_text(encoding="utf-8"), generated, START, END, WARN)
                 != p.read_text(encoding="utf-8")]
        dirty += [p.name for p, gen, s, e, w in clog_jobs
                  if render_block(p.read_text(encoding="utf-8"), gen, s, e, w)
                  != p.read_text(encoding="utf-8")]
        dirty += [p.name for p, gen, s, e, w in geo_jobs
                  if render_block(p.read_text(encoding="utf-8"), gen, s, e, w)
                  != p.read_text(encoding="utf-8")]
        dirty += build_provider_pages(data, site, check=True)
        dirty += build_seo.build_seo_pages(data, site, sys.modules[__name__], check=True)
        dirty += build_llm_price_history(site, check=True)
        if dirty:
            print(f"[llm build --check] OUT OF DATE: {', '.join(dirty)} — spusť `python llm/build.py`.")
            return 1
        print("[llm build --check] OK — stránky jsou aktuální vůči data/models.json.")
        return 0

    changed = [p.name for p in targets if inject(p, generated)]
    for p, gen, s, e, w in clog_jobs + geo_jobs:
        text = p.read_text(encoding="utf-8")
        new_text = render_block(text, gen, s, e, w)
        if new_text != text:
            p.write_text(new_text, encoding="utf-8")
            changed.append(p.name)
    changed += build_feeds(site.get("domain", "wizardcost.com"),
                           site.get("base_path", "/llm"), clog_entries)
    changed += build_provider_pages(data, site, check=False)
    changed += build_seo.build_seo_pages(data, site, sys.modules[__name__], check=False)
    changed += build_llm_price_history(site, check=False)

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
