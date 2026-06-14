#!/usr/bin/env python3
"""build_catalog.py — generátor přehledových stránek z dat (Agent C).

Generuje DVĚ stránky plně z `data/tools.json` (žádné napevno zadané ceny/limity):

  • tools.html  — přehled nástrojů + hosting variant (Cloud / VPS / vlastní server).
                  Pro každou variantu: jméno, tagline, NEJLEVNĚJŠÍ cena při výchozím
                  objemu (5 000 runs) přes engine, klíčové featury, odkaz na
                  <slug>-pricing.html. U "own" variant měsíční (elektřina) + jednorázové
                  HW "~$X" (hw_tier_for) + spec.
  • limits.html — tabulka limitů plánů: Tool/varianta, included RUNS (z plánů
                  opsIncluded), workflow limit, max steps, execution timeout, log
                  history. Self-host varianty zahrnuty. Vše reálné, jednotka = "runs".

Vstupní bod: `build_catalog_pages(tools, site, tools_meta, *, check=False) -> list[str]`.

Kontrakt hosting variant: `build_hosting.expand_hosting_variants(tools)`
(Cloud/VPS/own), `hw_tier_for(variant, runs)` (hwOneOff + spec pro "own").
Engine: `_root_engine().cheapest_monthly(variant, runs, steps=3)` → {cost, label, est}.

Standalone:
    python automation/build_catalog.py            # zapíše tools.html + limits.html
    python automation/build_catalog.py --check     # vrátí, co by se změnilo (bez zápisu)

Pozn.: build.py NEimportuje (cyklický import) — malé helpery (_logo, _month_year,
_root_engine, _html_escape) jsou zkopírované z build.py dle vzoru render_vs_page.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from build_hosting import expand_hosting_variants, hw_tier_for

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "tools.json"
SITE = ROOT / "data" / "site.json"

EMAILCAP_ACTION = "https://assets.mailerlite.com/jsonp/2426816/forms/190009354045359550/subscribe"

# výchozí objem pro "cena při objemu" na přehledu (runs/měsíc)
DEFAULT_VOLUME = 5000
DEFAULT_STEPS = 3


# ---------------------------------------------------------------------------
# Helpery (zkopírované z build.py — NEimportovat build.py: cyklický import)
# ---------------------------------------------------------------------------

def _root_engine():
    """Importuje root build.py kvůli cheapest_monthly — JEDINÁ kopie cost logiky."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rootbuild", ROOT.parent / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _logo(slug: str) -> str:
    """Favicon URL — slug je base slug (variant používá variantOf)."""
    domain = {"n8n": "n8n.io", "make": "make.com", "pipedream": "pipedream.com",
              "zapier": "zapier.com", "activepieces": "activepieces.com",
              "automatisch": "automatisch.io", "node-red": "nodered.org"}.get(slug)
    if not domain:
        return ""
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


def _fmt_usd(cost, est: bool) -> str:
    body = f"{cost:,.2f}".rstrip("0").rstrip(".") if isinstance(cost, float) else f"{cost:,}"
    return ("~$" if est else "$") + body


def _base_slug(variant: dict) -> str:
    return variant.get("variantOf") or variant["slug"]


def _kind_badge(kind: str) -> str:
    """Hosting kind → (label, css třída)."""
    return {
        "cloud": ("Cloud", "badge-blue"),
        "saas": ("Cloud", "badge-blue"),
        "vps": ("Self-host · VPS", "badge-green"),
        "own": ("Self-host · own server", "badge-green"),
    }.get(kind, ("Cloud", "badge-blue"))


def _limit_label(v) -> str:
    """opsIncluded / workflowLimit: None = unlimited; jinak číslo s oddělovači."""
    if v is None:
        return '<span class="check">Unlimited</span>'
    return f"{v:,}"


# ---------------------------------------------------------------------------
# CSS (samostatná šablona — sdílí design tokeny s vs/compare/tools/limits)
# ---------------------------------------------------------------------------

