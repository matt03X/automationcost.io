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
from i18n_util import lang_prefix, hreflang_links, lang_switcher, site_langs
import integration_counts as ic  # jediný zdroj počtů integrací + typové labely
from _partials import dashboard_header as _dashboard_header  # sdílený nav HTML

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


def _iso_date(tools_meta: dict) -> str:
    """ISO YYYY-MM-DD posledního ručního review cen → schema.org dateModified
    (freshness signál pro AI/GEO citace). Fixní fallback drží --check deterministický."""
    import datetime as _dt
    lr = (tools_meta or {}).get("last_reviewed")
    if lr:
        try:
            _dt.date(*[int(x) for x in lr.split("-")])  # validace formátu
            return lr
        except (ValueError, TypeError):
            pass
    return "2026-06-01"


def _page_graph_ld(domain: str, canonical: str, name: str, desc: str, iso_date: str,
                   about_name: str | None = None, about_url: str | None = None,
                   offers: dict | None = None) -> str:
    """WebPage + Organization + WebSite @graph pro GEO/AI-citace: dateModified (freshness),
    identita vydavatele (WizardCost) + isPartOf, volitelně entita softwaru přes `about`.
    `offers` (AggregateOffer, USD) se připne na SoftwareApplication — reálný cenový range
    z enginu, stejná veřejná data jako v tabulkách, jen strojově čitelná (schváleno userem)."""
    home_url = f"https://{domain}/"
    org_id = f"{home_url}#org"
    webpage = {
        "@type": "WebPage", "@id": f"{canonical}#webpage", "url": canonical,
        "name": name, "description": desc, "inLanguage": "en",
        "isPartOf": {"@id": f"{home_url}#website"},
        "publisher": {"@id": org_id}, "dateModified": iso_date,
    }
    if about_name:
        about = {
            "@type": "SoftwareApplication", "name": about_name,
            "applicationCategory": "BusinessApplication", "operatingSystem": "Web",
            "url": about_url or home_url,
        }
        if offers:
            about["offers"] = offers
        webpage["about"] = about
    return json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "@id": org_id, "name": "WizardCost", "url": home_url,
             "description": ("Independent, data-driven software pricing comparisons. Prices "
                             "verified by hand from official vendor pricing pages and dated "
                             "in a public changelog.")},
            {"@type": "WebSite", "@id": f"{home_url}#website", "name": "WizardCost",
             "url": home_url, "publisher": {"@id": org_id}},
            webpage,
        ],
    }, ensure_ascii=False, indent=2)


def _site_prefix(domain: str, base_path: str) -> str:
    bp = (base_path or "").strip("/")
    return f"https://{domain}/{bp}".rstrip("/") if bp else f"https://{domain}"


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _clamp_desc(text: str, n: int = 158) -> str:
    """Trim a meta description to <= n chars on a word boundary (+ ellipsis)."""
    if not text or len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(" ,.;:—–-")
    return cut + "…"


def _clamp_title(title: str, n: int = 60) -> str:
    """Keep <title> <= n rendered chars, trimming the core but preserving the ' | brand' suffix.

    Titles may contain the &amp; entity (5 chars, renders as 1), so length is measured
    on the rendered form. A guardrail only — generators should keep cores short already.
    """
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


def _label_runs(label: str, tr=None) -> str:
    """Engine vrací interní label s '+ops' (overage) — user-facing musí být 'runs'."""
    overage = tr("pp.overage", "overage") if tr else "overage"
    return label.replace("+ops", f"+ {overage}")


def _plan_cards_for_variant(engine, variant: dict, tr=None) -> str:
    """Karty: pro každý VOLUME jedna karta s reálnou cenou (monthly + roční, je-li).

    Cena nese data-month/data-annual atributy → JS toggle přepíná zobrazení.
    Default = monthly. Plán bez annualUsd → annual == monthly (žádná roční řádka)."""
    if tr is None:
        def tr(key, default):
            return default
    kind = variant.get("hostingKind", "saas")
    cards = []
    for runs in VOLUMES:
        r, ra = _engine_costs(engine, variant, runs)
        if r is None:
            continue
        price_m = _fmt_usd(r["cost"], r["est"])
        price_a = _fmt_usd(ra["cost"], ra["est"]) if ra else price_m
        suffix = tr("pp.suffix_mo_elec", "/mo electricity") if kind == "own" else tr("pp.suffix_mo", "/mo")
        pct = _discount_pct(r["cost"], ra["cost"]) if ra else None
        detail = [f"<li>{tr('pp.runs_per_month', '{runs:,} runs / month').format(runs=runs)}</li>",
                  f"<li>{_html_escape(_label_runs(r['label'], tr))}</li>"]
        if kind == "own":
            tier = hw_tier_for(variant, runs)
            if tier:
                detail.append(f"<li>{tr('pp.hardware_oneoff', '+ ~${hw:,} hardware (one-off)').format(hw=tier.get('hwOneOff', 0))}</li>")
                if tier.get("spec"):
                    detail.append(f'<li class="spec">{_html_escape(tier["spec"])}</li>')
        # roční řádek pod cenou: jen když plán reálně nabízí roční slevu
        if pct is not None:
            annual_note = (f'        <div class="plan-annual" data-month="" '
                           f'data-annual="{tr("pp.annual_save", "{price}{suffix} billed annually — save {pct}%").format(price=price_a, suffix=suffix, pct=pct)}">'
                           f'</div>\n')
        elif kind not in ("own", "vps") and not variant.get("selfHostOnly"):
            annual_note = ('        <div class="plan-annual" data-month="" '
                           f'data-annual="{tr("pp.no_annual", "No annual pricing tracked yet")}"></div>\n')
        else:
            annual_note = ""
        cards.append(
            '      <div class="plan-card">\n'
            f'        <div class="plan-name">{tr("pp.plan_runs", "{runs:,} runs").format(runs=runs)}</div>\n'
            f'        <div class="plan-price"><span class="price-num" data-month="{price_m}" '
            f'data-annual="{price_a}">{price_m}</span><span class="price-suffix">{suffix}</span></div>\n'
            f'{annual_note}'
            f'        <ul class="plan-detail">\n          ' + "\n          ".join(detail) + "\n"
            "        </ul>\n      </div>")
    return "\n".join(cards)


def _variant_section(engine, variant: dict, tr=None) -> str:
    if tr is None:
        def tr(key, default):
            return default
    kind = variant.get("hostingKind", "saas")
    label = tr(f"pp.kind_{kind}", _KIND_LABEL.get(kind, "Plans"))
    if kind == "own":
        note = ('<p class="plan-note">' + tr("pp.note_own",
                "Monthly figure is electricity only — the software is free. "
                "One-off hardware cost (a mini PC or Pi you keep) is shown per volume.") + '</p>')
    elif kind == "vps":
        note = ('<p class="plan-note">' + tr("pp.note_vps",
                "Monthly figure is the rented server (VPS + database) that "
                "scales with volume — the software itself is free.") + '</p>')
    else:
        note = ""
    cards = _plan_cards_for_variant(engine, variant, tr)
    if not cards:
        return ""
    return (f'    <h3 class="variant-head">{label}</h3>\n'
            f'    <div class="plans-grid">\n{cards}\n    </div>\n    {note}')


def _comparison_table(engine, by_slug: dict, focus_slug: str, vol: int, tr=None) -> str:
    """„<Tool> vs alternativy" na daném runs objemu — ceny VŠECH 7 toolů z enginu.

    Price cell nese data-month/data-annual → JS toggle přepíná i tabulku.
    Plán bez roční slevy: annual == monthly (cell se nemění)."""
    if tr is None:
        def tr(key, default):
            return default
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
        sh = (f'<span class="tag-yes">{tr("pp.sh_yes", "Yes (free SW)")}</span>' if t.get("selfHostable")
              else f'<span class="tag-no">{tr("pp.sh_no", "No")}</span>')
        rows.append(
            f"        <tr><td>{name}</td>"
            f'<td class="price-cell"><span class="price-num" data-month="{price_m}" '
            f'data-annual="{price_a}">{price_m}</span></td>'
            f'<td>{ic.label(s)}</td>'
            f"<td>{sh}</td></tr>")
    return "\n".join(rows)


