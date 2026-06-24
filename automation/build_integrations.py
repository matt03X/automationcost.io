#!/usr/bin/env python3
"""build_integrations.py — generátor stránky „Integration finder" z naškrábaných katalogů.

Čte týdenní snapshoty z `automation/data/integrations/<vendor>/latest.json`
(zdroj = scripts/integrations-audit.js), zmatchuje stejnou integraci napříč 7 nástroji
(kanonický název + kurátorský alias map), a vygeneruje:

  • automation/data/integrations/index.json   — kanonická matice (apps × 7 nástrojů),
                                                 datová vrstva pro client-side finder
  • automation/integrations.html              — stránka: server-rendered matice
                                                 populárních integrací (crawlovatelné, SEO)
                                                 + JS finder nad PLNÝM indexem (vyber
                                                 integraci → vyfiltruj nástroje co ji nemají)

POCTIVOST (projekt má legal/fact gate — tady to platí dvojnásob, je to srovnání konkurence):
  • Match = podle NORMALIZOVANÉHO NÁZVU z VEŘEJNÉHO katalogu každého nástroje k danému datu.
    Absence = „nenalezeno v katalogu pod tímhle názvem", NE „nedá se to nikdy".
  • node-red katalog = KOMUNITNÍ npm moduly (ne first-party konektory) → renderuje se
    jako „community" odlišně, NIKDY jako rovnocenný first-party check.
  • Čísla = počet položek v katalogu, ne known o kvalitě/hloubce konektoru.

Vstupní bod: `build_integrations_page(tools, site, tools_meta, *, check=False) -> list[str]`.
Standalone:
    python automation/build_integrations.py            # zapíše index.json + integrations.html
    python automation/build_integrations.py --check     # co by se změnilo (bez zápisu)

Pozn.: importuje sdílené chrome (head/nav/footer/CSS) z build_catalog (DRY) — stejně
jako build_catalog importuje z build.py. Generované soubory NEEDITOVAT ručně.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from build_catalog import (
    _BASE_HEAD_CSS, _EMAILCAP_CSS, _EMAILCAP_JS, _emailcap, _finder_cta,
    _footer, _head, _html_escape, _load_site, _logo, _month_year, _nav,
    _strip_injected,
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "tools.json"
INT_DIR = ROOT / "data" / "integrations"

# pořadí sloupců (first-party konektory; node-red zvlášť = community)
FIRST_PARTY = ["zapier", "make", "n8n", "pipedream", "activepieces", "automatisch"]
TOOLS_ORDER = FIRST_PARTY + ["node-red"]
# kolik nejvíc-multiplatformních appek server-renderovat do viditelné matice (SEO/crawl)
POPULAR_RENDER = 120
# práh „populární" pro server-render (počet first-party nástrojů, co integraci mají)
POPULAR_MIN_TOOLS = 3


# ---------------------------------------------------------------------------
# Kanonizace + alias map
# ---------------------------------------------------------------------------

def _canon(s: str) -> str:
    """Normalizovaný klíč pro match napříč nástroji: bez diakritiky, bez závorek,
    jen [a-z0-9]. 'Google Sheets' → 'googlesheets', 'Twitter / X' → 'twitterx'."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\([^)]*\)", "", s)        # zahoď text v závorkách
    s = s.lower()
    return re.sub(r"[^a-z0-9]+", "", s)


# Kurátorský alias map: různé názvy téže appky → jeden kanonický klíč. Řeší
# fragmentaci u POPULÁRNÍCH appek (twitter/x, quickbooks varianty, …). Hodnota =
# cílový kanon. Rozšiřuj podle change reportů; drobné překlepy katalogů sem nepatří.
_ALIAS = {
    "x": "twitter", "xformerlytwitter": "twitter", "xtwitter": "twitter", "twitterx": "twitter",
    "quickbooksonline": "quickbooks", "quickbooksonlineapp": "quickbooks", "intuitquickbooks": "quickbooks",
    "claude": "anthropic", "anthropicclaude": "anthropic", "claudeai": "anthropic",
    "openaichatgpt": "openai", "chatgpt": "openai",
    "googlegmail": "gmail", "googleemail": "gmail",
    "googlecalendar2": "googlecalendar",
    "microsoft365": "office365", "microsoftoffice365": "office365",
    "metafacebook": "facebook", "facebookpages": "facebook",
    "youtubedata": "youtube",
    "wordpresscom": "wordpress", "wordpressorg": "wordpress",
    "monday": "mondaycom", "mondaylabs": "mondaycom",
    "googlebigquery": "bigquery",
    "amazons3": "awss3", "s3": "awss3",
    "hubspotcrm": "hubspot",
    "linkedinads": "linkedin",
    "telegrambot": "telegram",
    "whatsappbusiness": "whatsapp", "whatsappbusinesscloud": "whatsapp",
    "googleadsapi": "googleads",
}


def _alias(key: str) -> str:
    return _ALIAS.get(key, key)


# generické tokeny v node-red id (nevypovídají o appce) — pro čistší blob
_NR_STRIP = re.compile(r"\b(node|red|contrib|nodes?)\b")


# ---------------------------------------------------------------------------
# Načtení katalogů + sestavení matice
# ---------------------------------------------------------------------------