_BASE_HEAD_CSS = """    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0a0e17; --surface: #111827; --surface2: #1a2236;
      --border: #1f2d45; --text: #e8edf5; --muted: #6b7a99;
      --accent: #10b981; --accent-br: #16d18c; --accent-dim: rgba(16,185,129,0.09); --accent-glow: rgba(16,185,129,0.20); --ink: #04130d; --link: #6f9bff; --border2: #27375a; --text2: #a8b4cc;
      --green: #10b981; --yellow: #f59e0b; --red: #ef4444; --radius: 14px; --radius-sm: 9px;
      --font: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; --display: 'Hanken Grotesk', 'Plus Jakarta Sans', sans-serif; --mono: 'JetBrains Mono', ui-monospace, monospace;
    }
    body {
      background: var(--bg);
      background-image: radial-gradient(ellipse 70% 50% at 50% -8%, rgba(16,185,129,0.20), transparent 60%), radial-gradient(ellipse 60% 50% at 100% 0%, rgba(16,185,129,0.08), transparent 50%);
      background-repeat: no-repeat; background-attachment: fixed;
      color: var(--text); font-family: var(--font); font-size: 15.5px; line-height: 1.7; letter-spacing: 0.01em; min-height: 100vh; -webkit-font-smoothing: antialiased;
    }
    a { color: var(--link); text-decoration: none; }
    a:hover { color: #9fbcff; }
    h1, h2, h3 { font-family: var(--display); letter-spacing: -0.02em; text-wrap: balance; }

    /* Nav */
    header { position: fixed; top: 0; left: 0; right: 0; z-index: 100; background: rgba(10,14,23,0.86); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); border-bottom: 1px solid var(--border); }
    body { padding-top: 100px; }
    .nav-top { padding: 0 32px; height: 56px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border); }
    .nav-bottom { border-bottom: 2px solid var(--border); padding: 0 32px; display: flex; gap: 0; overflow-x: auto; scrollbar-width: none; }
    .nav-bottom::-webkit-scrollbar { display: none; }
    .nav-bottom a { padding: 12px 20px; font-size: 14px; color: var(--muted); text-decoration: none; white-space: nowrap; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: color 0.15s, border-color 0.15s; flex-shrink: 0; }
    .nav-bottom a:hover { color: var(--text); }
    .nav-bottom a.active { color: var(--text); font-weight: 700; border-bottom-color: var(--accent); }
    .logo { display: flex; align-items: center; gap: 0; font-family: var(--display); font-weight: 800; font-size: 1.08rem; color: var(--text); letter-spacing: -0.01em; text-decoration: none; }
    .logo span { color: var(--accent); }
    .logo .io { color: var(--muted); font-weight: 600; }
    .logo-icon { width: 28px; height: 28px; flex-shrink: 0; margin-right: 9px; }
    .nav-badge { font-family: var(--mono); font-size: 11px; background: var(--surface2); border: 1px solid var(--border2); border-radius: 20px; padding: 4px 12px; color: var(--muted); display: flex; align-items: center; gap: 7px; letter-spacing: 0.01em; }
    .nav-badge::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 7px var(--accent); }

    .wrap { max-width: 1160px; margin: 0 auto; padding: 0 32px; }

    /* Hero */
    .hero { padding: 60px 0 36px; }
    .hero-badge { display: inline-flex; align-items: center; gap: 8px; background: var(--surface2); border: 1px solid var(--border2); border-radius: 100px; font-family: var(--mono); font-size: 11.5px; color: var(--text2); padding: 6px 15px; margin-bottom: 22px; letter-spacing: 0.02em; }
    .hero h1 { font-size: clamp(2rem, 4vw, 3rem); font-weight: 800; line-height: 1.1; letter-spacing: -0.02em; margin-bottom: 16px; }
    .hero h1 em { font-style: normal; color: var(--accent); }
    .hero p { color: var(--text2); font-size: 1.08rem; max-width: 660px; line-height: 1.7; text-wrap: pretty; }

    .badge { display: inline-block; font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 5px; }
    .badge-green { background: rgba(16,185,129,0.15); color: var(--green); border: 1px solid rgba(16,185,129,0.3); }
    .badge-blue { background: rgba(111,155,255,0.13); color: #9fbcff; border: 1px solid rgba(111,155,255,0.28); }
    .badge-yellow { background: rgba(245,158,11,0.15); color: var(--yellow); border: 1px solid rgba(245,158,11,0.3); }
    .badge-muted { background: var(--surface2); color: var(--muted); border: 1px solid var(--border); }
    .check { color: var(--green); font-weight: 700; }
    .cross { color: var(--red); }

    /* Footer */
    footer { border-top: 1px solid var(--border); padding: 40px 24px; text-align: center; font-family: var(--display); font-size: 12.5px; color: var(--muted); line-height: 1.85; margin-top: 56px; }
    footer a { color: var(--muted); }

    /* Funnel CTA */
    .finder-cta { background: linear-gradient(160deg, rgba(16,185,129,0.10), var(--surface) 65%); border: 1px solid rgba(16,185,129,0.35); border-radius: var(--radius); padding: 32px 36px; margin: 24px 0 8px; display: flex; align-items: center; gap: 28px; flex-wrap: wrap; }
    .finder-cta-text { flex: 1 1 340px; }
    .finder-cta h2 { font-size: 1.5rem; font-weight: 800; margin-bottom: 8px; }
    .finder-cta p { color: var(--text2); font-size: 14.5px; line-height: 1.6; max-width: 560px; }
    .btn-primary-lg { background: var(--accent); color: var(--ink); border-radius: var(--radius-sm); padding: 15px 28px; font-family: var(--font); font-size: 15px; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center; gap: 9px; box-shadow: 0 0 0 1px rgba(16,185,129,0.4), 0 10px 30px rgba(16,185,129,0.28); transition: transform 0.15s, box-shadow 0.15s, background 0.15s; white-space: nowrap; }
    .btn-primary-lg:hover { background: var(--accent-br); transform: translateY(-1px); box-shadow: 0 0 0 1px rgba(16,185,129,0.5), 0 14px 36px rgba(16,185,129,0.4); color: var(--ink); }

    @media (max-width: 760px) {
      .wrap { padding-left: 18px; padding-right: 18px; }
      .nav-top { padding-left: 18px; padding-right: 18px; }
      .nav-bottom { padding-left: 8px; padding-right: 8px; }
      .nav-bottom a { padding: 13px 14px; }
    }
    @media (max-width: 620px) { .nav-badge { display: none; } }"""