def _faq_with_prices(engine, tool: dict, ed_faq: list, by_slug: dict, tr=None) -> list[dict]:
    """Editorial FAQ (bez cen) + generované price-bearing otázky (z enginu).

    tr(key, default) lokalizuje generované (price-bearing) otázky; ceny, odkazy a
    názvy nástrojů jsou frozen přes {placeholder}. ed_faq (editorial, price-free)
    přichází už lokalizované z merged editorial dictu."""
    if tr is None:
        def tr(key, default):
            return default
    name = tool["name"]
    faq = []
    # price-bearing: kolik to stojí měsíčně přes všechny volume body
    parts = []
    for vol in VOLUMES:
        r = engine.cheapest_monthly(tool, vol, STEPS)
        if r:
            parts.append(f"{_fmt_usd(r['cost'], r['est'])} at {vol:,} runs")
    if parts:
        joined = ", ".join(parts[:-1]) + ((" " + tr("faq.and", "and") + " ") if len(parts) > 1 else "") + parts[-1]
        faq.append({
            "q": tr("faq.cost_q", "How much does {name} cost per month?").format(name=name),
            "a": tr("faq.cost_a",
                    "On the cheapest qualifying plan (3-step workflows, monthly billing) {name} runs {prices}. See the plans and comparison table above for the full breakdown."
                    ).format(name=name, prices=joined),
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
            link = f'<a href="{cs}-pricing.html">{by_slug[cs]["name"]}</a>'
            faq.append({
                "q": tr("faq.cheaper_q", "What is cheaper than {name}?").format(name=name),
                "a": tr("faq.cheaper_a",
                        "At {vol:,} runs/month the cheapest pick we track is {link} at {cprice} vs {name} at {tprice}. Use the calculator for your exact volume."
                        ).format(vol=vol, link=link, cprice=_fmt_usd(cr['cost'], cr['est']),
                                 name=name, tprice=_fmt_usd(rt['cost'], rt['est'])),
            })
    # editorial (price-free) na konec
    for f in ed_faq:
        faq.append({"q": f["q"], "a": f["a"]})
    faq.append({
        "q": tr("faq.accuracy_q", "How accurate are these prices?"),
        "a": tr("faq.accuracy_a",
                'Taken from official pricing pages and verified by hand. Values marked ~ are estimates '
                'for custom enterprise tiers. Every change we record lands in the '
                '<a href="changelog.html">price changelog</a>.'),
    })
    return faq


_WORTH_CLS = {"good": "tag-yes", "warn": "tag-warn", "bad": "tag-no"}

FX_PATH = ROOT / "data" / "fx.json"


def _display_fx() -> dict:
    """USD→X multiplikátory pro měnový přepínač (display only, USD = zdroj pravdy).

    Z data/fx.json["display_rates"]. Chybí-li → jen USD (přepínač zobrazí jen $)."""
    try:
        dr = json.loads(FX_PATH.read_text(encoding="utf-8")).get("display_rates", {})
    except Exception:
        dr = {}
    out = {k: dr[k] for k in ("usd", "eur", "czk") if isinstance(dr.get(k), (int, float))}
    out.setdefault("usd", 1)
    return out


def _currency_switcher() -> str:
    """Měnový přepínač (USD/EUR/CZK) — stejný .ac-dd pattern jako globus.
    Aktivní měnu řídí JS z localStorage (klient-side preference, ne server)."""
    return (
        '<div class="ac-dd ac-cur">\n'
        '      <button class="ac-dd-btn" aria-expanded="false" aria-haspopup="true" '
        'aria-label="Currency / Währung"><span class="ac-cur-label">$</span>'
        '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg></button>\n'
        '      <div class="ac-dd-menu ac-cur-menu">\n'
        '        <a href="#" data-cur="usd">USD&nbsp;($)</a>\n'
        '        <a href="#" data-cur="eur">EUR&nbsp;(€)</a>\n'
        '        <a href="#" data-cur="czk">CZK&nbsp;(Kč)</a>\n'
        '      </div>\n'
        '    </div>'
    )


def render_pricing_page(slug: str, tools: list[dict], variants_by_base: dict,
                        editorial: dict, site: dict, tools_meta: dict, engine,
                        *, lang: str = "en", langs: list[str] | None = None,
                        tr=None) -> str:
    # tr(key, english_default) → translation or the inline English default, so the
    # EN build is byte-identical (no regression). `editorial` is already the
    # language-merged dict, so ed[...] carries translated copy for non-EN.
    if tr is None:
        def tr(key, default):
            return default
    langs = list(langs) if langs else ["en"]
    by_slug = {t["slug"]: t for t in tools}
    tool = by_slug[slug]
    name = tool["name"]
    ed = editorial["tools"][slug]
    month_year = _month_year(tools_meta)
    domain = site.get("domain", "wizardcost.com")
    base_path = site.get("base_path", "")
    prefix = lang_prefix(domain, base_path, lang)
    en_prefix = lang_prefix(domain, base_path, "en")   # breadcrumb parents → real EN pages
    canonical = f"{prefix}/{slug}-pricing.html"
    rel = f"{slug}-pricing.html"
    hreflang = hreflang_links(domain, base_path, rel, langs) if len(langs) > 1 else ""
    switcher = lang_switcher(base_path, rel, langs, lang) if len(langs) > 1 else ""
    cur_switcher = _currency_switcher()
    fx_json = json.dumps(_display_fx(), ensure_ascii=False)
    cur_note = tr("pp.cur_note", "≈ Converted from USD at today's rate — not the amount you're billed.")

    # ── plán sekce: hosting varianty (Cloud / VPS / vlastní server) ──
    variants = variants_by_base.get(slug, [])
    plan_sections = "\n".join(s for s in (_variant_section(engine, v, tr) for v in variants) if s)

    # ── srovnávací tabulka (20k runs) ──
    cmp_vol = 20000
    cmp_rows = _comparison_table(engine, by_slug, slug, cmp_vol, tr)

    # ── when worth it ──
    worth_rows = "\n".join(
        f'        <tr><td>{_html_escape(w["case"])}</td>'
        f'<td class="{_WORTH_CLS.get(w["tier"], "tag-no")}">{_html_escape(w["verdict"])}</td></tr>'
        for w in ed.get("whenWorthIt", []))

    # ── FAQ (editorial + generované ceny) ──
    faq = _faq_with_prices(engine, tool, ed.get("faq", []), by_slug, tr)
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
        f'        <div class="related-card-desc">{tr("pp.related_desc", "Pricing &amp; features compared")}</div>\n'
        f"      </a>" for o in PRICING_SLUGS if o != slug)

    # ── breadcrumb JSON-LD (SERP breadcrumbs + topická struktura) ──
    # Parent crumbs point at the real EN pages (tools.html není lokalizovaná); leaf = aktuální stránka.
    home_url = f"https://{domain}/"
    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": tr("bc.home", "Home"), "item": home_url},
            {"@type": "ListItem", "position": 2, "name": tr("bc.tools", "Automation tools"), "item": f"{en_prefix}/tools.html"},
            {"@type": "ListItem", "position": 3, "name": tr("bc.pricing", "{name} pricing").format(name=name), "item": canonical},
        ],
    }, ensure_ascii=False, indent=2)

    # ── outbound CTA (affiliate jen s hasAffiliate) ── {name} frozen, slovosled přes placeholder
    if tool.get("hasAffiliate"):
        primary = (f'<a href="{tool["affiliateUrl"]}" target="_blank" rel="noopener sponsored" '
                   f'class="btn-primary">{tr("pp.cta_try", "Try {name} free →").format(name=name)}</a>')
    else:
        primary = (f'<a href="{tool["homepage"]}" target="_blank" rel="noopener" '
                   f'class="btn-primary">{tr("pp.cta_visit", "Visit {name} →").format(name=name)}</a>')

    # ── <meta description> s reálnými cenami z dat (ceny VŽDY z enginu přes {prices} placeholder) ──
    desc_parts = []
    for vol in (VOLUMES[0], VOLUMES[2], VOLUMES[3]):
        r = engine.cheapest_monthly(tool, vol, STEPS)
        if r:
            desc_parts.append(f"{_fmt_usd(r['cost'], r['est'])} at {vol:,} runs")
    desc = tr(f"meta.{slug}-pricing.description",
              "{name} pricing 2026: {prices}. Real plans, self-host options and how {name} compares on cost per run."
              ).format(name=name, prices=", ".join(desc_parts))
    # editorial seo_title override (pricing-editorial.json) → per-tool title without touching template default
    _ed_seo_title = ed.get("seo_title")
    title = (_ed_seo_title if _ed_seo_title else
             tr(f"meta.{slug}-pricing.title",
                "{name} Pricing 2026 — Plans &amp; Real Cost | WizardCost").format(name=name))
    og_title = title.split(" | ")[0].replace("&amp;", "&")

    # ── Citation-ready key facts (GEO playbook A10 #2): one dated, standalone,
    # quotable sentence with the headline numbers, in SSR HTML — the prime thing
    # an LLM lifts for "how much does X cost". Computed from the engine, not typed.
    _kf_lo = engine.cheapest_monthly(tool, VOLUMES[0], STEPS)
    _kf_hi = engine.cheapest_monthly(tool, VOLUMES[3], STEPS)
    key_facts_html = ""
    if _kf_lo and _kf_hi:
        _selfhost = "self-host" in (_kf_lo.get("label", "") + _kf_hi.get("label", "")).lower()
        _tail = (" Self-hosting is free — the figure is the server it "
                 "runs on, not a tool fee." if _selfhost else "")
        _kf = (f"As of {month_year}, the cheapest plan we track for {name} costs "
               f"{_fmt_usd(_kf_lo['cost'], _kf_lo['est'])} per month at {VOLUMES[0]:,} runs and "
               f"{_fmt_usd(_kf_hi['cost'], _kf_hi['est'])} at {VOLUMES[3]:,} runs "
               f"(cheapest qualifying plan, 3-step workflows, monthly billing), from "
               f"{name}'s official pricing, verified by hand.{_tail}")
        key_facts_html = ('<p class="hero-facts" style="margin-top:14px;font-size:0.95rem;'
                          f'opacity:0.88;line-height:1.6;max-width:680px;">{_kf}</p>')
    # ── AggregateOffer: reálný měsíční cost-range z enginu napříč VOLUMES (USD).
    #    Stejná veřejná čísla jako v tabulkách/meta — jen strojově čitelná pro AI/Google
    #    citace. offerCount = počet plánů nástroje. Odhady (~) jdou do schématu jako číslo. ──
    _costs = [r["cost"] for vol in VOLUMES
              if (r := engine.cheapest_monthly(tool, vol, STEPS)) is not None]
    offers = None
    if _costs:
        offers = {"@type": "AggregateOffer", "priceCurrency": "USD",
                  "lowPrice": round(min(_costs), 2), "highPrice": round(max(_costs), 2)}
        if tool.get("plans"):
            offers["offerCount"] = len(tool["plans"])

    # ── WebPage + Organization + WebSite graf (GEO/AI-citace: freshness + identita
    #    vydavatele + entita nástroje + cenový range). dateModified = poslední ruční review. ──
    page_ld = _page_graph_ld(
        site.get("domain", "wizardcost.com"), canonical,
        f"{name} Pricing 2026 — Plans, Run Limits & Real Cost", desc, _iso_date(tools_meta),
        about_name=name, about_url=tool.get("homepage"), offers=offers)

    css = _PRICING_CSS

    # ── localized chrome strings (precomputed; {name}/{cmp_vol}/{month_year} frozen via placeholders) ──
    cta_calc = tr("pp.cta_calc", "Calculate my {name} cost").format(name=name)
    cta_compare_all = tr("pp.cta_compare_all", "Compare all 7 tools")
    hero_trust = tr("pp.hero_trust",
                    "Prices verified {month_year} · taken from {name}'s official pricing · all figures per <strong>run</strong>"
                    ).format(month_year=month_year, name=name)
    heads_up = tr("pp.heads_up", "Heads up:")
    h2_plans = tr("pp.h2_plans", "{name} plans &amp; real cost").format(name=name)
    plans_sub = tr("pp.plans_sub", "Cheapest qualifying plan at four typical run volumes (3-step workflows) — prices generated live from our data, never hand-typed. Toggle to see prices when billed annually.")
    lbl_monthly = tr("pp.monthly", "Monthly")
    lbl_annual = tr("pp.annual", "Annual")
    h2_vs = tr("pp.h2_vs", "{name} vs alternatives").format(name=name)
    vs_sub = tr("pp.vs_sub", "Price for {cmp_vol:,} runs / month across every tool we track. Use the Monthly / Annual toggle above to switch how the prices are billed.").format(cmp_vol=cmp_vol)
    th_tool = tr("pp.th_tool", "Tool")
    th_price = tr("pp.th_price", "Price for {cmp_vol:,} runs").format(cmp_vol=cmp_vol)
    th_integrations = tr("pp.th_integrations", "Integrations")
    th_selfhost = tr("pp.th_selfhost", "Self-host")
    billing_m = tr("pp.billing_monthly_paren", "(monthly)")
    billing_a = tr("pp.billing_annual_paren", "(billed annually)")
    alt_links = (f'<a href="{slug}-alternatives.html">'
                 + tr("pp.see_alts", "See all {name} alternatives →").format(name=name) + "</a> · "
                 '<a href="cheapest-automation-tool.html">' + tr("pp.cheapest", "Cheapest automation tool →") + "</a> · "
                 '<a href="compare.html">' + tr("pp.full_compare", "Full interactive comparison →") + "</a> · "
                 '<a href="limits.html">' + tr("pp.limits_link", "Plan limits &amp; run caps →") + "</a>")
    h2_worth = tr("pp.h2_worth", "When {name} is worth it").format(name=name)
    th_usecase = tr("pp.th_usecase", "Use case")
    th_verdict = tr("pp.th_verdict", "Verdict")
    h2_faq = tr("pp.h2_faq", "Frequently asked questions")
    h2_h2h = tr("pp.h2_h2h", "Compare {name} head-to-head").format(name=name)
    footer_part = tr("pp.footer_part", "&copy; 2026 AutomationCost.io · part of WizardCost")
    footer_tagline = tr("pp.footer_tagline", "AutomationCost.io · Independent, data-driven comparisons · Prices verified {month_year}").format(month_year=month_year)
    footer_affiliate = tr("pp.footer_affiliate", "Some links are affiliate links — we may earn a commission at no extra cost to you. This never affects our rankings or recommendations.")
    foot_privacy = tr("nav.privacy", "Privacy")
    foot_terms = tr("nav.terms", "Terms")
    foot_affiliate = tr("nav.affiliate_disclosure", "Affiliate Disclosure")
    fab_label = tr("pp.fab", "Find my best tool")

    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build_pricing.py z data/tools.json + data/pricing-editorial.json — needituj ručně -->
  <title>{_clamp_title(title)}</title>
  <meta name="description" content="{_html_escape(_clamp_desc(desc))}">
  <link rel="canonical" href="{canonical}">
{hreflang}
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="AutomationCost.io">
  <meta property="og:title" content="{_html_escape(og_title)}">
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
  <script type="application/ld+json">
{page_ld}
  </script>
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
{css}
  </style>
  <link rel="stylesheet" href="app.css">
  <link rel="stylesheet" href="dashboard.css">
</head>
<body class="ac anim">

{_dashboard_header(active="", extra=cur_switcher)}

