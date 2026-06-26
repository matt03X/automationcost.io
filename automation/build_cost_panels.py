"""build_cost_panels.py — statické SVG cost panely pro SEO stránky.

Tři funkce generují inline SVG z engine dat (cheapest_monthly):
  svg_vs_bars       — grouped bar chart pro vs-stránky (tool A vs B × 4 volumes)
  svg_pricing_bars  — vertical bar progression pro pricing-stránky (1 tool × 4 volumes)
  svg_alt_bars      — horizontal ranking bars pro alternatives-stránky (6 tools @ ALT_VOL)

Pravidla:
  - Čistě statické SVG, žádný JS
  - Barvy z Caret DS (kanonické hex — kopie dashboard.css tokenů)
  - Bars vždy od nuly (žádná zkrácená osa)
  - Insight jako titulek (Tufte: info v nadpise, ne "cost comparison")
  - role="img" + aria-label + skrytá <table> pro screen-readery a crawler
  - Data POUZE z parametrů (čísla z engine, nikdy vymyšlená)
"""
from __future__ import annotations

import math

# ── Kanonické Caret DS hex (kopie dashboard.css — nesmí se lišit) ─────────────
_VENDOR_HEX: dict[str, str] = {
    "zapier":       "#FF4F00",
    "make":         "#B02DE9",
    "n8n":          "#EA4B71",
    "pipedream":    "#3b82f6",
    "activepieces": "#6E56CF",
    "automatisch":  "#0EA5E9",
    "node-red":     "#8F0000",
}
_GREEN   = "#16d18c"   # --auto / --green — vítěz / nejlevnější
_GREEN2  = "#10b981"   # slightly dimmer green for gradient stop
_MUTED   = "#736e8e"   # --tx3 / --muted
_TX2     = "#b3aeca"   # --tx2 / --text2
_TX      = "#f2f0fa"   # --tx / --text
_PANEL   = "#0e0d17"   # --panel
_PANEL2  = "#12111c"   # --panel2 — graf plocha
_BORDER  = "#221f33"   # --b — grid lines
_BORDER2 = "#2e2a44"   # --b2 — slightly lighter


def _vol_label(v: int) -> str:
    """1000 → '1k', 20000 → '20k', 100000 → '100k'."""
    if v >= 1_000_000:
        return f"{v // 1_000_000}M"
    return f"{v // 1000}k"


def _fmt_c(cost: float, est: bool) -> str:
    """Format cost for SVG bar labels: $49, ~$1,200, $0."""
    if cost == 0:
        return "$0"
    if cost >= 1000:
        body = f"{cost:,.0f}"
    elif cost >= 10:
        body = f"{cost:.0f}"
    elif cost >= 1:
        body = f"{cost:.1f}".rstrip("0").rstrip(".")
    else:
        body = f"{cost:.2f}".rstrip("0").rstrip(".")
    return ("~$" if est else "$") + body


def _fmt_grid(v: float) -> str:
    """Y-axis grid label: compact, read at a glance."""
    if v >= 1000:
        return f"${v / 1000:.0f}k"
    if v >= 100:
        return f"${v:.0f}"
    if v >= 10:
        return f"${v:.0f}"
    if v > 0:
        return f"${v:.1f}"
    return "$0"


def _vendor_hex(slug: str) -> str:
    return _VENDOR_HEX.get(slug, _GREEN)


def _slug_id(slug: str) -> str:
    """SVG-safe ID fragment (no hyphens)."""
    return slug.replace("-", "_")


# ──────────────────────────────────────────────────────────────────────────────
# 1. VS-page: grouped vertical bar chart (tool A vs B × 4 volumes)
# ──────────────────────────────────────────────────────────────────────────────