# tools.html — kartová mřížka variant
_TOOLS_CSS = _BASE_HEAD_CSS + """
    .group { margin-bottom: 40px; }
    .group-head { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
    .group-head img { width: 40px; height: 40px; border-radius: 10px; background: #fff; padding: 4px; object-fit: contain; flex-shrink: 0; }
    .group-head h2 { font-size: 1.4rem; font-weight: 800; }
    .group-head .tagline { font-size: 13.5px; color: var(--muted); width: 100%; }
    .var-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
    .var-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px 24px; display: flex; flex-direction: column; }
    .var-card .var-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
    .var-card h3 { font-size: 1.05rem; font-weight: 800; }
    .price-line { font-family: var(--mono); font-weight: 700; font-size: 1.5rem; color: var(--accent-br); margin: 4px 0 2px; }
    .price-sub { font-size: 12.5px; color: var(--muted); margin-bottom: 4px; }
    .hw-line { font-size: 12.5px; color: var(--text2); margin-top: 6px; }
    .hw-line .hw-cost { font-family: var(--mono); font-weight: 700; color: var(--text); }
    .spec-line { font-size: 11.5px; color: var(--muted); margin-top: 4px; line-height: 1.5; }
    .feat { list-style: none; margin: 14px 0 16px; }
    .feat li { font-size: 13px; color: var(--text2); padding: 4px 0; display: flex; gap: 8px; }
    .feat li::before { content: "✓"; color: var(--green); font-weight: 700; flex-shrink: 0; }
    .feat li.no { color: var(--muted); }
    .feat li.no::before { content: "✗"; color: var(--red); }
    .var-cta { margin-top: auto; display: inline-flex; align-items: center; justify-content: center; gap: 7px; background: var(--surface2); border: 1px solid var(--border2); color: var(--text); font-weight: 700; font-size: 13px; padding: 11px 18px; border-radius: var(--radius-sm); text-decoration: none; transition: border-color 0.15s, color 0.15s; }
    .var-cta:hover { border-color: var(--accent); color: var(--text); }
    .tbl-note { font-family: var(--mono); font-size: 11.5px; color: var(--muted); margin: 8px 0 8px; line-height: 1.7; }
    @media (max-width: 520px) { .var-grid { grid-template-columns: 1fr; } }"""

# limits.html — tabulka
_LIMITS_CSS = _BASE_HEAD_CSS + """
    .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-sm); margin-bottom: 12px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th { background: var(--surface2); color: var(--muted); font-family: var(--mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--border); white-space: nowrap; }
    td { padding: 11px 14px; border-bottom: 1px solid var(--border); background: var(--surface); vertical-align: middle; white-space: nowrap; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: var(--surface2); }
    td.tool-col { font-weight: 700; }
    .td-tool { display: flex; align-items: center; }
    .tool-logo { width: 22px; height: 22px; border-radius: 5px; object-fit: contain; vertical-align: middle; margin-right: 8px; background: #fff; padding: 2px; flex-shrink: 0; }
    .host-tag { font-family: var(--mono); font-size: 10.5px; color: var(--muted); margin-left: 8px; }
    .tbl-note { font-family: var(--mono); font-size: 11.5px; color: var(--muted); margin: 0 0 40px; line-height: 1.7; }
    .faq { margin-bottom: 64px; }
    .faq-item { border-bottom: 1px solid var(--border); padding: 20px 0; }
    .faq-item:first-child { border-top: 1px solid var(--border); }
    .faq-q { font-weight: 700; font-size: 15px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
    .faq-q::after { content: "+"; color: var(--muted); font-size: 1.2rem; flex-shrink: 0; }
    .faq-item.open .faq-q::after { content: "−"; }
    .faq-a { color: var(--muted); font-size: 14px; line-height: 1.7; display: none; margin-top: 10px; }
    .faq-item.open .faq-a { display: block; }
    .section { margin: 44px 0 16px; }
    .section h2 { font-size: 1.5rem; font-weight: 800; margin-bottom: 8px; }"""


# ---------------------------------------------------------------------------
# Společné fragmenty (nav, head, emailcap, footer) — generované
# ---------------------------------------------------------------------------

def _head(title: str, desc: str, canonical: str, css: str, ld_json: str | None,
          prefix: str) -> str:
    ld = f'  <script type="application/ld+json">\n{ld_json}\n  </script>\n' if ld_json else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- generováno build_catalog.py z data/tools.json — needituj ručně -->
  <title>{title}</title>
  <meta name="description" content="{_html_escape(desc)}">
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="AutomationCost.io">
  <meta property="og:title" content="{_html_escape(title)}">
  <meta property="og:description" content="{_html_escape(desc)}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="{prefix}/og-image.png">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{prefix}/og-image.png">
{ld}  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Hanken+Grotesk:wght@500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
{css}
  </style>
</head>
<body>
"""


def _nav(active: str, month_year: str) -> str:
    def cls(name):
        return ' class="active"' if name == active else ""
    return f"""