def _load_catalog(vendor: str) -> list[dict]:
    f = INT_DIR / vendor / "latest.json"
    if not f.exists():
        return []
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("integrations", [])
    except (ValueError, OSError):
        return []


def _load_counts() -> dict:
    f = INT_DIR / "counts.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("counts", {})
        except (ValueError, OSError):
            pass
    return {}


def build_matrix() -> dict:
    """Sestaví kanonickou matici apps × 7 nástrojů z naškrábaných katalogů.

    Vrací { apps: [{name, category, support:{tool:0|1|2}, score}], counts, date }.
    support: 0 = nemá, 1 = first-party konektor, 2 = node-red community modul.
    score = počet first-party nástrojů (řazení; node-red se do score nepočítá)."""
    by_key: dict[str, dict] = {}

    for v in FIRST_PARTY:
        for it in _load_catalog(v):
            key = _alias(_canon(it.get("name", "")))
            if not key:
                continue
            e = by_key.setdefault(key, {"name": it["name"], "category": it.get("category"), "support": {}})
            e["support"][v] = 1
            # preferuj „hezčí" display: kratší a s mezerou/velkým písmenem (čitelnější)
            cand = it["name"]
            if cand and (" " in cand or cand[:1].isupper()) and len(cand) <= len(e["name"]):
                e["name"] = cand
            if not e.get("category") and it.get("category"):
                e["category"] = it["category"]

    # node-red = KOMUNITNÍ npm moduly. Match přes substring v očištěném blobu id
    # (token ≥4 znaky). Renderuje se jako „community" (2), NIKDY jako first-party (1).
    nr_blob = "|" + "|".join(_canon(_NR_STRIP.sub("", x.get("slug", ""))) for x in _load_catalog("node-red")) + "|"
    for key, e in by_key.items():
        if len(key) >= 4 and key in nr_blob:
            e["support"]["node-red"] = 2

    apps = []
    for e in by_key.values():
        score = sum(1 for v in FIRST_PARTY if e["support"].get(v))
        apps.append({"name": e["name"].strip(), "category": (e.get("category") or "").strip() or None,
                     "support": e["support"], "score": score})
    # řazení: nejvíc first-party nástrojů první, pak abecedně
    apps.sort(key=lambda a: (-a["score"], a["name"].lower()))
    return {"apps": apps, "counts": _load_counts()}


def _index_json(matrix: dict, tools_meta: dict) -> str:
    """Kompaktní index.json pro client-side finder (fetchuje ho stránka)."""
    apps = [{
        "n": a["name"],
        "c": a["category"] or "",
        "t": [a["support"].get(v, 0) for v in TOOLS_ORDER],
    } for a in matrix["apps"]]
    out = {
        "_note": ("Kanonická matice integrací apps × 7 nástrojů z týdenního auditu. "
                  "t[] = support per nástroj v pořadí 'tools': 0=nemá, 1=first-party konektor, "
                  "2=node-red community modul. Match podle normalizovaného názvu z veřejného "
                  "katalogu — evidence, ne zdroj pravdy."),
        "date": _month_year(tools_meta),
        "tools": TOOLS_ORDER,
        "counts": matrix["counts"],
        "apps": apps,
    }
    # 1 app/řádek → čitelné git diffy
    lines = [json.dumps(a, ensure_ascii=False, separators=(",", ":")) for a in apps]
    head = json.dumps({k: out[k] for k in ("_note", "date", "tools", "counts")}, ensure_ascii=False, indent=2)[:-2]
    return head + ',\n  "apps": [\n    ' + ",\n    ".join(lines) + "\n  ]\n}\n"


# ---------------------------------------------------------------------------
# CSS (Caret DS — staví na _BASE_HEAD_CSS z build_catalog)
# ---------------------------------------------------------------------------

