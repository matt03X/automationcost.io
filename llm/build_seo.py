#!/usr/bin/env python3
"""llm/build_seo.py — programmatic long-tail SEO stránky /llm/ subsite.

Zrcadlo automation/build_pricing.py `build_seo_pages`: data-driven, ceny VŽDY
z enginu (canonical_monthly z build.py — kanonický chatbot scénář 100k/2000/300/70 %),
řazení podle objektivního ≈$/mo (fair-competition neutral, žádné „X× levnější"
/zlehčování). Generuje CELÉ stránky, nikdy needitovat ručně:

    cheapest-llm-api.html        — všech N modelů řazených dle ≈$/mo (1×)
    <brand>-alternatives.html    — alternativy k providerovi, řazené dle ≈$/mo (6×)
    <a>-vs-<b>.html              — provider head-to-head (15×, všechny dvojice)

Volá build.py main():  build_seo_pages(data, site, <build-module>, check=...)
— build-module = sám build.py (předán kvůli sdíleným helperům canonical_monthly,
PROVIDER_PAGES, nav_dropdown_html, _verified_month, _usd, _fmt_mo, _fmt_ctx,
_join, _site_prefix, _strip_injected). NEimportujeme build přímo (build.py je
__main__ a sám importuje tento modul → bránilo by to cyklickému importu).

Shell (CSS / nav header / footer / dropdown JS) se extrahuje z
_provider-template.html → vizuální identita zůstává 1:1 s provider stránkami.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "_provider-template.html"

# Brandové slugy podle hledanosti (rozhodnutí jako u provider stránek:
# produkt vyhrává nad providerem — „claude alternatives" > „anthropic alternatives",
# „grok"/„gemini" jsou produkty). alt = slug stránky alternatives, vs = člen
# vs-slugu. brand = label v copy/H1 (sjednoceno napříč všemi stránkami).
SEO = {
    "openai":    {"brand": "OpenAI",   "alt": "openai-alternatives",    "vs": "openai"},
    "anthropic": {"brand": "Claude",   "alt": "claude-alternatives",    "vs": "claude"},
    "google":    {"brand": "Gemini",   "alt": "gemini-alternatives",    "vs": "gemini"},
    "deepseek":  {"brand": "DeepSeek", "alt": "deepseek-alternatives",  "vs": "deepseek"},
    "xai":       {"brand": "Grok",     "alt": "grok-alternatives",      "vs": "grok"},
    "mistral":   {"brand": "Mistral",  "alt": "mistral-alternatives",   "vs": "mistral"},
}
# Pevné pořadí = pořadí v models.json; určuje směr vs-slugu (a-vs-b, a před b).
PROVIDER_ORDER = ["openai", "anthropic", "google", "deepseek", "xai", "mistral"]

TIER_LABEL = {"frontier": "frontier (flagship-class)", "mid": "mid", "budget": "budget"}


# ── shell z _provider-template.html (CSS/nav/footer/dropdown JS) ─────────────

_EXTRA_CSS = """
    .page-head p strong { color: var(--text); }
    .section { margin-top: 40px; }
    .section h2 { font-family: var(--display); font-size: 1.4rem; font-weight: 800; letter-spacing: -0.02em; }
    .section p.sub { color: var(--muted); font-size: 13.5px; margin-top: 6px; max-width: 700px; line-height: 1.55; }
    .tbl-card td a { color: var(--link); }
    .tbl-card td a:hover { color: var(--accent-br); }
    .m-sub { display: block; font-family: var(--font); font-size: 11.5px; color: var(--muted); font-weight: 500; margin-top: 2px; }
    tr.cheapest td { background: var(--accent-dim); }
    .verdict { background: linear-gradient(160deg, rgba(217,123,251,0.12), var(--surface) 60%); border: 1px solid rgba(217,123,251,0.35); border-radius: var(--radius); padding: 20px 24px; margin-top: 24px; }
    .verdict h2 { font-family: var(--display); font-size: 1.15rem; font-weight: 800; margin-bottom: 6px; }
    .verdict p { color: var(--text2); font-size: 14px; line-height: 1.65; }
    .verdict p + p { margin-top: 8px; }
    .verdict b { color: var(--text); }
    .faq { margin-top: 10px; }
    .faq-item { border-bottom: 1px solid var(--border); }
    .faq-q { width: 100%; background: none; border: 0; color: var(--text); font-family: var(--font); font-size: 15px; font-weight: 700; text-align: left; padding: 16px 0; cursor: pointer; display: flex; justify-content: space-between; align-items: center; gap: 16px; }
    .faq-q:hover { color: var(--accent-br); }
    .faq-chevron { flex-shrink: 0; transition: transform 0.2s; color: var(--muted); }
    .faq-item.open .faq-chevron { transform: rotate(180deg); }
    .faq-a { display: none; color: var(--text2); font-size: 14px; line-height: 1.7; padding-bottom: 16px; }
    .faq-item.open .faq-a { display: block; }
    .faq-a a { color: var(--link); text-decoration: underline; }