<header>
  <div class="nav-top">
    <a href="/" class="logo">
      <svg class="logo-icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
        <defs><linearGradient id="acmk" x1="14" y1="10" x2="30" y2="38" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#2fe39c"></stop><stop offset="1" stop-color="#0ea66e"></stop></linearGradient></defs>
        <path d="M28.5 10.5 L13.5 24 L28.5 37.5" stroke="url(#acmk)" stroke-width="6.8" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="M 36.5 17.8 Q 37.864 22.636 42.7 24 Q 37.864 25.364 36.5 30.2 Q 35.136 25.364 30.3 24 Q 35.136 22.636 36.5 17.8 Z" fill="#eafff5"></path>
      </svg>
      Automation<span>Cost</span><span class="io" style="font-size:0.72em; margin-left:7px;">by WizardCost</span>
    </a>
    <span class="nav-badge">Updated {month_year} · Real pricing data</span>
  </div>
  <nav class="nav-bottom">
    <a href="index.html"{cls('home')}>Home</a>
    <a href="calculator.html"{cls('calculator')}>Calculator</a>
    <a href="compare.html"{cls('compare')}>Compare</a>
    <a href="limits.html"{cls('limits')}>Pricing & Limits</a>
    <a href="tools.html"{cls('tools')}>Tools</a>
    <a href="changelog.html"{cls('changelog')}>Changelog</a>
  </nav>
</header>
"""


def _emailcap(title: str, sub: str) -> str:
    return f"""
  <!-- EMAILCAP:HTML:START — price-drop alerts (catalog variant, generováno).
       Disclosure text schválen ownerem 2026-06-11 — NEMĚNIT bez jeho OK. -->
  <section class="price-alerts" id="price-alerts">
    <div class="pa-label">Price-drop alerts</div>
    <div class="pa-title">{title}</div>
    <p class="pa-sub">{sub}</p>
    <form class="pa-form" id="pa-form" action="{EMAILCAP_ACTION}" method="post" novalidate>
      <label for="pa-email" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);">Email address</label>
      <input class="pa-input" id="pa-email" name="fields[email]" type="email" inputmode="email" autocomplete="email" required placeholder="you@company.com">
      <input type="hidden" name="ml-submit" value="1"><input type="hidden" name="anticsrf" value="true"><button class="pa-btn" id="pa-btn" type="submit">Get price alerts</button>
    </form>
    <div class="pa-msg" id="pa-msg" role="status" aria-live="polite"></div>
    <p class="pa-note">Price-change alerts only. No newsletter, unsubscribe anytime. <a href="privacy.html">Privacy</a></p>
  </section>
  <!-- EMAILCAP:HTML:END -->"""


_EMAILCAP_CSS = """    /* ── EMAILCAP:CSS:START ── price-drop alerts capture block (reusable) ── */
    .price-alerts { background: var(--surface); border: 1px solid var(--border2); border-radius: var(--radius); padding: 24px 28px; margin: 44px 0 0; }
    .pa-label { font-family: var(--mono); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.14em; color: var(--accent); margin-bottom: 8px; }
    .pa-title { font-family: var(--display); font-size: 17px; font-weight: 800; letter-spacing: -0.01em; }
    .pa-sub { font-size: 13.5px; color: var(--text2); margin-top: 5px; line-height: 1.55; max-width: 560px; }
    .pa-form { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 16px; }
    .pa-input { flex: 1 1 240px; min-width: 0; background: var(--bg); border: 1px solid var(--border2); border-radius: var(--radius-sm); padding: 12px 16px; font-family: var(--font); font-size: 14.5px; color: var(--text); transition: border-color 0.15s, box-shadow 0.15s; }
    .pa-input::placeholder { color: var(--muted); }
    .pa-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(16,185,129,0.20); }
    .pa-btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; background: var(--accent); color: var(--ink); border: 0; cursor: pointer; font-family: var(--font); font-weight: 700; font-size: 14px; padding: 12px 22px; border-radius: var(--radius-sm); white-space: nowrap; transition: background 0.15s; }
    .pa-btn:hover { background: var(--accent-br); }
    .pa-btn:disabled { opacity: 0.6; cursor: default; }
    .pa-note { font-size: 12.5px; color: var(--muted); margin-top: 12px; line-height: 1.55; }
    .pa-note a { color: var(--muted); text-decoration: underline; text-underline-offset: 2px; }
    .pa-note a:hover { color: var(--text2); }
    .pa-msg { display: none; margin-top: 14px; font-size: 14px; line-height: 1.55; }
    .pa-msg.show { display: flex; align-items: flex-start; gap: 9px; }
    .pa-msg svg { flex-shrink: 0; margin-top: 3px; }
    .pa-msg.ok { color: var(--green); }
    .pa-msg.err { color: var(--red); }
    .price-alerts.subscribed .pa-form, .price-alerts.subscribed .pa-note { display: none; }
    @media (max-width: 520px) { .price-alerts { padding: 20px 18px; } .pa-form { flex-direction: column; } .pa-btn { width: 100%; min-height: 44px; } }
    /* ── EMAILCAP:CSS:END ── */"""


_EMAILCAP_JS = """
/* ── EMAILCAP:JS:START — wire every .price-alerts form on the page ── */
(function () {
  var OK_MSG  = 'Check your inbox to confirm your subscription.';
  var ERR_MSG = 'Something went wrong — please try again.';
  var OK_ICON  = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';
  var ERR_ICON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>';
  function show(msgEl, ok, text) {
    msgEl.className = 'pa-msg show ' + (ok ? 'ok' : 'err');
    msgEl.innerHTML = (ok ? OK_ICON : ERR_ICON) + '<span>' + text + '</span>';
  }
  document.querySelectorAll('.price-alerts form.pa-form').forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var card  = form.closest('.price-alerts');
      var input = form.querySelector('.pa-input');
      var btn   = form.querySelector('.pa-btn');
      var msgEl = card.querySelector('.pa-msg');
      if (!input.value || input.validity.typeMismatch || input.value.indexOf('@') < 1) {
        show(msgEl, false, 'Please enter a valid email address.');
        input.focus();
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Subscribing…';
      fetch(form.action, { method: 'POST', body: new FormData(form) })
        .then(function (r) { if (!r.ok) throw new Error(r.status); })
        .then(function () { card.classList.add('subscribed'); show(msgEl, true, OK_MSG); })
        .catch(function () {
          btn.disabled = false;
          btn.textContent = 'Get price alerts';
          show(msgEl, false, ERR_MSG);
        });
    });
  });
})();
/* ── EMAILCAP:JS:END ── */"""


def _footer(month_year: str) -> str:
    return f"""