_FINDER_CSS = _BASE_HEAD_CSS + """
    .tbl-note { font-family: var(--mono); font-size: 11.5px; color: var(--muted); margin: 8px 0; line-height: 1.7; }
    .disclaimer { background: var(--surface); border: 1px solid var(--border2); border-left: 3px solid var(--yellow); border-radius: var(--radius-sm); padding: 16px 20px; margin: 20px 0; font-size: 13px; color: var(--text2); line-height: 1.65; }
    .disclaimer strong { color: var(--text); }

    /* Finder controls */
    .finder { background: var(--surface); border: 1px solid var(--border2); border-radius: var(--radius); padding: 22px 24px; margin: 20px 0 12px; }
    .finder-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
    .finder-search { flex: 1 1 320px; min-width: 0; position: relative; }
    .finder-search input { width: 100%; background: var(--bg); border: 1px solid var(--border2); border-radius: var(--radius-sm); padding: 13px 16px 13px 42px; font-family: var(--font); font-size: 15px; color: var(--text); }
    .finder-search input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }
    .finder-search svg { position: absolute; left: 14px; top: 50%; transform: translateY(-50%); color: var(--muted); }
    .finder-mode { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text2); cursor: pointer; user-select: none; }
    .finder-mode input { width: 16px; height: 16px; accent-color: var(--accent); }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; min-height: 4px; }
    .chip { display: inline-flex; align-items: center; gap: 7px; background: var(--accent-dim); border: 1px solid rgba(16,185,129,0.4); color: var(--accent-br); border-radius: 100px; padding: 5px 10px 5px 12px; font-size: 13px; font-weight: 600; }
    .chip button { background: none; border: 0; color: var(--accent-br); cursor: pointer; font-size: 15px; line-height: 1; padding: 0; }
    .suggest { position: absolute; top: calc(100% + 6px); left: 0; right: 0; background: var(--surface2); border: 1px solid var(--border2); border-radius: var(--radius-sm); max-height: 320px; overflow-y: auto; z-index: 30; display: none; box-shadow: 0 14px 40px rgba(0,0,0,0.45); }
    .suggest.show { display: block; }
    .suggest div { padding: 10px 14px; font-size: 14px; cursor: pointer; display: flex; justify-content: space-between; gap: 10px; }
    .suggest div:hover, .suggest div.active { background: var(--accent-dim); }
    .suggest .s-cat { color: var(--muted); font-size: 12px; }

    /* Matrix table */
    .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius-sm); margin-bottom: 8px; }
    table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
    th { background: var(--surface2); color: var(--muted); font-family: var(--mono); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; padding: 10px 12px; text-align: center; border-bottom: 1px solid var(--border); white-space: nowrap; }
    th.app-col { text-align: left; }
    th .th-tool { display: inline-flex; flex-direction: column; align-items: center; gap: 5px; }
    th .th-tool img { width: 24px; height: 24px; border-radius: 5px; background: #fff; padding: 2px; }
    th .th-count { font-size: 9.5px; color: var(--muted); font-weight: 400; }
    th.dim { opacity: 0.32; }
    td { padding: 10px 12px; border-bottom: 1px solid var(--border); background: var(--surface); text-align: center; }
    td.app-col { text-align: left; font-weight: 600; color: var(--text); white-space: nowrap; }
    td.app-col .cat { display: block; font-weight: 400; font-size: 11.5px; color: var(--muted); }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: var(--surface2); }
    td.dim { opacity: 0.3; }
    .yes { color: var(--green); font-weight: 800; }
    .no { color: #39465f; }
    .comm { color: var(--yellow); font-weight: 700; font-size: 11px; font-family: var(--mono); }
    .legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: 12.5px; color: var(--muted); margin: 6px 0 28px; }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .result-meta { font-size: 13px; color: var(--text2); margin: 4px 0 10px; min-height: 18px; }
    .empty { text-align: center; color: var(--muted); padding: 30px; font-size: 14px; }
    .section { margin: 48px 0 14px; }
    .section h2 { font-size: 1.5rem; font-weight: 800; margin-bottom: 6px; }
    .section p { color: var(--text2); font-size: 14.5px; max-width: 720px; }

    .faq { margin: 16px 0 56px; }
    .faq-item { border-bottom: 1px solid var(--border); padding: 18px 0; }
    .faq-item:first-child { border-top: 1px solid var(--border); }
    .faq-q { font-weight: 700; font-size: 15px; cursor: pointer; display: flex; justify-content: space-between; gap: 12px; }
    .faq-q::after { content: "+"; color: var(--muted); font-size: 1.2rem; }
    .faq-item.open .faq-q::after { content: "−"; }
    .faq-a { color: var(--muted); font-size: 14px; line-height: 1.7; display: none; margin-top: 10px; }
    .faq-item.open .faq-a { display: block; }
    @media (max-width: 760px) { th .th-tool img { width: 20px; height: 20px; } td, th { padding: 9px 8px; } }"""


# ---------------------------------------------------------------------------
# Render řádků matice (server-side — populární appky, crawlovatelné)
# ---------------------------------------------------------------------------

def _cell(val: int) -> str:
    if val == 1:
        return '<span class="yes" title="First-party connector">✓</span>'
    if val == 2:
        return '<span class="comm" title="Community node (npm)">comm</span>'
    return '<span class="no" title="Not in public catalog">·</span>'


def _matrix_rows(apps: list[dict]) -> str:
    out = []
    for a in apps:
        cat = f'<span class="cat">{_html_escape(a["category"])}</span>' if a.get("category") else ""
        cells = "".join(f'<td data-tool="{v}">{_cell(a["support"].get(v, 0))}</td>' for v in TOOLS_ORDER)
        out.append(f'        <tr data-name="{_html_escape(a["name"]).lower()}">\n'
                   f'          <td class="app-col">{_html_escape(a["name"])}{cat}</td>\n'
                   f'          {cells}\n        </tr>')
    return "\n".join(out)


def _th_tools(counts: dict) -> str:
    out = ['        <th class="app-col">Integration</th>']
    for v in TOOLS_ORDER:
        name = {"zapier": "Zapier", "make": "Make", "n8n": "n8n", "pipedream": "Pipedream",
                "activepieces": "Activepieces", "automatisch": "Automatisch", "node-red": "Node-RED"}[v]
        c = counts.get(v)
        cnt = f'<span class="th-count">{c:,}</span>' if isinstance(c, int) else ""
        out.append(f'        <th data-tool="{v}"><span class="th-tool"><img src="{_logo(v)}" alt="{name}">{name}{cnt}</span></th>')
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Client finder JS — fetchne index.json, filtruje, „skryj nástroje co nemají"
# ---------------------------------------------------------------------------