<div class="wrap">

  <div class="page-hero">
    <div class="tool-badge"><img src="{_logo(slug)}" alt="{name}">{name}</div>
    <h1>{ed["h1"]}</h1>
    <p>{ed["intro"]}</p>
    <div class="cta-row">
      {primary}
      <a href="calculator.html" class="btn-secondary">{cta_calc}</a>
      <a href="compare.html" class="btn-secondary">{cta_compare_all}</a>
    </div>
    <div class="hero-trust">{hero_trust}</div>
    {key_facts_html}
  </div>

  <div class="warning-box"><strong>{heads_up}</strong> {ed["warn"]}</div>

  <div class="section">
    <h2>{h2_plans}</h2>
    <p class="section-sub">{plans_sub}</p>
    <div class="billing-toggle" role="group" aria-label="Billing period">
      <button type="button" class="bt-opt is-active" data-billing="month" aria-pressed="true">{lbl_monthly}</button>
      <button type="button" class="bt-opt" data-billing="annual" aria-pressed="false">{lbl_annual}</button>
    </div>
    <p class="cur-note" hidden>{cur_note}</p>
{plan_sections}
  </div>

  <div class="section">
    <h2>{h2_vs}</h2>
    <p class="section-sub">{vs_sub}</p>
    <table class="comparison-table">
      <thead><tr><th>{th_tool}</th><th>{th_price} <span class="th-billing" data-month="{billing_m}" data-annual="{billing_a}">{billing_m}</span></th><th>{th_integrations}</th><th>{th_selfhost}</th></tr></thead>
      <tbody>
{cmp_rows}
      </tbody>
    </table>
    <p style="margin-top:12px">{alt_links}</p>
  </div>

  <div class="section">
    <h2>{h2_worth}</h2>
    <table class="comparison-table">
      <thead><tr><th>{th_usecase}</th><th>{th_verdict}</th></tr></thead>
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
    <h2>{h2_faq}</h2>
    <div class="faq" style="margin-top:8px;">
{faq_html}
    </div>
  </div>

  <div class="section">
    <h2>{h2_h2h}</h2>
    <div class="related-grid">
{related}
    </div>
  </div>

</div>

<footer>
  <div style="margin-bottom:6px;color:#6b7a99">{footer_part}</div>
  <div>{footer_tagline}</div>
  <div style="margin-top:6px">{footer_affiliate}</div>
  <div style="margin-top:6px"><a href="privacy.html">{foot_privacy}</a> · <a href="terms.html">{foot_terms}</a> · <a href="affiliate.html">{foot_affiliate}</a></div>
</footer>

<script>
function toggleFaq(el) {{ el.closest(".faq-item").classList.toggle("open"); }}

/* ── billing (Monthly/Annual) + currency (USD/EUR/CZK display-only) ──
   USD is canonical (data-month/data-annual hold USD). The currency layer
   re-formats every .price-num from the USD base × FX — a display estimate
   (disclaimer shown), never re-baking the source prices. ── */