<footer>
  AutomationCost · part of WizardCost · Prices verified {month_year} · <a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a> · <a href="affiliate.html">Affiliate Disclosure</a>
</footer>
"""


def _finder_cta(heading: str, body: str) -> str:
    return f"""
  <div class="finder-cta">
    <div class="finder-cta-text">
      <h2>{heading}</h2>
      <p>{body}</p>
    </div>
    <a href="calculator.html" class="btn-primary-lg">Find my best tool
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6"><polyline points="9 18 15 12 9 6"/></svg>
    </a>
  </div>
"""


# ---------------------------------------------------------------------------
# Featury (krátký výtah pro kartu — z dat, runs ne ops)
# ---------------------------------------------------------------------------

def _feat_items(variant: dict) -> list[tuple[str, bool]]:
    """(text, positive) — klíčové featury pro kartu, z tools.json."""
    items = [
        (f"{variant['integrations']:,}+ integrations", True),
        (f"Max steps / workflow: {variant['maxSteps']}", True),
        (f"Execution timeout: {variant['timeout']}", True),
    ]
    items.append(("AI / LLM nodes", variant.get("aiFeatures", False)))
    items.append(("Code steps", variant.get("codeSteps", False)))
    items.append(("GDPR-friendly", variant.get("gdprFriendly", False)))
    return items


# ---------------------------------------------------------------------------
# tools.html — přehled (varianty seskupené pod base nástrojem)
# ---------------------------------------------------------------------------

def _render_var_card(variant: dict, engine) -> str:
    kind = variant.get("hostingKind", "saas")
    kind_label, badge_cls = _kind_badge(kind)
    base = _base_slug(variant)
    r = engine.cheapest_monthly(variant, DEFAULT_VOLUME, DEFAULT_STEPS)
    if r is None:
        price_block = '<div class="price-line">—</div>'
    else:
        price = _fmt_usd(r["cost"], r["est"])
        # engine label může nést "+ops" (vendorův přepočet) — na webu jednotka = runs
        plan_label = r["label"].replace("+ops", "+ overage")
        if kind == "own":
            sub = f"electricity / mo @ {DEFAULT_VOLUME:,} runs"
        else:
            sub = f"per mo @ {DEFAULT_VOLUME:,} runs · {_html_escape(plan_label)}"
        price_block = (f'<div class="price-line">{price}<span style="font-size:0.9rem;color:var(--muted);font-weight:600">/mo</span></div>'
                       f'<div class="price-sub">{sub}</div>')

    hw_block = ""
    if kind == "own":
        tier = hw_tier_for(variant, DEFAULT_VOLUME)
        if tier:
            one_off = tier.get("hwOneOff")
            spec = tier.get("spec", "")
            if one_off is not None:
                hw_block += (f'<div class="hw-line">One-off hardware: '
                             f'<span class="hw-cost">~${one_off:,}</span></div>')
            if spec:
                hw_block += f'<div class="spec-line">{_html_escape(spec)}</div>'

    feats = "\n".join(
        f'          <li{"" if ok else " class=\"no\""}>{_html_escape(t)}</li>'
        for t, ok in _feat_items(variant))

    return f"""      <div class="var-card">
        <div class="var-top">
          <h3>{_html_escape(variant['name'])}</h3>
          <span class="badge {badge_cls}">{kind_label}</span>
        </div>
        {price_block}
        {hw_block}
        <ul class="feat">
{feats}
        </ul>
        <a class="var-cta" href="{base}-pricing.html">See {_html_escape(variant.get('name', base))} pricing →</a>
      </div>"""


def _render_tools_html(tools: list[dict], variants: list[dict], site: dict,
                       tools_meta: dict, engine) -> str:
    month_year = _month_year(tools_meta)
    domain = site.get("domain", "wizardcost.com")
    base_path = (site.get("base_path", "") or "").strip("/")
    prefix = f"https://{domain}/{base_path}".rstrip("/") if base_path else f"https://{domain}"
    canonical = f"{prefix}/tools.html"

    # seskup varianty podle base nástroje (zachová pořadí z tools.json)
    order = [t["slug"] for t in tools]
    by_base = {s: [] for s in order}
    for v in variants:
        by_base.setdefault(_base_slug(v), []).append(v)
    by_slug = {t["slug"]: t for t in tools}

    groups = []
    for s in order:
        vs = by_base.get(s)
        if not vs:
            continue
        base = by_slug[s]
        cards = "\n".join(_render_var_card(v, engine) for v in vs)
        n_var = len(vs)
        plural = "" if n_var == 1 else "s"
        groups.append(f"""  <div class="group" id="{s}">
    <div class="group-head">
      <img src="{_logo(s)}" alt="{_html_escape(base['name'])}">
      <h2>{_html_escape(base['name'])}</h2>
      <div class="tagline">{_html_escape(base['tagline'])} · {n_var} hosting option{plural}</div>
    </div>
    <div class="var-grid">
{cards}
    </div>
  </div>""")

    # ItemList JSON-LD (base nástroje)
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "ItemList",
        "name": "Automation tools — pricing overview",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": by_slug[s]["name"]}
            for i, s in enumerate(order) if by_base.get(s)],
    }, ensure_ascii=False, indent=2)

    css = _TOOLS_CSS + "\n" + _EMAILCAP_CSS
    title = ("Best Automation Tools 2026 — Pricing & Hosting Options | AutomationCost.io")
    desc = ("Every automation tool priced from real data — n8n, Make, Pipedream, Zapier, "
            "Activepieces, Automatisch and Node-RED. Cloud, VPS and own-server hosting, "
            f"cheapest cost at {DEFAULT_VOLUME:,} runs/mo, plus key features.")

    # jednoduchý TOC styl inline (drobnost — design se řeší zvlášť)
    toc_inline = ""
    if groups:
        chips = "\n".join(
            f'    <a href="#{s}" style="display:inline-flex;align-items:center;gap:7px;'
            f'background:var(--surface);border:1px solid var(--border);border-radius:8px;'
            f'padding:7px 12px;font-size:13px;font-weight:600;color:var(--muted)">'
            f'<img src="{_logo(s)}" alt="{by_slug[s]["name"]}" '
            f'style="width:18px;height:18px;border-radius:4px;background:#fff;padding:1px">'
            f'{by_slug[s]["name"]}</a>'
            for s in order if by_base.get(s))
        toc_inline = (f'  <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:40px">\n'
                      f'{chips}\n  </div>\n')

    note = (f"Cheapest qualifying plan at {DEFAULT_VOLUME:,} runs/mo, {DEFAULT_STEPS} steps per "
            "workflow, monthly billing — computed live from each vendor's real plans. "
            "Self-host VPS = rented server (scales with volume); own server = home electricity "
            "(monthly) plus a one-off hardware cost. Values marked ~ are estimates for "
            f"custom tiers. Verified {month_year} — see the "
            '<a href="changelog.html">price changelog</a>.')

    body = f"""