_FINDER_JS = """
/* ── INTEGRATION FINDER ── fetchne index.json, vyhledávání + multi-select +
   režim „skryj nástroje, co nemají všechny vybrané integrace" ── */
(function () {
  var TOOLS = %TOOLS%;
  var NAMES = %NAMES%;
  var box = document.getElementById('finder');
  if (!box) return;
  var input = box.querySelector('#fsearch');
  var sug = box.querySelector('#fsuggest');
  var chipsEl = box.querySelector('#fchips');
  var hideMode = box.querySelector('#fhide');
  var tbody = document.getElementById('ix-body');
  var thead = document.getElementById('ix-head');
  var meta = document.getElementById('ix-meta');
  var APPS = [], selected = [], activeSug = -1;

  fetch('data/integrations/index.json').then(function (r) { return r.json(); })
    .then(function (d) { APPS = d.apps || []; render(); })
    .catch(function () { if (meta) meta.textContent = 'Could not load the integration index.'; });

  function matches(q) {
    q = q.toLowerCase();
    var out = [];
    for (var i = 0; i < APPS.length && out.length < 12; i++) {
      if (APPS[i].n.toLowerCase().indexOf(q) !== -1 && selected.indexOf(APPS[i].n) === -1) out.push(APPS[i]);
    }
    return out;
  }
  function renderSuggest(q) {
    if (!q) { sug.classList.remove('show'); sug.innerHTML = ''; return; }
    var m = matches(q); activeSug = -1;
    sug.innerHTML = m.map(function (a) {
      return '<div data-name="' + esc(a.n) + '">' + esc(a.n) + (a.c ? '<span class="s-cat">' + esc(a.c) + '</span>' : '') + '</div>';
    }).join('');
    sug.classList.toggle('show', m.length > 0);
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function addChip(name) {
    if (selected.indexOf(name) !== -1) return;
    selected.push(name); input.value = ''; renderSuggest(''); render(); input.focus();
  }
  function removeChip(name) { selected = selected.filter(function (n) { return n !== name; }); render(); }

  function render() {
    chipsEl.innerHTML = selected.map(function (n) {
      return '<span class="chip">' + esc(n) + '<button aria-label="Remove" data-rm="' + esc(n) + '">×</button></span>';
    }).join('');

    // které nástroje mají VŠECHNY vybrané integrace (first-party=1, community=2 počítá taky)
    var rows = selected.map(function (n) {
      var a = APPS.find(function (x) { return x.n === n; });
      return a ? a.t : TOOLS.map(function () { return 0; });
    });
    var toolHas = TOOLS.map(function (_, ti) { return rows.every(function (r) { return r[ti] > 0; }); });

    // dim/hide sloupce, co nemají všechny vybrané (jen když je něco vybráno)
    var hide = hideMode.checked && selected.length > 0;
    TOOLS.forEach(function (t, ti) {
      var on = selected.length === 0 || toolHas[ti];
      thead.querySelectorAll('[data-tool="' + t + '"]').forEach(function (el) { el.classList.toggle('dim', !on); el.style.display = (hide && !on) ? 'none' : ''; });
    });

    if (selected.length === 0) {
      meta.innerHTML = 'Type an app above to see which tools support it. The table below shows the most cross-platform integrations.';
      // ukaž default populární tělo (server-rendered zůstává), jen zruš dim
      tbody.querySelectorAll('tr').forEach(function (tr) {
        tr.style.display = '';
        TOOLS.forEach(function (t) { tr.querySelectorAll('[data-tool="' + t + '"]').forEach(function (td) { td.classList.remove('dim'); td.style.display = ''; }); });
      });
      return;
    }

    // postav řádky jen pro vybrané integrace
    var ok = TOOLS.filter(function (_, ti) { return toolHas[ti]; }).map(function (_, i) { return i; });
    var supportingTools = TOOLS.filter(function (_, ti) { return toolHas[ti]; })
      .map(function (t) { return NAMES[t] || t; });
    meta.innerHTML = supportingTools.length
      ? '<strong>' + supportingTools.length + ' / ' + TOOLS.length + '</strong> tools support all ' + selected.length + ' selected: <strong style="color:var(--accent-br)">' + supportingTools.map(esc).join(', ') + '</strong>'
      : 'No single tool covers all ' + selected.length + ' selected integrations as first-party or community.';

    var html = selected.map(function (n) {
      var a = APPS.find(function (x) { return x.n === n; }); if (!a) return '';
      var cat = a.c ? '<span class="cat">' + esc(a.c) + '</span>' : '';
      var cells = TOOLS.map(function (t, ti) {
        var v = a.t[ti], cls = (hide && !toolHas[ti]) ? ' style="display:none"' : (toolHas[ti] ? '' : ' class="dim"');
        var mark = v === 1 ? '<span class="yes">✓</span>' : (v === 2 ? '<span class="comm">comm</span>' : '<span class="no">·</span>');
        return '<td data-tool="' + t + '"' + cls + '>' + mark + '</td>';
      }).join('');
      return '<tr data-name="' + esc(n).toLowerCase() + '"><td class="app-col">' + esc(n) + cat + '</td>' + cells + '</tr>';
    }).join('');
    tbody.innerHTML = html || '<tr><td class="empty" colspan="' + (TOOLS.length + 1) + '">No data.</td></tr>';
  }

  input.addEventListener('input', function () { renderSuggest(input.value.trim()); });
  input.addEventListener('keydown', function (e) {
    var items = sug.querySelectorAll('div');
    if (e.key === 'ArrowDown') { activeSug = Math.min(activeSug + 1, items.length - 1); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { activeSug = Math.max(activeSug - 1, 0); e.preventDefault(); }
    else if (e.key === 'Enter') { if (items[activeSug]) addChip(items[activeSug].getAttribute('data-name')); else if (items[0]) addChip(items[0].getAttribute('data-name')); e.preventDefault(); return; }
    else if (e.key === 'Escape') { sug.classList.remove('show'); return; }
    items.forEach(function (it, i) { it.classList.toggle('active', i === activeSug); });
  });
  sug.addEventListener('click', function (e) { var d = e.target.closest('div[data-name]'); if (d) addChip(d.getAttribute('data-name')); });
  chipsEl.addEventListener('click', function (e) { var b = e.target.closest('button[data-rm]'); if (b) removeChip(b.getAttribute('data-rm')); });
  hideMode.addEventListener('change', render);
  document.addEventListener('click', function (e) { if (!box.contains(e.target)) sug.classList.remove('show'); });
})();
/* ── /INTEGRATION FINDER ── */"""