window.AC_FX = {fx_json};
(function () {{
  var FX = window.AC_FX || {{ usd: 1 }};
  var billing = "month";
  var currency = "usd";
  try {{ currency = localStorage.getItem("ac-cur") || "usd"; }} catch (e) {{}}
  if (!FX[currency]) currency = "usd";
  function fmtConv(usd, cur, est) {{
    var v = Math.round(usd * (FX[cur] || 1)).toLocaleString("en-US");
    var pre = est ? "~" : "";
    if (cur === "czk") return pre + v + " Kč";
    if (cur === "eur") return pre + "€" + v;
    return pre + "$" + v;
  }}
  function applyBilling() {{
    var attr = billing === "annual" ? "data-annual" : "data-month";
    document.querySelectorAll("[" + attr + "]").forEach(function (el) {{
      if (el.classList.contains("bt-opt")) return;
      el.textContent = el.getAttribute(attr) || "";
    }});
  }}
  function applyCurrency() {{
    var note = document.querySelector(".cur-note");
    if (note) note.hidden = currency === "usd";
    if (currency === "usd") return;
    document.querySelectorAll(".price-num").forEach(function (el) {{
      var m = el.textContent.match(/(~)?\\$\\s?([0-9][0-9,]*(?:\\.[0-9]+)?)/);
      if (!m) return;
      el.textContent = fmtConv(parseFloat(m[2].replace(/,/g, "")), currency, !!m[1]);
    }});
  }}
  function render() {{ applyBilling(); applyCurrency(); }}
  var bt = document.querySelector(".billing-toggle");
  if (bt) {{
    bt.querySelectorAll(".bt-opt").forEach(function (b) {{
      b.addEventListener("click", function () {{
        billing = b.getAttribute("data-billing");
        bt.querySelectorAll(".bt-opt").forEach(function (x) {{
          var on = x.getAttribute("data-billing") === billing;
          x.classList.toggle("is-active", on);
          x.setAttribute("aria-pressed", on ? "true" : "false");
        }});
        render();
      }});
    }});
  }}
  function syncCur() {{
    var lab = document.querySelector(".ac-cur .ac-cur-label");
    if (lab) lab.textContent = currency === "eur" ? "€" : currency === "czk" ? "Kč" : "$";
    document.querySelectorAll(".ac-cur [data-cur]").forEach(function (a) {{
      a.setAttribute("aria-current", a.getAttribute("data-cur") === currency ? "true" : "false");
    }});
  }}
  document.querySelectorAll(".ac-cur [data-cur]").forEach(function (a) {{
    a.addEventListener("click", function (e) {{
      e.preventDefault();
      currency = a.getAttribute("data-cur");
      if (!FX[currency]) currency = "usd";
      try {{ localStorage.setItem("ac-cur", currency); }} catch (e2) {{}}
      syncCur();
      render();
      var dd = a.closest(".ac-dd");
      if (dd) {{ dd.classList.remove("open"); var bb = dd.querySelector(".ac-dd-btn"); if (bb) bb.setAttribute("aria-expanded", "false"); }}
    }});
  }});
  syncCur();
  render();
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
<a href="calculator.html" class="funnel-fab" aria-label="Find my cheapest tool"><svg width="17" height="17" viewBox="0 0 48 48" fill="none"><path d="M29 11 L15 24 L29 37" stroke="#04130d" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round"/><circle cx="34.5" cy="24" r="3.4" fill="#04130d"/></svg> {fab_label}</a>
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
    langs = site_langs(site)   # EN pages advertise the available translations (hreflang + switcher)

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
                                       site, tools_meta, engine, lang="en", langs=langs)
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
               body_html, faq_ld, breadcrumb_ld, faq_html, page_ld="") -> str:
    css = _PRICING_CSS
    title = _clamp_title(title)
    desc = _clamp_desc(desc)
    page_ld_block = (f'  <script type="application/ld+json">\n{page_ld}\n  </script>\n'
                     if page_ld else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build_pricing.py (build_seo_pages) z data/tools.json — needituj ručně -->
  <title>{_clamp_title(title)}</title>
  <meta name="description" content="{_html_escape(_clamp_desc(desc))}">
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
{page_ld_block}  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
{css}
  </style>
  <link rel="stylesheet" href="app.css">
  <link rel="stylesheet" href="dashboard.css">
</head>
<body class="ac anim">

{_dashboard_header(active="")}

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
  <div style="margin-top:6px"><a href="methodology.html">Methodology</a> · <a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> · <a href="affiliate.html">Affiliate Disclosure</a></div>
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
            f"<td>{ic.label(s)}</td><td>{sh}</td>"
            f"<td><a href=\"{_vs_slug(slug, s)}.html\">{_html_escape(name)} vs {_html_escape(t['name'])} →</a></td></tr>")
    table = "\n".join(rows)

    oss_sentence = (f" For the self-hostable route like {name}, look at "
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
         "a": ((f"Yes — {', '.join(oss)} are self-hostable, so beyond a server bill they're effectively free. "
                "Activepieces also has a cloud free tier (10 active flows, unlimited runs).") if oss
               else "Several tools offer free tiers — see the comparison for current limits.")},
        {"q": f"How accurate are these prices?",
         "a": ("Every figure is generated from each vendor's official pricing via our cost engine, verified "
               f"{month_year}. Values marked ~ are estimates for custom enterprise tiers. See the "
               '<a href="changelog.html">price changelog</a> for every change we record.')},
    ]
    faq_ld, faq_html = _seo_faq(faq)
    title = f"{name} Alternatives 2026 — Priced &amp; Compared | WizardCost"
    desc = (f"The best {name} alternatives in 2026, priced at real run volumes. "
            f"{cheapest_name} is the lowest-cost option we track at {ALT_VOL:,} runs/mo — "
            f"compare every alternative on cost, integrations and self-hosting.")
    breadcrumb_ld = _seo_breadcrumb_ld(site, prefix, f"{name} alternatives", canonical)
    page_ld = _page_graph_ld(site.get("domain", "wizardcost.com"), canonical,
                             f"{name} Alternatives 2026 — Priced & Compared", desc,
                             _iso_date(tools_meta), about_name=name, about_url=tool.get("homepage"))
    return _seo_shell(title=title, desc=desc, canonical=canonical, prefix=prefix,
                      month_year=month_year, h1=f"The best {_html_escape(name)} alternatives in 2026",
                      intro_html=intro, body_html=body, faq_ld=faq_ld,
                      breadcrumb_ld=breadcrumb_ld, faq_html=faq_html, page_ld=page_ld)


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
             f"{hi:,} runs it's <strong>{hi_name}</strong>. Self-hosted tools "
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
    <div class="warning-box" style="margin-top:16px"><strong>Note:</strong> self-hosted figures are the server bill (VPS + DB), not a tool fee — the software is free to self-host. Activepieces is $0 on its cloud free tier (up to 10 active flows). Values marked ~ are estimates for custom enterprise tiers.</div>
    <p style="margin-top:14px"><a href="calculator.html">Get your exact cheapest tool from the calculator →</a> · <a href="self-hosted-automation-cost.html">Self-host vs cloud cost →</a></p>
  </div>"""

    faq = [
        {"q": "What is the cheapest automation tool?",
         "a": (f"It depends on volume. Among cloud tools, the lowest published price we track at {lo:,} runs/month "
               f"is {lo_name}, and at {hi:,} runs it's {hi_name}. Self-hosted tools (n8n, Activepieces,"
               "Automatisch, Node-RED) are cheaper still — you pay only for the server. See the matrix above.")},
        {"q": "What is the cheapest cloud (no self-host) automation tool?",
         "a": ("Among fully managed cloud tools, the lowest cost shifts with volume — check the highlighted cells "
               'in the table for your run level, or use the <a href="calculator.html">calculator</a> for your exact numbers.')},
        {"q": "Is there a free automation tool?",
         "a": ("Yes. Activepieces has a cloud free tier (10 active flows, unlimited runs), and n8n, Activepieces, "
               "Automatisch and Node-RED are free to self-host for just a server cost.")},
        {"q": "How accurate are these prices?",
         "a": ("They're generated from each vendor's official pricing via our cost engine, verified "
               f"{month_year}; see the <a href=\"changelog.html\">price changelog</a> for every recorded change.")},
    ]
    faq_ld, faq_html = _seo_faq(faq)
    title = "The Cheapest Automation Tool in 2026 (Real Prices) | WizardCost"
    desc = (f"The cheapest automation tool in 2026, priced at every volume. At {lo:,} runs/mo it's {lo_name}; "
            f"at {hi:,} runs {hi_name}. Self-hosted tools run at just a server bill — see the full ranked matrix.")
    breadcrumb_ld = _seo_breadcrumb_ld(site, prefix, "Cheapest automation tool", canonical)
    page_ld = _page_graph_ld(site.get("domain", "wizardcost.com"), canonical,
                             "The Cheapest Automation Tool in 2026 (Real Prices)", desc,
                             _iso_date(tools_meta))
    return _seo_shell(title=title, desc=desc, canonical=canonical, prefix=prefix,
                      month_year=month_year, h1="The cheapest automation tool in 2026",
                      intro_html=intro, body_html=body, faq_ld=faq_ld,
                      breadcrumb_ld=breadcrumb_ld, faq_html=faq_html, page_ld=page_ld)


def render_selfhost_page(by_slug: dict, site: dict, tools_meta: dict, engine) -> str:
    """Self-host vs cloud cost hub — cílí na rostoucí self-host/n8n vlnu. VŠECHNA čísla
    z enginu (žádná nová cenová tvrzení). Self-host i cloud sloupec z hosting VARIANT podle
    hostingKind (vps/own vs saas/cloud) — aby cloud free tier (Activepieces $0) nezamořil
    self-host sloupec. Editorial = jen rámující próza + poctivý maintenance catch."""
    month_year = _month_year(tools_meta)
    prefix = _site_prefix(site.get("domain", "wizardcost.com"), site.get("base_path", ""))
    canonical = f"{prefix}/self-hosted-automation-cost.html"

    variants = expand_hosting_variants(list(by_slug.values()))
    sh_vars = [v for v in variants if v.get("hostingKind") == "vps"]   # realistický self-host = pronájem VPS
    cl_vars = [v for v in variants if v.get("hostingKind") in ("saas", "cloud")]
    sh_tool_names = ", ".join(t["name"] for t in by_slug.values() if t.get("selfHostable"))

    def _base_name(var):
        return _html_escape(by_slug[var["variantOf"]]["name"])

    def _best(vlist, vol, paid_only=False):
        cand = []
        for var in vlist:
            r = engine.cheapest_monthly(var, vol, STEPS)
            if r and (not paid_only or r["cost"] > 0):
                cand.append((var, r))
        return min(cand, key=lambda x: x[1]["cost"]) if cand else None

    # free cloud tier (typicky Activepieces $0, ≤10 flows) — poctivě disclose, neschovávat
    _free = _best(cl_vars, VOLUMES[-1])
    free_name = _base_name(_free[0]) if _free and _free[1]["cost"] == 0 else None
    free_caveat = (f"a free cloud tier ({free_name}, up to 10 active flows at $0) can undercut self-host on raw "
                   "cost for very small usage") if free_name else \
                  "free cloud tiers can undercut self-host on raw cost for very small usage"

    rows = []
    for vol in VOLUMES:
        sb, cb = _best(sh_vars, vol), _best(cl_vars, vol, paid_only=True)
        sh_cell = (f"{_fmt_usd(sb[1]['cost'], sb[1]['est'])} "
                   f"<span style=\"color:var(--muted);font-size:13px\">{_base_name(sb[0])}</span>") if sb else "—"
        cl_cell = (f"{_fmt_usd(cb[1]['cost'], cb[1]['est'])} "
                   f"<span style=\"color:var(--muted);font-size:13px\">{_base_name(cb[0])}</span>") if cb else "—"
        if sb and cb:
            cheaper = "Self-host" if sb[1]["cost"] < cb[1]["cost"] else ("Cloud" if cb[1]["cost"] < sb[1]["cost"] else "Tie")
        else:
            cheaper = "—"
        cls = ' class="cheap"' if cheaper == "Self-host" else ""
        rows.append(f"        <tr><td>{vol:,} runs/mo</td><td{cls}>{sh_cell}</td><td>{cl_cell}</td><td>{cheaper}</td></tr>")
    table = "\n".join(rows)

    lo, hi = VOLUMES[0], VOLUMES[-1]
    sb_lo, cb_lo = _best(sh_vars, lo), _best(cl_vars, lo, paid_only=True)
    sb_hi, cb_hi = _best(sh_vars, hi), _best(cl_vars, hi, paid_only=True)
    sh_lo_fmt = _fmt_usd(sb_lo[1]["cost"], sb_lo[1]["est"]) if sb_lo else "a low server bill"
    sh_hi_fmt = _fmt_usd(sb_hi[1]["cost"], sb_hi[1]["est"]) if sb_hi else "—"
    cl_lo_fmt = _fmt_usd(cb_lo[1]["cost"], cb_lo[1]["est"]) if cb_lo else "—"
    cl_hi_fmt = _fmt_usd(cb_hi[1]["cost"], cb_hi[1]["est"]) if cb_hi else "—"

    intro = (
        "Self-hosting means running the automation software on your own server, so you pay for the "
        f"server — not a per-run subscription. {sh_tool_names} are free to self-host: their "
        f"cost is just the VPS (plus a database at scale), which our engine models from about {sh_lo_fmt}/mo. "
        f"Against paid cloud the maths is one-sided: self-host runs about {sh_lo_fmt}/mo at {lo:,} runs versus "
        f"{cl_lo_fmt} for the cheapest paid cloud plan, and the gap widens to {sh_hi_fmt} vs {cl_hi_fmt} at "
        f"{hi:,} runs, because a server bill is roughly flat while cloud is priced per run. One honest caveat: "
        f"{free_caveat}. And self-host is only “free” if you don’t count your own time to set up, secure, "
        "monitor and back up the server.")

    body = f"""  <div class="section">
    <h2>Self-host vs paid cloud: cost at each volume</h2>
    <p class="section-sub">Cheapest self-host (rented VPS) vs cheapest <em>paid</em> managed-cloud plan, 3-step workflows, generated live from our data. Self-host figures are the server bill (VPS + database), not a tool fee. Free cloud tiers are excluded from the table and discussed below.</p>
    <table class="comparison-table">
      <thead><tr><th>Volume</th><th>Cheapest self-host</th><th>Cheapest paid cloud</th><th>Cheaper</th></tr></thead>
      <tbody>
{table}
      </tbody>
    </table>
    <div class="warning-box" style="margin-top:16px"><strong>Two honest catches:</strong> (1) self-host figures cover only the server (VPS + database) — they exclude your time to install, secure, update, monitor and back up the stack, which for a small team can outweigh the saving. (2) {free_caveat[0].upper() + free_caveat[1:]}. The software is free to self-host; the figure shown is infrastructure. Values marked ~ are estimates for custom tiers.</div>
    <p style="margin-top:14px"><a href="calculator.html">Get your exact cheapest setup from the calculator →</a> · <a href="cheapest-automation-tool.html">Cheapest automation tool overall →</a></p>
  </div>"""

    faq = [
        {"q": "Is self-hosting n8n worth it?",
         "a": (f"Versus paid cloud, usually yes on cost: self-hosted n8n runs on a flat VPS bill (from about "
               f"{sh_lo_fmt}/mo) with no per-run fees, while n8n Cloud and other paid plans climb with usage. The "
               "trade-offs are your own time to set up, secure and maintain the server — and that a free cloud "
               'tier can be cheaper still for very small usage. Model your exact numbers in the '
               '<a href="calculator.html">calculator</a>.')},
        {"q": "How much does self-hosted automation cost?",
         "a": (f"Only the server it runs on. Our engine models {sh_tool_names} self-hosted from about {sh_lo_fmt}/mo "
               "(small VPS, low volume) up to higher tiers as throughput grows and you add a database — the "
               "software itself is free to self-host.")},
        {"q": "Cloud vs self-host — which is cheaper?",
         "a": (f"Against paid cloud, self-host is cheaper at every volume in our data — about {sh_lo_fmt} vs "
               f"{cl_lo_fmt} at {lo:,} runs, widening to {sh_hi_fmt} vs {cl_hi_fmt} at {hi:,} runs. The exception "
               "is free cloud tiers (up to ~10 flows), which can undercut self-host for small usage. See the "
               "table above.")},
        {"q": "Which automation tools can be self-hosted?",
         "a": (f"{sh_tool_names} are self-hostable. Make, Zapier and Pipedream are cloud-only. If "
               "you need EU data residency or full control, these self-hostable tools are the ones to look at.")},
        {"q": "How accurate are these prices?",
         "a": ("They're generated from each vendor's official pricing and our server-cost model via the cost "
               f"engine, verified {month_year}; see the <a href=\"changelog.html\">price changelog</a>.")},
    ]
    faq_ld, faq_html = _seo_faq(faq)
    title = "Self-Hosted Automation Cost 2026 — Cloud vs Self-Host (Real Prices) | WizardCost"
    desc = (f"Self-hosted automation cost in 2026: {sh_tool_names} run on a VPS from about {sh_lo_fmt}/mo vs "
            f"{cl_lo_fmt}+ for paid cloud — self-host beats paid cloud at every volume, though free tiers can "
            "undercut it for small usage. Real comparison plus the maintenance catch.")
    breadcrumb_ld = _seo_breadcrumb_ld(site, prefix, "Self-hosted automation cost", canonical)
    page_ld = _page_graph_ld(site.get("domain", "wizardcost.com"), canonical,
                             "Self-hosted automation cost in 2026 — cloud vs self-host", desc,
                             _iso_date(tools_meta))
    return _seo_shell(title=title, desc=desc, canonical=canonical, prefix=prefix,
                      month_year=month_year, h1="Self-hosted automation cost in 2026",
                      intro_html=intro, body_html=body, faq_ld=faq_ld,
                      breadcrumb_ld=breadcrumb_ld, faq_html=faq_html, page_ld=page_ld)


def render_roi_page(by_slug: dict, site: dict, tools_meta: dict, engine) -> str:
    """ROI / break-even kalkulačka — "Is automation worth it?"

    Server-rendered obsah (crawlovatelné + AI-citovatelné):
    - Intro odpovídající "is automation worth it"
    - Vysvětlení vzorce ROI
    - Worked-example tabulka (scénáře × cheapest tool z enginu)
    - Interaktivní ROI widget (self-contained client JS)
    - "When NOT worth it" sekce (poctivost = feature)
    - FAQ + JSON-LD

    NÁKLADOVÁ STRANA: z enginu (cheapest_monthly). Žádná třetí kopie pricing logiky.
    MINUTY/HODINA: editorial DEFAULT, označeno jako ilustrativní, uživatelsky nastavitelné.
    """
    month_year = _month_year(tools_meta)
    prefix = _site_prefix(site.get("domain", "wizardcost.com"), site.get("base_path", ""))
    canonical = f"{prefix}/is-automation-worth-it.html"

    # ── Nákladová strana z enginu: cheapest tool per scénář ──────────────────
    # Tři reprezentativní scénáře: low / mid / high volume
    # Parametry: (label, runs/mo, tasks/run_for_display, hrly_rate)
    ROI_SCENARIOS = [
        ("Small team (500 runs/mo)",    500,   3,  30),
        ("Growing team (5,000 runs/mo)", 5000,  3,  40),
        ("Active ops (20,000 runs/mo)", 20000, 3,  50),
    ]
    scenario_rows = []
    for label, runs, _steps, hr in ROI_SCENARIOS:
        best_slug, best_r = None, None
        for s in PRICING_SLUGS:
            r = engine.cheapest_monthly(by_slug[s], runs, STEPS)
            # paid_only=True: free-tier ($0) tools skipped — ROI tabulka ukazuje
            # reálný placený tool, aby net savings / return / break-even byly konečné.
            if r and r["cost"] > 0 and (best_r is None or r["cost"] < best_r["cost"]):
                best_slug, best_r = s, r
        if best_r is None:
            continue
        tool_name = by_slug[best_slug]["name"] if best_slug else "—"
        tool_cost = best_r["cost"]
        # Illustrative default: 3 min saved per run (editorial, NOT vendor claim)
        mins_saved_per_run = 3
        hrs_saved = (runs * mins_saved_per_run) / 60
        value_usd = hrs_saved * hr
        net = value_usd - tool_cost
        roi_x = round(value_usd / tool_cost, 0) if tool_cost > 0 else None
        # break-even: how many total minutes/mo needed to cover tool cost
        be_mins = (tool_cost / hr) * 60 if (hr > 0 and tool_cost > 0) else None

        roi_str = f"{int(roi_x):,}x" if roi_x is not None else "∞ (free tier)"
        be_str = f"~{int(be_mins):,} min/mo" if be_mins is not None else "n/a (free tier)"
        row_class = ' class="cheap"' if net > 0 else ""
        scenario_rows.append(
            f"        <tr>"
            f"<td>{label}</td>"
            f"<td>${tool_cost:,.0f}/mo<br><span style=\"color:var(--muted);font-size:12px\">{tool_name}</span></td>"
            f"<td>{hrs_saved:,.0f} hrs</td>"
            f"<td>${value_usd:,.0f}</td>"
            f"<td{row_class}>${net:,.0f}</td>"
            f"<td>{roi_str}</td>"
            f"<td>{be_str}</td>"
            f"</tr>"
        )
    table_rows = "\n".join(scenario_rows)

    # Anchor cheapest tool at the representative ALT_VOL for hero summary
    anchor_slug, anchor_r = None, None
    for s in PRICING_SLUGS:
        r = engine.cheapest_monthly(by_slug[s], ALT_VOL, STEPS)
        if r and (anchor_r is None or r["cost"] < anchor_r["cost"]):
            anchor_slug, anchor_r = s, r
    anchor_name = by_slug[anchor_slug]["name"] if anchor_slug else "n8n"
    anchor_cost_fmt = _fmt_usd(anchor_r["cost"], anchor_r["est"]) if anchor_r else "$8"

    # ── body: worked-example table + widget + when-not-worth-it ─────────────
    body = f"""  <div class="section">
    <h2>The ROI formula — how the maths works</h2>
    <p class="section-sub">Automation earns back time. Time has a dollar value. Compare that value to the tool cost and you get ROI.</p>
    <div class="warning-box" style="margin-bottom:24px">
      <strong>Formula:</strong> <em>Value of time saved = (runs/mo &times; minutes saved per run &divide; 60) &times; your hourly rate.</em>
      Net savings = value &minus; tool cost. Return on cost = value &divide; tool cost. Break-even = tool cost &divide; (hourly rate &divide; 60) minutes per month.
    </div>
    <p style="color:var(--muted);font-size:13.5px;margin-bottom:20px">
      The table below uses <strong>3 min saved per run</strong> as a conservative editorial default and three typical hourly rates. These are illustrative starting points — adjust them in the interactive calculator below.
      <strong>Minutes saved per run is NOT a vendor claim</strong> — it is your estimate based on how long you currently do the task manually.
    </p>
    <div style="overflow-x:auto">
    <table class="comparison-table">
      <thead>
        <tr>
          <th>Scenario</th>
          <th>Cheapest tool ({month_year})</th>
          <th>Time saved</th>
          <th>Value of time</th>
          <th>Net savings/mo</th>
          <th>Return on cost</th>
          <th>Break-even</th>
        </tr>
      </thead>
      <tbody>
{table_rows}
      </tbody>
    </table>
    </div>
    <p class="tbl-note" style="margin-top:10px">
      Tool costs generated live from official pricing via our engine, verified {month_year}.
      "Value of time" uses an illustrative 3 min/run &times; $40/hr default — change it in the calculator below.
      Table shows the cheapest <em>paid</em> plan per scenario — a free tier (Activepieces cloud free tier, up to 10 active flows) or self-hosted option (n8n, Activepieces, Node-RED) can bring tool cost to $0 and push ROI even higher; see the <a href="cheapest-automation-tool.html">cheapest-tool breakdown</a> or <a href="self-hosted-automation-cost.html">self-host vs cloud cost</a>.
      Values marked ~ are estimates for custom enterprise tiers.
    </p>
  </div>

  <!-- ── Interactive ROI widget ── self-contained, no framework dependency ── -->
  <div class="section" id="roi-widget">
    <h2>ROI calculator — your numbers</h2>
    <p class="section-sub">Enter your own values. All arithmetic happens client-side; no data is sent anywhere.</p>
    <div class="roi-card">
      <div class="roi-inputs">
        <div class="roi-field">
          <label class="roi-label" for="roi-runs">Runs / tasks per month</label>
          <input type="number" id="roi-runs" class="roi-input" value="1000" min="1" max="1000000" step="100">
          <div class="roi-hint">How many automated tasks run per month total</div>
        </div>
        <div class="roi-field">
          <label class="roi-label" for="roi-mins">Minutes saved per run <span class="roi-est-badge">your estimate</span></label>
          <input type="number" id="roi-mins" class="roi-input" value="3" min="0.1" max="120" step="0.5">
          <div class="roi-hint">How long you currently spend on this task manually (per single run)</div>
        </div>
        <div class="roi-field">
          <label class="roi-label" for="roi-rate">Your hourly rate ($)</label>
          <input type="number" id="roi-rate" class="roi-input" value="40" min="1" max="500" step="5">
          <div class="roi-hint">Your loaded hourly cost or opportunity cost. VA rate, employee fully-loaded cost, or your own time value.</div>
        </div>
      </div>
      <div class="roi-disclosure">
        <strong>What this calculates:</strong> value of time freed from manual work &times; your rate.
        It does <em>not</em> account for: automation setup time, ongoing maintenance, error handling, or tasks that cannot be fully automated.
        Minutes per run is <strong>your estimate</strong> — not a vendor benchmark or our claim.
      </div>
      <div class="roi-results" id="roi-results" hidden>
        <div class="roi-results-grid">
          <div class="roi-stat">
            <div class="roi-stat-label">Time saved</div>
            <div class="roi-stat-value" id="r-hours">—</div>
            <div class="roi-stat-sub">hrs / month</div>
          </div>
          <div class="roi-stat">
            <div class="roi-stat-label">Value of time</div>
            <div class="roi-stat-value accent" id="r-value">—</div>
            <div class="roi-stat-sub">at your rate</div>
          </div>
          <div class="roi-stat">
            <div class="roi-stat-label">Cheapest tool</div>
            <div class="roi-stat-value" id="r-tool">—</div>
            <div class="roi-stat-sub" id="r-tool-name">—</div>
          </div>
          <div class="roi-stat roi-stat-accent">
            <div class="roi-stat-label">Net savings / mo</div>
            <div class="roi-stat-value" id="r-net">—</div>
            <div class="roi-stat-sub" id="r-net-sub">value minus tool cost</div>
          </div>
          <div class="roi-stat">
            <div class="roi-stat-label">Return on cost</div>
            <div class="roi-stat-value" id="r-roi">—</div>
            <div class="roi-stat-sub">value &divide; tool cost</div>
          </div>
          <div class="roi-stat">
            <div class="roi-stat-label">Break-even point</div>
            <div class="roi-stat-value" id="r-be">—</div>
            <div class="roi-stat-sub">min/mo to cover cost</div>
          </div>
        </div>
        <div class="roi-payback" id="r-payback-row">
          <span id="r-payback-label">Payback period:</span> <strong id="r-payback">—</strong>
        </div>
        <div class="roi-cta-row">
          <a href="calculator.html" class="btn-primary">Find the exact cheapest tool for my volume →</a>
          <a href="compare.html" class="btn-secondary">Compare all 7 tools</a>
        </div>
        <div class="tbl-note" style="margin-top:12px">
          Tool cost from official pricing via our engine ({month_year}). ROI calculation is illustrative — see the disclosure above.
          <a href="changelog.html">Price changelog</a> · <a href="cheapest-automation-tool.html">Cheapest tool breakdown</a>
        </div>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>When automation is NOT worth it</h2>
    <p class="section-sub">Honesty is a feature. Automation isn't always the right call — here's when the ROI math turns negative.</p>
    <table class="comparison-table">
      <thead><tr><th>Situation</th><th>Why ROI suffers</th><th>Verdict</th></tr></thead>
      <tbody>
        <tr>
          <td>Very low volume (&lt; ~50 runs/mo)</td>
          <td>Setup and maintenance time exceeds the hours saved. Even at 3 min/run and $40/hr, 50 runs saves 2.5 hrs — but initial setup of a decent workflow often takes 4–10 hrs.</td>
          <td class="tag-no">Skip or defer</td>
        </tr>
        <tr>
          <td>One-off or irregular tasks</td>
          <td>If the task runs once, automation ROI is negative by definition — you spend more building it than doing it once manually.</td>
          <td class="tag-no">Do it manually</td>
        </tr>
        <tr>
          <td>High exception rate (&gt; 20% failures)</td>
          <td>Automations that need constant human intervention aren't saving time — they're shifting it. Net savings drop fast when you add error-handling overhead.</td>
          <td class="tag-warn">Fix the process first</td>
        </tr>
        <tr>
          <td>Process is poorly defined</td>
          <td>"Automate chaos and you get automated chaos." If humans can't do the task consistently, an automation won't either. Nail the process first.</td>
          <td class="tag-warn">Document before automating</td>
        </tr>
        <tr>
          <td>Maintenance overhead is high</td>
          <td>API changes, credential rotations, upstream format changes — maintenance on fragile integrations can consume more time than the automation saves. Factor in realistic upkeep.</td>
          <td class="tag-warn">Budget maintenance time</td>
        </tr>
        <tr>
          <td>High-volume, straightforward tasks</td>
          <td>When volume is high and the task is clean, automation is almost always worth it. ROI scales linearly with runs — the more you do, the better the payback.</td>
          <td class="tag-yes">Strong ROI</td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="section">
    <h2>Next steps</h2>
    <p class="section-sub">Once you know automation is worth it, the cost of the tool matters — use these to find the cheapest option for your volume.</p>
    <div class="related-grid">
      <a href="calculator.html" class="related-card">
        <div class="related-card-name">Automation cost calculator</div>
        <div class="related-card-desc">Your exact volume → cheapest tool ranked</div>
      </a>
      <a href="compare.html" class="related-card">
        <div class="related-card-name">Compare all 7 tools</div>
        <div class="related-card-desc">Side-by-side pricing, limits &amp; features</div>
      </a>
      <a href="cheapest-automation-tool.html" class="related-card">
        <div class="related-card-name">Cheapest automation tool</div>
        <div class="related-card-desc">Full ranked matrix at every volume</div>
      </a>
      <a href="self-hosted-automation-cost.html" class="related-card">
        <div class="related-card-name">Self-host vs cloud cost</div>
        <div class="related-card-desc">When self-hosting beats paid cloud</div>
      </a>
    </div>
  </div>"""

    # ── Pricing lookup table for client widget (engine data, representative volumes) ──
    # JS-side: given runs, find cheapest tool cost via linear interpolation between anchor points.
    # We emit a lookup array [[runs, toolSlug, toolName, costUsd, isEst], ...] sorted by runs.
    # The widget uses this to anchor "tool cost" rather than hardcoding any prices.
    _widget_anchors = []
    for vol in [100, 250, 500, 1000, 2500, 5000, 10000, 20000, 50000, 100000]:
        best_s, best_r = None, None
        for s in PRICING_SLUGS:
            r = engine.cheapest_monthly(by_slug[s], vol, STEPS)
            if r and (best_r is None or r["cost"] < best_r["cost"]):
                best_s, best_r = s, r
        if best_r:
            _widget_anchors.append({
                "runs": vol,
                "slug": best_s,
                "name": by_slug[best_s]["name"],
                "cost": round(best_r["cost"], 2),
                "est": best_r["est"],
            })
    anchors_json = json.dumps(_widget_anchors, ensure_ascii=False)

    # ── FAQ ─────────────────────────────────────────────────────────────────
    # Anchor cheapest cost used in FAQ (engine data at a concrete volume)
    _faq_vol = 1000
    _faq_best_s, _faq_best_r = None, None
    for s in PRICING_SLUGS:
        r = engine.cheapest_monthly(by_slug[s], _faq_vol, STEPS)
        if r and (_faq_best_r is None or r["cost"] < _faq_best_r["cost"]):
            _faq_best_s, _faq_best_r = s, r
    _faq_tool = by_slug[_faq_best_s]["name"] if _faq_best_s else "n8n"
    _faq_cost = _fmt_usd(_faq_best_r["cost"], _faq_best_r["est"]) if _faq_best_r else "$8"

    faq = [
        {"q": "Is automation worth the cost?",
         "a": (f"For recurring, well-defined tasks at meaningful volume, yes — often significantly. At 1,000 runs/mo, "
               f"saving 3 min per run frees ~50 hrs of work. Valued at $40/hr that is $2,000 in time against a tool "
               f"cost starting from {_faq_cost}/mo ({_faq_tool} at {_faq_vol:,} runs). "
               "The maths turns negative for very low volume (under ~50 runs/mo), one-off tasks, or processes "
               "with high exception rates. Use the calculator above to model your exact scenario.")},
        {"q": "How do I calculate automation ROI?",
         "a": ("ROI = (value of time saved &minus; tool cost) &divide; tool cost. "
               "Value of time saved = (runs/mo &times; minutes saved per run &divide; 60) &times; your hourly rate. "
               "The break-even point is: tool cost &divide; (hourly rate &divide; 60) = minimum minutes per month needed "
               "to cover the tool. The calculator on this page does all of this from your inputs.")},
        {"q": "How long does automation take to pay for itself?",
         "a": (f"At common volumes and rates, payback is effectively immediate — a {_faq_cost}/mo tool "
               "against even $500/mo in time saved pays back on day one of the month. Payback only stretches "
               "longer when setup time is large relative to ongoing savings — factor in how many hours it takes "
               "to build and maintain the workflow, not just the run-time savings.")},
        {"q": "Automation vs hiring a VA — which is cheaper?",
         "a": ("A VA costs $5–25/hr (offshore) or $15–50/hr (domestic) plus your coordination time. "
               "An automation tool costs $8–$150/mo depending on volume. For tasks a VA would spend "
               "10+ hrs/mo on, automation almost always wins on unit economics — but only if the task "
               "is structured enough to automate reliably. Hybrid (automation handles the repeatable "
               "steps, VA handles exceptions) is often the real-world answer.")},
        {"q": "How much time does automation actually save?",
         "a": ("It depends entirely on the task. Simple data-transfer automations (copy row from form "
               "to CRM, send a notification) typically save 1–5 minutes per run. Multi-step document "
               "processing or approval workflows can save 15–30 min per run. The 3 min/run default in "
               "our calculator is a conservative starting point for simple workflows — adjust it to match "
               "your actual task. We do not make a claim about what automations save; that is your "
               "measurement to make from your own process.")},
        {"q": "What is the cheapest automation tool right now?",
         "a": (f"At {ALT_VOL:,} runs/month the cheapest option we track is "
               f"{anchor_name} at {anchor_cost_fmt}/mo (verified {month_year}). "
               "Self-hosted tools (n8n, Activepieces, Node-RED) cost only the server, which is lower still. "
               f"See the <a href=\"cheapest-automation-tool.html\">full ranked matrix</a> or the "
               f"<a href=\"calculator.html\">calculator</a> for your exact volume.")},
        {"q": "How accurate are the tool costs in this calculator?",
         "a": (f"Tool costs are generated from each vendor's official public pricing via our cost engine, "
               f"verified {month_year}. Every price change we record is dated in the "
               '<a href="changelog.html">price changelog</a>. Values marked ~ are estimates for custom '
               "enterprise tiers. We do not add any markup or adjustment to the engine output.")},
    ]
    faq_ld, faq_html = _seo_faq(faq)

    # ── JSON-LD ──────────────────────────────────────────────────────────────
    title = "Is Automation Worth It? ROI &amp; Break-Even Calculator 2026 | WizardCost"
    desc = (f"Calculate automation ROI: enter your runs, minutes saved and hourly rate — get net savings, "
            f"return on cost and break-even. Tool costs from official pricing (cheapest at {ALT_VOL:,} runs: "
            f"{anchor_name} at {anchor_cost_fmt}/mo, verified {month_year}).")
    breadcrumb_ld = _seo_breadcrumb_ld(site, prefix, "Is automation worth it?", canonical)
    page_ld = _page_graph_ld(site.get("domain", "wizardcost.com"), canonical,
                             "Is Automation Worth It? ROI & Break-Even Calculator 2026", desc,
                             _iso_date(tools_meta))

    # ── Widget JS (self-contained, client-side) ──────────────────────────────
    # Interpolates cheapest tool cost from engine anchors; computes ROI metrics from user inputs.
    # anchor lookup: given user runs, find cheapest tool cost via step interpolation.
    widget_js = f"""