<div class="wrap">

  <div class="hero">
    <div class="hero-badge">{len([s for s in order if by_base.get(s)])} tools · {len(variants)} hosting options · verified {month_year.lower()}</div>
    <h1>Automation tools — <em>priced from real data</em></h1>
    <p>Every tool, every hosting option — Cloud, self-host VPS, and your own server.
       Cheapest monthly cost at {DEFAULT_VOLUME:,} runs/mo, computed live from each vendor's
       real plans. The unit is a <strong>run</strong> (one workflow execution), not an op.</p>
  </div>

{toc_inline}  <p class="tbl-note">{note}</p>

{chr(10).join(groups)}

{_finder_cta("Not sure which one fits?", "Skip the reading — answer 4 quick questions and get your cheapest-fit tool ranked at your exact volume in 30 seconds.")}
{_emailcap("Get an email when any of these tools changes pricing.",
           'Every change is verified by hand and published to the <a href="changelog.html">changelog</a> — one email per confirmed change.')}
</div>
"""

    return (_head(title, desc, canonical, css, ld, prefix)
            + _nav("tools", month_year)
            + body
            + _footer(month_year)
            + "\n<script>\nfunction toggleFaq(el) { el.parentElement.classList.toggle(\"open\"); }\n"
            + _EMAILCAP_JS
            + "\n</script>\n\n</body>\n</html>\n")


# ---------------------------------------------------------------------------
# limits.html — tabulka limitů plánů (s included RUNS)
# ---------------------------------------------------------------------------

def _included_runs_for_variant(variant: dict) -> str:
    """Included runs (z plánů opsIncluded). Vrátí čitelný souhrn napříč plány."""
    kind = variant.get("hostingKind", "saas")
    if kind in ("vps", "own"):
        return '<span class="check">Unlimited</span>'
    # cloud/saas: vezmi placené plány s opsIncluded; ukaž rozsah min–max
    incs = [p.get("opsIncluded") for p in variant.get("plans", [])
            if p.get("monthlyUsd") not in (None,) and not p.get("selfHostOnly")]
    finite = [i for i in incs if i is not None]
    has_unlimited = any(i is None for i in incs)
    if not finite:
        return '<span class="check">Unlimited</span>' if has_unlimited else "—"
    lo, hi = min(finite), max(finite)
    rng = f"{lo:,}" if lo == hi else f"{lo:,} – {hi:,}"
    if has_unlimited:
        rng += " (+ unlimited tier)"
    return rng


def _free_runs_for_variant(variant: dict) -> str:
    """Included runs na free/entry plánu (nejlevnější placený nebo free)."""
    kind = variant.get("hostingKind", "saas")
    if kind in ("vps", "own"):
        return '<span class="check">Unlimited</span>'
    plans = [p for p in variant.get("plans", []) if not p.get("selfHostOnly")]
    free = next((p for p in plans if p.get("monthlyUsd") == 0), None)
    if free is not None:
        return _limit_label(free.get("opsIncluded"))
    # bez free planu → nejlevnější placený entry
    paid = [p for p in plans if p.get("monthlyUsd")]
    if paid:
        entry = min(paid, key=lambda p: p["monthlyUsd"])
        return _limit_label(entry.get("opsIncluded")) + ' <span class="host-tag">(entry plan)</span>'
    return "—"


def _workflow_limit_for_variant(variant: dict) -> str:
    kind = variant.get("hostingKind", "saas")
    if kind in ("vps", "own"):
        return '<span class="check">Unlimited</span>'
    wls = [p.get("workflowLimit") for p in variant.get("plans", [])
           if not p.get("selfHostOnly")]
    if all(w is None for w in wls):
        return '<span class="check">Unlimited</span>'
    finite = [w for w in wls if w is not None]
    if not finite:
        return '<span class="check">Unlimited</span>'
    lo, hi = min(finite), max(finite)
    rng = f"{lo:,}" if lo == hi else f"{lo:,} – {hi:,}"
    if any(w is None for w in wls):
        rng += " (+ unlimited tier)"
    return rng


def _render_limits_row(variant: dict) -> str:
    base = _base_slug(variant)
    kind = variant.get("hostingKind", "saas")
    host_label = {"cloud": "Cloud", "saas": "Cloud", "vps": "VPS", "own": "Own server"}.get(kind, "")
    # u SaaS (Make/Pipedream/Zapier) nepřidávej redundantní "· Cloud" tag
    show_tag = kind in ("cloud", "vps", "own")
    tag = f'<span class="host-tag">· {host_label}</span>' if show_tag else ""
    logo = _logo(base)
    img = (f'<img src="{logo}" class="tool-logo" alt="{_html_escape(variant["name"])}" '
           f'onerror="this.style.display=\'none\'">' if logo else "")
    data_self = "1" if kind in ("vps", "own") else "0"
    data_free = "1" if (kind in ("vps", "own") or any(
        p.get("monthlyUsd") == 0 for p in variant.get("plans", []))) else "0"
    data_ai = "1" if variant.get("aiFeatures") else "0"
    data_gdpr = "1" if variant.get("gdprFriendly") else "0"
    return f"""        <tr data-name="{_html_escape(variant['name'])}" data-selfhost="{data_self}" data-ai="{data_ai}" data-free="{data_free}" data-gdpr="{data_gdpr}">
          <td class="tool-col"><span class="td-tool">{img}{_html_escape(variant['name'])}{tag}</span></td>
          <td>{_included_runs_for_variant(variant)}</td>
          <td>{_free_runs_for_variant(variant)}</td>
          <td>{_workflow_limit_for_variant(variant)}</td>
          <td>{_html_escape(variant['maxSteps'])}</td>
          <td>{_html_escape(variant['timeout'])}</td>
          <td>{_html_escape(variant['logHistory'])}</td>
        </tr>"""


def _render_limits_html(tools: list[dict], variants: list[dict], site: dict,
                        tools_meta: dict) -> str:
    month_year = _month_year(tools_meta)
    domain = site.get("domain", "wizardcost.com")
    base_path = (site.get("base_path", "") or "").strip("/")
    prefix = f"https://{domain}/{base_path}".rstrip("/") if base_path else f"https://{domain}"
    canonical = f"{prefix}/limits.html"

    rows = "\n".join(_render_limits_row(v) for v in variants)

    faqs = [
        ("What counts as a run?",
         "A run is one execution of a workflow, regardless of how many steps it contains. "
         "We price everything on runs so tools are directly comparable. Vendors label the "
         "underlying unit differently — Zapier bills per action step (tasks), Make per module "
         "execution (credits/operations), n8n and Activepieces per full workflow execution, "
         "Pipedream by compute credits — and our engine converts each vendor's unit back to "
         "runs using the steps per workflow you set."),
        ("Are self-hosted tools really unlimited?",
         "Yes — self-hosted n8n, Activepieces, Automatisch and Node-RED have no run, workflow "
         "or step limits. You only pay for infrastructure: a rented VPS (scales with volume) "
         "or your own server (home electricity plus a one-off hardware cost). See the "
         '<a href="tools.html">tools overview</a> for the real numbers at each volume.'),
        ("Why are VPS and own-server shown as separate rows?",
         "Because the cost model is different. Self-host on a rented VPS is a monthly server "
         "bill that scales with volume. Self-host on your own server is mostly free — you pay "
         "home electricity each month plus a one-off hardware purchase. Both give unlimited "
         "runs, so we split them out so you can compare honestly."),
        ("How accurate is this data?",
         f"Every limit and price is read straight from data/tools.json, verified against each "
         f"vendor's pricing page in {month_year}. When a tool changes a plan we record it in "
         'the <a href="changelog.html">price changelog</a> and this page regenerates.'),
    ]
    faq_ld = json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer",
                                "text": a.replace('<a href="changelog.html">', "")
                                .replace('<a href="tools.html">', "").replace("</a>", "")}}
            for q, a in faqs],
    }, ensure_ascii=False, indent=2)
    faq_html = "\n".join(
        f'    <div class="faq-item">\n      <div class="faq-q" onclick="toggleFaq(this)">{q}</div>\n'
        f'      <div class="faq-a">{a}</div>\n    </div>' for q, a in faqs)

    css = _LIMITS_CSS + "\n" + _EMAILCAP_CSS
    title = "Automation Tool Pricing & Limits 2026 — Runs, Steps, Timeouts | AutomationCost.io"
    desc = ("Plan limits for every automation tool and hosting option — included runs, workflow "
            "caps, max steps, execution timeout and log history for n8n, Make, Pipedream, Zapier, "
            "Activepieces, Automatisch and Node-RED, including self-host VPS and own-server.")

    note = ("All values from real vendor plans. Included runs = the run allowance on paid cloud "
            "plans (range across tiers); free runs = the run allowance on the free / entry plan. "
            "Self-host VPS and own-server give unlimited runs, workflows and steps. Verified "
            f"{month_year} — see the <a href=\"changelog.html\">price changelog</a>.")

    body = f"""