# ---------------------------------------------------------------------------
# Render stránky
# ---------------------------------------------------------------------------

def _render_html(matrix: dict, site: dict, tools_meta: dict) -> str:
    month_year = _month_year(tools_meta)
    domain = site.get("domain", "wizardcost.com")
    base_path = (site.get("base_path", "") or "").strip("/")
    prefix = f"https://{domain}/{base_path}".rstrip("/") if base_path else f"https://{domain}"
    canonical = f"{prefix}/integrations.html"
    counts = matrix["counts"]
    apps = matrix["apps"]

    total_apps = len(apps)
    popular = [a for a in apps if a["score"] >= POPULAR_MIN_TOOLS][:POPULAR_RENDER]
    total_listed = sum(v for v in counts.values() if isinstance(v, int))

    th = _th_tools(counts)
    rows = _matrix_rows(popular)

    names_map = {"zapier": "Zapier", "make": "Make", "n8n": "n8n", "pipedream": "Pipedream",
                 "activepieces": "Activepieces", "automatisch": "Automatisch", "node-red": "Node-RED"}

    faqs = [
        ("How do you know which tools support an integration?",
         f"Every week an automated audit pulls the complete public app catalog of each tool "
         f"straight from its own source — Zapier, Make, n8n, Pipedream and Activepieces from "
         f"their public APIs, Pipedream and Automatisch from their open-source repos, and "
         f"Node-RED from its community catalogue. We match the same app across tools by "
         f"normalized name. A ✓ means the app is listed in that tool's public catalogue as of "
         f"{month_year}; a blank means it was not found there by name."),
        ("Why is Node-RED shown differently?",
         "Node-RED's catalogue is made of community-published npm modules, not first-party "
         "connectors like the other tools ship. So a Node-RED match is marked <strong>comm</strong> "
         "(community) rather than a first-party ✓ — it means someone has published a community "
         "node for that app, which may be unofficial or partial. Treat it as a starting point, "
         "not a vendor-supported integration."),
        ("An app I use isn't listed — does that mean it's impossible?",
         "Not necessarily. Absence means the app wasn't found in that tool's public catalogue "
         "under the name we searched. Most tools also offer a generic HTTP / webhook / code step "
         "that can talk to almost any API, and apps are sometimes listed under a different name. "
         "Use this as a fast first filter, then confirm on the tool's own site."),
        ("How current is this?",
         f"The catalogue is re-checked weekly and this page regenerates from it. When an app is "
         f"added or removed from any tool, the change is recorded. Last verified {month_year}."),
    ]
    faq_ld = json.dumps({
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"<[^>]+>", "", a)}}
                       for q, a in faqs],
    }, ensure_ascii=False, indent=2)
    faq_html = "\n".join(
        f'    <div class="faq-item">\n      <div class="faq-q" onclick="toggleFaq(this)">{q}</div>\n'
        f'      <div class="faq-a">{a}</div>\n    </div>' for q, a in faqs)

    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "AutomationCost", "item": prefix + "/"},
            {"@type": "ListItem", "position": 2, "name": "Integration finder", "item": canonical},
        ],
    }, ensure_ascii=False, indent=2)

    title = "Integration Finder — Which Automation Tool Supports Your App? | WizardCost"
    desc = (f"Search {total_apps:,} integrations across Zapier, Make, n8n, Pipedream, Activepieces, "
            f"Automatisch and Node-RED. Pick the apps you need and instantly see which tool "
            f"supports them all. Catalog re-checked weekly.")

    finder_js = (_FINDER_JS
                 .replace("%TOOLS%", json.dumps(TOOLS_ORDER))
                 .replace("%NAMES%", json.dumps(names_map)))

    css = _FINDER_CSS + "\n" + _EMAILCAP_CSS

    body = f"""
<div class="wrap">

  <div class="hero">
    <div class="hero-badge">{total_apps:,} apps matched · {len(TOOLS_ORDER)} tools · verified {month_year.lower()}</div>
    <h1>Which automation tool <em>has the integrations you need?</em></h1>
    <p>Search across <strong>{total_listed:,}</strong> catalog listings from all seven tools.
       Add the apps your workflow needs and instantly see which tools cover them — and which
       to rule out. Every catalogue is pulled straight from the source and re-checked weekly.</p>
  </div>

  <div class="finder" id="finder">
    <div class="finder-row">
      <div class="finder-search">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
        <input id="fsearch" type="text" placeholder="Search an app — e.g. Slack, HubSpot, Notion…" autocomplete="off" aria-label="Search integrations">
        <div class="suggest" id="fsuggest"></div>
      </div>
      <label class="finder-mode"><input type="checkbox" id="fhide"> Hide tools that don't have all selected</label>
    </div>
    <div class="chips" id="fchips"></div>
  </div>

  <div class="result-meta" id="ix-meta"></div>

  <div class="legend">
    <span><span class="yes">✓</span> First-party connector</span>
    <span><span class="comm">comm</span> Node-RED community module (npm)</span>
    <span><span class="no">·</span> Not in public catalogue</span>
  </div>

  <div class="table-wrap">
    <table>
      <thead id="ix-head">
        <tr>
{th}
        </tr>
      </thead>
      <tbody id="ix-body">
{rows}
      </tbody>
    </table>
  </div>
  <p class="tbl-note">Showing the {len(popular)} most cross-platform integrations (supported by {POPULAR_MIN_TOOLS}+ first-party tools). Use the search above to look up any of the {total_apps:,} matched apps.</p>

  <div class="disclaimer">
    <strong>How to read this.</strong> A ✓ means the app appears in that tool's public app
    catalogue (pulled from each vendor's own API / repo / catalogue, {month_year}); a blank
    means it wasn't found there <em>by name</em>. <strong>Node-RED</strong> entries are
    community-published npm modules, not first-party connectors — shown as <strong>comm</strong>.
    Counts are catalogue listings, not a measure of how deep each connector is. Apps are matched
    by normalized name plus a curated alias list, so an occasional mismatch is possible — always
    confirm on the tool's own site before committing. This is an independent comparison; all
    product names are trademarks of their respective owners.
  </div>

{_finder_cta("Know the apps — now find the cheapest fit.", "You've got the integrations sorted. Answer 4 quick questions and get the cheapest tool that covers your apps at your real volume in 30 seconds.")}

  <div class="section" id="faq">
    <h2>Frequently asked questions</h2>
    <p>How the integration data is sourced, matched and kept current.</p>
  </div>
  <div class="faq">
{faq_html}
  </div>

{_emailcap("Get an email when a tool adds or drops an integration.",
           "Every change is verified and recorded — one email per confirmed catalogue change.")}
</div>
"""

    from build_pricing import _page_graph_ld, _iso_date  # GEO graf (freshness + identita)
    page_ld = _page_graph_ld(domain, canonical, title.replace("&amp;", "&"), desc, _iso_date(tools_meta))
    head = _head(title, desc, canonical, css, faq_ld, prefix, page_ld=page_ld)
    # breadcrumb jako další JSON-LD blok
    head = head.replace("</head>", f'  <script type="application/ld+json">\n{breadcrumb_ld}\n  </script>\n</head>', 1)

    return (head
            + _nav("integrations", month_year)
            + body
            + _footer(month_year)
            + "\n<script>\nfunction toggleFaq(el) { el.parentElement.classList.toggle(\"open\"); }\n"
            + finder_js
            + _EMAILCAP_JS
            + "\n</script>\n\n<script src=\"app.js\"></script>\n</body>\n</html>\n")


