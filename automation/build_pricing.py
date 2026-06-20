"""build_pricing.py — generátor <slug>-pricing.html pro 7 toolů (zrcadlo build_vs_pages).

Plně data-driven: karty plánů (vč. hosting variant Cloud / VPS / vlastní server),
srovnávací tabulka na runs objemech, <meta>, JSON-LD FAQ, editorial z
data/pricing-editorial.json — VŠECHNY ceny z enginu (cheapest_monthly), reálné
scrapnuté z tools.json. Jednotka = runs (NE „ops"). Volume body sjednoceny s
pairs.json: [1000, 5000, 20000, 100000].

P (orchestrátor) zavolá v main():  build_pricing_pages(data["tools"], site,
data.get("_meta", {}), check=...)  — viz build_vs_pages.

KONTRAKT (read-only závislosti):
  build_hosting.expand_hosting_variants(tools) / hw_tier_for(tool, runs)
  _root_engine().cheapest_monthly(tool|variant, runs, steps=3)  → {cost, label, est}

Malé helpery (_root_engine, _logo, _month_year, _site_prefix, _html_escape,
_fmt_usd) jsou ZKOPÍROVANÉ z build.py (NE importované — bránilo by to cyklickému
importu build.py ↔ build_pricing). EMAILCAP + nav markup zkopírovány z render_vs_page.
"""
from __future__ import annotations
import json
from pathlib import Path

from build_hosting import expand_hosting_variants, hw_tier_for

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "tools.json"
EDITORIAL = ROOT / "data" / "pricing-editorial.json"

# 7 toolů, v pořadí podle search-priority (jako pairs.json)
PRICING_SLUGS = ["zapier", "make", "n8n", "pipedream", "activepieces",
                 "automatisch", "node-red"]
VOLUMES = [1000, 5000, 20000, 100000]   # runs/mo — sjednoceno s pairs.json
STEPS = 3                               # workflows steps — stejné assumptions jako homepage DEMO

# MailerLite price-drop alerts endpoint — schválený owner 2026-06-11 (shodný s build.py).
EMAILCAP_ACTION = "https://assets.mailerlite.com/jsonp/2426816/forms/190009354045359550/subscribe"

# GA4/ANALYTICS bloky vkládá build.py až po generování → pro --check je strip.
AN_START = "<!-- ANALYTICS (build.py) -->"
AN_END = "<!-- /ANALYTICS -->"
GA_START = "<!-- GA4 (build.py) -->"
GA_END = "<!-- /GA4 -->"