"""


def _tpl_parts() -> tuple[str, str, str, str]:
    """(css, header_tpl, footer_tpl, dropdown_js) vyseknuté z provider šablony —
    jediný zdroj vizuálu, SEO stránky tak nikdy nedriftnou od provider stránek."""
    tpl = TEMPLATE.read_text(encoding="utf-8")
    css = tpl.split("<style>", 1)[1].split("</style>", 1)[0] + _EXTRA_CSS
    header = "<header>" + tpl.split("<header>", 1)[1].split("</header>", 1)[0] + "</header>"
    footer = "<footer>" + tpl.split("<footer>", 1)[1].split("</footer>", 1)[0] + "</footer>"
    scripts = re.findall(r"<script>.*?</script>", tpl, re.S)
    dropdown_js = next(s for s in scripts if "nav-dropdown" in s)
    return css, header, footer, dropdown_js


def _faq_html(faq: list[dict]) -> str:
    return "\n".join(
        '      <div class="faq-item">\n'
        '        <button class="faq-q" onclick="toggleFaq(this)">' + f["q"]
        + '<svg class="faq-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" '
          'stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></button>\n'
        f'        <div class="faq-a">{f["a"]}</div>\n      </div>' for f in faq)


def _faq_ld(faq: list[dict]) -> str:
    return json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": f["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq],
    }, ensure_ascii=False, indent=2)


def _breadcrumb_ld(domain: str, prefix: str, leaf: str, canonical: str) -> str:
    return json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": f"https://{domain}/"},
            {"@type": "ListItem", "position": 2, "name": "LLM API pricing", "item": f"{prefix}/"},
            {"@type": "ListItem", "position": 3, "name": leaf, "item": canonical},
        ],
    }, ensure_ascii=False, indent=2)


def _shell(parts: tuple, *, title: str, desc: str, canonical: str, prefix: str,
           crumb: str, h1: str, lead: str, month: str, body: str, faq: list[dict],
           nav: str) -> str:
    css, header, footer, dropdown_js = parts
    header = header.replace("{{NAV_DROPDOWN}}", nav).replace("{{VERIFIED_MONTH}}", month)
    footer = footer.replace("{{VERIFIED_MONTH}}", month)
    domain = canonical.split("/llm/", 1)[0].replace("https://", "")
    repl = {
        "%%TITLE%%": title, "%%DESC%%": desc, "%%CANONICAL%%": canonical,
        "%%OGIMG%%": f"{prefix}/og-image.png", "%%FAQLD%%": _faq_ld(faq),
        "%%BCLD%%": _breadcrumb_ld(domain, prefix, crumb.split(" / ")[-1], canonical),
        "%%CSS%%": css, "%%HEADER%%": header, "%%FOOTER%%": footer,
        "%%DROPDOWNJS%%": dropdown_js, "%%CRUMB%%": crumb, "%%H1%%": h1,
        "%%LEAD%%": lead, "%%VERIFIED%%": month, "%%BODY%%": body,
        "%%FAQHTML%%": _faq_html(faq),
    }
    page = _SHELL
    for k, v in repl.items():
        page = page.replace(k, v)
    return page


_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build_seo.py z data/models.json — needituj ručně -->
  <title>%%TITLE%%</title>
  <meta name="description" content="%%DESC%%">
  <link rel="canonical" href="%%CANONICAL%%">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="WizardCost">
  <meta property="og:title" content="%%TITLE%%">
  <meta property="og:description" content="%%DESC%%">
  <meta property="og:url" content="%%CANONICAL%%">
  <meta property="og:image" content="%%OGIMG%%">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="%%OGIMG%%">
  <script type="application/ld+json">
%%FAQLD%%
  </script>
  <script type="application/ld+json">
%%BCLD%%
  </script>
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
%%CSS%%
  </style>
</head>
<body>

%%HEADER%%

<section class="page-head wrap">
  <div class="crumb">%%CRUMB%%</div>
  <h1>%%H1%%</h1>
  <p>%%LEAD%%</p>
  <div class="verify-line">Prices verified %%VERIFIED%% · changes logged in the <a href="changelog.html">changelog</a></div>
</section>

%%BODY%%

<section class="wrap">
  <div class="section">
    <h2>Frequently asked questions</h2>
    <div class="faq">
%%FAQHTML%%
    </div>
  </div>
</section>

%%FOOTER%%

%%DROPDOWNJS%%
<script>function toggleFaq(el){el.closest(".faq-item").classList.toggle("open");}</script>
</body>
</html>
"""