<div class="wrap">

  <div class="hero">
    <div class="hero-badge">{len(variants)} hosting options · verified {month_year.lower()}</div>
    <h1>Automation tool <em>pricing &amp; limits</em> compared</h1>
    <p>The numbers that actually matter — included runs, workflow caps, max steps, execution
       timeouts and log history. Every tool plus its self-host VPS and own-server options.
       The unit is a <strong>run</strong> (one workflow execution), not an op.</p>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Tool / variant</th>
          <th>Included runs (paid)</th>
          <th>Free runs</th>
          <th>Workflow limit</th>
          <th>Max steps</th>
          <th>Execution timeout</th>
          <th>Log history</th>
        </tr>
      </thead>
      <tbody id="limits-body">
{rows}
      </tbody>
    </table>
  </div>
  <p class="tbl-note">{note}</p>

{_finder_cta("Still comparing? Let us pick for you.", "Answer 4 quick questions and get your cheapest-fit tool ranked at your exact run volume in 30 seconds.")}
{_emailcap("Get an email when a tool changes its limits or pricing.",
           'Every change is verified by hand and published to the <a href="changelog.html">changelog</a> — one email per confirmed change.')}
  <div class="section" id="faq">
    <h2>Frequently asked questions</h2>
  </div>
  <div class="faq">
{faq_html}
  </div>

