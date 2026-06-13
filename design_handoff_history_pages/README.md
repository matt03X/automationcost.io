# Handoff — Price history stránky (editorial data-viz)

**Od:** Claude Design → **Pro:** Claude Code · **branch:** `design/history-pages`

Sada „price history" v editorial/data-journalism skinu. Trust flex, ne ceník:
„ověřujeme proti archivu, tady je přesně co se (ne)změnilo, s odkazem na důkaz."

## Soubory
- `history-index.html` → `/automation/history.html` — přehled všech vendorů: stat band
  (0 core hikes / 30 mo / N changes), řádky vendorů s mini step-sparklinou + „stable since"/
  „N changes" badge, odkaz na detail. Řádky čte z `#history-index-data` JSON bloku.
- `_history-detail-n8n.html` → **vzor** pro detail per vendor (`/automation/history/{slug}.html`).
  Full step chart + event timeline s evidence odkazy. n8n je ukázka; generuj všechny 4 ze stejné
  šablony jako provider stránky.

## Struktura (odsouhlaseno): detail = SAMOSTATNÁ stránka
- Index `/automation/history.html` → detaily `/automation/history/{slug}.html`
  (slug pořadí dle vašich konvencí). Detail samostatně kvůli share asetu (vlastní URL + og).
- Prolink: history (dlouhodobý vizuál) ↔ changelog (textový log) — oba směry.

## ⚠ Data placeholder — finální z history.json (jako provider/scatter)
- Markery: `HISTORY_INDEX_DATA:START/END` (index) a `LLM_…`→ u detailu data v JS (k převodu na
  stejný `#…-data` blok při integraci). Build naplní z `automation/data/history.json` + parity test.
- Per vendor z history.json: `series` (cena per plán v čase — step), `events` (datum, typ
  limits/plan-launch/packaging/gap, **evidence URL**), `summary`, `trackedSince`, `changeCount`, currency.
- **Krok = horizontála (cena platí) + vertikála (den změny)** — NIKDY diagonála (lhala by o
  postupném poklesu). Plochá čára = „stable" feature, zvýraznit.
- **Discontinued plán** (n8n $120) končí značkou ×, nepadá na nulu.
- Model/plán bez archivního důkazu nevykresluj.

## Chart konvence (z research A7 — dodrženo)
1. Step chart, ne line. 2. Ploché čáry zdůraznit jako trust signál + „no change" badge.
3. Anotace událostí přímo v grafu (tečka na schodu + popisek + „evidence ↗"). 4. Discontinued = ×.
5. Stálé barvy per vendor napříč webem (Make #6d5dfc, Zapier #ff4f00, n8n #ea4b71, Pipedream #00b46e
   — potvrď/uprav dle brand konvence). 6. Evidence odkazy ven na archive.org, `rel="noopener"` — záměrné, neodstraňovat.

## Share asset
- Detail i index počítají se statickým exportem **1200×675** + **4:5** mobil. Titulek = věta s pointou
  („n8n hasn't changed its core price since 2024"), watermark „wizardcost.com · source: Wayback archive · {date}".
  Faceless distribuce (r/automation). og:image PNG 1200×630.

## Co řeší engineering, ne design
- Naplnění JSON bloků z history.json + parity test · fyzické URL/routing detailů ·
  head metadata, og:image, statický export pipeline · finální evidence URL (archive snapshoty).

## Pravidla (working agreement, CLAUDE.md)
- Vizuál/CSS/layout/skin/ne-faktické copy = laděno volně → preview.
- Čísla, ceny, datumy událostí, evidence tvrzení, history.json = **engineering**, v mocku placeholder.
- Faceless. Branch `design/history-pages` → preview → owner OK → produkce.