# ── společné helpery nad daty (ceny z enginu) ───────────────────────────────

def _all_models(data: dict) -> list[tuple[dict, dict]]:
    return [(p, m) for p in data["providers"] for m in p["models"]]


def _prov_stats(eng, prov: dict) -> dict:
    """Souhrn providera: nejlevnější model + ≈$/mo, top model (models[0]) + ≈$/mo,
    max ověřený context window."""
    costs = [(m, eng.canonical_monthly(m)) for m in prov["models"]]
    cheap_m, cheap_mo = min(costs, key=lambda t: t[1])
    top_m = prov["models"][0]
    ctxs = [m["contextWindow"] for m in prov["models"] if m.get("contextWindow")]
    return {"cheap": (cheap_m, cheap_mo), "top": (top_m, eng.canonical_monthly(top_m)),
            "max_ctx": max(ctxs) if ctxs else None, "n": len(prov["models"])}


def _cross(eng, data: dict, *, exclude: tuple = (), calc: bool = True) -> str:
    """Pill řádek interních odkazů (vzor provider .cross): compare + 6 pricing
    + cheapest + calculator, mimo `exclude` (self)."""
    total = sum(len(p["models"]) for p in data["providers"])
    links = []
    if "compare.html" not in exclude:
        links.append(f'    <a href="compare.html">All {total} models →</a>')
    for slug in PROVIDER_ORDER:
        c = eng.PROVIDER_PAGES[slug]
        if c["page"] not in exclude:
            links.append(f'    <a href="{c["page"]}">{c["cross"]} →</a>')
    if "cheapest-llm-api.html" not in exclude:
        links.append('    <a href="cheapest-llm-api.html">Cheapest LLM API →</a>')
    if calc and "index.html" not in exclude:
        links.append('    <a href="index.html">Open calculator →</a>')
    return '  <div class="cross">\n' + "\n".join(links) + "\n  </div>"


def _calc_cta(title: str, sub: str) -> str:
    return (f'  <a class="next-cta" href="index.html">\n    <div>\n'
            f'      <div class="nc-title">{title}</div>\n'
            f'      <div class="nc-sub">{sub}</div>\n    </div>\n'
            '    <span class="nc-arrow">Open calculator'
            '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2.6"><polyline points="9 18 15 12 9 6"/></svg></span>\n  </a>')


def _model_cell(eng, prov: dict, m: dict, link: bool = True) -> str:
    """První buňka: jméno modelu (+ tier badge) + provider podtitul, link na pricing."""
    page = eng.PROVIDER_PAGES[prov["slug"]]["page"]
    name = (f'<a href="{page}"><span class="m-name">{m["name"]}</span></a>' if link
            else f'<span class="m-name">{m["name"]}</span>')
    return (f'{name}<span class="m-tier">{m["tier"].upper()}</span>'
            f'<span class="m-sub">{prov["name"]}</span>')


# ── cheapest-llm-api.html ───────────────────────────────────────────────────