# ---------------------------------------------------------------------------
# Veřejné API
# ---------------------------------------------------------------------------

_AF_NAMES = {"zapier": "Zapier", "make": "Make", "n8n": "n8n", "pipedream": "Pipedream",
            "activepieces": "Activepieces", "automatisch": "Automatisch", "node-red": "Node-RED"}
_AF_DOMAIN = {"zapier": "zapier.com", "make": "make.com", "n8n": "n8n.io", "pipedream": "pipedream.com",
              "activepieces": "activepieces.com", "automatisch": "automatisch.io", "node-red": "nodered.org"}

_AF_CSS = _BASE_HEAD_CSS + """
    .container { max-width: 860px; margin: 0 auto; padding: 0 32px; }
    @media (max-width: 600px) { .container { padding: 0 18px; } }
    .af-search { position: relative; margin: 22px 0 8px; }
    .af-search input { width: 100%; background: var(--surface); border: 1px solid var(--border2); border-radius: var(--radius); padding: 16px 18px; font-family: var(--font); font-size: 17px; color: var(--text); }
    .af-search input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }
    .af-drop { position: absolute; left: 0; right: 0; top: calc(100% + 6px); background: var(--surface); border: 1px solid var(--border2); border-radius: var(--radius); max-height: 340px; overflow: auto; z-index: 30; display: none; box-shadow: 0 14px 44px rgba(0,0,0,.5); }
    .af-drop.on { display: block; }
    .af-opt { padding: 11px 16px; cursor: pointer; display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--border); }
    .af-opt:last-child { border-bottom: none; }
    .af-opt:hover, .af-opt.hl { background: var(--surface2); }
    .af-opt .cnt { color: var(--muted); font-size: 12px; white-space: nowrap; }
    .af-opt mark { background: transparent; color: var(--accent); }
    .af-hint { color: var(--muted); font-size: 13px; margin: 6px 0 0; }
    .af-result { margin: 28px 0 6px; display: none; }
    .af-result.on { display: block; }
    .af-result h2 { margin: 0 0 2px; }
    .af-result .rsub { color: var(--muted); font-size: 13px; margin: 0 0 16px; }
    .af-grid { display: grid; gap: 10px; }
    .af-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; background: var(--surface); border: 1px solid var(--border2); border-radius: var(--radius-sm); padding: 13px 16px; }
    .af-row .nm { display: flex; align-items: center; gap: 10px; font-weight: 600; }
    .af-row img { width: 22px; height: 22px; border-radius: 5px; background: #fff; padding: 1px; object-fit: contain; }
    .af-yes { color: var(--green); font-weight: 700; font-size: 14px; }
    .af-no { color: var(--muted); }
    .af-comm { color: var(--yellow); font-size: 12px; border: 1px solid var(--border2); border-radius: 5px; padding: 2px 7px; }
    .af-tally { color: var(--text2); font-size: 13px; margin-top: 14px; }
"""

