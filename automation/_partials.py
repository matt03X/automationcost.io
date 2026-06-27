"""_partials.py — sdílené HTML fragmenty (nav, logo) pro /automation stránky.

Jediný zdroj pravdy pro nav markup. Importuj místo inline kopií ve build_*.py.
NEMĚŇ data, ceny ani engine logiku — čistě vizuální/strukturální vrstva.

Použití:
    from _partials import dashboard_header

    html = dashboard_header(active="compare")            # žádné extra
    html = dashboard_header(active="", extra=cur_sw)    # s currency switcherem

active hodnoty: 'compare' | 'pricing' | 'integrations' | '' (žádný active link)
extra:          volitelný HTML string vložený těsně před CTA tlačítko (currency/lang switcher)
"""
from __future__ import annotations

_CARET_SVG = (
    '<svg class="logo-icon" viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="acmk" x1="14" y1="10" x2="30" y2="38" gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#2fe39c"></stop>'
    '<stop offset="1" stop-color="#0ea66e"></stop>'
    '</linearGradient></defs>'
    '<path d="M28.5 10.5 L13.5 24 L28.5 37.5" stroke="url(#acmk)" stroke-width="6.8"'
    ' stroke-linecap="round" stroke-linejoin="round"></path>'
    '<path d="M 36.5 17.8 Q 37.864 22.636 42.7 24 Q 37.864 25.364 36.5 30.2'
    ' Q 35.136 25.364 30.3 24 Q 35.136 22.636 36.5 17.8 Z" fill="#eafff5"></path>'
    '</svg>'
)

_DD_MENU = """      <div class="ac-dd-menu">
        <a href="index.html">AutomationCost home</a>
        <a href="tools.html">Tools</a>
        <a href="app-finder.html">App finder</a>
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
      </div>"""

_CTA_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="2.8"><polyline points="9 18 15 12 9 6"/></svg>'
)

_MORE_SVG = (
    '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    ' stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>'
)


def caret_logo() -> str:
    """Caret SVG element (jen <svg>, bez textu) — verbatim z index.html."""
    return _CARET_SVG


def dashboard_header(active: str = "", extra: str = "") -> str:
    """Sdílený jednořádkový nav pro všechny /automation podstránky.

    Args:
        active: klíč aktivního odkazu — 'compare' | 'pricing' | 'integrations' | ''
        extra:  volitelný HTML vložený před CTA tlačítko (currency switcher atd.)

    Returns:
        HTML string obsahující #ac-progress + <nav class="ac-nav"> blok.
    """
    def _cls(name: str) -> str:
        """Vrátí class attr string pro nav link."""
        if name == active:
            return ' class="active ac-hide-sm"'
        return ' class="ac-hide-sm"'

    extra_str = f"\n    {extra.strip()}" if extra and extra.strip() else ""

    return f"""
<div id="ac-progress"></div>

<nav class="ac-nav">
  <a href="/automation/" class="logo">
    {_CARET_SVG}
    Automation<span>Cost</span><span class="io" style="font-size:0.72em; margin-left:7px;">by WizardCost</span>
  </a>
  <div class="ac-links">
    <a href="compare.html"{_cls('compare')}>Compare</a>
    <a href="limits.html"{_cls('pricing')}>Pricing</a>
    <a href="integrations.html"{_cls('integrations')}>Integrations</a>
    <div class="ac-dd">
      <button class="ac-dd-btn" aria-expanded="false" aria-haspopup="true">More
        {_MORE_SVG}
      </button>
{_DD_MENU}
    </div>{extra_str}
    <a href="calculator.html" class="ac-cta">Calculator
      {_CTA_SVG}
    </a>
  </div>
</nav>
"""