/* ── ROI widget — self-contained, no dependencies ── */
(function () {{
  var ANCHORS = {anchors_json};

  function findAnchor(runs) {{
    if (!ANCHORS.length) return null;
    // Exact match or step down to nearest anchor below
    var best = ANCHORS[0];
    for (var i = 0; i < ANCHORS.length; i++) {{
      if (ANCHORS[i].runs <= runs) best = ANCHORS[i];
      else break;
    }}
    return best;
  }}

  function fmt(n, prefix) {{
    if (n === null || isNaN(n)) return '—';
    var rounded = Math.round(n);
    return (prefix || '') + rounded.toLocaleString('en-US');
  }}

  function compute() {{
    var runs = parseFloat(document.getElementById('roi-runs').value) || 0;
    var mins = parseFloat(document.getElementById('roi-mins').value) || 0;
    var rate = parseFloat(document.getElementById('roi-rate').value) || 0;
    if (runs <= 0 || mins <= 0 || rate <= 0) {{
      document.getElementById('roi-results').hidden = true;
      return;
    }}

    var anchor = findAnchor(runs);
    var toolCost = anchor ? anchor.cost : 8;
    var toolName = anchor ? anchor.name : 'cheapest tool';
    var toolEst  = anchor ? anchor.est  : false;

    var hrsSaved = (runs * mins) / 60;
    var value    = hrsSaved * rate;
    var net      = value - toolCost;
    var roiX     = toolCost > 0 ? value / toolCost : null;
    // break-even: how many total minutes/mo to cover tool cost
    var beMins   = rate > 0 ? (toolCost / rate) * 60 : null;

    // Payback period: if break-even < 1 day → "< 1 day"; else days
    var paybackStr = '';
    if (beMins !== null) {{
      // mins of work per month vs total minutes used per month
      // calendar: assume 22 working days, 8 hrs each = 10560 min/mo
      var workingMinsPerMo = 22 * 8 * 60;
      if (beMins <= 0) {{
        paybackStr = 'Immediate';
      }} else if (beMins < workingMinsPerMo / 22) {{
        paybackStr = '< 1 working day';
      }} else {{
        var days = Math.ceil(beMins / (8 * 60));
        paybackStr = days + ' working day' + (days !== 1 ? 's' : '');
      }}
    }}

    document.getElementById('r-hours').textContent    = hrsSaved < 1 ? hrsSaved.toFixed(1) + ' hrs' : fmt(hrsSaved) + ' hrs';
    document.getElementById('r-value').textContent    = '$' + Math.round(value).toLocaleString('en-US');
    document.getElementById('r-tool').textContent     = (toolEst ? '~' : '') + '$' + toolCost.toLocaleString('en-US', {{minimumFractionDigits: 0, maximumFractionDigits: 2}}) + '/mo';
    document.getElementById('r-tool-name').textContent = toolName + ' (at your volume)';
    document.getElementById('r-net').textContent      = (net >= 0 ? '+' : '') + '$' + Math.round(net).toLocaleString('en-US') + '/mo';
    document.getElementById('r-net-sub').textContent  = net >= 0 ? 'value minus tool cost' : 'cost exceeds time value — check volume or rate';
    document.getElementById('r-roi').textContent      = roiX !== null ? Math.round(roiX) + 'x' : '—';
    document.getElementById('r-be').textContent       = beMins !== null ? Math.ceil(beMins) + ' min/mo' : '—';

    var prow = document.getElementById('r-payback-row');
    if (paybackStr) {{
      document.getElementById('r-payback').textContent = paybackStr;
      prow.hidden = false;
    }} else {{
      prow.hidden = true;
    }}

    // Colour net savings
    var netEl = document.getElementById('r-net');
    netEl.className = 'roi-stat-value' + (net >= 0 ? ' accent' : ' warn');

    document.getElementById('roi-results').hidden = false;
  }}

  ['roi-runs', 'roi-mins', 'roi-rate'].forEach(function (id) {{
    var el = document.getElementById(id);
    if (el) {{ el.addEventListener('input', compute); el.addEventListener('change', compute); }}
  }});
  compute();
}})();
"""

    # ── Widget CSS (injected into page style block) ───────────────────────────
    widget_css = """
    /* ── ROI widget ── */
    .roi-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 28px; margin-bottom: 8px; }
    .roi-inputs { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 20px; }
    .roi-field { display: flex; flex-direction: column; gap: 6px; }
    .roi-label { font-size: 13px; font-weight: 700; color: var(--text); }
    .roi-est-badge { background: rgba(245,158,11,0.15); color: var(--orange); border-radius: 4px; padding: 1px 6px; font-size: 11px; font-weight: 700; margin-left: 6px; }
    .roi-input { background: var(--bg); border: 1px solid var(--border2); border-radius: var(--radius-sm); padding: 10px 14px; color: var(--text); font-family: var(--mono); font-size: 1rem; font-weight: 700; width: 100%; transition: border-color 0.15s; }
    .roi-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(16,185,129,0.15); }
    .roi-hint { font-size: 12px; color: var(--muted); line-height: 1.5; }
    .roi-disclosure { background: rgba(245,158,11,0.06); border: 1px solid rgba(245,158,11,0.2); border-radius: 8px; padding: 14px 18px; font-size: 13px; color: var(--text2); line-height: 1.6; margin-bottom: 20px; }
    .roi-results { border-top: 1px solid var(--border); padding-top: 24px; }
    .roi-results-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(155px, 1fr)); gap: 14px; margin-bottom: 18px; }
    .roi-stat { background: var(--surface2); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 16px 18px; }
    .roi-stat-accent { border-color: rgba(16,185,129,0.35); background: rgba(16,185,129,0.06); }
    .roi-stat-label { font-family: var(--mono); font-size: 10.5px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); margin-bottom: 6px; }
    .roi-stat-value { font-family: var(--mono); font-size: 1.35rem; font-weight: 800; color: var(--text); letter-spacing: -0.02em; }
    .roi-stat-value.accent { color: var(--accent-br); }
    .roi-stat-value.warn { color: var(--orange); }
    .roi-stat-sub { font-size: 11.5px; color: var(--muted); margin-top: 3px; }
    .roi-payback { font-size: 14px; color: var(--text2); margin-bottom: 16px; }
    .roi-cta-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
    .tbl-note { font-family: var(--mono); font-size: 11.5px; color: var(--muted); line-height: 1.7; }
    @media (max-width: 520px) {
      .roi-card { padding: 18px; }
      .roi-inputs { grid-template-columns: 1fr; }
      .roi-results-grid { grid-template-columns: repeat(2, 1fr); }
      .roi-cta-row { flex-direction: column; }
      .roi-cta-row > a { text-align: center; }
    }"""

    css = _PRICING_CSS + widget_css

    intro = (
        f"Yes — for recurring, well-defined tasks at meaningful volume. "
        f"The cheapest automation tool we track at {ALT_VOL:,} runs/month costs {anchor_cost_fmt}/mo ({anchor_name}, {month_year}). "
        "If your team spends even a few hours a month on repeatable manual work, that tool cost is typically a fraction "
        "of the time value freed. This page lets you calculate your specific ROI: enter your volume, minutes saved "
        "per task, and hourly rate — see your net savings, return on cost, and break-even in seconds. "
        "We also cover when automation is <em>not</em> worth it, because that matters too."
    )

    # ── Full page HTML ─────────────────────────────────────────────────────
    # Using _seo_shell would miss the widget JS. Build the page directly.
    domain = site.get("domain", "wizardcost.com")
    og_title = "Is Automation Worth It? ROI & Break-Even Calculator 2026"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build_pricing.py (render_roi_page) z data/tools.json — needituj ručně -->
  <title>{_clamp_title(title)}</title>
  <meta name="description" content="{_html_escape(_clamp_desc(desc))}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="AutomationCost.io">
  <meta property="og:title" content="{_html_escape(og_title)}">
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
  <script type="application/ld+json">
{page_ld}
  </script>
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
{css}
  </style>
  <link rel="stylesheet" href="app.css">
  <link rel="stylesheet" href="dashboard.css">
</head>
<body class="ac anim">

{_dashboard_header(active="")}

<div class="wrap">

  <div class="page-hero">
    <div class="nav-badge" style="display:inline-flex;margin-bottom:20px">Updated {month_year}</div>
    <h1>Is automation worth it?</h1>
    <p>{intro}</p>
    <div class="cta-row">
      <a href="#roi-widget" class="btn-primary">Calculate my ROI</a>
      <a href="calculator.html" class="btn-secondary">Find cheapest tool for my volume</a>
    </div>
    <div class="hero-trust">Tool costs verified {month_year} · generated live from official pricing · all figures per <strong>run</strong>, 3-step workflows</div>
  </div>

{body}

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
  <div style="margin-top:6px">Tool costs on this page come from each vendor's official public pricing page via our cost engine — the same data powering the calculator. ROI calculations are illustrative: they use your inputs and do not account for setup time, maintenance, or tasks that cannot be fully automated. We do not claim any specific time savings — that is your measurement to make from your own process.</div>
  <div style="margin-top:6px"><a href="methodology.html">Methodology</a> · <a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> · <a href="affiliate.html">Affiliate Disclosure</a></div>
</footer>

<script>
function toggleFaq(el) {{ el.closest(".faq-item").classList.toggle("open"); }}
{widget_js}
</script>
<a href="calculator.html" class="funnel-fab" aria-label="Find my cheapest tool"><svg width="17" height="17" viewBox="0 0 48 48" fill="none"><path d="M29 11 L15 24 L29 37" stroke="#04130d" stroke-width="6.4" stroke-linecap="round" stroke-linejoin="round"/><circle cx="34.5" cy="24" r="3.4" fill="#04130d"/></svg> Find my best tool</a>
<script src="app.js"></script>
</body>
</html>
"""