# ── helpery zkopírované z build.py (NEimportovat — cyklický import) ──────────
def _root_engine():
    """Root build.py kvůli cheapest_monthly — JEDINÁ kopie cost logiky (parita s JS)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rootbuild", ROOT.parent / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _logo(slug: str) -> str:
    domain = {"n8n": "n8n.io", "make": "make.com", "pipedream": "pipedream.com",
              "zapier": "zapier.com", "activepieces": "activepieces.com",
              "automatisch": "automatisch.io", "node-red": "nodered.org"}[slug]
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


def _month_year(tools_meta: dict) -> str:
    import datetime as _dt
    lr = (tools_meta or {}).get("last_reviewed")
    if lr:
        try:
            return _dt.date(*[int(x) for x in lr.split("-")]).strftime("%B %Y")
        except ValueError:
            pass
    return "June 2026"


def _site_prefix(domain: str, base_path: str) -> str:
    bp = (base_path or "").strip("/")
    return f"https://{domain}/{bp}".rstrip("/") if bp else f"https://{domain}"


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _fmt_usd(cost, est: bool) -> str:
    body = f"{cost:,.2f}".rstrip("0").rstrip(".") if isinstance(cost, float) else f"{cost:,}"
    return ("~$" if est else "$") + body


def _strip_injected(text: str) -> str:
    """Odstraní GA4/ANALYTICS bloky (vkládané build.py po generování) pro --check porovnání."""
    import re as _re
    for s, e in ((GA_START, GA_END), (AN_START, AN_END)):
        text = _re.sub(_re.escape(s) + r".*?" + _re.escape(e) + r"\n?\s*", "", text, flags=_re.S)
    return text


# ── helpery generátoru ──────────────────────────────────────────────────────
_KIND_LABEL = {
    "saas": "Cloud",
    "cloud": "Cloud",
    "vps": "Self-host · VPS",
    "own": "Self-host · own server",
}


def _engine_cost(engine, variant: dict, runs: int, billing: str = "monthly"):
    """cheapest_monthly → dict {cost,label,est}; chyba → None (přeskočí kartu/řádek)."""
    return engine.cheapest_monthly(variant, runs, STEPS, billing=billing)


def _engine_costs(engine, variant: dict, runs: int):
    """Vrátí (monthly, annual) dvojici dictů; annual může == monthly (žádná sleva)."""
    m = _engine_cost(engine, variant, runs, "monthly")
    a = _engine_cost(engine, variant, runs, "annual")
    return m, a


def _discount_pct(monthly: float, annual: float) -> int | None:
    """Sleva % roční vs měsíční účtování; None když roční sleva neexistuje."""
    if not isinstance(monthly, (int, float)) or not isinstance(annual, (int, float)):
        return None
    if monthly <= 0 or annual >= monthly:
        return None
    return round((1 - annual / monthly) * 100)


def _label_runs(label: str) -> str:
    """Engine vrací interní label s '+ops' (overage) — user-facing musí být 'runs'."""
    return label.replace("+ops", "+ overage")


def _plan_cards_for_variant(engine, variant: dict) -> str:
    """Karty: pro každý VOLUME jedna karta s reálnou cenou (monthly + roční, je-li).

    Cena nese data-month/data-annual atributy → JS toggle přepíná zobrazení.
    Default = monthly. Plán bez annualUsd → annual == monthly (žádná roční řádka)."""
    kind = variant.get("hostingKind", "saas")
    cards = []
    for runs in VOLUMES:
        r, ra = _engine_costs(engine, variant, runs)
        if r is None:
            continue
        price_m = _fmt_usd(r["cost"], r["est"])
        price_a = _fmt_usd(ra["cost"], ra["est"]) if ra else price_m
        suffix = "/mo electricity" if kind == "own" else "/mo"
        pct = _discount_pct(r["cost"], ra["cost"]) if ra else None
        detail = [f"<li>{runs:,} runs / month</li>", f"<li>{_html_escape(_label_runs(r['label']))}</li>"]
        if kind == "own":
            tier = hw_tier_for(variant, runs)
            if tier:
                detail.append(f"<li>+ ~${tier.get('hwOneOff', 0):,} hardware (one-off)</li>")
                if tier.get("spec"):
                    detail.append(f'<li class="spec">{_html_escape(tier["spec"])}</li>')
        # roční řádek pod cenou: jen když plán reálně nabízí roční slevu
        if pct is not None:
            annual_note = (f'        <div class="plan-annual" data-month="" '
                           f'data-annual="{price_a}{suffix} billed annually — save {pct}%">'
                           f'</div>\n')
        elif kind not in ("own", "vps") and not variant.get("selfHostOnly"):
            annual_note = ('        <div class="plan-annual" data-month="" '
                           'data-annual="No annual pricing tracked yet"></div>\n')
        else:
            annual_note = ""
        cards.append(
            '      <div class="plan-card">\n'
            f'        <div class="plan-name">{runs:,} runs</div>\n'
            f'        <div class="plan-price"><span class="price-num" data-month="{price_m}" '
            f'data-annual="{price_a}">{price_m}</span><span class="price-suffix">{suffix}</span></div>\n'
            f'{annual_note}'
            f'        <ul class="plan-detail">\n          ' + "\n          ".join(detail) + "\n"
            "        </ul>\n      </div>")
    return "\n".join(cards)


def _variant_section(engine, variant: dict) -> str:
    kind = variant.get("hostingKind", "saas")
    label = _KIND_LABEL.get(kind, "Plans")
    if kind == "own":
        note = ('<p class="plan-note">Monthly figure is electricity only — the software is free. '
                'One-off hardware cost (a mini PC or Pi you keep) is shown per volume.</p>')
    elif kind == "vps":
        note = ('<p class="plan-note">Monthly figure is the rented server (VPS + database) that '
                'scales with volume — the software itself is free.</p>')
    else:
        note = ""
    cards = _plan_cards_for_variant(engine, variant)
    if not cards:
        return ""
    return (f'    <h3 class="variant-head">{label}</h3>\n'
            f'    <div class="plans-grid">\n{cards}\n    </div>\n    {note}')


def _comparison_table(engine, by_slug: dict, focus_slug: str, vol: int) -> str:
    """„<Tool> vs alternativy" na daném runs objemu — ceny VŠECH 7 toolů z enginu.

    Price cell nese data-month/data-annual → JS toggle přepíná i tabulku.
    Plán bez roční slevy: annual == monthly (cell se nemění)."""
    rows = []
    ordered = [focus_slug] + [s for s in PRICING_SLUGS if s != focus_slug]
    for s in ordered:
        t = by_slug[s]
        r = engine.cheapest_monthly(t, vol, STEPS)
        if r is None:
            continue
        ra = engine.cheapest_monthly(t, vol, STEPS, billing="annual")
        price_m = _fmt_usd(r["cost"], r["est"])
        price_a = _fmt_usd(ra["cost"], ra["est"]) if ra else price_m
        is_focus = s == focus_slug
        name = (f'<strong>{t["name"]}</strong>' if is_focus
                else f'<a href="{s}-pricing.html">{t["name"]}</a>')
        sh = ('<span class="tag-yes">Yes (free SW)</span>' if t.get("selfHostable")
              else '<span class="tag-no">No</span>')
        rows.append(
            f"        <tr><td>{name}</td>"
            f'<td class="price-cell"><span class="price-num" data-month="{price_m}" '
            f'data-annual="{price_a}">{price_m}</span></td>'
            f'<td>{t["integrations"]:,}+</td>'
            f"<td>{sh}</td></tr>")
    return "\n".join(rows)


def _faq_with_prices(engine, tool: dict, ed_faq: list, by_slug: dict) -> list[dict]:
    """Editorial FAQ (bez cen) + generované price-bearing otázky (z enginu)."""
    name = tool["name"]
    faq = []
    # price-bearing: kolik to stojí měsíčně přes všechny volume body
    parts = []
    for vol in VOLUMES:
        r = engine.cheapest_monthly(tool, vol, STEPS)
        if r:
            parts.append(f"{_fmt_usd(r['cost'], r['est'])} at {vol:,} runs")
    if parts:
        faq.append({
            "q": f"How much does {name} cost per month?",
            "a": (f"On the cheapest qualifying plan (3-step workflows, monthly billing) {name} runs "
                  + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
                  + ". See the plans and comparison table above for the full breakdown."),
        })
    # cheaper-than: vůči nejlevnější alternativě na 20k
    vol = 20000
    rt = engine.cheapest_monthly(tool, vol, STEPS)
    alts = [(s, engine.cheapest_monthly(by_slug[s], vol, STEPS))
            for s in PRICING_SLUGS if s != tool["slug"]]
    alts = [(s, r) for s, r in alts if r]
    if rt and alts:
        cheapest = min(alts, key=lambda x: x[1]["cost"])
        cs, cr = cheapest
        if cr["cost"] < rt["cost"]:
            faq.append({
                "q": f"What is cheaper than {name}?",
                "a": (f"At {vol:,} runs/month the cheapest pick we track is "
                      f'<a href="{cs}-pricing.html">{by_slug[cs]["name"]}</a> at '
                      f"{_fmt_usd(cr['cost'], cr['est'])} vs {name} at "
                      f"{_fmt_usd(rt['cost'], rt['est'])}. Use the calculator for your exact volume."),
            })
    # editorial (price-free) na konec
    for f in ed_faq:
        faq.append({"q": f["q"], "a": f["a"]})
    faq.append({
        "q": "How accurate are these prices?",
        "a": ("Taken from official pricing pages and verified by hand. Values marked ~ are estimates "
              "for custom enterprise tiers. Every change we record lands in the "
              '<a href="changelog.html">price changelog</a>.'),
    })
    return faq


_WORTH_CLS = {"good": "tag-yes", "warn": "tag-warn", "bad": "tag-no"}


def render_pricing_page(slug: str, tools: list[dict], variants_by_base: dict,
                        editorial: dict, site: dict, tools_meta: dict, engine) -> str:
    by_slug = {t["slug"]: t for t in tools}
    tool = by_slug[slug]
    name = tool["name"]
    ed = editorial["tools"][slug]
    month_year = _month_year(tools_meta)
    prefix = _site_prefix(site.get("domain", "wizardcost.com"), site.get("base_path", ""))
    canonical = f"{prefix}/{slug}-pricing.html"

    # ── plán sekce: hosting varianty (Cloud / VPS / vlastní server) ──
    variants = variants_by_base.get(slug, [])
    plan_sections = "\n".join(s for s in (_variant_section(engine, v) for v in variants) if s)

    # ── srovnávací tabulka (20k runs) ──
    cmp_vol = 20000
    cmp_rows = _comparison_table(engine, by_slug, slug, cmp_vol)

    # ── when worth it ──
    worth_rows = "\n".join(
        f'        <tr><td>{_html_escape(w["case"])}</td>'
        f'<td class="{_WORTH_CLS.get(w["tier"], "tag-no")}">{_html_escape(w["verdict"])}</td></tr>'
        for w in ed.get("whenWorthIt", []))

    # ── FAQ (editorial + generované ceny) ──
    faq = _faq_with_prices(engine, tool, ed.get("faq", []), by_slug)
    faq_ld = json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": f["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq],
    }, ensure_ascii=False, indent=2)
    faq_html = "\n".join(
        '      <div class="faq-item">\n'
        '        <button class="faq-q" onclick="toggleFaq(this)">' + f["q"]
        + '<svg class="faq-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" '
          'stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></button>\n'
        f'        <div class="faq-a">{f["a"]}</div>\n      </div>' for f in faq)

    # ── related compare → dedikované X-vs-Y stránky (interní linky pro SEO) ──
    # Linkujeme všech 6 head-to-head stránek tohoto nástroje (slug v pořadí
    # PRICING_SLUGS — všechny páry existují) místo jen compare.html?tools.
    def _vs_slug(a, b):
        return f"{a}-vs-{b}" if PRICING_SLUGS.index(a) < PRICING_SLUGS.index(b) else f"{b}-vs-{a}"
    related = "\n".join(
        f'      <a href="{_vs_slug(slug, o)}.html" class="related-card">\n'
        f'        <div class="related-card-name">{_html_escape(name)} vs {_html_escape(by_slug[o]["name"])}</div>\n'
        f'        <div class="related-card-desc">Pricing &amp; features compared</div>\n'
        f"      </a>" for o in PRICING_SLUGS if o != slug)

    # ── breadcrumb JSON-LD (SERP breadcrumbs + topická struktura) ──
    home_url = f"https://{site.get('domain', 'wizardcost.com')}/"
    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": home_url},
            {"@type": "ListItem", "position": 2, "name": "Automation tools", "item": f"{prefix}/tools.html"},
            {"@type": "ListItem", "position": 3, "name": f"{name} pricing", "item": canonical},
        ],
    }, ensure_ascii=False, indent=2)

    # ── outbound CTA (affiliate jen s hasAffiliate) ──
    if tool.get("hasAffiliate"):
        primary = (f'<a href="{tool["affiliateUrl"]}" target="_blank" rel="noopener sponsored" '
                   f'class="btn-primary">Try {name} free →</a>')
    else:
        primary = (f'<a href="{tool["homepage"]}" target="_blank" rel="noopener" '
                   f'class="btn-primary">Visit {name} →</a>')

    # ── <meta description> s reálnými cenami z dat ──
    desc_parts = []
    for vol in (VOLUMES[0], VOLUMES[2], VOLUMES[3]):
        r = engine.cheapest_monthly(tool, vol, STEPS)
        if r:
            desc_parts.append(f"{_fmt_usd(r['cost'], r['est'])} at {vol:,} runs")
    desc = (f"{name} pricing 2026: " + ", ".join(desc_parts)
            + f". Real plans, self-host options and how {name} compares on cost per run.")
    title = f"{name} Pricing 2026 — Plans, Run Limits &amp; Real Cost | AutomationCost.io"

    # ── Citation-ready key facts (GEO playbook A10 #2): one dated, standalone,
    # quotable sentence with the headline numbers, in SSR HTML — the prime thing
    # an LLM lifts for "how much does X cost". Computed from the engine, not typed.
    _kf_lo = engine.cheapest_monthly(tool, VOLUMES[0], STEPS)
    _kf_hi = engine.cheapest_monthly(tool, VOLUMES[3], STEPS)
    key_facts_html = ""
    if _kf_lo and _kf_hi:
        _selfhost = "self-host" in (_kf_lo.get("label", "") + _kf_hi.get("label", "")).lower()
        _tail = (" Self-hosting is free open-source software — the figure is the server it "
                 "runs on, not a tool fee." if _selfhost else "")
        _kf = (f"As of {month_year}, the cheapest plan we track for {name} costs "
               f"{_fmt_usd(_kf_lo['cost'], _kf_lo['est'])} per month at {VOLUMES[0]:,} runs and "
               f"{_fmt_usd(_kf_hi['cost'], _kf_hi['est'])} at {VOLUMES[3]:,} runs "
               f"(cheapest qualifying plan, 3-step workflows, monthly billing), from "
               f"{name}'s official pricing, verified by hand.{_tail}")
        key_facts_html = ('<p class="hero-facts" style="margin-top:14px;font-size:0.95rem;'
                          f'opacity:0.88;line-height:1.6;max-width:680px;">{_kf}</p>')

    css = _PRICING_CSS

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build_pricing.py z data/tools.json + data/pricing-editorial.json — needituj ručně -->
  <title>{title}</title>
  <meta name="description" content="{_html_escape(desc)}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="AutomationCost.io">
  <meta property="og:title" content="{_html_escape(f'{name} Pricing 2026 — Plans, Run Limits & Real Cost')}">
  <meta property="og:description" content="{_html_escape(desc)}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{prefix}/og-image.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{prefix}/og-image.png">
  <script type="application/ld+json">
{faq_ld}
  </script>
  <script type="application/ld+json">
{breadcrumb_ld}
  </script>
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
{css}
  </style>
  <link rel="stylesheet" href="app.css">
</head>
<body class="ac anim">

<div id="ac-progress"></div>

<nav class="ac-nav">
  <a href="/" class="logo">
    <svg class="logo-icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs><linearGradient id="acmk" x1="14" y1="10" x2="30" y2="38" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#2fe39c"></stop><stop offset="1" stop-color="#0ea66e"></stop></linearGradient></defs>
      <path d="M28.5 10.5 L13.5 24 L28.5 37.5" stroke="url(#acmk)" stroke-width="6.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M 36.5 17.8 Q 37.864 22.636 42.7 24 Q 37.864 25.364 36.5 30.2 Q 35.136 25.364 30.3 24 Q 35.136 22.636 36.5 17.8 Z" fill="#eafff5"></path>
    </svg>
    Automation<span>Cost</span><span class="io" style="font-size:0.72em; margin-left:7px;">by WizardCost</span>
  </a>
  <div class="ac-links">
    <a href="compare.html" class="ac-hide-sm">Compare</a>
    <a href="limits.html" class="ac-hide-sm">Pricing</a>
    <div class="ac-dd">
      <button class="ac-dd-btn" aria-expanded="false" aria-haspopup="true">More
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="ac-dd-menu">
        <a href="index.html">AutomationCost home</a>
        <a href="tools.html">Tools</a>
        <a href="changelog.html">Changelog</a>
        <a href="price-history.html">Price history</a>
        <div class="ac-dd-sep">Pricing guides</div>
        <a href="n8n-pricing.html"><img src="https://www.google.com/s2/favicons?domain=n8n.io&sz=32" alt="">n8n Pricing</a>
        <a href="make-pricing.html"><img src="https://www.google.com/s2/favicons?domain=make.com&sz=32" alt="">Make Pricing</a>
        <a href="zapier-pricing.html"><img src="https://www.google.com/s2/favicons?domain=zapier.com&sz=32" alt="">Zapier Pricing</a>
        <a href="pipedream-pricing.html"><img src="https://www.google.com/s2/favicons?domain=pipedream.com&sz=32" alt="">Pipedream Pricing</a>
        <a href="activepieces-pricing.html"><img src="https://www.google.com/s2/favicons?domain=activepieces.com&sz=32" alt="">Activepieces Pricing</a>
        <a href="automatisch-pricing.html"><img src="https://www.google.com/s2/favicons?domain=automatisch.io&sz=32" alt="">Automatisch Pricing</a>
        <a href="node-red-pricing.html"><img src="https://www.google.com/s2/favicons?domain=nodered.org&sz=32" alt="">Node-RED Pricing</a>
        <div class="ac-dd-sep">Other wizards</div>
        <a href="/llm/">LLMCost <span class="ac-dd-tag">Live</span></a>
        <span class="ac-dd-soon">EmailCost <span class="ac-dd-tag soon">Soon</span></span>
        <span class="ac-dd-soon">CRMCost <span class="ac-dd-tag soon">Soon</span></span>
      </div>
    </div>
    <a href="calculator.html" class="ac-cta">Calculator
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8"><polyline points="9 18 15 12 9 6"/></svg>
    </a>
  </div>
</nav>

<div class="wrap">

  <div class="page-hero">
    <div class="tool-badge"><img src="{_logo(slug)}" alt="{name}">{name}</div>
    <h1>{ed["h1"]}</h1>
    <p>{ed["intro"]}</p>
    <div class="cta-row">
      {primary}
      <a href="calculator.html" class="btn-secondary">Calculate my {name} cost</a>
      <a href="compare.html" class="btn-secondary">Compare all 7 tools</a>
    </div>
    <div class="hero-trust">Prices verified {month_year} · taken from {name}'s official pricing · all figures per <strong>run</strong></div>
    {key_facts_html}
  </div>

  <div class="warning-box"><strong>Heads up:</strong> {ed["warn"]}</div>

  <div class="section">
    <h2>{name} plans &amp; real cost</h2>
    <p class="section-sub">Cheapest qualifying plan at four typical run volumes (3-step workflows) — prices generated live from our data, never hand-typed. Toggle to see prices when billed annually.</p>
    <div class="billing-toggle" role="group" aria-label="Billing period">
      <button type="button" class="bt-opt is-active" data-billing="month" aria-pressed="true">Monthly</button>
      <button type="button" class="bt-opt" data-billing="annual" aria-pressed="false">Annual</button>
    </div>
{plan_sections}
  </div>

  <div class="section">
    <h2>{name} vs alternatives</h2>
    <p class="section-sub">Price for {cmp_vol:,} runs / month across every tool we track. Use the Monthly / Annual toggle above to switch how the prices are billed.</p>
    <table class="comparison-table">
      <thead><tr><th>Tool</th><th>Price for {cmp_vol:,} runs <span class="th-billing" data-month="(monthly)" data-annual="(billed annually)">(monthly)</span></th><th>Integrations</th><th>Self-host</th></tr></thead>
      <tbody>
{cmp_rows}
      </tbody>
    </table>
    <p style="margin-top:12px"><a href="{slug}-alternatives.html">See all {name} alternatives →</a> · <a href="cheapest-automation-tool.html">Cheapest automation tool →</a> · <a href="compare.html">Full interactive comparison →</a></p>
  </div>

  <div class="section">
    <h2>When {name} is worth it</h2>
    <table class="comparison-table">
      <thead><tr><th>Use case</th><th>Verdict</th></tr></thead>
      <tbody>
{worth_rows}
      </tbody>
    </table>
  </div>

  <!-- EMAILCAP:HTML:START — price-drop alerts (pricing copy variant, generováno).
       Disclosure text schválen ownerem 2026-06-11 — NEMĚNIT bez jeho OK. -->
  <!-- price-drop alerts e-mail form disabled 2026-06-16 — compliance: no e-mail collection while the project stays faceless (no MailerLite signup, no consent banner needed). Previous markup is in git history; re-enable by restoring the price-alerts section + EMAILCAP_ACTION. -->
  <!-- EMAILCAP:HTML:END -->

  <div class="section">
    <h2>Frequently asked questions</h2>
    <div class="faq" style="margin-top:8px;">
{faq_html}
    </div>
  </div>

  <div class="section">
    <h2>Compare {name} head-to-head</h2>
    <div class="related-grid">
{related}
    </div>
  </div>

</div>

<footer>
  <div style="margin-bottom:6px;color:#6b7a99">&copy; 2026 AutomationCost.io · part of WizardCost</div>
  <div>AutomationCost.io · Independent, data-driven comparisons · Prices verified {month_year}</div>
  <div style="margin-top:6px">Some links are affiliate links — we may earn a commission at no extra cost to you. This never affects our rankings or recommendations.</div>
  <div style="margin-top:6px"><a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> · <a href="affiliate.html">Affiliate Disclosure</a></div>
</footer>

<script>
function toggleFaq(el) {{ el.closest(".faq-item").classList.toggle("open"); }}

/* ── billing Monthly/Annual toggle — vanilla, default monthly ── */
(function () {{
  var toggle = document.querySelector(".billing-toggle");
  if (!toggle) return;
  function apply(period) {{
    var attr = period === "annual" ? "data-annual" : "data-month";
    document.querySelectorAll("[" + attr + "]").forEach(function (el) {{
      if (el.classList.contains("bt-opt")) return;
      el.textContent = el.getAttribute(attr) || "";
    }});
    toggle.querySelectorAll(".bt-opt").forEach(function (b) {{
      var on = b.getAttribute("data-billing") === period;
      b.classList.toggle("is-active", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
    }});
  }}
  toggle.querySelectorAll(".bt-opt").forEach(function (b) {{
    b.addEventListener("click", function () {{ apply(b.getAttribute("data-billing")); }});
  }});
}})();

/* ── EMAILCAP:JS:START — wire every .price-alerts form on the page ── */
(function () {{
  var OK_MSG  = 'Check your inbox to confirm your subscription.';
  var ERR_MSG = 'Something went wrong — please try again.';
  var OK_ICON  = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
  var ERR_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
  function show(msgEl, ok, text) {{
    msgEl.className = 'pa-msg show ' + (ok ? 'ok' : 'err');
    msgEl.innerHTML = (ok ? OK_ICON : ERR_ICON) + '<span>' + text + '</span>';
  }}
  document.querySelectorAll('.price-alerts form.pa-form').forEach(function (form) {{
    form.addEventListener('submit', function (e) {{
      e.preventDefault();
      var card  = form.closest('.price-alerts');
      var input = form.querySelector('.pa-input');
      var btn   = form.querySelector('.pa-btn');
      var msgEl = card.querySelector('.pa-msg');
      if (!input.value || input.validity.typeMismatch || input.value.indexOf('@') < 1) {{
        show(msgEl, false, 'Please enter a valid email address.');
        input.focus();
        return;
      }}
      btn.disabled = true;
      btn.textContent = 'Subscribing…';
      fetch(form.action, {{ method: 'POST', body: new FormData(form) }})
        .then(function (r) {{ if (!r.ok) throw new Error(r.status); }})
        .then(function () {{ card.classList.add('subscribed'); show(msgEl, true, OK_MSG); }})
        .catch(function () {{
          btn.disabled = false;
          btn.textContent = 'Get price alerts';
          show(msgEl, false, ERR_MSG);
        }});
    }});
  }});
}})();
/* ── EMAILCAP:JS:END ── */
</script>
<a href="calculator.html" class="funnel-fab" aria-label="Find my cheapest tool"><svg width="17" height="17" viewBox="0 0 48 48" fill="none"><path d="M29 11 L15 24 L29 37" stroke="#04130d" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round"/><circle cx="34.5" cy="24" r="3.4" fill="#04130d"/></svg> Find my best tool</a>
<script src="app.js"></script>
</body>
</html>
"""