_AF_JS = """
(function(){
  var q=document.getElementById('afq'), drop=document.getElementById('afdrop'), res=document.getElementById('afres');
  if(!q) return;
  var hl=-1, matches=[];
  function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function logo(d){return 'https://www.google.com/s2/favicons?domain='+d+'&sz=64';}
  function mark(name,t){var i=name.toLowerCase().indexOf(t);if(i<0)return esc(name);return esc(name.slice(0,i))+'<mark>'+esc(name.slice(i,i+t.length))+'</mark>'+esc(name.slice(i+t.length));}
  function search(term){
    term=term.trim().toLowerCase(); if(!term){drop.classList.remove('on');return;}
    var starts=[],contains=[];
    for(var i=0;i<AF_APPS.length;i++){var l=AF_APPS[i][0].toLowerCase();
      if(l.indexOf(term)===0)starts.push(i); else if(l.indexOf(term)>-1)contains.push(i);
      if(starts.length>=12)break;}
    matches=starts.concat(contains).slice(0,12); hl=-1;
    if(!matches.length){drop.innerHTML='<div class="af-opt"><span class="af-no">No app matches \\u201c'+esc(term)+'\\u201d.</span></div>';drop.classList.add('on');return;}
    drop.innerHTML=matches.map(function(idx){var a=AF_APPS[idx];var have=a[1].filter(function(x){return x===1||x===2;}).length;
      return '<div class="af-opt" data-i="'+idx+'"><span><b>'+mark(a[0],term)+'</b></span><span class="cnt">'+have+'/'+AF_TOOLS.length+' tools</span></div>';}).join('');
    drop.classList.add('on');
  }
  function pick(idx){var a=AF_APPS[idx];q.value=a[0];drop.classList.remove('on');render(a);}
  function render(a){var t=a[1],have=0;
    var rows=AF_TOOLS.map(function(tool,i){var v=t[i],cell;
      if(v===1){have++;cell='<span class="af-yes">\\u2713 Yes</span>';}
      else if(v===2){have++;cell='<span class="af-comm">community</span>';}
      else cell='<span class="af-no">\\u2014</span>';
      return '<div class="af-row"><span class="nm"><img src="'+logo(tool.domain)+'" onerror="this.style.visibility=&quot;hidden&quot;">'+esc(tool.name)+'</span>'+cell+'</div>';}).join('');
    res.innerHTML='<h2>'+esc(a[0])+'</h2><p class="rsub">Integration availability across the '+AF_TOOLS.length+' tools</p><div class="af-grid">'+rows+'</div><div class="af-tally"><b>'+have+'</b> of '+AF_TOOLS.length+' tools integrate with '+esc(a[0])+'.</div>';
    res.classList.add('on');
  }
  function paint(){var os=drop.querySelectorAll('.af-opt');for(var k=0;k<os.length;k++)os[k].classList.toggle('hl',k===hl);var el=drop.querySelector('.af-opt.hl');if(el)el.scrollIntoView({block:'nearest'});}
  q.addEventListener('input',function(){search(q.value);res.classList.remove('on');});
  q.addEventListener('keydown',function(e){
    if(!drop.classList.contains('on'))return;
    if(e.key==='ArrowDown'){hl=Math.min(hl+1,matches.length-1);paint();e.preventDefault();}
    else if(e.key==='ArrowUp'){hl=Math.max(hl-1,0);paint();e.preventDefault();}
    else if(e.key==='Enter'){if(hl>=0&&matches[hl]!=null)pick(matches[hl]);else if(matches.length)pick(matches[0]);e.preventDefault();}
    else if(e.key==='Escape')drop.classList.remove('on');
  });
  drop.addEventListener('mousedown',function(e){var o=e.target.closest('.af-opt');if(o&&o.dataset.i!=null)pick(+o.dataset.i);});
  document.addEventListener('click',function(e){if(!e.target.closest('.af-search'))drop.classList.remove('on');});
})();
"""