def render_hidden_cost_page(by_slug: dict, site: dict, tools_meta: dict, engine) -> str:
    """Generuje automation/hidden-cost-automation.html — skryté náklady platforem.

    Všechna čísla z enginu / tools.json (žádná nová cenová tvrzení).
    REVIEW: editorial prose + overage/upgrade logic needs owner sign-off.
    """
    month_year = _month_year(tools_meta)
    prefix = _site_prefix(site.get("domain", "wizardcost.com"), site.get("base_path", ""))
    canonical = f"{prefix}/hidden-cost-automation.html"

    # ── sekce 1: overage / upgrade chování ──────────────────────────────────
    # Zdrojem je tools.json: overage: null na plan úrovni = žádné PAYG, upgrade na vyšší tier.
    # Pipedream má creditBands (tiered per-credit rate) na paid plánech, ale per _meta todo
    # (2026-06-13): overage je nyní "Contact Sales only" — zobrazujeme creditBands jako referenci.
    def _overage_behavior(tool: dict) -> str:
        """Textový popis co se stane po překročení limitu — čistě z tools.json."""
        slug = tool["slug"]
        # zjisti, zda má JAKÝKOLI placený plán creditBands (Pipedream)
        has_credit_bands = any(p.get("creditBands") for p in tool.get("plans", []))
        # zjisti, zda má nástroj opsIncluded limity (tedy může překročit)
        paid_plans_with_limit = [p for p in tool.get("plans", [])
                                  if p.get("monthlyUsd") and p.get("opsIncluded")]
        if not paid_plans_with_limit and not has_credit_bands:
            # self-host only (n8n self-host, Activepieces, Automatisch, Node-RED)
            return "No ops limit — self-host runs are unlimited by software"
        if has_credit_bands:
            return "Tiered per-credit rate applies (Contact Sales for current rates)"
        # všechny ostatní placené plány s overage: null = tier upgrade
        return "Must upgrade to next volume tier (no pay-as-you-go)"

    def _entry_plan(tool: dict) -> dict | None:
        """Nejlevnější placený plán s opsIncluded (ne self-host only)."""
        candidates = [p for p in tool.get("plans", [])
                      if p.get("monthlyUsd") and p.get("opsIncluded")
                      and not p.get("selfHostOnly")]
        return min(candidates, key=lambda p: p["monthlyUsd"]) if candidates else None

    overage_rows = []
    for slug in PRICING_SLUGS:
        t = by_slug[slug]
        ep = _entry_plan(t)
        if ep:
            limit_str = f"{ep['opsIncluded']:,} {t.get('unitModel', 'runs')}/mo"
            price_str = f"${ep['monthlyUsd']:,.2f}".rstrip("0").rstrip(".") + "/mo"
        else:
            limit_str = "Unlimited (self-host)"
            price_str = "Server cost only"
        behavior = _overage_behavior(t)
        overage_rows.append(
            f"        <tr>"
            f"<td><a href=\"{slug}-pricing.html\">{_html_escape(t['name'])}</a></td>"
            f"<td>{limit_str}</td>"
            f"<td>{price_str}</td>"
            f"<td>{behavior}</td>"
            f"</tr>"
        )
    overage_table = "\n".join(overage_rows)

    # ── sekce 2: annual billing markup ──────────────────────────────────────
    # markup % = (monthlyUsd - annualUsd) / annualUsd * 100
    # Pokud plán nemá annualUsd → "No annual option" (platba jen měsíčně)
    def _annual_markup(tool: dict) -> tuple[str, str, str]:
        """(monthly_str, annual_str, markup_str) — z entry plánu s oběma cenami."""
        ep = _entry_plan(tool)
        if not ep:
            return ("Server cost", "Server cost", "N/A")
        monthly = ep.get("monthlyUsd")
        annual = ep.get("annualUsd")
        if monthly is None:
            return ("Custom", "Custom", "N/A")
        m_str = f"${monthly:,.2f}".rstrip("0").rstrip(".")
        if annual is None:
            return (m_str, "Monthly only", "0% — no annual plan")
        a_str = f"${annual:,.2f}".rstrip("0").rstrip(".")
        if annual <= 0:
            return (m_str, a_str, "N/A")
        markup = (monthly - annual) / annual * 100
        if markup < 0.5:
            return (m_str, a_str, "No premium")
        return (m_str, a_str, f"+{markup:.0f}% monthly premium")

    # určí, zda je markup "velký" (>= 30%) pro zvýraznění
    def _markup_val(tool: dict) -> float:
        ep = _entry_plan(tool)
        if not ep:
            return 0.0
        m, a = ep.get("monthlyUsd"), ep.get("annualUsd")
        if not m or not a or a <= 0:
            return 0.0
        return (m - a) / a * 100

    markup_rows = []
    for slug in PRICING_SLUGS:
        t = by_slug[slug]
        m_str, a_str, mk_str = _annual_markup(t)
        val = _markup_val(t)
        highlight = ' class="tag-warn"' if val >= 30 else ""
        markup_rows.append(
            f"        <tr>"
            f"<td><a href=\"{slug}-pricing.html\">{_html_escape(t['name'])}</a></td>"
            f"<td>{m_str}/mo</td>"
            f"<td>{a_str}/mo</td>"
            f'<td{highlight}>{mk_str}</td>'
            f"</tr>"
        )
    markup_table = "\n".join(markup_rows)

    # ── sekce 3: self-host tools for escape hatch ─────────────────────────
    sh_tools = [t for t in by_slug.values() if t.get("selfHostable")]
    sh_names = ", ".join(t["name"] for t in sh_tools)

    # ── introtext ──────────────────────────────────────────────────────────
    intro = (
        "The price shown on an automation tool's pricing page is rarely the price you end up paying. "
        "Volume limits, overage tiers and annual billing premiums can add 20–50% on top of the headline "
        "number — before you've even started. This page maps out the three hidden costs that most often "
        "catch teams off guard, using the same data that powers our calculator."
    )

    body = f"""  <div class="section">
    <h2>1. What happens when you exceed your limit</h2>
    <p class="section-sub">Each tool sets a monthly ops/runs/credit ceiling. Here's what triggers when you hit it — sourced from each vendor's published pricing, verified {month_year}.</p>
    <table class="comparison-table">
      <thead><tr><th>Tool</th><th>Entry plan limit</th><th>Entry plan price</th><th>When you exceed it</th></tr></thead>
      <tbody>
{overage_table}
      </tbody>
    </table>
    <div class="warning-box" style="margin-top:16px"><strong>Key takeaway:</strong> most cloud tools use <em>tier-based pricing</em> — you pay for the next volume bracket, not just the overage. A single busy month can push you into a tier that costs 2–3× more. Self-hosted tools (n8n, Activepieces, Automatisch, Node-RED) have no ops ceiling at all: the limit is your server capacity.</div>
  </div>

  <div class="section">
    <h2>2. Annual billing premium</h2>
    <p class="section-sub">Choosing monthly billing over annual means you pay a premium on many platforms. The table below compares the entry-plan monthly vs annual price (billed-annually price expressed as $/mo), and shows the effective markup you pay for the flexibility of monthly billing.</p>
    <table class="comparison-table">
      <thead><tr><th>Tool</th><th>Monthly billing</th><th>Annual billing ($/mo)</th><th>Monthly premium</th></tr></thead>
      <tbody>
{markup_table}
      </tbody>
    </table>
    <div class="warning-box" style="margin-top:16px"><strong>Note:</strong> "Monthly premium" is the extra cost of paying month-to-month vs committing to a year. Highlighted cells (<span class="tag-warn">orange</span>) indicate a premium of 30% or more. Self-hosted tools have no subscription, so the annual vs monthly distinction doesn't apply. Server costs are typically billed monthly by the hour.</div>
  </div>

  <div class="section">
    <h2>3. The self-hosted escape hatch</h2>
    <p>If overage charges and billing lock-in are a concern, the cleanest exit is switching to a self-hostable tool. {_html_escape(sh_names)} are free to run — the only recurring cost is the server it runs on. (Licensing differs: Automatisch and Node-RED are open-source; Activepieces is open-core; n8n is fair-code under its Sustainable Use License — all are free to self-host.)</p>
    <p style="margin-top:12px">Our <a href="self-hosted-automation-cost.html">self-hosted automation cost guide</a> models VPS costs from entry level up to high-volume workloads and compares them directly against paid cloud plans. The short version: at most volumes self-hosting is cheaper than paid cloud, and there are no overages by design.</p>
    <p style="margin-top:12px"><a href="self-hosted-automation-cost.html">See self-host vs cloud cost breakdown →</a></p>
  </div>

  <div class="section">
    <h2>Calculate your real cost</h2>
    <p>Enter your actual monthly run volume in the calculator and it shows the full cost — including which tier you land on and whether a paid cloud plan or self-hosting is cheaper for your usage.</p>
    <div class="cta-row" style="margin-top:16px">
      <a href="calculator.html" class="btn-primary">Open calculator →</a>
      <a href="compare.html" class="btn-secondary">Compare all tools</a>
      <a href="cheapest-automation-tool.html" class="btn-secondary">Cheapest automation tool</a>
    </div>
  </div>"""

    faq = [
        {"q": "What happens if I exceed my automation plan limit?",
         "a": ("It depends on the tool. Most cloud platforms use tier-based pricing: exceeding your monthly "
               "limit means upgrading to the next volume bracket for the whole month — not just paying for "
               "the extra runs. Pipedream historically offered per-credit overage but this is now quote-only. "
               "Self-hosted tools (n8n, Activepieces, Automatisch, Node-RED) have no hard ops "
               "ceiling — you're limited only by your server capacity.")},
        {"q": "Is n8n really free?",
         "a": ("n8n the software is fair-code (source-available under the Sustainable Use License) and free to self-host. You pay "
               "only for the server: a basic VPS starts around $8/mo for low-volume workloads. n8n Cloud is "
               "a paid hosted service with a separate pricing structure. See the "
               '<a href="n8n-pricing.html">n8n pricing breakdown</a> and the '
               '<a href="self-hosted-automation-cost.html">self-host cost guide</a> for exact figures.')},
        {"q": "Which automation tool has the lowest annual billing premium?",
         "a": ("Tools that offer only monthly billing (like some self-hosted plans) have no annual premium "
               "by definition. Among cloud tools, the annual discount varies — check the table above for "
               "current entry-plan figures. Self-hosted tools (n8n, Activepieces, Automatisch, Node-RED) "
               "have no subscription to lock into at all, so the annual vs monthly question doesn't arise.")},
        {"q": "Can I pay month-to-month for automation tools?",
         "a": ("Yes — Zapier, Make, and Pipedream all offer monthly billing, but you pay a premium over "
               "annual pricing. The markup is visible in the table above. n8n Cloud also offers monthly "
               "billing. Self-hosted tools have no subscription; the server (VPS) is typically billed by "
               "the hour or month with no commitment required.")},
        {"q": "How do I avoid automation overage charges?",
         "a": ("Three strategies work reliably: (1) Monitor your run volume before it hits the limit — "
               "most platforms send alerts. (2) Self-host a free-to-run tool (n8n, Activepieces) — "
               "no per-run fee means no overages. (3) Choose a tool whose tier jump is smaller, or whose "
               "entry plan already covers your peak volume. The "
               '<a href="calculator.html">calculator</a> shows which tier you land on at your volume.')},
    ]
    faq_ld, faq_html = _seo_faq(faq)
    title = "Hidden Costs of Automation Tools: Overages, Annual Fees &amp; Surprises | WizardCost"
    desc = ("Zapier, Make and Pipedream overage behavior, annual billing premiums and volume tier traps — "
            "everything that's not on the pricing page. Plus the self-hosted tools that cost only your server.")
    breadcrumb_ld = _seo_breadcrumb_ld(site, prefix, "Hidden costs of automation tools", canonical)
    page_ld = _page_graph_ld(site.get("domain", "wizardcost.com"), canonical,
                             "Hidden Costs of Automation Tools: Overages, Annual Fees & Surprises", desc,
                             _iso_date(tools_meta))
    return _seo_shell(title=title, desc=desc, canonical=canonical, prefix=prefix,
                      month_year=month_year, h1="The hidden costs of automation tools",
                      intro_html=intro, body_html=body, faq_ld=faq_ld,
                      breadcrumb_ld=breadcrumb_ld, faq_html=faq_html, page_ld=page_ld)