def build_pricing_pages(tools: list[dict], site: dict, tools_meta: dict,
                        *, check: bool = False) -> list[str]:
    """Vygeneruje <slug>-pricing.html pro 7 toolů z dat (zrcadlo build_vs_pages).

    check=True → nezapisuje, vrátí seznam souborů které by se změnily (CI --check;
    porovnává bez GA4/analytics bloků). Jinak zapíše a vrátí seznam změněných."""
    if not EDITORIAL.exists():
        return []
    editorial = json.loads(EDITORIAL.read_text(encoding="utf-8"))
    engine = _root_engine()
    by_slug = {t["slug"]: t for t in tools}

    # hosting varianty seskupené podle base slug (variantOf)
    variants_by_base: dict[str, list[dict]] = {}
    for v in expand_hosting_variants(tools):
        variants_by_base.setdefault(v.get("variantOf", v["slug"]), []).append(v)

    out = []
    for slug in PRICING_SLUGS:
        if slug not in by_slug or slug not in editorial.get("tools", {}):
            continue
        target = ROOT / f"{slug}-pricing.html"
        rendered = render_pricing_page(slug, tools, variants_by_base, editorial,
                                       site, tools_meta, engine)
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        dirty = existing is None or _strip_injected(existing) != rendered
        if check:
            if dirty:
                out.append(target.name)
        elif dirty:
            target.write_text(rendered, encoding="utf-8")
            out.append(target.name)
    return out


