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


def js_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def js_num(v) -> str:
    return "null" if v is None else str(v)


# Kanonický scénář pro ≈$/mo sloupec compare (MUSÍ sedět s USE_CASES chatbot
# defaulty v index.html a footnote textem na compare — měnit synchronně!).
# Paritu Python↔JS hlídá calc-test/test-llm-engine.js.
CANON = {"req": 100000, "in_tok": 2000, "out_tok": 300, "cache": 0.70}


def canonical_monthly(m: dict) -> float:
    """Python port cost() z index.html pro kanonický scénář (bez batch)."""
    c = CANON["cache"]
    cached = m.get("cachedInputPerM")
    in_rate = m["inputPerM"] * (1 - c) + cached * c if cached is not None else m["inputPerM"]
    in_cost = CANON["req"] * CANON["in_tok"] / 1e6 * in_rate
    out_cost = CANON["req"] * CANON["out_tok"] / 1e6 * m["outputPerM"]
    return round(in_cost + out_cost, 4)


def render_models(data: dict) -> str:
    """const MODELS pro index.html + compare.html. Pole per model:
    n (name), p (provider name), pslug, t (tier), i/o (USD za 1M in/out),
    cached (USD za 1M cached input; null = bez cache), batch (násobitel; null),
    ctx (context window v tokenech; null), mo (kanonický ≈$/mo — viz CANON)."""
    lines = ["const MODELS = ["]
    for prov in data["providers"]:
        for m in prov["models"]:
            lines.append(
                "  { "
                f'n: {js_str(m["name"])}, p: {js_str(prov["name"])}, pslug: {js_str(prov["slug"])}, '
                f't: {js_str(m["tier"])}, i: {js_num(m["inputPerM"])}, o: {js_num(m["outputPerM"])}, '
                f'cached: {js_num(m.get("cachedInputPerM"))}, batch: {js_num(m.get("batchDiscount"))}, '
                f'ctx: {js_num(m.get("contextWindow"))}, mo: {canonical_monthly(m)} }},'
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
                          "over 200k tokens at $4 in / $18 out per 1M — the calculator prices "
                          "all prompts at the base rate."},
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
        '        <button class="faq-q" onclick="toggleFaq(this)">' + f["q"]
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
    tokens = {
        "TITLE": f'{cfg["h1"]} ({month}) — WizardCost',
        "DESC": (f'{names} — {cfg["vendor"]} API prices per 1M tokens, prompt caching and batch '
                 f'discounts, verified {month}.'),
        "CANONICAL": f'{_site_prefix(domain, base_path)}/{cfg["page"]}',
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
    # scoring blok (recommendation engine) — jen index.html
    idx = ROOT / "index.html"
    if idx.exists() and SCORING.exists() and SC_START in idx.read_text(encoding="utf-8"):
        clog_jobs.append((idx, render_scoring(data), SC_START, SC_END, SC_WARN))

    if args.check:
        dirty = [p.name for p in targets
                 if render_block(p.read_text(encoding="utf-8"), generated, START, END, WARN)
                 != p.read_text(encoding="utf-8")]
        dirty += [p.name for p, gen, s, e, w in clog_jobs
                  if render_block(p.read_text(encoding="utf-8"), gen, s, e, w)
                  != p.read_text(encoding="utf-8")]
        dirty += build_provider_pages(data, site, check=True)
        dirty += build_seo.build_seo_pages(data, site, sys.modules[__name__], check=True)
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
    changed += build_provider_pages(data, site, check=False)
    changed += build_seo.build_seo_pages(data, site, sys.modules[__name__], check=False)

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