def render_cheapest(eng, data: dict, site: dict, month: str, nav: str, parts: tuple) -> str:
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "/llm")
    prefix = eng._site_prefix(domain, base_path)
    canonical = f"{prefix}/cheapest-llm-api.html"
    total = sum(len(p["models"]) for p in data["providers"])

    rows_data = sorted(((p, m, eng.canonical_monthly(m)) for p, m in _all_models(data)),
                       key=lambda t: t[2])
    cheapest_mo = rows_data[0][2]
    cheap_p, cheap_m, _ = rows_data[0]
    # nejlevnější per tier (rows_data je vzestupně → první výskyt = nejlevnější)
    by_tier: dict[str, tuple] = {}
    for p, m, mo in rows_data:
        by_tier.setdefault(m["tier"], (p, m, mo))

    rows = []
    for i, (p, m, mo) in enumerate(rows_data):
        cached = eng._usd(m["cachedInputPerM"]) if m.get("cachedInputPerM") is not None else "—"
        best = ' class="best"' if i == 0 else ""
        cls = ' class="cheapest"' if i == 0 else ""
        rows.append(
            f"        <tr{cls}>\n"
            f"          <td>{_model_cell(eng, p, m)}</td>\n"
            f'          <td>{eng._usd(m["inputPerM"])}</td><td>{eng._usd(m["outputPerM"])}</td>'
            f'<td>{cached}</td><td{best}>{eng._fmt_mo(mo)}</td>\n        </tr>')

    tier_bits = []
    for t in ("frontier", "mid", "budget"):
        if t in by_tier:
            p, m, mo = by_tier[t]
            tier_bits.append(f'{TIER_LABEL[t]}: <strong>{m["name"]}</strong> ({eng._fmt_mo(mo)})')
    lead = (f'The cheapest LLM API we track is <strong>{cheap_m["name"]}</strong> ({cheap_p["name"]}) '
            f'at about {eng._fmt_mo(cheapest_mo)}/month on our example chatbot workload. '
            f'Cheapest per class — {"; ".join(tier_bits)}. '
            f'All {total} models priced by the same engine as the '
            f'<a href="index.html">calculator</a>, ranked by cost below.')

    body = f"""<section class="wrap">
  <div class="section">
    <h2>Every LLM API, ranked by cost</h2>
    <p class="sub">All {total} models we track, cheapest first, on one example workload — chatbot, 100k requests/mo, 2,000 input / 300 output tokens per request, 70% of input cached. Prompt caching is already priced in. The cheapest row is highlighted.</p>
    <div class="tbl-card">
      <table>
        <thead>
          <tr><th>Model</th><th>$ input /1M</th><th>$ output /1M</th><th>$ cached /1M</th><th>≈ $/mo *</th></tr>
        </thead>
        <tbody>
{chr(10).join(rows)}
        </tbody>
      </table>
    </div>
    <p class="tbl-foot">* Same engine as the <a href="index.html">calculator</a>. Your real number depends on volume, token mix and cache share — tier (frontier / mid / budget) is our editorial class, not a benchmark.</p>
  </div>
{_calc_cta("Cheapest for <em>your</em> workload, not ours",
           "Change the volume, token mix and cache share and the calculator re-ranks every model live.")}
{_cross(eng, data, exclude=("cheapest-llm-api.html",))}
</section>"""

    faq = [
        {"q": "What is the cheapest LLM API?",
         "a": (f"On our example chatbot workload the cheapest LLM API we track is {cheap_m['name']} "
               f"({cheap_p['name']}) at about {eng._fmt_mo(cheapest_mo)}/month. Budget-tier models are "
               "almost always the lowest cost, but the cheapest model for you depends on your token mix "
               'and how much of the prompt you cache — the <a href="index.html">calculator</a> re-ranks '
               "for your numbers.")},
        {"q": "What is the cheapest frontier (flagship-class) LLM API?",
         "a": ((f"Among frontier-class models the lowest cost we track is "
                f"{by_tier['frontier'][1]['name']} ({by_tier['frontier'][0]['name']}) at about "
                f"{eng._fmt_mo(by_tier['frontier'][2])}/month on the example workload. See the ranked "
                "table above for every tier.") if "frontier" in by_tier
               else "See the ranked table above for the cheapest model in each tier.")},
        {"q": "Why is the price shown as a monthly figure and not per token?",
         "a": ("Per-token list prices are hard to compare because input, output and cached tokens are "
               "billed at different rates. The ≈ $/mo column runs one realistic workload through every "
               "model so you can compare them on a single number. Per-1M token rates are in the table too.")},
        {"q": "How accurate are these prices?",
         "a": (f"Every per-token rate is taken from the provider's official pricing and verified by hand "
               f"({month}). The monthly figure is computed, not quoted. Every change we record lands in "
               'the <a href="changelog.html">price changelog</a>.')},
    ]
    title = "The Cheapest LLM API in 2026 (Ranked by Real Cost) — WizardCost"
    desc = (f"The cheapest LLM API in 2026, all {total} models ranked by real monthly cost. "
            f"{cheap_m['name']} is the lowest we track at ~{eng._fmt_mo(cheapest_mo)}/mo — compare "
            "OpenAI, Claude, Gemini, DeepSeek, Grok and Mistral on price, caching and context.")
    crumb = '<a href="index.html">LLM</a> / cheapest LLM API'
    h1 = "The cheapest LLM API in 2026"
    return _shell(parts, title=title, desc=desc, canonical=canonical, prefix=prefix,
                  crumb=crumb, h1=h1, lead=lead, month=month, body=body, faq=faq, nav=nav)