def render_methodology_page(by_slug: dict, site: dict, tools_meta: dict, engine) -> str:
    """Generuje automation/methodology.html — jak ověřujeme ceny (E-E-A-T, sources).

    Zrcadlí llm/methodology.html. Všechna čísla/zdroje z tools.json + audit pipeline.
    """
    month_year = _month_year(tools_meta)
    prefix = _site_prefix(site.get("domain", "wizardcost.com"), site.get("base_path", ""))
    canonical = f"{prefix}/methodology.html"
    reviewed = tools_meta.get("last_reviewed", month_year)
    slugs = PRICING_SLUGS
    ntools = len(slugs)

    src_rows = []
    for s in slugs:
        t = by_slug[s]
        url = (t.get("homepage") or "").split(" ", 1)[0]
        host = url.replace("https://", "").replace("http://", "").rstrip("/")
        nplans = len([p for p in t.get("plans", []) if p.get("monthlyUsd") is not None])
        link = (f'<a href="{url}" target="_blank" rel="noopener nofollow">{host}</a>' if url else "—")
        src_rows.append(
            "        <tr>\n"
            f'          <td><strong>{_html_escape(t["name"])}</strong></td>\n'
            f"          <td>{nplans}</td>\n"
            f"          <td>{link}</td>\n"
            f"          <td>{reviewed}</td>\n        </tr>")

    intro = (f"Every price here is taken by hand from the tool's official pricing page, verified on a dated "
             f"pass, and turned into a real monthly figure by the same engine as the "
             f'<a href="calculator.html">calculator</a> — never quoted from memory or a third party. '
             f"Here is exactly where each tool's numbers come from, what they mean, and what we don't claim.")

    body = f"""  <div class="section">
    <h2>How we price automation tools</h2>
    <p class="step-sub">Four rules, the same for every tool.</p>
    <ol style="line-height:1.75;padding-left:1.2em;">
      <li><strong>One source of truth per tool.</strong> Every plan price and limit comes from the vendor's own official pricing page (listed below) — not a blog, aggregator or screenshot.</li>
      <li><strong>Verified by hand, then promoted.</strong> A scrape or research pass is only <em>evidence</em>; a number reaches our data file only after a human confirms it against the official page. Raw dumps are kept dated for audit.</li>
      <li><strong>Computed, not quoted.</strong> The cost you see is calculated by our engine from each plan's price, included runs and overage at a stated workload — so tools compare on one number. We never invent a monthly price.</li>
      <li><strong>Every change is logged.</strong> Prices are committed before the site rebuilds, so each change is dated in the public <a href="changelog.html">changelog</a> with the tool it came from.</li>
    </ol>
  </div>

  <div class="section">
    <h2>Sources — every number traces to an official page</h2>
    <p class="step-sub">{ntools} tools, cloud and self-hosted. Last full verification: {reviewed}.</p>
    <div class="tbl-card">
      <table class="comparison-table">
        <thead><tr><th>Tool</th><th>Paid plans tracked</th><th>Official pricing source</th><th>Last verified</th></tr></thead>
        <tbody>
{chr(10).join(src_rows)}
        </tbody>
      </table>
    </div>
    <p style="margin-top:10px;color:#6b7a99;font-size:14px">Self-hosted figures (n8n, Activepieces, Automatisch, Node-RED) are the server bill our engine models from VPS list prices — the software itself is free to self-host.</p>
  </div>

  <div class="section">
    <h2>Is a "run" the same across tools? No — and it matters</h2>
    <p>A "run" is not a fixed unit. Each tool meters work differently: <strong>Zapier</strong> bills per <em>task</em> (one action step), <strong>Make</strong> per <em>operation</em> (one module call, renamed "credits" in 2026), <strong>n8n</strong> per <em>workflow execution</em> (a whole run, regardless of steps), and <strong>Pipedream</strong> per <em>credit</em> (compute time). The <em>same</em> automation can therefore consume a very different billed quantity from one tool to the next — a multi-step workflow is one n8n execution but many Zapier tasks.</p>
    <p>What this means for our numbers: we model a realistic <strong>multi-step workflow</strong> and convert your monthly run volume into each tool's own billed unit, so the cost column is apples-to-apples on the same work — not on a raw "runs" number that means something different per tool. Treat small cross-tool gaps as a tie until you map your real workflows; the <a href="calculator.html">calculator</a> lets you set your exact volume and steps.</p>
  </div>

  <div class="section">
    <h2>What each number means</h2>
    <div class="tbl-card">
      <table class="comparison-table">
        <thead><tr><th>Field</th><th>Definition</th></tr></thead>
        <tbody>
          <tr><td><strong>Monthly cost</strong></td><td>The cheapest qualifying plan for your volume, computed by the engine — the plan whose included allowance covers your runs, or the next tier up.</td></tr>
          <tr><td><strong>Included runs</strong></td><td>The run / task / operation allowance bundled in a paid plan (range shown across tiers).</td></tr>
          <tr><td><strong>Overage</strong></td><td>What happens past the limit: most tools require upgrading to the next volume tier (no pay-as-you-go); some bill a per-unit rate.</td></tr>
          <tr><td><strong>Self-host</strong></td><td>For self-hostable tools, the modelled VPS (plus a database at scale) — infrastructure only, not a tool fee.</td></tr>
          <tr><td><strong>~ (tilde)</strong></td><td>An estimate for a custom / enterprise tier the vendor doesn't price publicly — held as an estimate rather than a quoted fact.</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <h2>Known limits &amp; confidence</h2>
    <p>We would rather show a gap than a guess:</p>
    <ul style="line-height:1.75;padding-left:1.2em;">
      <li><strong>Enterprise tiers</strong> with "contact sales" pricing are marked ~ and estimated — they are not vendor-quoted facts.</li>
      <li><strong>Self-host VPS cost</strong> is modelled from public VPS list prices (Elestio / Netcup tiers); your real server bill depends on provider, region and add-ons, and excludes your own time to install, secure and maintain the stack.</li>
      <li><strong>Annual vs monthly billing</strong> differs per tool; we show the monthly-billing figure unless noted, and the annual premium is broken out on the <a href="hidden-cost-automation.html">hidden-cost page</a>.</li>
      <li><strong>Our example workflow is an assumption</strong>, not a vendor fact — change volume and steps in the calculator for your case.</li>
    </ul>
  </div>

  <div class="section">
    <h2>How we keep it current</h2>
    <p>An automated job re-reads every official pricing page each morning and flags any change; a second job watches plan limits, licensing and feature facts. Those flags are evidence — a human still confirms before a number changes. Confirmed changes are dated in the <a href="changelog.html">changelog</a> (with an <a href="feed.xml">RSS feed</a>), and we take a commission only from a single optional affiliate link that never affects rankings — so nothing here is pay-to-rank.</p>
  </div>

  <div class="section" style="text-align:center">
    <h2>See it on your own numbers</h2>
    <p>The calculator uses these exact prices — set your volume, workflow type and budget, and it re-ranks every tool live.</p>
    <div class="cta-row" style="margin-top:16px;justify-content:center">
      <a href="calculator.html" class="btn-primary">Open calculator →</a>
      <a href="changelog.html" class="btn-secondary">Price changelog</a>
      <a href="/llm/methodology.html" class="btn-secondary">LLM pricing methodology</a>
    </div>
  </div>"""

    faq = [
        {"q": "Where do your automation prices come from?",
         "a": ("Each plan price and limit is taken by hand from the tool's official pricing page (listed in the "
               "sources table above) and confirmed by a person before it enters our data. The monthly figure is "
               "computed by our engine, not quoted.")},
        {"q": "Why can't I compare tools on “runs” alone?",
         "a": ("Because a run isn't one unit: Zapier bills per task, Make per operation/credit, n8n per workflow "
               "execution and Pipedream per credit. One multi-step workflow is a single n8n execution but many "
               "Zapier tasks. We model a realistic workflow and convert to each tool's own unit so costs compare "
               "on the same work.")},
        {"q": "Do the tool vendors pay you?",
         "a": ("Only one tool has an optional affiliate link, clearly disclosed, and it never affects rankings — "
               "those are by objective cost only. Self-hosted tools, which we often rank cheapest, have no "
               "affiliate at all.")},
        {"q": "How often are prices checked?",
         "a": (f"An automated job re-reads every official pricing page daily and flags changes; a human confirms "
               f"before any number moves. The last full hand-verification was {reviewed}, and every change is "
               'dated in the <a href="changelog.html">changelog</a>.')},
    ]
    faq_ld, faq_html = _seo_faq(faq)
    title = "How We Verify Automation Pricing — Methodology | WizardCost"
    desc = ("How we verify automation tool pricing: every plan traced to the vendor's official page, "
            "verified by hand and computed not quoted — plus why a “run” isn't the same unit across tools.")
    breadcrumb_ld = _seo_breadcrumb_ld(site, prefix, "Methodology", canonical)
    page_ld = _page_graph_ld(site.get("domain", "wizardcost.com"), canonical,
                             "How We Verify Automation Pricing — Methodology", desc,
                             _iso_date(tools_meta))
    return _seo_shell(title=title, desc=desc, canonical=canonical, prefix=prefix,
                      month_year=month_year, h1="How we verify automation pricing",
                      intro_html=intro, body_html=body, faq_ld=faq_ld,
                      breadcrumb_ld=breadcrumb_ld, faq_html=faq_html, page_ld=page_ld)

def build_seo_pages(tools: list[dict], site: dict, tools_meta: dict, *, check: bool = False) -> list[str]:
    """Vygeneruje long-tail SEO stránky (alternatives ×7 + cheapest ×1 + self-host ×1 + roi ×1)."""
    engine = _root_engine()
    by_slug = {t["slug"]: t for t in tools}
    out = []
    targets = [(f"{s}-alternatives.html", lambda s=s: render_alternatives_page(s, by_slug, site, tools_meta, engine))
               for s in PRICING_SLUGS if s in by_slug]
    targets.append(("cheapest-automation-tool.html", lambda: render_cheapest_page(by_slug, site, tools_meta, engine)))
    targets.append(("self-hosted-automation-cost.html", lambda: render_selfhost_page(by_slug, site, tools_meta, engine)))
    targets.append(("is-automation-worth-it.html", lambda: render_roi_page(by_slug, site, tools_meta, engine)))
    targets.append(("hidden-cost-automation.html", lambda: render_hidden_cost_page(by_slug, site, tools_meta, engine)))
    targets.append(("methodology.html", lambda: render_methodology_page(by_slug, site, tools_meta, engine)))
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
