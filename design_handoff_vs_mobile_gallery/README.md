# Handoff — vs-pages example · mobilní padding fix · screenshot galerie

**Datum:** 2026-06-11 · **Od:** Claude Design · **Pro:** Claude Code (engineering)

Tři dodávky podle zadání z 2026-06-11 (`docs/vs-pages-brief.md` na branch `vs-pages`
+ `docs/design-backlog.md` na master). Balíček je připraven pro přenos přes repo branch.

---

## 1) `automation/_vs-example.html` — vzorová vs-stránka (Zapier vs Make)

→ patří na **branch `vs-pages`** jako `automation/_vs-example.html`.

Kompletní stránka podle briefu: hero verdikt, cena podle objemu (4 objemy), CTA na
kalkulátor, feature diff (jen rozdílové řádky), pros/cons, FAQ (5 otázek, vzor
`faq-item`/`toggleFaq`), outbound CTA (affiliate + `rel="sponsored"` jen Make),
cross-linky, standardní footer. Styl = automation subsite (accent `#10b981`, stejné fonty).

**Důležité pro generátor:**
- **Verdiktová věta v `.verdict` je ručně psané pole v datech páru** — vkládat doslovně,
  negenerovat ze šablony. Pro Zapier vs Make je napsaná v souboru.
- **Čísla v tabulce jsou aktualizovaná na nový engine** (Zapier Free bez pay-as-you-go):
  1k → $44.99 Professional +ops · 5k → ~$130 · 20k → ~$345 · 100k → ~$1,065
  (Enterprise estimates). Make beze změny ($0/$9/$18/~$45). Odpovídá DEMO datům
  v root `index.html` na masteru — při generování ber čísla z build.py, ne ze souboru.
- Verdikt a FAQ #1 jsou přepočítané na nová čísla (14–24× při placených objemech).
- Žádný JS engine na stránce — jen `toggleFaq`. Head metadata (canonical, og:image PNG,
  FAQPage JSON-LD, GA4) doplňuje build — v souboru je komentář-kotva.
- Cross-linky odkazují i na zatím neexistující `zapier-vs-n8n.html`, `make-vs-n8n.html`,
  `zapier-vs-pipedream.html` — slugy podle search volume si určíte při generování.

## 2) Root `index.html` — fix mobilního paddingu (backlog #1, BUG)

→ patří na **master** (po integraci a testech).

**Příčina potvrzena:** `.hero`, `.demo-section` a `.section` používaly shorthand
`padding: X 0 Y`, který má stejnou specificitu jako `.wrap { padding: 0 32px }`
a je v CSS později → nuloval boční padding na **všech** šířkách (na desktopu to
maskuje `max-width: 1080px`). Na ≤520px pak `.hero-cta { align-items: stretch }`
roztáhl CTA buttony od kraje ke kraji.

**Fix (minimální, longhand):** hledej komentáře `FIX(mobile-edges)` — 4 místa:
- `.hero` → `padding-top: 104px; padding-bottom: 56px;`
- `.demo-section` → `padding-top: 64px;`
- `.section` → `padding-top: 84px;`
- `@media ≤620px` `.hero` → `padding-top: 68px; padding-bottom: 40px;`

Boční odsazení tím všude přebírá `.wrap` (32px desktop / 18px ≤760px). Prošlo
celou homepage na 375px: hero CTA, stats řádek, demo karta + vol-chips, wizards
grid, edge-rows, footer — nic interaktivního není blíž než 18px od hrany.
Ověřit `calc-test/scout-mobile-edges.js` (375px sweep) před deployem.

**Pozor:** soubor vychází z aktuálního masteru včetně GA4 bloku a DEMO dat —
při integraci diffni proti masteru, změny jsou jen označená 4 CSS místa + galerie (bod 3).

## 3) Galerie screenshotů nástrojů (backlog #2) — v témže `index.html`

Sekce „Under the hood" mezi wizard gridem a „Why WizardCost", ohraničená komentáři
`GALLERY:HTML:START/END`; CSS blok `GALLERY:CSS:START/END`. Je integrovaná rovnou
ve fixnutém `index.html`, takže ji vidíte v kontextu — pokud ji chcete nasadit
později/zvlášť, oba bloky se vyjmou čistě.

- **Desktop-only:** ≤1023.98px `display: none` (mobil už je hustý, viz backlog #1).
- **Žádný layout shift:** `width`/`height` atributy + `aspect-ratio: 1600/1000` na `img`.
- **Výkon:** `loading="lazy"` + `decoding="async"`, sekce je hluboko pod foldem —
  nesoutěží s hero LCP. Reálné soubory exportujte jako WebP/AVIF 1600×1000.
- **Obrázky:** `assets/shots/*.svg` jsou **placeholdery** (pruhovaný vzor + popisek).
  Nahraďte vlastními capturami z test účtů nebo oficiálními press/brand assety —
  faceless, žádní lidé, žádný stock. Zachovejte názvy souborů, nebo přepište 4 `src`:
  `n8n-editor` · `make-scenario` · `zapier-editor` · `pipedream-workflow`
  (výběr = 4 nástroje z homepage DEMO). Kontext je srovnávací review — logo +
  product UI OK, nesmí působit jako endorsement.
- Karty mají decentní „browser chrome" lištu s popiskem capture — drží to vizuální
  jazyk demo karty, ne marketingové rendery.

---

## Co v balíčku NENÍ (záměrně)
- Head metadata, canonical, og/twitter, GA4, FAQPage JSON-LD — práce buildu/engineeringu.
- og:image pro vs-stránky — až bude, PNG 1200×630 (zatím sdílený automation/og-image.png).
- Reálné screenshoty nástrojů — potřebují živé test účty, viz bod 3.

## Soubory
```
design_handoff_vs_mobile_gallery/
├── README.md                        ← tento soubor
├── index.html                       ← root homepage: padding fix + galerie (→ master)
├── assets/shots/                    ← 4 SVG placeholdery (→ master, nahradit WebP)
└── automation/
    ├── _vs-example.html             ← vzorová vs-stránka (→ branch vs-pages)
    └── favicon.svg                  ← jen pro lokální náhled, v repu už je
```