# ── <brand>-alternatives.html ───────────────────────────────────────────────

def render_alternatives(eng, slug: str, data: dict, site: dict, month: str, nav: str, parts: tuple) -> str:
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "/llm")
    prefix = eng._site_prefix(domain, base_path)
    brand = SEO[slug]["brand"]
    canonical = f"{prefix}/{SEO[slug]['alt']}.html"
    provs = {p["slug"]: p for p in data["providers"]}
    focus = provs[slug]
    focus_st = _prov_stats(eng, focus)

    others = [provs[s] for s in PROVIDER_ORDER if s != slug]
    ranked = sorted(((p, _prov_stats(eng, p)) for p in others), key=lambda t: t[1]["cheap"][1])
    cheapest_alt = ranked[0]

    rows = []
    for i, (p, st) in enumerate(ranked):
        page = eng.PROVIDER_PAGES[p["slug"]]["page"]
        vs_file = _vs_file(slug, p["slug"])
        cm, cmo = st["cheap"]
        tm, tmo = st["top"]
        ctx = eng._fmt_ctx(st["max_ctx"]) if st["max_ctx"] else "—"
        best = ' class="best"' if i == 0 else ""
        rows.append(
            f"        <tr>\n"
            f'          <td><a href="{page}"><span class="m-name">{p["name"]}</span></a>'
            f'<span class="m-sub">{st["n"]} models · cheapest {cm["name"]}</span></td>\n'
            f'          <td{best}>{eng._fmt_mo(cmo)}</td><td>{eng._fmt_mo(tmo)}</td>'
            f'<td>{ctx}</td>\n'
            f'          <td><a href="{vs_file}">{brand} vs {SEO[p["slug"]]["brand"]} →</a></td>\n'
            f'        </tr>')

    fc_m, fc_mo = focus_st["cheap"]
    alt_p, alt_st = cheapest_alt
    cheaper = " — cheaper than" if alt_st["cheap"][1] < fc_mo else " — versus"
    lead = (f'Looking for a {brand} API alternative? We priced every provider we track on the same '
            f'workload, so you can compare on real cost — not marketing. The lowest-cost alternative '
            f'to {brand} is <strong>{alt_p["name"]}</strong> '
            f'({eng._fmt_mo(alt_st["cheap"][1])}/mo at its cheapest{cheaper} {brand}\'s '
            f'{eng._fmt_mo(fc_mo)}). Ranked by cost, with context window and head-to-head links below.')

    body = f"""<section class="wrap">
  <div class="section">
    <h2>{brand} alternatives, ranked by cost</h2>
    <p class="sub">Every alternative provider priced on the same example workload (chatbot, 100k requests/mo, 70% cached). “Cheapest” is each provider's lowest-cost model; “top” is its flagship. Lowest cheapest-price is highlighted.</p>
    <div class="tbl-card">
      <table>
        <thead>
          <tr><th>Provider</th><th>Cheapest ≈ $/mo</th><th>Top model ≈ $/mo</th><th>Max context</th><th>Head-to-head</th></tr>
        </thead>
        <tbody>
{chr(10).join(rows)}
        </tbody>
      </table>
    </div>
    <p class="tbl-foot">≈ $/mo from the same engine as the <a href="index.html">calculator</a>. See <a href="{eng.PROVIDER_PAGES[slug]["page"]}">{brand} pricing</a> in detail or the full <a href="cheapest-llm-api.html">cheapest LLM API</a> ranking.</p>
  </div>
{_calc_cta(f"Is {brand} actually the right price for you?",
           f"Put {brand} next to every alternative at your volume, token mix and cache share.")}
{_cross(eng, data, exclude=(SEO[slug]["alt"] + ".html",))}
</section>"""

    faq = [
        {"q": f"What is the best {brand} alternative?",
         "a": (f"It depends what you're optimising for. On cost, the lowest-priced alternative we track "
               f"is {alt_p['name']} ({eng._fmt_mo(alt_st['cheap'][1])}/mo at its cheapest). For a "
               f"flagship-class alternative, compare the “top model” column above. Use the "
               '<a href="index.html">calculator</a> to rank them for your exact workload.')},
        {"q": f"What is the cheapest {brand} alternative?",
         "a": (f"At its cheapest model, {alt_p['name']} is the lowest-cost alternative to {brand} we "
               f"track ({eng._fmt_mo(alt_st['cheap'][1])}/mo on the example workload). See the ranked "
               "table above for the full order.")},
        {"q": f"How do these alternatives compare to {brand} on price?",
         "a": (f"{brand}'s cheapest model runs about {eng._fmt_mo(fc_mo)}/mo on our example workload. "
               "Each alternative in the table is priced the same way, so the numbers are directly "
               'comparable. Head-to-head pages break each pairing down model by model.')},
        {"q": "How accurate are these prices?",
         "a": (f"Every per-token rate is taken from each provider's official pricing and verified by hand "
               f"({month}); the monthly figure is computed by our cost engine. Changes are logged in the "
               '<a href="changelog.html">price changelog</a>.')},
    ]
    title = f"Best {brand} API Alternatives 2026 — Priced &amp; Compared | WizardCost"
    desc = (f"The best {brand} API alternatives in 2026, priced on a real workload. {alt_p['name']} is "
            f"the lowest-cost option we track at ~{eng._fmt_mo(alt_st['cheap'][1])}/mo — compare every "
            f"{brand} alternative on cost, context window and caching.")
    crumb = f'<a href="index.html">LLM</a> / {brand} alternatives'
    h1 = f"The best {brand} API alternatives in 2026"
    return _shell(parts, title=title, desc=desc, canonical=canonical, prefix=prefix,
                  crumb=crumb, h1=h1, lead=lead, month=month, body=body, faq=faq, nav=nav)


