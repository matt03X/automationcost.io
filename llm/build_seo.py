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
        '        <button class="faq-q" aria-expanded="false" onclick="toggleFaq(this)">' + f["q"]
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


def _clamp_desc(text: str, n: int = 158) -> str:
    """Trim a meta description to <= n chars on a word boundary (+ ellipsis)."""
    if not text or len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ,.;:—–-")
    return cut + "…"


def _clamp_title(title: str, n: int = 60) -> str:
    """Keep <title> <= n rendered chars, trimming the core but preserving the ' | brand' suffix."""
    if not title or len(title.replace("&amp;", "&")) <= n:
        return title
    if " | " in title:
        core, brand = title.rsplit(" | ", 1)
        budget = n - len(" | " + brand.replace("&amp;", "&"))
        if budget >= 16:
            r_core = core.replace("&amp;", "&")
            trimmed = r_core[:budget].rsplit(" ", 1)[0].rstrip(" ,.;:—–-&")
            return trimmed.replace("&", "&amp;") + " | " + brand
    r = title.replace("&amp;", "&")[:n - 1].rsplit(" ", 1)[0].rstrip(" ,.;:—–-&")
    return r.replace("&", "&amp;") + "…"


def _shell(parts: tuple, *, title: str, desc: str, canonical: str, prefix: str,
           crumb: str, h1: str, lead: str, month: str, body: str, faq: list[dict],
           nav: str) -> str:
    css, header, footer, dropdown_js = parts
    header = header.replace("{{NAV_DROPDOWN}}", nav).replace("{{VERIFIED_MONTH}}", month)
    footer = footer.replace("{{VERIFIED_MONTH}}", month)
    domain = canonical.split("/llm/", 1)[0].replace("https://", "")
    repl = {
        "%%TITLE%%": _clamp_title(title), "%%DESC%%": _clamp_desc(desc), "%%CANONICAL%%": canonical,
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
<script>function toggleFaq(el){var o=el.closest(".faq-item").classList.toggle("open");el.setAttribute("aria-expanded",o?"true":"false");}</script>
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
    for slug in PROVIDER_ORDER:
        alt = SEO[slug]["alt"] + ".html"
        if alt not in exclude:
            links.append(f'    <a href="{alt}">{SEO[slug]["brand"]} alternatives →</a>')
    if "cheapest-llm-api.html" not in exclude:
        links.append('    <a href="cheapest-llm-api.html">Cheapest LLM API →</a>')
    if "is-llm-worth-it.html" not in exclude:
        links.append('    <a href="is-llm-worth-it.html">Is an LLM API worth it? →</a>')
    if calc and "calculator.html" not in exclude:
        links.append('    <a href="calculator.html">Open calculator →</a>')
    return '  <div class="cross">\n' + "\n".join(links) + "\n  </div>"


def _calc_cta(title: str, sub: str) -> str:
    return (f'  <a class="next-cta" href="calculator.html">\n    <div>\n'
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
            f'<a href="calculator.html">calculator</a>, ranked by cost below.')

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
    <p class="tbl-foot">* Same engine as the <a href="calculator.html">calculator</a>. Your real number depends on volume, token mix and cache share — tier (frontier / mid / budget) is our editorial class, not a benchmark.</p>
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
               'and how much of the prompt you cache — the <a href="calculator.html">calculator</a> re-ranks '
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
    <p class="tbl-foot">≈ $/mo from the same engine as the <a href="calculator.html">calculator</a>. See <a href="{eng.PROVIDER_PAGES[slug]["page"]}">{brand} pricing</a> in detail or the full <a href="cheapest-llm-api.html">cheapest LLM API</a> ranking.</p>
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
               '<a href="calculator.html">calculator</a> to rank them for your exact workload.')},
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
    <p>Both are priced by the same engine, so compare your own workload in the <a href="calculator.html">calculator</a> — the cheaper choice flips with your token mix and cache share.</p>
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
    <p class="tbl-foot">* Same engine as the <a href="calculator.html">calculator</a>. See <a href="{eng.PROVIDER_PAGES[a_slug]["page"]}">{ba} pricing</a> · <a href="{eng.PROVIDER_PAGES[b_slug]["page"]}">{bb} pricing</a> in full.</p>
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
               '<a href="calculator.html">calculator</a>.')},
        {"q": f"Which has the bigger context window, {ba} or {bb}?",
         "a": (f"The largest context window we've verified is {ctx_a} for {ba} and {ctx_b} for {bb}. "
               "Context windows vary by model within each provider — see the pricing pages for the "
               "per-model figures.")},
        {"q": f"{ba} vs {bb}: which API should I choose?",
         "a": ("It depends on your workload. Compare the side-by-side table above for list prices and the "
               "≈ $/mo column for a like-for-like cost, then run your own volume through the "
               '<a href="calculator.html">calculator</a>. We rank on cost and published specs only — the '
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

def render_methodology(eng, data: dict, site: dict, month: str, nav: str, parts: tuple) -> str:
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "/llm")
    prefix = eng._site_prefix(domain, base_path)
    canonical = f"{prefix}/methodology.html"
    meta = data.get("_meta", {})
    sources = meta.get("sources", {})
    reviewed = meta.get("last_reviewed", month)
    total = sum(len(p["models"]) for p in data["providers"])
    nprov = len(data["providers"])

    src_rows = []
    for p in data["providers"]:
        raw = sources.get(p["slug"], "")
        url = raw.split(" ", 1)[0]
        host = url.replace("https://", "").replace("http://", "").rstrip("/")
        src_rows.append(
            "        <tr>\n"
            f'          <td><strong>{p["name"]}</strong></td>\n'
            f'          <td>{len(p["models"])}</td>\n'
            f'          <td><a href="{url}" target="_blank" rel="noopener nofollow">{host}</a></td>\n'
            f"          <td>{reviewed}</td>\n        </tr>")

    lead = (f"Every price here is taken by hand from the provider's official pricing page, verified on a "
            f"dated pass, and turned into a monthly figure by the same engine as the "
            f'<a href="calculator.html">calculator</a> — never quoted from memory or a third party. '
            f"Here is exactly where each of the {total} models' numbers come from, what they mean, and what "
            f"we don't claim.")

    body = f"""<section class="wrap">
  <div class="section">
    <h2>How we price LLM APIs</h2>
    <p class="sub">Four rules, the same for every model.</p>
    <ol style="line-height:1.75;padding-left:1.2em;">
      <li><strong>One source of truth per provider.</strong> Every per-token rate comes from the vendor's own official pricing page (listed below) — not a blog, aggregator or screenshot.</li>
      <li><strong>Verified by hand, then promoted.</strong> A scrape or research pass is only <em>evidence</em>; a number reaches our data file only after a human confirms it against the official page. Raw dumps are kept dated for audit.</li>
      <li><strong>Computed, not quoted.</strong> The "≈ $/mo" you see is calculated by our engine from input, output and cached rates at a stated workload — so models compare on one number. We never invent a monthly price.</li>
      <li><strong>Every change is logged.</strong> Prices are committed before the site rebuilds, so each change is dated in the public <a href="changelog.html">changelog</a> with the provider it came from.</li>
    </ol>
  </div>

  <div class="section">
    <h2>Sources — every number traces to an official page</h2>
    <p class="sub">{total} models across {nprov} providers. Last full verification: {reviewed}.</p>
    <div class="tbl-card">
      <table>
        <thead><tr><th>Provider</th><th>Models</th><th>Official pricing source</th><th>Last verified</th></tr></thead>
        <tbody>
{chr(10).join(src_rows)}
        </tbody>
      </table>
    </div>
    <p class="tbl-foot">Mistral's per-model lineup is taken from the official model cards on docs.mistral.ai; the public FAQ price page lists only the flagship.</p>
  </div>

  <div class="section">
    <h2>Are tokens the same across models? No — and it matters</h2>
    <p>A "token" is not a fixed unit. Each model family uses its <strong>own tokenizer</strong>, so the <em>same text</em> becomes a different number of tokens from one provider to the next — commonly a <strong>10–30% spread</strong> (wider for non-English text and code). Two models at the same "$ per 1M tokens" can therefore cost differently for the <em>same prompt</em>, because one encodes it in fewer tokens.</p>
    <p>Tokens aren't equal in <strong>value</strong> either: a token from a frontier model carries more capability than one from a budget model, so price per token says nothing about quality.</p>
    <p>What this means for our numbers: we compare <strong>list price per 1M tokens</strong> as the billing unit — the honest, vendor-published basis — and run every model through <strong>one identical workload</strong> (same token counts) so the ≈ $/mo column is apples-to-apples on price. Treat cross-provider gaps inside ~10–20% as a tie until you test your own prompts; the <a href="calculator.html">calculator</a> lets you plug in your real token mix.</p>
  </div>

  <div class="section">
    <h2>What each number means</h2>
    <div class="tbl-card">
      <table>
        <thead><tr><th>Field</th><th>Definition</th></tr></thead>
        <tbody>
          <tr><td><strong>$ input / 1M</strong></td><td>List price per 1M input (prompt) tokens — standard tier, short context.</td></tr>
          <tr><td><strong>$ output / 1M</strong></td><td>List price per 1M output (completion) tokens.</td></tr>
          <tr><td><strong>$ cached / 1M</strong></td><td>Price per 1M cached / read input tokens. "—" = caching not offered or not yet verified (we then bill input at the full rate).</td></tr>
          <tr><td><strong>Batch</strong></td><td>Multiplier for the provider's Batch API (×0.5 = 50% off). "—" = no batch tier, or the exact discount is unverified and we hold it empty rather than guess.</td></tr>
          <tr><td><strong>Context</strong></td><td>Maximum context window, in tokens.</td></tr>
          <tr><td><strong>Tier</strong></td><td><em>Editorial</em> class (frontier / mid / budget) for ranking — our judgement, not a benchmark. The calculator never compares price across tiers.</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <h2>Known limits &amp; confidence</h2>
    <p>We would rather show a gap than a guess:</p>
    <ul style="line-height:1.75;padding-left:1.2em;">
      <li><strong>Mistral cached prices</strong> are held empty (except the flagship): Mistral documents a caching rule but doesn't publish per-model cached rates, so we bill input at the full rate rather than estimate.</li>
      <li><strong>Batch multipliers for xAI and DeepSeek</strong> are held empty: a batch or cache discount exists, but the exact figure isn't officially tabled, so we don't apply one.</li>
      <li><strong>Long-context surcharges</strong> (e.g. Gemini above 200k tokens) are noted in our data but not yet in the calculation — short-context pricing is shown.</li>
      <li><strong>Tier and our example workload are assumptions</strong>, not vendor facts — change them in the calculator for your case.</li>
    </ul>
  </div>

  <div class="section">
    <h2>What we exclude, and why</h2>
    <ul style="line-height:1.75;padding-left:1.2em;">
      <li><strong>Cohere</strong> — the current lineup is sold as enterprise instances with no public per-token price, so it can't be verified the same way.</li>
      <li><strong>Meta Llama</strong> — priced only through third-party hosts with their own rates; planned for a later pass once we can compare hosts fairly.</li>
    </ul>
    <p class="tbl-foot">We track the {total} models we can verify against an official, first-party price. We would rather cover fewer models accurately than more on guesswork.</p>
  </div>

  <div class="section">
    <h2>How we keep it current</h2>
    <p>An automated job re-reads all {nprov} official price pages every morning and flags any change; a second job watches context windows, caching, batch and deprecations. Those flags are evidence — a human still confirms before a number changes. Confirmed changes are dated in the <a href="changelog.html">changelog</a>, and we take no commission from any model provider, so nothing here is pay-to-rank.</p>
  </div>
{_calc_cta("See it on your own numbers", "The calculator uses these exact prices — plug in your volume, token mix and cache share, and it re-ranks every model live.")}
{_cross(eng, data, exclude=("methodology.html",))}
</section>"""

    faq = [
        {"q": "Where do your LLM prices come from?",
         "a": ("Each per-token rate is taken by hand from the provider's official pricing page (listed in the "
               "sources table above) and confirmed by a person before it enters our data. The monthly figure is "
               "computed by our engine, not quoted.")},
        {"q": "Are token counts the same across providers?",
         "a": ("No. Every model family uses its own tokenizer, so the same text becomes a different number of "
               "tokens — typically a 10–30% spread, wider for non-English text and code. We compare list price "
               "per 1M tokens as the billing unit and run one identical workload through every model, so treat "
               "small cross-provider differences as a tie until you test your own prompts.")},
        {"q": "Do the model providers pay you?",
         "a": ("No. The LLM section carries no affiliate links and no sponsored placement — rankings are by "
               "objective cost only. It exists to be an accurate, independent reference.")},
        {"q": "How often are prices checked?",
         "a": (f"An automated job re-reads every official price page daily and flags changes; a human confirms "
               f"before any number moves. The last full hand-verification was {reviewed}, and every change is "
               'dated in the <a href="changelog.html">changelog</a>.')},
    ]
    title = "How We Verify LLM API Pricing — Methodology & Sources | WizardCost"
    desc = ("How we verify LLM API pricing: every model's price traced to its provider's official page, "
            "verified by hand and computed not quoted — plus why tokens aren't equal across models.")
    crumb = '<a href="index.html">LLM</a> / methodology'
    h1 = "How we verify LLM API pricing"
    return _shell(parts, title=title, desc=desc, canonical=canonical, prefix=prefix,
                  crumb=crumb, h1=h1, lead=lead, month=month, body=body, faq=faq, nav=nav)



def _iwi_cost(m: dict, tasks: float, in_tok: float, out_tok: float, cache: float) -> float:
    """Parametrizovaný náklad modelu (port canonical_monthly, libovolný workload)."""
    in_per_m = m["inputPerM"]
    out_per_m = m["outputPerM"]
    cached = m.get("cachedInputPerM")
    in_rate = in_per_m * (1 - cache) + cached * cache if cached is not None else in_per_m
    return tasks * in_tok / 1e6 * in_rate + tasks * out_tok / 1e6 * out_per_m


def _smoney(x: float) -> str:
    """$ částka: centy/desetiny u malých, celé u velkých (aby levné scénáře nebyly '$0')."""
    if x < 100:
        return f"{x:,.2f}".rstrip("0").rstrip(".")
    return f"{x:,.0f}"


def _roi_str(roi) -> str:
    """ROI multiplikátor — nad 1000× cap na '1,000×+' (honest, ale ne hype-looking)."""
    if roi is None:
        return "—"
    return "1,000×+" if roi >= 1000 else f"{roi:,}×"


def render_is_llm_worth_it(eng, data: dict, site: dict, month: str, nav: str, parts: tuple) -> str:
    """is-llm-worth-it.html — ROI / break-even pro LLM API (zrcadlí automation ROI,
    ale s PER-MODEL rozpadem: každý model = náklad + ROI + úspora pro tvůj scénář).
    Nákladová strana z enginu (canonical formula). Žádné nové cenové tvrzení."""
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "/llm")
    prefix = eng._site_prefix(domain, base_path)
    canonical = f"{prefix}/is-llm-worth-it.html"
    models = [(p, m) for p, m in _all_models(data)]

    def cheapest_at(tasks, it, ot, cache=0.0):
        ranked = sorted(((p, m, _iwi_cost(m, tasks, it, ot, cache)) for p, m in models), key=lambda t: t[2])
        return ranked[0]  # (prov, model, cost)

    # ── worked scenarios: (label, tasks/mo, in_tok, out_tok, min ušetřených/task, $/hod) ──
    SCEN = [
        ("Support replies — 10k tickets/mo", 10000, 1500, 400, 6, 28),
        ("Content drafts — 2k pieces/mo", 2000, 900, 1200, 20, 35),
        ("Doc classification — 100k docs/mo", 100000, 600, 60, 1, 28),
    ]
    rows = []
    for label, tasks, it, ot, mins, rate in SCEN:
        p, m, cost = cheapest_at(tasks, it, ot)
        hrs = tasks * mins / 60
        value = hrs * rate
        net = value - cost
        roi = round(value / cost) if cost > 0 else None
        be_tasks = int(cost / (rate * mins / 60)) if (rate and mins) else None
        be_disp = "n/a" if be_tasks is None else ("&lt;1" if be_tasks < 1 else f"~{be_tasks:,}")
        cls = ' class="cheap"' if net > 0 else ""
        rows.append(
            "        <tr>"
            f"<td>{label}</td>"
            f'<td>${_smoney(cost)}/mo<br><span class="m-sub2">{m["name"]}</span></td>'
            f"<td>{hrs:,.0f} hrs</td>"
            f"<td>${value:,.0f}</td>"
            f'<td{cls}>${net:,.0f}</td>'
            f"<td>{_roi_str(roi)}</td>"
            f"<td>{be_disp}/mo</td>"
            "</tr>")
    scen_rows = "\n".join(rows)

    # hero anchor — cheapest model at a representative chatbot workload
    ap, am, acost = cheapest_at(100000, 2000, 300, 0.70)
    anchor = f'{am["name"]} at about ${_smoney(acost)}/mo'

    # model data pro widget (JS)
    mjs = []
    for p, m in models:
        c = m.get("cachedInputPerM")
        mjs.append('{n:%s,p:%s,i:%s,o:%s,c:%s,t:%s}' % (
            json.dumps(m["name"], ensure_ascii=False), json.dumps(p["name"], ensure_ascii=False), m["inputPerM"], m["outputPerM"],
            ("null" if c is None else c), json.dumps(m["tier"], ensure_ascii=False)))
    models_js = "[\n      " + ",\n      ".join(mjs) + "\n    ]"

    body = f"""<section class="wrap">
  <div class="section">
    <h2>The ROI formula — does an LLM API pay for itself?</h2>
    <p class="sub">An LLM call replaces work a person would otherwise do. Put a dollar value on that work, compare it to the API cost, and you get ROI.</p>
    <div class="formula-card">
      Net savings = work value &minus; API cost &nbsp;·&nbsp; Return on cost = work value &divide; API cost &nbsp;·&nbsp; Break-even = the number of tasks/mo whose saved time covers the API bill.
    </div>
    <p class="sub" style="margin-top:12px">API cost is computed by the same engine as the <a href="calculator.html">calculator</a> from each model's per-token price — never quoted from memory. The cheapest model we track for a typical chatbot workload is <strong>{anchor}</strong>.</p>
  </div>

  <div class="section">
    <h2>Worked examples — cheapest model, real ROI</h2>
    <p class="sub">Each row prices every one of our {len(models)} models at the workload and shows the cheapest, with the value of the human time it offsets. Saved-time and rate are editorial assumptions — change them in the calculator below.</p>
    <div class="tbl-card">
      <table>
        <thead><tr><th>Scenario</th><th>API cost</th><th>Time offset</th><th>Work value</th><th>Net savings/mo</th><th>Return</th><th>Break-even</th></tr></thead>
        <tbody>
{scen_rows}
        </tbody>
      </table>
    </div>
    <p class="tbl-foot">Cheapest model per scenario, no caching assumed (caching only lowers cost further). "Return" = value ÷ API cost. A long, clean, high-volume task is where LLM ROI is strongest.</p>
  </div>

  <div class="section">
    <h2>ROI calculator — every model, your numbers</h2>
    <p class="sub">Set your task and what an hour of the work it replaces is worth. We price all {len(models)} models and rank them by ROI — so you see which model has which return and how much each saves.</p>
    <div class="iwi-widget">
      <div class="iwi-inputs">
        <label>Tasks / month<input id="iwi-tasks" type="number" value="10000" min="0"></label>
        <label>Input tokens / task<input id="iwi-in" type="number" value="1500" min="0"></label>
        <label>Output tokens / task<input id="iwi-out" type="number" value="400" min="0"></label>
        <label>Minutes a human would spend / task<input id="iwi-mins" type="number" value="6" min="0" step="0.5"></label>
        <label>Hourly cost of that person ($)<input id="iwi-rate" type="number" value="28" min="0"></label>
        <label>Cached input share (%)<input id="iwi-cache" type="number" value="0" min="0" max="100"></label>
      </div>
      <div id="iwi-verdict" class="iwi-verdict" hidden></div>
      <div class="tbl-card" style="margin-top:14px">
        <table id="iwi-table">
          <thead><tr><th>Model</th><th>API cost/mo</th><th>Net savings/mo</th><th>Return</th></tr></thead>
          <tbody id="iwi-rows"></tbody>
        </table>
      </div>
      <p class="iwi-disc">Work value = (tasks × minutes ÷ 60) × hourly cost. API cost from each model's published per-token price (verified {month}); ROI is illustrative — real value depends on your task and quality bar. Models aren't interchangeable: a budget model may need review a frontier model wouldn't. See <a href="methodology.html">methodology</a>.</p>
    </div>
  </div>

  <div class="section">
    <h2>When an LLM API is <em>not</em> worth it</h2>
    <p class="sub">Honesty is a feature. The ROI math turns negative here:</p>
    <div class="tbl-card">
      <table>
        <thead><tr><th>Situation</th><th>Why ROI suffers</th><th>Verdict</th></tr></thead>
        <tbody>
          <tr><td>One-off or tiny volume</td><td>Engineering and prompt-tuning time dwarfs the saved minutes when you run it a handful of times.</td><td class="tag-no">Skip</td></tr>
          <tr><td>Zero error tolerance</td><td>If every output needs a human to verify, you've shifted work, not removed it — and added latency and token cost on top.</td><td class="tag-no">Risky</td></tr>
          <tr><td>The work is already cheap</td><td>If a person does the task in seconds for near-zero cost, the API bill plus oversight rarely beats it.</td><td class="tag-warn">Marginal</td></tr>
          <tr><td>High volume, clear task, tolerant of small error</td><td>Cost per task is cents, the offset is real minutes — ROI scales with volume.</td><td class="tag-yes">Strong ROI</td></tr>
        </tbody>
      </table>
    </div>
  </div>
{_calc_cta("Tune it on your real prompts", "The calculator uses these exact prices — set your token mix, cache share and volume and it re-ranks every model live.")}
{_cross(eng, data, exclude=("is-llm-worth-it.html",))}
</section>
<style>
  .formula-card {{ background: var(--surface2); border: 1px solid var(--border2); border-radius: var(--radius-sm); padding: 14px 18px; font-size: 14.5px; color: var(--text2); line-height: 1.7; }}
  .m-sub2 {{ color: var(--muted); font-size: 12px; }}
  td.cheap {{ color: var(--accent-br); font-weight: 700; }}
  .tag-yes {{ color: #16d18c; font-weight: 700; }} .tag-no {{ color: #ef6a6a; font-weight: 700; }} .tag-warn {{ color: #f0b84e; font-weight: 700; }}
  .iwi-widget {{ background: var(--surface); border: 1px solid var(--border2); border-radius: var(--radius); padding: 20px; }}
  .iwi-inputs {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
  .iwi-inputs label {{ display: flex; flex-direction: column; gap: 5px; font-size: 12.5px; color: var(--text2); font-weight: 600; }}
  .iwi-inputs input {{ background: var(--surface2); border: 1px solid var(--border2); border-radius: 8px; padding: 9px 11px; color: var(--text); font-family: var(--font); font-size: 15px; }}
  .iwi-inputs input:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  .iwi-verdict {{ margin-top: 16px; padding: 14px 16px; border-radius: var(--radius-sm); font-size: 15px; font-weight: 600; }}
  .iwi-verdict.good {{ background: rgba(16,185,129,0.10); border: 1px solid rgba(16,185,129,0.35); color: #6ee7b7; }}
  .iwi-verdict.bad {{ background: rgba(239,68,68,0.10); border: 1px solid rgba(239,68,68,0.35); color: #fca5a5; }}
  #iwi-table td:first-child {{ font-weight: 600; }}
  .iwi-disc {{ color: var(--muted); font-size: 12px; margin-top: 12px; line-height: 1.6; }}
</style>
<script>
(function() {{
  var MODELS = {models_js};
  function num(id) {{ return parseFloat(document.getElementById(id).value) || 0; }}
  function money(n) {{ if (Math.abs(n) < 100) {{ return '$' + (Math.round(n*100)/100).toLocaleString('en-US', {{maximumFractionDigits:2}}); }} return '$' + Math.round(n).toLocaleString('en-US'); }}
  function roiStr(x) {{ if (x === null) return '—'; return x >= 1000 ? '1,000×+' : Math.round(x).toLocaleString('en-US') + '×'; }}
  function compute() {{
    var tasks = num('iwi-tasks'), it = num('iwi-in'), ot = num('iwi-out');
    var mins = num('iwi-mins'), rate = num('iwi-rate'), cache = Math.min(Math.max(num('iwi-cache'),0),100)/100;
    var value = tasks * mins / 60 * rate;
    var ranked = MODELS.map(function(m) {{
      var inRate = (m.c !== null) ? (m.i*(1-cache) + m.c*cache) : m.i;
      var cost = tasks*it/1e6*inRate + tasks*ot/1e6*m.o;
      return {{ m: m, cost: cost, net: value - cost, roi: cost > 0 ? value/cost : null }};
    }}).sort(function(a,b) {{ return a.cost - b.cost; }});
    var tb = document.getElementById('iwi-rows'); tb.innerHTML = '';
    ranked.forEach(function(r, i) {{
      var tr = document.createElement('tr');
      var net = (r.net >= 0 ? '+' : '') + money(r.net);
      var roi = roiStr(r.roi);
      tr.innerHTML = '<td>' + r.m.n + ' <span class="m-sub2">' + r.m.p + '</span></td>'
        + '<td>' + money(r.cost) + '/mo</td>'
        + '<td' + (r.net >= 0 ? ' class="cheap"' : ' style="color:#ef6a6a"') + '>' + net + '</td>'
        + '<td>' + roi + '</td>';
      tb.appendChild(tr);
    }});
    var best = ranked[0];
    var v = document.getElementById('iwi-verdict');
    if (tasks <= 0 || value <= 0) {{ v.hidden = true; return; }}
    v.hidden = false;
    if (best.net >= 0) {{
      v.className = 'iwi-verdict good';
      v.innerHTML = 'Worth it: cheapest model <strong>' + best.m.n + '</strong> costs ' + money(best.cost)
        + '/mo and offsets ' + money(value) + ' of work — net <strong>' + money(best.net) + '/mo</strong> ('
        + roiStr(best.roi) + ' return).';
    }} else {{
      v.className = 'iwi-verdict bad';
      v.innerHTML = 'Not yet: even the cheapest model (' + best.m.n + ', ' + money(best.cost)
        + '/mo) costs more than the ' + money(value) + ' of work it offsets. Raise volume, minutes saved or the hourly rate.';
    }}
  }}
  ['iwi-tasks','iwi-in','iwi-out','iwi-mins','iwi-rate','iwi-cache'].forEach(function(id) {{
    document.getElementById(id).addEventListener('input', compute);
  }});
  compute();
}})();
</script>"""

    faq = [
        {"q": "Is using an LLM API worth it?",
         "a": ("It depends on volume and how much human time each call offsets. At high volume on a clear task, "
               "cost per task is cents while the offset is real minutes, so ROI is strong. For one-off or "
               "zero-error-tolerance work it often isn't — the calculator above shows the break-even for your case.")},
        {"q": "Which model gives the best ROI?",
         "a": ("Since the work value is the same whichever model does it, the cheapest model that meets your quality "
               "bar has the highest ROI. The calculator ranks all our models by cost for your token mix — but a budget "
               "model that needs review can erase its savings, so weigh quality, not just price.")},
        {"q": "How do you calculate the API cost?",
         "a": (f"From each model's official per-token input/output (and cached) price, verified {month}, at the volume "
               "and token sizes you enter — the same engine as the main calculator. We never quote a monthly price.")},
        {"q": "What about prompt caching and batch discounts?",
         "a": ("Caching only lowers cost (set your cached share in the calculator); the worked examples assume none, so "
               "they're conservative. Batch APIs cut cost further on non-interactive jobs — see each model's pricing page.")},
    ]
    title = "Is an LLM API Worth It? ROI & Break-Even Calculator | WizardCost"
    desc = ("Is an LLM API worth the cost? Price every model at your volume and see ROI, net savings and break-even — "
            "which model pays for itself, and when it doesn't.")
    crumb = '<a href="index.html">LLM</a> / is it worth it'
    h1 = "Is an LLM API worth it?"
    lead = ("An LLM call replaces work a person would do. Price every model at your real workload, value the time it "
            "offsets, and see which models pay for themselves — and when none do.")
    return _shell(parts, title=title, desc=desc, canonical=canonical, prefix=prefix,
                  crumb=crumb, h1=h1, lead=lead, month=month, body=body, faq=faq, nav=nav)

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
        ("methodology.html", lambda: render_methodology(eng, data, site, month, nav, parts)),
        ("is-llm-worth-it.html", lambda: render_is_llm_worth_it(eng, data, site, month, nav, parts)),
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