def _app_finder_html(matrix: dict, site: dict, tools_meta: dict) -> str:
    """Samostatná stránka app-finder.html — searchbar + dropdown → jeden app → kdo ho má.
    Data inline (žádný fetch); stejné chrome (head/nav/footer) jako integrations.html."""
    month_year = _month_year(tools_meta)
    domain = site.get("domain", "wizardcost.com")
    base_path = (site.get("base_path", "") or "").strip("/")
    prefix = f"https://{domain}/{base_path}".rstrip("/") if base_path else f"https://{domain}"
    canonical = f"{prefix}/app-finder.html"
    counts = matrix["counts"]
    apps = matrix["apps"]
    total = len(apps)
    counts_str = " &middot; ".join(f"{_AF_NAMES[v]} {counts.get(v, 0):,}" for v in TOOLS_ORDER)

    af_apps = [[a["name"], [a["support"].get(v, 0) for v in TOOLS_ORDER]] for a in apps]
    data_js = json.dumps(af_apps, ensure_ascii=False, separators=(",", ":"))
    tools_js = json.dumps([{"name": _AF_NAMES[v], "domain": _AF_DOMAIN[v]} for v in TOOLS_ORDER], ensure_ascii=False)

    title = f"App finder — which automation tool has an app? · {month_year}"
    desc = (f"Type any app — Slack, HubSpot, Notion — and instantly see which of the {len(TOOLS_ORDER)} "
            f"automation tools (Zapier, Make, n8n, Pipedream, Activepieces, Automatisch, Node-RED) integrate with it.")

    body = f"""
<div class="container">
  <div class="hero">
    <h1>Which tool has the app you need?</h1>
    <p class="lead">Type an app — e.g. <strong>Slack</strong>, HubSpot, Notion — and see which of the {len(TOOLS_ORDER)} automation tools integrate with it. {total:,} apps, re-checked weekly.</p>
  </div>
  <div class="section">
    <div class="af-search">
      <input id="afq" type="text" placeholder="Search an app…" autocomplete="off" spellcheck="false" aria-label="Search an app">
      <div class="af-drop" id="afdrop"></div>
    </div>
    <p class="af-hint">{total:,} apps across {len(TOOLS_ORDER)} tools. Start typing.</p>
    <div class="af-result" id="afres"></div>
    <p class="tbl-note">✓ native connector &middot; <span class="af-comm">community</span> Node-RED community module (npm) &middot; — not in the public catalogue &middot; counts: {counts_str}. <a href="integrations.html">Full integration matrix →</a></p>
  </div>
{_finder_cta("Found your app — now find the cheapest tool that has it.", "Answer 4 quick questions and get the cheapest tool that covers your apps at your real volume in 30 seconds.")}
</div>
"""
    from build_pricing import _page_graph_ld, _iso_date
    page_ld = _page_graph_ld(domain, canonical, title.replace("&amp;", "&"), desc, _iso_date(tools_meta))
    head = _head(title, desc, canonical, _AF_CSS, None, prefix, page_ld=page_ld)
    return (head
            + _nav("integrations", month_year)
            + body
            + _footer(month_year)
            + "\n<script>\nvar AF_TOOLS=" + tools_js + ";\nvar AF_APPS=" + data_js + ";\n"
            + _AF_JS
            + "\n</script>\n\n<script src=\"app.js\"></script>\n</body>\n</html>\n")


def build_integrations_page(tools: list[dict], site: dict, tools_meta: dict,
                            *, check: bool = False) -> list[str]:
    """Vygeneruje automation/integrations.html + data/integrations/index.json.

    Vrací jména změněných souborů (nebo co by se v check módu změnilo).
    Když nejsou naškrábané katalogy (INT_DIR prázdný), je no-op."""
    if not INT_DIR.exists() or not (INT_DIR / "zapier" / "latest.json").exists():
        return []
    matrix = build_matrix()
    if not matrix["apps"]:
        return []

    out: list[str] = []
    targets = {
        INT_DIR / "index.json": _index_json(matrix, tools_meta),
        ROOT / "integrations.html": _render_html(matrix, site, tools_meta),
        ROOT / "app-finder.html": _app_finder_html(matrix, site, tools_meta),
    }
    for target, rendered in targets.items():
        existing = target.read_text(encoding="utf-8") if target.exists() else None
        comp = _strip_injected(existing) if (existing is not None and target.suffix == ".html") else existing
        dirty = existing is None or comp != rendered
        if check:
            if dirty:
                out.append(target.name)
        elif dirty:
            target.write_text(rendered, encoding="utf-8")
            out.append(target.name)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Generuj integrations.html + index.json z naškrábaných katalogů.")
    parser.add_argument("--check", action="store_true", help="Nezapisuj; vypiš co by se změnilo (exit 1 pokud out-of-date).")
    args = parser.parse_args()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    site = _load_site()
    tools_meta = data.get("_meta", {})
    result = build_integrations_page(data["tools"], site, tools_meta, check=args.check)
    if args.check:
        if result:
            print(f"[integrations --check] OUT OF DATE: {', '.join(result)} — spusť generátor.")
            return 1
        print("[integrations --check] OK — integrations.html + index.json aktuální.")
        return 0
    print(f"[integrations] zapsáno: {', '.join(result)}" if result else "[integrations] beze změny.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