# ── <a>-vs-<b>.html ─────────────────────────────────────────────────────────

def _vs_file(a_slug: str, b_slug: str) -> str:
    ia, ib = PROVIDER_ORDER.index(a_slug), PROVIDER_ORDER.index(b_slug)
    x, y = (a_slug, b_slug) if ia < ib else (b_slug, a_slug)
    return f'{SEO[x]["vs"]}-vs-{SEO[y]["vs"]}.html'


def render_vs(eng, a_slug: str, b_slug: str, data: dict, site: dict, month: str, nav: str, parts: tuple) -> str:
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "/llm")
    prefix = eng._site_prefix(domain, base_path)
    provs = {p["slug"]: p for p in data["providers"]}
    A, B = provs[a_slug], provs[b_slug]
    ba, bb = SEO[a_slug]["brand"], SEO[b_slug]["brand"]
    canonical = f"{prefix}/{_vs_file(a_slug, b_slug)}"
    sa, sb = _prov_stats(eng, A), _prov_stats(eng, B)

    # sloučená tabulka obou lineupů, vzestupně dle ≈$/mo
    merged = sorted(((p, m, eng.canonical_monthly(m)) for p in (A, B) for m in p["models"]),
                    key=lambda t: t[2])
    cheapest_overall = merged[0]
    rows = []
    for p, m, mo in merged:
        cached = eng._usd(m["cachedInputPerM"]) if m.get("cachedInputPerM") is not None else "—"
        best = ' class="best"' if (p, m, mo) is cheapest_overall else ""
        rows.append(
            f"        <tr>\n          <td>{_model_cell(eng, p, m)}</td>\n"
            f'          <td>{eng._usd(m["inputPerM"])}</td><td>{eng._usd(m["outputPerM"])}</td>'
            f'<td>{cached}</td><td{best}>{eng._fmt_mo(mo)}</td>\n        </tr>')

    # verdikt — objektivní fakta (nejlevnější a top per provider, context), žádné hodnocení
    cheap_a, cheap_b = sa["cheap"], sb["cheap"]
    lower = ba if cheap_a[1] < cheap_b[1] else (bb if cheap_b[1] < cheap_a[1] else None)
    if lower:
        budget_line = (f'At the budget end, <b>{lower}</b> is the lower-cost option on this workload: '
                       f'{ba}\'s cheapest ({cheap_a[0]["name"]}) is {eng._fmt_mo(cheap_a[1])}/mo vs '
                       f'{bb}\'s ({cheap_b[0]["name"]}) {eng._fmt_mo(cheap_b[1])}/mo.')
    else:
        budget_line = (f'At the budget end both land at {eng._fmt_mo(cheap_a[1])}/mo on this workload '
                       f'({ba}: {cheap_a[0]["name"]}, {bb}: {cheap_b[0]["name"]}).')
    top_a, top_b = sa["top"], sb["top"]
    top_line = (f'At the top end, {ba}\'s flagship {top_a[0]["name"]} runs {eng._fmt_mo(top_a[1])}/mo vs '
                f'{bb}\'s {top_b[0]["name"]} at {eng._fmt_mo(top_b[1])}/mo.')
    ctx_a = eng._fmt_ctx(sa["max_ctx"]) if sa["max_ctx"] else "not verified"
    ctx_b = eng._fmt_ctx(sb["max_ctx"]) if sb["max_ctx"] else "not verified"
    ctx_line = f'Largest verified context window — {ba}: {ctx_a}; {bb}: {ctx_b}.'

    lead = (f'{ba} vs {bb}, compared on real cost. We ran every model from both on the same example '
            f'workload (chatbot, 100k requests/mo, 70% cached) so the prices line up directly. '
            f'The lowest-cost model across both is <strong>{cheapest_overall[1]["name"]}</strong> '
            f'({eng._fmt_mo(cheapest_overall[2])}/mo). Full table and verdict below.')

    body = f"""<section class="wrap">
  <div class="verdict">
    <h2>{ba} vs {bb}: the short answer</h2>
    <p>{budget_line}</p>
    <p>{top_line} {ctx_line}</p>
    <p>Both are priced by the same engine, so compare your own workload in the <a href="index.html">calculator</a> — the cheaper choice flips with your token mix and cache share.</p>
  </div>
  <div class="section">
    <h2>{ba} and {bb} models, priced side by side</h2>
    <p class="sub">Every model from both providers on one example workload (100k requests/mo, 2,000 input / 300 output tokens, 70% cached), cheapest first. The single lowest-cost model is highlighted.</p>
    <div class="tbl-card">
      <table>
        <thead>
          <tr><th>Model</th><th>$ input /1M</th><th>$ output /1M</th><th>$ cached /1M</th><th>≈ $/mo *</th></tr>
        </thead>
        <tbody>
{chr(10).join(rows)}
        </tbody>
      </table>
    </div>
    <p class="tbl-foot">* Same engine as the <a href="index.html">calculator</a>. See <a href="{eng.PROVIDER_PAGES[a_slug]["page"]}">{ba} pricing</a> · <a href="{eng.PROVIDER_PAGES[b_slug]["page"]}">{bb} pricing</a> in full.</p>
  </div>
{_calc_cta(f"{ba} or {bb} for your workload?",
           "The cheaper option depends on your volume and cache share — run both through the calculator.")}
{_cross(eng, data, exclude=(_vs_file(a_slug, b_slug),))}
</section>"""

    faq = [
        {"q": f"Is {ba} or {bb} cheaper?",
         "a": (f"On our example chatbot workload, {ba}'s cheapest model ({cheap_a[0]['name']}) is "
               f"{eng._fmt_mo(cheap_a[1])}/mo and {bb}'s ({cheap_b[0]['name']}) is "
               f"{eng._fmt_mo(cheap_b[1])}/mo. "
               + (f"So {lower} is lower-cost at the budget end" if lower else "They're level at the budget end")
               + '. The cheaper choice can flip with your token mix — check the '
               '<a href="index.html">calculator</a>.')},
        {"q": f"Which has the bigger context window, {ba} or {bb}?",
         "a": (f"The largest context window we've verified is {ctx_a} for {ba} and {ctx_b} for {bb}. "
               "Context windows vary by model within each provider — see the pricing pages for the "
               "per-model figures.")},
        {"q": f"{ba} vs {bb}: which API should I choose?",
         "a": ("It depends on your workload. Compare the side-by-side table above for list prices and the "
               "≈ $/mo column for a like-for-like cost, then run your own volume through the "
               '<a href="index.html">calculator</a>. We rank on cost and published specs only — the '
               '<a href="changelog.html">changelog</a> records every price change.')},
        {"q": "How accurate are these prices?",
         "a": (f"Every per-token rate is taken from each provider's official pricing and verified by hand "
               f"({month}); the monthly figure is computed by our cost engine, not quoted.")},
    ]
    title = f"{ba} vs {bb} API Pricing 2026 — Cost Compared | WizardCost"
    desc = (f"{ba} vs {bb} API pricing in 2026, compared on a real workload. {cheapest_overall[1]['name']} "
            f"is the lowest-cost model across both at ~{eng._fmt_mo(cheapest_overall[2])}/mo — see every "
            "model priced side by side, plus context windows and caching.")
    crumb = f'<a href="index.html">LLM</a> / {ba} vs {bb}'
    h1 = f"{ba} vs {bb}: API pricing compared"
    return _shell(parts, title=title, desc=desc, canonical=canonical, prefix=prefix,
                  crumb=crumb, h1=h1, lead=lead, month=month, body=body, faq=faq, nav=nav)