# ════════════════════════════════════════════════════════════════════════════
# Programmatic long-tail SEO stránky (data-driven, engine ceny):
#   <slug>-alternatives.html   — „best <Tool> alternatives" (7×)
#   cheapest-automation-tool.html — „cheapest automation tool" (1×)
# Sdílí shell/CSS/nav/footer s pricing stránkami. Fair-competition neutral:
# řazení podle CENY (objektivní fakt z enginu), žádné „X× cheaper"/zlehčování;
# ceny VŽDY z enginu. Jen interní odkazy (žádný affiliate placement tady).
# ════════════════════════════════════════════════════════════════════════════
ALT_VOL = 20000   # reprezentativní objem pro alternatives ranking

def _seo_breadcrumb_ld(site: dict, prefix: str, leaf: str, canonical: str) -> str:
    return json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home",
             "item": f"https://{site.get('domain', 'wizardcost.com')}/"},
            {"@type": "ListItem", "position": 2, "name": "Automation tools", "item": f"{prefix}/tools.html"},
            {"@type": "ListItem", "position": 3, "name": leaf, "item": canonical},
        ],
    }, ensure_ascii=False, indent=2)


def _seo_faq(faq: list[dict]) -> tuple[str, str]:
    faq_ld = json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": f["q"],
                        "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq],
    }, ensure_ascii=False, indent=2)
    faq_html = "\n".join(
        '      <div class="faq-item">\n'
        '        <button class="faq-q" onclick="toggleFaq(this)">' + f["q"]
        + '<svg class="faq-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" '
          'stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></button>\n'
        f'        <div class="faq-a">{f["a"]}</div>\n      </div>' for f in faq)
    return faq_ld, faq_html