def svg_vs_bars(
    a_name: str, b_name: str,
    a_slug: str, b_slug: str,
    costs: list[tuple[dict, dict]],   # [(ra, rb), ...] from cheapest_monthly
    volumes: list[int],
    month_year: str,
) -> str:
    """Grouped bar chart: A vs B at each volume. Returns <figure> HTML block."""
    a_col = _vendor_hex(a_slug)
    b_col = _vendor_hex(b_slug)
    a_gid = "vg_a_" + _slug_id(a_slug)
    b_gid = "vg_b_" + _slug_id(b_slug)

    W, H = 680, 218
    PAD_T = 50   # title (20px) + subtitle (34px) + some space
    PAD_B = 56   # vol labels (14px below baseline) + "runs/mo" (28px) + legend row
    PAD_L = 46   # y-axis labels (rightmost is ~38px wide)
    PAD_R = 12
    chart_w = W - PAD_L - PAD_R    # 622
    chart_h = H - PAD_T - PAD_B    # 112

    n = len(volumes)
    bar_w = 26
    gap_inner = 8
    group_w = bar_w * 2 + gap_inner   # 60

    # Evenly distribute groups within chart_w
    group_gap = (chart_w - n * group_w) // (n + 1)
    group_gap = max(20, group_gap)    # minimum spacing
    gx0 = PAD_L + group_gap          # first group start x

    all_costs = [r["cost"] for ra, rb in costs for r in (ra, rb) if r]
    max_c = max(all_costs) if all_costs else 1.0

    def bh(cost: float) -> int:
        return max(3, round(chart_h * min(cost / max_c, 1.0)))

    def by_(cost: float) -> int:
        return PAD_T + chart_h - bh(cost)

    # Insight title: biggest absolute cost gap across volumes
    best_i = max(range(n), key=lambda i: abs(costs[i][0]["cost"] - costs[i][1]["cost"]))
    ra_b, rb_b = costs[best_i]
    lo, hi = sorted([ra_b["cost"], rb_b["cost"]])
    if lo > 0 and hi > 0:
        ratio = hi / lo
        cheaper = a_name if ra_b["cost"] < rb_b["cost"] else b_name
        pricier = b_name if cheaper == a_name else a_name
        if ratio >= 1.1:
            insight = f"{cheaper} is {ratio:.1f}× cheaper than {pricier} at {_vol_label(volumes[best_i])} runs/mo"
        else:
            insight = f"{a_name} and {b_name} cost similarly — see detail by volume"
    else:
        insight = f"{a_name} vs {b_name} — monthly cost by volume"

    p: list[str] = []

    p.append(f'<figure class="cost-panel" aria-label="Chart: {insight}">')
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%"'
        f' style="display:block;max-width:{W}px;margin:0 auto;" aria-hidden="true">'
    )

    # ── defs: gradients ──
    p.append("<defs>")
    for gid, col in ((a_gid, a_col), (b_gid, b_col)):
        p.append(f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">')
        p.append(f'  <stop offset="0%" stop-color="{col}" stop-opacity="0.95"/>')
        p.append(f'  <stop offset="100%" stop-color="{col}" stop-opacity="0.45"/>')
        p.append(f"</linearGradient>")
    p.append("</defs>")

    # ── background ──
    p.append(f'<rect width="{W}" height="{H}" fill="{_PANEL2}" rx="12"/>')

    # ── y-axis grid (3 lines at 33%, 67%, 100%) ──
    baseline_y = PAD_T + chart_h
    for frac in (0.33, 0.67, 1.0):
        gy = PAD_T + chart_h - round(chart_h * frac)
        p.append(
            f'<line x1="{PAD_L}" y1="{gy}" x2="{W - PAD_R}" y2="{gy}"'
            f' stroke="{_BORDER2}" stroke-width="1" stroke-dasharray="3,3"/>'
        )
        gl = _fmt_grid(max_c * frac)
        p.append(
            f'<text x="{PAD_L - 5}" y="{gy + 4}" font-family="JetBrains Mono,monospace"'
            f' font-size="9" fill="{_MUTED}" text-anchor="end">{gl}</text>'
        )

    # ── baseline ──
    p.append(
        f'<line x1="{PAD_L}" y1="{baseline_y}" x2="{W - PAD_R}" y2="{baseline_y}"'
        f' stroke="{_BORDER2}" stroke-width="1"/>'
    )

    # ── title + subtitle ──
    p.append(
        f'<text x="{PAD_L}" y="20" font-family="Hanken Grotesk,Plus Jakarta Sans,sans-serif"'
        f' font-size="13" font-weight="700" fill="{_TX}">{insight}</text>'
    )
    p.append(
        f'<text x="{PAD_L}" y="36" font-family="Plus Jakarta Sans,sans-serif"'
        f' font-size="10.5" fill="{_TX2}">Monthly cost · cheapest qualifying plan · 3-step workflows</text>'
    )

    # ── bars ──
    for i, (vol, (ra, rb)) in enumerate(zip(volumes, costs)):
        gx = gx0 + i * (group_w + group_gap)

        # Bar A
        bh_a = bh(ra["cost"])
        by_a = by_(ra["cost"])
        p.append(
            f'<rect x="{gx}" y="{by_a}" width="{bar_w}" height="{bh_a}"'
            f' fill="url(#{a_gid})" rx="3"/>'
        )
        la = _fmt_c(ra["cost"], ra.get("est", False))
        p.append(
            f'<text x="{gx + bar_w // 2}" y="{by_a - 4}" font-family="JetBrains Mono,monospace"'
            f' font-size="8.5" fill="{_TX}" text-anchor="middle">{la}</text>'
        )

        # Bar B
        bxb = gx + bar_w + gap_inner
        bh_b = bh(rb["cost"])
        by_b = by_(rb["cost"])
        p.append(
            f'<rect x="{bxb}" y="{by_b}" width="{bar_w}" height="{bh_b}"'
            f' fill="url(#{b_gid})" rx="3"/>'
        )
        lb = _fmt_c(rb["cost"], rb.get("est", False))
        p.append(
            f'<text x="{bxb + bar_w // 2}" y="{by_b - 4}" font-family="JetBrains Mono,monospace"'
            f' font-size="8.5" fill="{_TX}" text-anchor="middle">{lb}</text>'
        )

        # Volume label below group
        cx = gx + group_w // 2
        p.append(
            f'<text x="{cx}" y="{baseline_y + 14}" font-family="JetBrains Mono,monospace"'
            f' font-size="10" fill="{_TX2}" text-anchor="middle">{_vol_label(vol)}</text>'
        )

    # ── "runs / month" x-axis label ──
    p.append(
        f'<text x="{W // 2}" y="{baseline_y + 28}" font-family="Plus Jakarta Sans,sans-serif"'
        f' font-size="10" fill="{_MUTED}" text-anchor="middle">runs / month</text>'
    )

    # ── legend ──
    leg_y = H - 10
    leg_x = PAD_L
    for lname, lcol in ((a_name, a_col), (b_name, b_col)):
        p.append(f'<rect x="{leg_x}" y="{leg_y - 9}" width="12" height="9" fill="{lcol}" rx="2"/>')
        p.append(
            f'<text x="{leg_x + 16}" y="{leg_y}" font-family="Plus Jakarta Sans,sans-serif"'
            f' font-size="11" fill="{_TX2}">{lname}</text>'
        )
        leg_x += 16 + max(len(lname) * 7, 52) + 18

    # ── attribution ──
    p.append(
        f'<text x="{W - PAD_R}" y="{H - 4}" font-family="JetBrains Mono,monospace"'
        f' font-size="8" fill="{_MUTED}" text-anchor="end">'
        f"wizardcost.com · verified {month_year}</text>"
    )

    p.append("</svg>")

    # ── hidden accessible table (crawler + screen-reader) ──
    p.append(
        '<table style="position:absolute;width:1px;height:1px;overflow:hidden;'
        'clip:rect(0,0,0,0);border:0;">'
    )
    p.append(f"  <caption>{a_name} vs {b_name} — monthly cost by volume</caption>")
    p.append(f"  <thead><tr><th>runs/mo</th><th>{a_name}</th><th>{b_name}</th></tr></thead>")
    p.append("  <tbody>")
    for vol, (ra, rb) in zip(volumes, costs):
        fa = _fmt_c(ra["cost"], ra.get("est", False))
        fb = _fmt_c(rb["cost"], rb.get("est", False))
        p.append(f"    <tr><td>{vol:,}</td><td>{fa}/mo</td><td>{fb}/mo</td></tr>")
    p.append("  </tbody>")
    p.append("</table>")
    p.append("</figure>")

    return "\n".join(p)


# ──────────────────────────────────────────────────────────────────────────────
# 2. Pricing-page: vertical bar progression (1 tool × 4 volumes)
# ──────────────────────────────────────────────────────────────────────────────

def svg_pricing_bars(
    name: str,
    slug: str,
    vol_costs: list[tuple[int, dict | None]],   # [(vol, result), ...]
    month_year: str,
) -> str:
    """Vertical bar progression for a single tool across 4 volumes.
    Returned value = <figure> HTML block.
    """
    col = _vendor_hex(slug)
    gid = "pg_" + _slug_id(slug)

    W, H = 580, 196
    PAD_T = 50
    PAD_B = 50   # vol labels + "runs/mo"
    PAD_L = 46
    PAD_R = 12
    chart_w = W - PAD_L - PAD_R   # 522
    chart_h = H - PAD_T - PAD_B   # 96

    n = len(vol_costs)
    bar_w = max(50, (chart_w - (n + 1) * 20) // n)
    bar_w = min(bar_w, 90)
    gap = (chart_w - n * bar_w) // (n + 1)
    gap = max(14, gap)
    bx0 = PAD_L + gap

    valid = [(v, r) for v, r in vol_costs if r is not None]
    max_c = max(r["cost"] for _, r in valid) if valid else 1.0
    if max_c == 0:
        max_c = 1.0

    def bh(cost: float) -> int:
        return max(3, round(chart_h * min(cost / max_c, 1.0)))

    def by_(cost: float) -> int:
        return PAD_T + chart_h - bh(cost)

    # Insight title
    costs_valid = [r["cost"] for _, r in valid]
    if len(costs_valid) >= 2:
        lo_r = valid[0][1]
        hi_r = valid[-1][1]
        lo_vol, hi_vol = valid[0][0], valid[-1][0]
        lo_fmt = _fmt_c(lo_r["cost"], lo_r.get("est", False))
        hi_fmt = _fmt_c(hi_r["cost"], hi_r.get("est", False))
        insight = f"{name}: from {lo_fmt}/mo at {_vol_label(lo_vol)} to {hi_fmt}/mo at {_vol_label(hi_vol)} runs"
    else:
        insight = f"{name} pricing by volume"

    p: list[str] = []
    baseline_y = PAD_T + chart_h

    p.append(f'<figure class="cost-panel" aria-label="Chart: {insight}">')
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%"'
        f' style="display:block;max-width:{W}px;margin:0 auto;" aria-hidden="true">'
    )

    # ── defs ──
    p.append("<defs>")
    p.append(f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">')
    p.append(f'  <stop offset="0%" stop-color="{col}" stop-opacity="0.95"/>')
    p.append(f'  <stop offset="100%" stop-color="{col}" stop-opacity="0.40"/>')
    p.append("</linearGradient>")
    p.append("</defs>")

    # ── background ──
    p.append(f'<rect width="{W}" height="{H}" fill="{_PANEL2}" rx="12"/>')

    # ── y-axis grid ──
    for frac in (0.33, 0.67, 1.0):
        gy = PAD_T + chart_h - round(chart_h * frac)
        p.append(
            f'<line x1="{PAD_L}" y1="{gy}" x2="{W - PAD_R}" y2="{gy}"'
            f' stroke="{_BORDER2}" stroke-width="1" stroke-dasharray="3,3"/>'
        )
        gl = _fmt_grid(max_c * frac)
        p.append(
            f'<text x="{PAD_L - 5}" y="{gy + 4}" font-family="JetBrains Mono,monospace"'
            f' font-size="9" fill="{_MUTED}" text-anchor="end">{gl}</text>'
        )

    # ── baseline ──
    p.append(
        f'<line x1="{PAD_L}" y1="{baseline_y}" x2="{W - PAD_R}" y2="{baseline_y}"'
        f' stroke="{_BORDER2}" stroke-width="1"/>'
    )

    # ── title + subtitle ──
    p.append(
        f'<text x="{PAD_L}" y="20" font-family="Hanken Grotesk,Plus Jakarta Sans,sans-serif"'
        f' font-size="12.5" font-weight="700" fill="{_TX}">{insight}</text>'
    )
    p.append(
        f'<text x="{PAD_L}" y="36" font-family="Plus Jakarta Sans,sans-serif"'
        f' font-size="10.5" fill="{_TX2}">Cheapest qualifying plan · 3-step workflows · monthly billing</text>'
    )

    # ── bars ──
    for i, (vol, r) in enumerate(vol_costs):
        bx = bx0 + i * (bar_w + gap)
        cx = bx + bar_w // 2
        cost = r["cost"] if r else 0
        est = r.get("est", False) if r else False

        bh_val = bh(cost)
        by_val = by_(cost)
        p.append(
            f'<rect x="{bx}" y="{by_val}" width="{bar_w}" height="{bh_val}"'
            f' fill="url(#{gid})" rx="4"/>'
        )

        # Price label above bar
        lbl = _fmt_c(cost, est)
        p.append(
            f'<text x="{cx}" y="{by_val - 5}" font-family="JetBrains Mono,monospace"'
            f' font-size="9" font-weight="600" fill="{_TX}" text-anchor="middle">{lbl}</text>'
        )

        # Volume label below baseline
        p.append(
            f'<text x="{cx}" y="{baseline_y + 14}" font-family="JetBrains Mono,monospace"'
            f' font-size="10" fill="{_TX2}" text-anchor="middle">{_vol_label(vol)}</text>'
        )

    # ── "runs / month" ──
    p.append(
        f'<text x="{W // 2}" y="{baseline_y + 28}" font-family="Plus Jakarta Sans,sans-serif"'
        f' font-size="10" fill="{_MUTED}" text-anchor="middle">runs / month</text>'
    )

    # ── attribution ──
    p.append(
        f'<text x="{W - PAD_R}" y="{H - 4}" font-family="JetBrains Mono,monospace"'
        f' font-size="8" fill="{_MUTED}" text-anchor="end">'
        f"wizardcost.com · verified {month_year}</text>"
    )

    p.append("</svg>")

    # ── accessible table ──
    p.append(
        '<table style="position:absolute;width:1px;height:1px;overflow:hidden;'
        'clip:rect(0,0,0,0);border:0;">'
    )
    p.append(f"  <caption>{name} cost by volume (monthly)</caption>")
    p.append("  <thead><tr><th>runs/mo</th><th>monthly cost</th></tr></thead>")
    p.append("  <tbody>")
    for vol, r in vol_costs:
        lbl = _fmt_c(r["cost"], r.get("est", False)) if r else "n/a"
        p.append(f"    <tr><td>{vol:,}</td><td>{lbl}/mo</td></tr>")
    p.append("  </tbody>")
    p.append("</table>")
    p.append("</figure>")

    return "\n".join(p)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Alternatives-page: horizontal ranking bars (6 tools @ ALT_VOL)
# ──────────────────────────────────────────────────────────────────────────────

def svg_alt_bars(
    focus_name: str,
    priced: list[tuple[str, dict]],   # sorted cheapest→most expensive (slug, result)
    by_slug: dict,                     # slug → tool dict
    alt_vol: int,
    month_year: str,
) -> str:
    """Horizontal ranking bars: alternatives for focus_name, ranked cheapest→priciest.
    Returned value = <figure> HTML block.
    """
    if not priced:
        return ""

    n = len(priced)
    row_h = 28        # pixels per tool row (bar + spacing)
    bar_h = 16        # bar height within row
    W = 640
    PAD_T = 50        # title + subtitle
    PAD_B = 28        # attribution row
    PAD_L = 96        # tool name labels (left)
    PAD_R = 86        # price + ratio labels (right)
    chart_w = W - PAD_L - PAD_R   # 458
    H = PAD_T + n * row_h + PAD_B

    max_c = max(r["cost"] for _, r in priced) if priced else 1.0
    if max_c == 0:
        max_c = 1.0

    def bar_px(cost: float) -> int:
        return max(4, round(chart_w * min(cost / max_c, 1.0)))

    cheapest_slug, cheapest_r = priced[0]
    priciest_slug, priciest_r = priced[-1]
    cheapest_name = by_slug[cheapest_slug]["name"]
    priciest_name = by_slug[priciest_slug]["name"]
    c_fmt = _fmt_c(cheapest_r["cost"], cheapest_r.get("est", False))
    p_fmt = _fmt_c(priciest_r["cost"], priciest_r.get("est", False))
    insight = (
        f"{cheapest_name} ({c_fmt}) to {priciest_name} ({p_fmt})"
        f" at {_vol_label(alt_vol)} runs/mo — ranked cheapest first"
    )

    p: list[str] = []
    p.append(f'<figure class="cost-panel" aria-label="Chart: {insight}">')
    p.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%"'
        f' style="display:block;max-width:{W}px;margin:0 auto;" aria-hidden="true">'
    )

    # ── background ──
    p.append(f'<rect width="{W}" height="{H}" fill="{_PANEL2}" rx="12"/>')

    # ── title + subtitle ──
    p.append(
        f'<text x="{PAD_L}" y="20" font-family="Hanken Grotesk,Plus Jakarta Sans,sans-serif"'
        f' font-size="12.5" font-weight="700" fill="{_TX}">{insight}</text>'
    )
    p.append(
        f'<text x="{PAD_L}" y="36" font-family="Plus Jakarta Sans,sans-serif"'
        f' font-size="10.5" fill="{_TX2}">'
        f"Cheapest qualifying plan at {alt_vol:,} runs/mo · 3-step workflows</text>"
    )

    # ── baseline grid line ──
    p.append(
        f'<line x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{PAD_T + n * row_h}"'
        f' stroke="{_BORDER2}" stroke-width="1"/>'
    )

    # ── horizontal bars ──
    for i, (slug, r) in enumerate(priced):
        tool_name = by_slug[slug]["name"]
        cost = r["cost"]
        est = r.get("est", False)
        bw = bar_px(cost)
        row_y = PAD_T + i * row_h
        bar_top = row_y + (row_h - bar_h) // 2

        # Bar color: green for cheapest, vendor color for others
        col = _GREEN if i == 0 else _vendor_hex(slug)

        # Alternating row background (very subtle)
        if i % 2 == 0:
            p.append(
                f'<rect x="{PAD_L}" y="{row_y}" width="{chart_w}" height="{row_h}"'
                f' fill="rgba(255,255,255,0.02)" rx="0"/>'
            )

        # Bar
        p.append(
            f'<rect x="{PAD_L}" y="{bar_top}" width="{bw}" height="{bar_h}"'
            f' fill="{col}" opacity="0.85" rx="3"/>'
        )

        # Tool name (left)
        p.append(
            f'<text x="{PAD_L - 7}" y="{bar_top + bar_h - 3}" font-family="Plus Jakarta Sans,sans-serif"'
            f' font-size="11" fill="{_TX if i == 0 else _TX2}" text-anchor="end">{tool_name}</text>'
        )

        # Price label (right of bar)
        cost_lbl = _fmt_c(cost, est)
        p.append(
            f'<text x="{PAD_L + bw + 6}" y="{bar_top + bar_h - 3}" font-family="JetBrains Mono,monospace"'
            f' font-size="9.5" fill="{_GREEN if i == 0 else _TX2}">{cost_lbl}/mo</text>'
        )

        # Ratio vs cheapest (right margin), skip for cheapest itself
        if i > 0 and cheapest_r["cost"] > 0:
            ratio = cost / cheapest_r["cost"]
            if ratio >= 1.05:
                ratio_lbl = f"+{ratio:.1f}×"
                p.append(
                    f'<text x="{W - PAD_R + 6}" y="{bar_top + bar_h - 3}" font-family="JetBrains Mono,monospace"'
                    f' font-size="9" fill="{_MUTED}">{ratio_lbl}</text>'
                )

    # ── attribution ──
    p.append(
        f'<text x="{W - 8}" y="{H - 8}" font-family="JetBrains Mono,monospace"'
        f' font-size="8" fill="{_MUTED}" text-anchor="end">'
        f"wizardcost.com · verified {month_year}</text>"
    )

    p.append("</svg>")

    # ── accessible table ──
    p.append(
        '<table style="position:absolute;width:1px;height:1px;overflow:hidden;'
        'clip:rect(0,0,0,0);border:0;">'
    )
    p.append(
        f"  <caption>{focus_name} alternatives ranked by cost at {alt_vol:,} runs/mo</caption>"
    )
    p.append(
        "  <thead><tr><th>Tool</th><th>Monthly cost</th><th>vs cheapest</th></tr></thead>"
    )
    p.append("  <tbody>")
    for i, (slug, r) in enumerate(priced):
        tool_name = by_slug[slug]["name"]
        cost_lbl = _fmt_c(r["cost"], r.get("est", False))
        if i == 0 or cheapest_r["cost"] == 0:
            ratio_lbl = "cheapest"
        else:
            ratio_lbl = f"{r['cost'] / cheapest_r['cost']:.1f}×"
        p.append(f"    <tr><td>{tool_name}</td><td>{cost_lbl}/mo</td><td>{ratio_lbl}</td></tr>")
    p.append("  </tbody>")
    p.append("</table>")
    p.append("</figure>")

    return "\n".join(p)