# ── orchestrace (vzor automation build_seo_pages) ───────────────────────────

def build_seo_pages(data: dict, site: dict, eng, *, check: bool = False) -> list[str]:
    """Vygeneruje cheapest (1) + alternatives (6) + vs (15) stránky CELÉ z dat.

    check=True → nezapisuje, vrátí soubory které by se změnily (porovnává bez
    GA4/analytics bloků, ty build.py vkládá až po generování). Jinak zapíše."""
    if not TEMPLATE.exists():
        return []
    parts = _tpl_parts()
    month = eng._verified_month(data)
    nav = eng.nav_dropdown_html(data, None)

    targets: list[tuple[str, "callable"]] = [
        ("cheapest-llm-api.html", lambda: render_cheapest(eng, data, site, month, nav, parts)),
    ]
    for slug in PROVIDER_ORDER:
        targets.append((f'{SEO[slug]["alt"]}.html',
                        lambda slug=slug: render_alternatives(eng, slug, data, site, month, nav, parts)))
    for i, a in enumerate(PROVIDER_ORDER):
        for b in PROVIDER_ORDER[i + 1:]:
            targets.append((_vs_file(a, b),
                            lambda a=a, b=b: render_vs(eng, a, b, data, site, month, nav, parts)))

    out = []
    for fname, render in targets:
        target = ROOT / fname
        rendered = render()
        if "{{" in rendered or "%%" in rendered:
            raise SystemExit(f"CHYBA: nevyplněný token v {fname} — zkontroluj shell.")
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        dirty = existing is None or eng._strip_injected(existing) != rendered
        if check:
            if dirty:
                out.append(fname)
        elif dirty:
            target.write_text(rendered, encoding="utf-8")
            out.append(fname)
    return out