def _seo_shell(*, title, desc, canonical, prefix, month_year, h1, intro_html,
               body_html, faq_ld, breadcrumb_ld, faq_html) -> str:
    css = _PRICING_CSS
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build_pricing.py (build_seo_pages) z data/tools.json — needituj ručně -->
  <title>{title}</title>
  <meta name="description" content="{_html_escape(desc)}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="AutomationCost.io">
  <meta property="og:title" content="{_html_escape(title.split(' | ')[0].replace('&amp;', '&'))}">
  <meta property="og:description" content="{_html_escape(desc)}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{prefix}/og-image.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{prefix}/og-image.png">
  <script type="application/ld+json">
{faq_ld}
  </script>
  <script type="application/ld+json">
{breadcrumb_ld}
  </script>
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
{css}
  </style>
  <link rel="stylesheet" href="app.css">
</head>
<body class="ac anim">

<div id="ac-progress"></div>

<nav class="ac-nav">
  <a href="/" class="logo">
    <svg class="logo-icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs><linearGradient id="acmk" x1="14" y1="10" x2="30" y2="38" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#2fe39c"></stop><stop offset="1" stop-color="#0ea66e"></stop></linearGradient></defs>
      <path d="M28.5 10.5 L13.5 24 L28.5 37.5" stroke="url(#acmk)" stroke-width="6.8" stroke-linecap="round" stroke-linejoin="round"></path>
      <path d="M 36.5 17.8 Q 37.864 22.636 42.7 24 Q 37.864 25.364 36.5 30.2 Q 35.136 25.364 30.3 24 Q 35.136 22.636 36.5 17.8 Z" fill="#eafff5"></path>
    </svg>
    Automation<span>Cost</span><span class="io" style="font-size:0.72em; margin-left:7px;">by WizardCost</span>
  </a>
  <div class="ac-links">
    <a href="compare.html" class="ac-hide-sm">Compare</a>
    <a href="limits.html" class="ac-hide-sm">Pricing</a>
    <div class="ac-dd">
      <button class="ac-dd-btn" aria-expanded="false" aria-haspopup="true">More
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div class="ac-dd-menu">
        <a href="index.html">AutomationCost home</a>
        <a href="tools.html">Tools</a>
        <a href="changelog.html">Changelog</a>
        <a href="price-history.html">Price history</a>
        <div class="ac-dd-sep">Pricing guides</div>
        <a href="n8n-pricing.html"><img src="https://www.google.com/s2/favicons?domain=n8n.io&sz=32" alt="">n8n Pricing</a>
        <a href="make-pricing.html"><img src="https://www.google.com/s2/favicons?domain=make.com&sz=32" alt="">Make Pricing</a>
        <a href="zapier-pricing.html"><img src="https://www.google.com/s2/favicons?domain=zapier.com&sz=32" alt="">Zapier Pricing</a>
        <a href="pipedream-pricing.html"><img src="https://www.google.com/s2/favicons?domain=pipedream.com&sz=32" alt="">Pipedream Pricing</a>
        <a href="activepieces-pricing.html"><img src="https://www.google.com/s2/favicons?domain=activepieces.com&sz=32" alt="">Activepieces Pricing</a>
        <a href="automatisch-pricing.html"><img src="https://www.google.com/s2/favicons?domain=automatisch.io&sz=32" alt="">Automatisch Pricing</a>
        <a href="node-red-pricing.html"><img src="https://www.google.com/s2/favicons?domain=nodered.org&sz=32" alt="">Node-RED Pricing</a>
        <div class="ac-dd-sep">Other wizards</div>
        <a href="/llm/">LLMCost <span class="ac-dd-tag">Live</span></a>
        <span class="ac-dd-soon">EmailCost <span class="ac-dd-tag soon">Soon</span></span>
        <span class="ac-dd-soon">CRMCost <span class="ac-dd-tag soon">Soon</span></span>
      </div>
    </div>
    <a href="calculator.html" class="ac-cta">Calculator
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8"><polyline points="9 18 15 12 9 6"/></svg>
    </a>
  </div>
</nav>

<div class="wrap">

  <div class="page-hero">
    <h1>{h1}</h1>
    <p>{intro_html}</p>
    <div class="cta-row">
      <a href="calculator.html" class="btn-primary">Find my cheapest tool →</a>
      <a href="compare.html" class="btn-secondary">Compare all 7 tools</a>
    </div>
    <div class="hero-trust">Prices generated live from our data · verified {month_year} · all figures per <strong>run</strong>, 3-step workflows</div>
  </div>

{body_html}

  <div class="section">
    <h2>Frequently asked questions</h2>
    <div class="faq" style="margin-top:8px;">
{faq_html}
    </div>
  </div>

</div>

<footer>
  <div style="margin-bottom:6px;color:#6b7a99">&copy; 2026 AutomationCost.io · part of WizardCost</div>
  <div>AutomationCost.io · Independent, data-driven comparisons · Prices verified {month_year}</div>
  <div style="margin-top:6px">Some links are affiliate links — we may earn a commission at no extra cost to you. This never affects our rankings or recommendations.</div>
  <div style="margin-top:6px"><a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> · <a href="affiliate.html">Affiliate Disclosure</a></div>
</footer>