</div>
"""

    return (_head(title, desc, canonical, css, faq_ld, prefix)
            + _nav("limits", month_year)
            + body
            + _footer(month_year)
            + "\n<script>\nfunction toggleFaq(el) { el.parentElement.classList.toggle(\"open\"); }\n"
            + _EMAILCAP_JS
            + "\n</script>\n\n</body>\n</html>\n")


# ---------------------------------------------------------------------------
# Veřejné API
# ---------------------------------------------------------------------------

def _strip_injected(text: str) -> str:
    """Odstraní GA4/ANALYTICS bloky (vkládané build.py PO generování) pro porovnání
    v --check (jinak by se stránka jevila trvale 'dirty')."""
    import re as _re
    for s, e in (("<!-- GA4 (build.py) -->", "<!-- /GA4 -->"),
                 ("<!-- ANALYTICS (build.py) -->", "<!-- /ANALYTICS -->")):
        text = _re.sub(_re.escape(s) + r".*?" + _re.escape(e) + r"\n?\s*", "", text, flags=_re.S)
    return text


def build_catalog_pages(tools: list[dict], site: dict, tools_meta: dict,
                        *, check: bool = False) -> list[str]:
    """Vygeneruje automation/tools.html + automation/limits.html plně z dat.

    tools      — syrový seznam toolů z tools.json (před expanzí).
    site       — site.json (domain, base_path…) pro canonical/OG prefix.
    tools_meta — _meta z tools.json (last_reviewed → month/year).
    check=True — nezapisuj; vrať seznam souborů, které by se změnily.

    Vrací jména souborů, které byly zapsány (nebo by se v check módu změnily).
    """
    engine = _root_engine()
    variants = expand_hosting_variants(tools)

    targets = {
        ROOT / "tools.html": _render_tools_html(tools, variants, site, tools_meta, engine),
        ROOT / "limits.html": _render_limits_html(tools, variants, site, tools_meta),
    }

    out: list[str] = []
    for target, rendered in targets.items():
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        dirty = existing is None or _strip_injected(existing) != rendered
        if check:
            if dirty:
                out.append(target.name)
        elif dirty:
            target.write_text(rendered, encoding="utf-8")
            out.append(target.name)
    return out


def _load_site() -> dict:
    if SITE.exists():
        return json.loads(SITE.read_text(encoding="utf-8"))
    return {"domain": "wizardcost.com", "base_path": "automation"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generuj tools.html + limits.html z tools.json.")
    parser.add_argument("--check", action="store_true",
                        help="Nezapisuj; vypiš, co by se změnilo (exit 1 pokud out-of-date).")
    args = parser.parse_args()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    tools = data["tools"]
    site = _load_site()
    tools_meta = data.get("_meta", {})

    result = build_catalog_pages(tools, site, tools_meta, check=args.check)
    if args.check:
        if result:
            print(f"[catalog --check] OUT OF DATE: {', '.join(result)} — spusť generátor.")
            return 1
        print("[catalog --check] OK — tools.html + limits.html jsou aktuální.")
        return 0
    if result:
        print(f"[catalog] zapsáno: {', '.join(result)}")
    else:
        print("[catalog] beze změny (vše aktuální).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