<script>
function toggleFaq(el) {{ el.closest(".faq-item").classList.toggle("open"); }}
</script>
<a href="calculator.html" class="funnel-fab" aria-label="Find my cheapest tool"><svg width="17" height="17" viewBox="0 0 48 48" fill="none"><path d="M29 11 L15 24 L29 37" stroke="#04130d" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round"/><circle cx="34.5" cy="24" r="3.4" fill="#04130d"/></svg> Find my best tool</a>
<script src="app.js"></script>
</body>
</html>
"""


def _vs_slug(a: str, b: str) -> str:
    return f"{a}-vs-{b}" if PRICING_SLUGS.index(a) < PRICING_SLUGS.index(b) else f"{b}-vs-{a}"


def render_alternatives_page(slug: str, by_slug: dict, site: dict, tools_meta: dict, engine) -> str:
    tool = by_slug[slug]
    name = tool["name"]
    month_year = _month_year(tools_meta)
    prefix = _site_prefix(site.get("domain", "wizardcost.com"), site.get("base_path", ""))
    canonical = f"{prefix}/{slug}-alternatives.html"

    # ostatní nástroje seřazené podle ceny @ALT_VOL (objektivní fakt z enginu)
    others = [s for s in PRICING_SLUGS if s != slug]
    priced = []
    for s in others:
        r = engine.cheapest_monthly(by_slug[s], ALT_VOL, STEPS)
        if r:
            priced.append((s, r))
    priced.sort(key=lambda x: x[1]["cost"])
    cheapest_name = by_slug[priced[0][0]]["name"] if priced else ""
    oss = [by_slug[s]["name"] for s in others if by_slug[s].get("selfHostable")]

    # alternative karty (řádky tabulky) — cena, integrace, self-host, why + odkazy
    rows = []
    for s, r in priced:
        t = by_slug[s]
        sh = '<span class="tag-yes">Yes (free SW)</span>' if t.get("selfHostable") else '<span class="tag-no">No</span>'
        rows.append(
            f"        <tr><td><a href=\"{s}-pricing.html\"><strong>{_html_escape(t['name'])}</strong></a><br>"
            f"<span style=\"color:var(--muted);font-size:13px\">{_html_escape(t['tagline'])}</span></td>"
            f"<td class=\"price-cell\">{_fmt_usd(r['cost'], r['est'])}</td>"
            f"<td>{t['integrations']:,}+</td><td>{sh}</td>"
            f"<td><a href=\"{_vs_slug(slug, s)}.html\">{_html_escape(name)} vs {_html_escape(t['name'])} →</a></td></tr>")
    table = "\n".join(rows)

    oss_sentence = (f" For the open-source, self-hostable route like {name}, look at "
                    + ", ".join(oss[:-1]) + (f" or {oss[-1]}" if len(oss) > 1 else (oss[0] if oss else "")) + "."
                    ) if oss else ""
    intro = (f"Looking for a {name} alternative? We priced every tool we track at "
             f"{ALT_VOL:,} runs/month so you can compare on real cost, not marketing. "
             f"At that volume the lowest-cost option is <strong>{cheapest_name}</strong> — "
             f"but the closest fit depends on whether you want no-code, code-first or self-hosted.{oss_sentence} "
             "Full ranked prices and head-to-head links below.")

    body = f"""  <div class="section">
    <h2>{_html_escape(name)} alternatives, ranked by cost</h2>
    <p class="section-sub">Every alternative priced at {ALT_VOL:,} runs / month (cheapest qualifying plan, 3-step workflows) — generated live from our data. Self-hosted tools show the server bill, not a tool fee.</p>
    <table class="comparison-table">
      <thead><tr><th>Tool</th><th>Price at {ALT_VOL:,} runs/mo</th><th>Integrations</th><th>Self-host</th><th>Head-to-head</th></tr></thead>
      <tbody>
{table}
      </tbody>
    </table>
    <p style="margin-top:12px"><a href="{slug}-pricing.html">{_html_escape(name)} pricing in detail →</a> · <a href="compare.html">Full interactive comparison →</a></p>
  </div>"""

    faq = [
        {"q": f"What is the cheapest {name} alternative?",
         "a": (f"At {ALT_VOL:,} runs/month the lowest-cost alternative we track is {cheapest_name} "
               f"({_fmt_usd(priced[0][1]['cost'], priced[0][1]['est'])}/mo on its cheapest qualifying plan). "
               "Self-hosted tools can be lower still — their cost is just the server. See the ranked table above; "
               'your real number depends on volume — try the <a href="calculator.html">calculator</a>.')},
        {"q": f"Is there a free or open-source {name} alternative?",
         "a": ((f"Yes — {', '.join(oss)} are open-source and self-hostable, so beyond a server bill they're effectively free. "
                "Activepieces also has a cloud free tier (10 active flows, unlimited runs).") if oss
               else "Several tools offer free tiers — see the comparison for current limits.")},
        {"q": f"How accurate are these prices?",
         "a": ("Every figure is generated from each vendor's official pricing via our cost engine, verified "
               f"{month_year}. Values marked ~ are estimates for custom enterprise tiers. See the "
               '<a href="changelog.html">price changelog</a> for every change we record.')},
    ]
    faq_ld, faq_html = _seo_faq(faq)
    title = f"{name} Alternatives 2026 — Priced &amp; Compared | AutomationCost.io"
    desc = (f"The best {name} alternatives in 2026, priced at real run volumes. "
            f"{cheapest_name} is the lowest-cost option we track at {ALT_VOL:,} runs/mo — "
            f"compare every alternative on cost, integrations and self-hosting.")
    breadcrumb_ld = _seo_breadcrumb_ld(site, prefix, f"{name} alternatives", canonical)
    return _seo_shell(title=title, desc=desc, canonical=canonical, prefix=prefix,
                      month_year=month_year, h1=f"The best {_html_escape(name)} alternatives in 2026",
                      intro_html=intro, body_html=body, faq_ld=faq_ld,
                      breadcrumb_ld=breadcrumb_ld, faq_html=faq_html)


def render_cheapest_page(by_slug: dict, site: dict, tools_meta: dict, engine) -> str:
    month_year = _month_year(tools_meta)
    prefix = _site_prefix(site.get("domain", "wizardcost.com"), site.get("base_path", ""))
    canonical = f"{prefix}/cheapest-automation-tool.html"

    # matice tool × volume (cena z enginu), + nejlevnější per objem
    costs = {}   # slug -> {vol: r}
    for s in PRICING_SLUGS:
        costs[s] = {v: engine.cheapest_monthly(by_slug[s], v, STEPS) for v in VOLUMES}
    cheapest_per_vol = {}
    for v in VOLUMES:
        best = min((s for s in PRICING_SLUGS if costs[s][v]), key=lambda s: costs[s][v]["cost"])
        cheapest_per_vol[v] = best
    # řazení řádků podle ceny na největším objemu
    order = sorted(PRICING_SLUGS, key=lambda s: (costs[s][VOLUMES[-1]]["cost"] if costs[s][VOLUMES[-1]] else 9e9))

    head_cells = "".join(f"<th>{v:,} runs</th>" for v in VOLUMES)
    rows = []
    for s in order:
        t = by_slug[s]
        cells = []
        for v in VOLUMES:
            r = costs[s][v]
            cheap = ' class="cheap"' if cheapest_per_vol[v] == s else ""
            cells.append(f"<td{cheap}>{_fmt_usd(r['cost'], r['est']) if r else '—'}</td>")
        rows.append(f"        <tr><td><a href=\"{s}-pricing.html\">{_html_escape(t['name'])}</a></td>{''.join(cells)}</tr>")
    table = "\n".join(rows)

    lo, hi = VOLUMES[0], VOLUMES[-1]
    lo_name = by_slug[cheapest_per_vol[lo]]["name"]
    hi_name = by_slug[cheapest_per_vol[hi]]["name"]
    intro = (f"The cheapest automation tool depends on your volume and whether you'll self-host. "
             f"At {lo:,} runs/month the lowest price we track is <strong>{lo_name}</strong>; at "
             f"{hi:,} runs it's <strong>{hi_name}</strong>. Self-hosted, open-source tools "
             "(n8n, Activepieces, Automatisch, Node-RED) cost only the server they run on — effectively "
             "the floor at any volume. The full ranked matrix is below; prices come straight from each "
             "vendor's pricing, generated live.")

    summary = " · ".join(f"{v:,} runs: <strong>{_html_escape(by_slug[cheapest_per_vol[v]]['name'])}</strong>" for v in VOLUMES)
    body = f"""  <div class="section">
    <h2>Cheapest automation tool at each volume</h2>
    <p class="section-sub">Lowest-cost qualifying plan per tool, 3-step workflows, generated live from our data. Cheapest per column is highlighted.</p>
    <table class="comparison-table">
      <thead><tr><th>Tool</th>{head_cells}</tr></thead>
      <tbody>
{table}
      </tbody>
    </table>
    <p style="margin-top:12px">Cheapest at each volume — {summary}.</p>
    <div class="warning-box" style="margin-top:16px"><strong>Note:</strong> self-hosted figures are the server bill (VPS + DB), not a tool fee — the software is free and open-source. Activepieces is $0 on its cloud free tier (up to 10 active flows). Values marked ~ are estimates for custom enterprise tiers.</div>
    <p style="margin-top:14px"><a href="calculator.html">Get your exact cheapest tool from the calculator →</a></p>
  </div>"""

    faq = [
        {"q": "What is the cheapest automation tool?",
         "a": (f"It depends on volume. Among cloud tools, the lowest published price we track at {lo:,} runs/month "
               f"is {lo_name}, and at {hi:,} runs it's {hi_name}. Open-source self-hosted tools (n8n, Activepieces, "
               "Automatisch, Node-RED) are cheaper still — you pay only for the server. See the matrix above.")},
        {"q": "What is the cheapest cloud (no self-host) automation tool?",
         "a": ("Among fully managed cloud tools, the lowest cost shifts with volume — check the highlighted cells "
               'in the table for your run level, or use the <a href="calculator.html">calculator</a> for your exact numbers.')},
        {"q": "Is there a free automation tool?",
         "a": ("Yes. Activepieces has a cloud free tier (10 active flows, unlimited runs), and n8n, Activepieces, "
               "Automatisch and Node-RED are free open-source software you can self-host for just a server cost.")},
        {"q": "How accurate are these prices?",
         "a": ("They're generated from each vendor's official pricing via our cost engine, verified "
               f"{month_year}; see the <a href=\"changelog.html\">price changelog</a> for every recorded change.")},
    ]
    faq_ld, faq_html = _seo_faq(faq)
    title = "The Cheapest Automation Tool in 2026 (Real Prices) | AutomationCost.io"
    desc = (f"The cheapest automation tool in 2026, priced at every volume. At {lo:,} runs/mo it's {lo_name}; "
            f"at {hi:,} runs {hi_name}. Self-hosted tools run at just a server bill — see the full ranked matrix.")
    breadcrumb_ld = _seo_breadcrumb_ld(site, prefix, "Cheapest automation tool", canonical)
    return _seo_shell(title=title, desc=desc, canonical=canonical, prefix=prefix,
                      month_year=month_year, h1="The cheapest automation tool in 2026",
                      intro_html=intro, body_html=body, faq_ld=faq_ld,
                      breadcrumb_ld=breadcrumb_ld, faq_html=faq_html)


def build_seo_pages(tools: list[dict], site: dict, tools_meta: dict, *, check: bool = False) -> list[str]:
    """Vygeneruje long-tail SEO stránky (alternatives ×7 + cheapest ×1)."""
    engine = _root_engine()
    by_slug = {t["slug"]: t for t in tools}
    out = []
    targets = [(f"{s}-alternatives.html", lambda s=s: render_alternatives_page(s, by_slug, site, tools_meta, engine))
               for s in PRICING_SLUGS if s in by_slug]
    targets.append(("cheapest-automation-tool.html", lambda: render_cheapest_page(by_slug, site, tools_meta, engine)))
    for fname, render in targets:
        target = ROOT / fname
        rendered = render()
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        dirty = existing is None or _strip_injected(existing) != rendered
        if check:
            if dirty:
                out.append(fname)
        elif dirty:
            target.write_text(rendered, encoding="utf-8")
            out.append(fname)
    return out


# CSS šablona pricing stránek — port ze statických *-pricing.html + .price-alerts
# z _vs-example.html. Design se doladí zvlášť (saas-page-design); tady funkční + čistá.
_PRICING_CSS = """    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root { --bg: #0a0e17; --surface: #111827; --surface2: #1a2236; --border: #1f2d45; --border2: #27375a; --text: #e8edf5; --text2: #a8b4cc; --muted: #6b7a99; --accent: #10b981; --accent-br: #16d18c; --accent-dim: rgba(16,185,129,0.09); --accent-glow: rgba(16,185,129,0.20); --ink: #04130d; --link: #6f9bff; --green: #10b981; --yellow: #f59e0b; --orange: #f59e0b; --radius: 14px; --radius-sm: 9px; --font: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; --display: 'Hanken Grotesk', 'Plus Jakarta Sans', sans-serif; --mono: 'JetBrains Mono', ui-monospace, monospace; }
    body { background: var(--bg); color: var(--text); font-family: var(--font); font-size: 15.5px; line-height: 1.7; letter-spacing: 0.01em; min-height: 100vh; padding-top: 100px; }
    a { color: var(--link); text-decoration: none; }
    a:hover { color: #9fbcff; }
    h1, h2, h3 { font-family: var(--display); letter-spacing: -0.02em; }
    header { position: fixed; top: 0; left: 0; right: 0; z-index: 100; background: rgba(10,14,23,0.86); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border-bottom: 1px solid var(--border); }
    .nav-top { padding: 0 32px; height: 56px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }
    .nav-bottom { border-bottom: 2px solid var(--border); padding: 0 32px; display: flex; gap: 0; overflow-x: auto; scrollbar-width: none; }
    .nav-bottom::-webkit-scrollbar { display: none; }
    .nav-bottom a { padding: 12px 20px; font-size: 14px; color: var(--muted); text-decoration: none; white-space: nowrap; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: color 0.15s, border-color 0.15s; }
    .nav-bottom a:hover { color: var(--text); }
    .logo { display: flex; align-items: center; gap: 0; font-family: var(--display); font-weight: 800; font-size: 1.06rem; color: var(--text); letter-spacing: -0.01em; text-decoration: none; }
    .logo span { color: var(--accent); }
    .logo .io { color: var(--muted); font-weight: 600; }
    .logo-icon { width: 26px; height: 26px; flex-shrink: 0; margin-right: 11px; }
    .nav-badge { font-family: var(--mono); font-size: 11px; background: var(--surface2); border: 1px solid var(--border2); border-radius: 20px; padding: 4px 12px; color: var(--muted); }
    .wrap { max-width: 900px; margin: 0 auto; padding: 0 32px; }
    .page-hero { padding: 56px 0 36px; }
    .tool-badge { display: inline-flex; align-items: center; gap: 8px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 6px 14px; font-size: 13px; font-weight: 600; color: var(--muted); margin-bottom: 20px; }
    .tool-badge img { width: 18px; height: 18px; border-radius: 4px; background: #fff; padding: 1px; }
    .page-hero h1 { font-size: clamp(1.8rem, 4vw, 2.8rem); font-weight: 800; letter-spacing: -1px; line-height: 1.1; margin-bottom: 16px; }
    .page-hero p { color: var(--muted); font-size: 1.05rem; max-width: 640px; margin-bottom: 28px; }
    .cta-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
    .hero-trust { font-family: var(--mono); font-size: 12px; color: var(--muted); }
    .hero-trust strong { color: var(--accent-br); }
    .btn-primary { background: var(--accent); color: var(--ink); border: none; border-radius: var(--radius-sm); padding: 12px 24px; font-size: 14px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-block; box-shadow: 0 0 0 1px rgba(16,185,129,0.4), 0 6px 20px rgba(16,185,129,0.26); transition: transform 0.15s, box-shadow 0.15s, background 0.15s; }
    .btn-primary:hover { background: var(--accent-br); transform: translateY(-1px); text-decoration: none; box-shadow: 0 0 0 1px rgba(16,185,129,0.5), 0 10px 28px rgba(16,185,129,0.36); }
    .btn-secondary { background: var(--surface); color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 10px 20px; font-size: 14px; font-weight: 600; text-decoration: none; display: inline-block; transition: border-color 0.15s; }
    .btn-secondary:hover { border-color: var(--accent); text-decoration: none; }
    .section { margin-bottom: 48px; }
    .section h2 { font-size: 1.45rem; font-weight: 800; margin-bottom: 6px; }
    .section-sub { color: var(--muted); font-size: 14px; margin-bottom: 20px; max-width: 680px; }
    .billing-toggle { display: inline-flex; background: var(--surface); border: 1px solid var(--border2); border-radius: 999px; padding: 3px; gap: 2px; margin: 0 0 20px; }
    .bt-opt { background: none; border: none; color: var(--muted); font-family: var(--font); font-size: 13px; font-weight: 700; padding: 7px 18px; border-radius: 999px; cursor: pointer; transition: background 0.15s, color 0.15s; }
    .bt-opt:hover { color: var(--text); }
    .bt-opt.is-active { background: var(--accent); color: var(--ink); }
    .variant-head { font-family: var(--mono); font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--accent-br); margin: 22px 0 10px; }
    .plans-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; margin-bottom: 8px; }
    .plan-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
    .plan-name { font-family: var(--mono); font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }
    .plan-price { font-family: var(--mono); font-size: 1.55rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 4px; }
    .plan-price .price-suffix { font-size: 13px; font-weight: 400; color: var(--muted); }
    .plan-annual { font-family: var(--mono); font-size: 12px; font-weight: 600; color: var(--accent-br); min-height: 16px; margin-bottom: 4px; }
    .plan-annual:empty { min-height: 0; margin-bottom: 0; }
    .th-billing { font-family: var(--mono); font-weight: 600; text-transform: none; letter-spacing: 0; color: var(--muted); }
    .plan-detail { font-size: 13px; color: var(--muted); margin-top: 12px; line-height: 1.6; }
    .plan-detail li { list-style: none; padding: 2px 0; }
    .plan-detail li::before { content: "·"; margin-right: 6px; color: var(--accent); }
    .plan-detail li.spec { color: var(--text2); font-style: italic; }
    .plan-note { font-size: 12.5px; color: var(--muted); margin: 4px 0 0; max-width: 660px; }
    .comparison-table { width: 100%; border-collapse: collapse; font-size: 14px; }
    .comparison-table th { text-align: left; padding: 10px 14px; color: var(--muted); font-weight: 600; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); }
    .comparison-table td { padding: 12px 14px; border-bottom: 1px solid var(--border); }
    .comparison-table tr:last-child td { border-bottom: none; }
    .comparison-table tr:hover td { background: var(--surface2); }
    .comparison-table .price-cell { font-family: var(--mono); font-weight: 700; }
    .tag-yes { color: var(--green); font-weight: 700; }
    .tag-no { color: var(--muted); }
    .tag-warn { color: var(--orange); font-weight: 700; }
    .faq-item { border-bottom: 1px solid var(--border); }
    .faq-q { width: 100%; background: none; border: none; color: var(--text); font-family: inherit; font-size: 15px; font-weight: 600; text-align: left; padding: 18px 0; cursor: pointer; display: flex; justify-content: space-between; align-items: center; gap: 16px; }
    .faq-q:hover { color: var(--accent); }
    .faq-chevron { flex-shrink: 0; transition: transform 0.2s; color: var(--muted); }
    .faq-item.open .faq-chevron { transform: rotate(180deg); }
    .faq-a { display: none; color: var(--muted); font-size: 14px; line-height: 1.7; padding-bottom: 18px; }
    .faq-item.open .faq-a { display: block; }
    .related-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
    .related-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; text-decoration: none; color: var(--text); display: block; transition: border-color 0.15s; }
    .related-card:hover { border-color: var(--accent); text-decoration: none; }
    .related-card-name { font-weight: 700; font-size: 14px; margin-bottom: 4px; }
    .related-card-desc { font-size: 12px; color: var(--muted); }
    .warning-box { background: rgba(245,158,11,0.08); border: 1px solid rgba(245,158,11,0.3); border-radius: 8px; padding: 16px 20px; font-size: 14px; color: var(--muted); margin-bottom: 32px; }
    .warning-box strong { color: var(--orange); }
    .warning-box em { color: var(--text2); font-style: normal; }
    .price-alerts { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 28px; margin-bottom: 48px; }
    .pa-label { font-family: var(--mono); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--accent-br); margin-bottom: 8px; }
    .pa-title { font-family: var(--display); font-size: 1.25rem; font-weight: 800; margin-bottom: 6px; }
    .pa-sub { color: var(--muted); font-size: 14px; margin-bottom: 16px; }
    .pa-form { display: flex; gap: 10px; flex-wrap: wrap; }
    .pa-input { flex: 1; min-width: 220px; background: var(--bg); border: 1px solid var(--border2); border-radius: var(--radius-sm); padding: 12px 16px; color: var(--text); font-family: inherit; font-size: 14px; }
    .pa-input:focus { outline: none; border-color: var(--accent); }
    .pa-btn { background: var(--accent); color: var(--ink); border: none; border-radius: var(--radius-sm); padding: 12px 22px; font-size: 14px; font-weight: 700; cursor: pointer; }
    .pa-btn:hover { background: var(--accent-br); }
    .pa-btn:disabled { opacity: 0.6; cursor: default; }
    .pa-msg { display: none; align-items: center; gap: 8px; font-size: 13px; margin-top: 12px; }
    .pa-msg.show { display: flex; }
    .pa-msg.ok { color: var(--green); }
    .pa-msg.err { color: var(--orange); }
    .pa-note { font-size: 12px; color: var(--muted); margin-top: 12px; }
    .price-alerts.subscribed .pa-form { display: none; }
    footer { border-top: 1px solid var(--border); padding: 32px 24px; text-align: center; font-size: 12px; color: var(--muted); line-height: 1.8; margin-top: 64px; }
    footer a { color: var(--muted); }
    .funnel-fab { position: fixed; right: 22px; bottom: 22px; z-index: 90; display: inline-flex; align-items: center; gap: 9px; background: var(--accent); color: var(--ink); font-family: var(--font); font-size: 14px; font-weight: 700; padding: 13px 20px; border-radius: 100px; text-decoration: none; box-shadow: 0 10px 30px rgba(16,185,129,0.4), 0 0 0 1px rgba(16,185,129,0.5); transition: transform 0.15s, box-shadow 0.15s, background 0.15s; }
    .funnel-fab:hover { background: var(--accent-br); color: var(--ink); transform: translateY(-2px); text-decoration: none; box-shadow: 0 14px 38px rgba(16,185,129,0.5); }
    @media (max-width: 760px) {
      .wrap { padding-left: 18px; padding-right: 18px; }
      .nav-top { padding-left: 18px; padding-right: 18px; }
      .nav-bottom { padding-left: 8px; padding-right: 8px; }
      .nav-bottom a { padding: 13px 14px; }
    }
    @media (max-width: 620px) { .nav-badge { display: none; } }
    @media (max-width: 520px) {
      .cta-row { flex-direction: column; align-items: stretch; }
      .cta-row > a, .cta-row > button { width: 100%; text-align: center; justify-content: center; }
      .funnel-fab { right: 12px; bottom: 12px; padding: 11px 16px; font-size: 13px; }
    }"""
