# Datový kontrakt: `history.json` → Price History stránky

**Od Claude Code (engine/data). Pro Claude Design.** Čte se spolu s `_BRIEF-design-history-pages.md`.

Tohle je závazný popis tvaru dat, edge-casů a render pravidel. Brief popisuje *záměr*; tenhle dokument popisuje *co v JSON skutečně je* — kde se liší, platí tenhle dokument. Layout nech na sobě; čísla, tvar dat a co se (ne)smí renderovat řeším já.

---

## Kanonická vendor paleta (SCHVÁLENO 2026-06-13 — oficiální brand barvy)

Tyhle barvy jsou **kanon napříč celým webem** (zatím nikde jinde definované — tahle history sada je zavádí). Ověřeno proti oficiálním zdrojům; owner zvolil věrnost brandu. Engine je vkládá z tohoto seznamu, ne z placeholderů v mocku.

| `slug` | hex | zdroj |
|---|---|---|
| `zapier` | `#FF4F00` | brand.zapier.com — „Zap Orange" (design trefil ✓) |
| `n8n` | `#EA4B71` | n8n.io/brandguidelines — „Mandy" (design trefil ✓) |
| `make` | `#B02DE9` | Make „Electric Violet" — **změna oproti mocku** (`#6d5dfc` → `#B02DE9`) |
| `pipedream` | `#105ed5` | logo SVG `fill` na pipedream.com — **změna oproti mocku** (`#00b46e` zelená → `#105ed5` modrá; PD rebrandoval na modrou) |

Pozn. pro Design: mock měl Make modrofialovou a Pipedream zelenou. Owner rozhodl jet oficiální brand → Make je teď sytě purpurová, Pipedream modrá. Pokud to v editorial paletě vizuálně drhne (např. PD modrá vs. akcentová zelená skinu `--acc #10b981`), řekni — vyřešíme kontrastem/tónem, ne návratem k neoficiální barvě. Pro každý slug si urči i ztlumenou variantu (sekundární plán, sparkline) sám.

---

## Top-level tvar

```
{ "_meta": {...}, "vendors": [ {vendor}, … ] }
```

- `_meta.baseline_until` (`"2026-06-12"`) — hranice bootstrap-éry; data před ní jsou audit, ne vendor changelog. Pro stránku není nutné zobrazovat, ale nepleť s `trackedSince`.
- `_meta.last_reviewed` (`"2026-06-13"`) — datum poslední lidské revize. **Tohle je `{date}` do share-card footeru** ("source: Wayback archive · {date}"), ne dnešní datum.
- `_meta.method` — jednou větou metoda; vhodné jako tooltip / "How we track this" patička. Doslovně, neparafrázovat.
- `_meta.conventions` — slovník hodnot (viz `type` níže). Needituj texty, jsou to popisky pro tebe.

## Tvar `vendor`

| pole | typ | význam pro layout |
|---|---|---|
| `slug` | string | stálý klíč → **stálá barva per vendor napříč webem** (zapier/make/n8n/pipedream) |
| `name` | string | display |
| `trackedSince` | `"YYYY-MM"` | levý okraj časové osy pro tohoto vendora — **NE společný pro všechny** (viz edge 1) |
| `currency` | string | `"USD"` nebo `"USD→EUR"` (n8n) — viz edge 5 |
| `summary` | string | hlavní věta stránky/řádku; doslovně, je to ode mě. Z ní vychází i share titulek. |
| `series` | objekt `{ planName: [point] }` | data pro step chart |
| `events` | pole `{event}` | anotace + timeline |

## Tvar `point` (v `series`)

```
{ "date": "YYYY-MM" | "YYYY-MM-DD", "usd": number | null }
```

- `date` má **smíšenou granularitu**: většinou `YYYY-MM`, ale přesně bisectnuté zlomy mají `YYYY-MM-DD` (n8n `2025-08-07`). Parser musí umět obojí. Měsíc renderuj jako 1. den měsíce.
- `usd` = face value jak se zobrazila v archivu, **bez FX přepočtu**. U n8n jsou to čísla, která jsou na živé stránce dnes v €, ale historicky v $ — viz edge 5.
- `usd: null` = **plán ukončen k tomuto datu** (discontinued) — viz edge 2. NIKDY to nekresli jako pád na nulu.

## Tvar `event`

```
{ "date": …, "type": …, "priceChange": bool, "title": str, "detail": str, "evidence": [url] }
```

- `title` — krátký, jde přímo do anotace v grafu / řádku timeline. Doslovně.
- `detail` — delší kontext, expand/tooltip. Doslovně.
- `evidence` — pole archive.org URL (před/po snapshot). **Může být prázdné `[]`** → viz edge 3.
- `priceChange` — viz edge 4. V tomhle datasetu je **u všech eventů `false`** a to je celá pointa stránky.

---

## `type` — 6 hodnot (brief uváděl 4; řiď se tímhle)

| `type` | co to je | navrhovaný vizuální signál |
|---|---|---|
| `price` | headline cena plánu se pohnula | (v datasetu zatím NEEXISTUJE — ale styl připrav, ať je stránka připravená, až přijde) |
| `limits` | změna kvót/limitů, cena beze změny | n8n 2025-08-07, Pipedream free 300→100 |
| `plan-launch` | nový plán přibyl | Pipedream Connect |
| `plan-discontinued` | plán zmizel | (značí se přes `usd:null` v series; jako `type` zatím není samostatný event) |
| `packaging` | přejmenování/přebalení, ceny stejné | Zapier Pro→Professional, n8n annual-only |
| `catalog` | nový add-on mimo náš scope | Zapier AI Agents |
| `gap` | archiv nemá strojově čitelná čísla pro okno | viz edge 3 |

Pozn.: `plan-discontinued` je v `conventions` deklarovaný, ale aktuálně se discontinue vyjadřuje datovým bodem `usd:null` v `series`, ne samostatným eventem. Ošetři obě cesty.

---

## EDGE CASY — tady se rozbije naivní layout

**1. Časová osa NENÍ společná pro všechny vendory.** `trackedSince` je per vendor: Zapier/Pipedream 2024-06, Make 2025-02, n8n 2025-03. Na index sparkline a detail grafu používej osu daného vendora. Pokud někdy budeš dělat společný overlay, zarovnej na nejstarší (`2024-06`) a u mladších nech vlevo prázdno — nedokresluj data, která nemáme.

**2. Discontinued = `usd:null`, čára KONČÍ.** n8n `"$120 tier": [{2025-03, 120}, {2025-08-07, null}]`. Vykresli: horizontála na $120 od 2025-03 do 2025-08-07, pak **značka "discontinued" a konec** — žádná vertikála dolů, žádný pád na nulu. (Brief sekce 4 to chce taky — tady je to potvrzené tvarem dat.)

**3. `gap` event má `evidence: []` → NEKRESLI "evidence ↗" odkaz.** Make 2024-06, Pipedream 2026-02. Prázdné `evidence` = renderuj event jako neutrální šedý marker "no archive data" **bez** odkazu (jinak vznikne mrtvý link). Obecné pravidlo: odkaz "evidence ↗" renderuj **jen když `evidence.length > 0`**, a vyrenderuj tolik odkazů, kolik je v poli (typicky 2 = před/po).

**4. `priceChange: false` u VŠECH eventů je feature.** Celá stránka je důkaz "ceny se nehnuly". Doporučení: `priceChange:false` eventy stylově odliš jako "no price change" (klidná/šedá anotace), ať vizuálně nesplývají s reálnou cenovou změnou. Až přijde první `priceChange:true`, ten musí vyčnívat (akcentová barva). Nestav layout tak, že `priceChange:true` je nemyslitelný.

**5. n8n currency `"USD→EUR"`.** Čísla v `series` jsou face values; symbol se na živé stránce změnil z $ na € se stejnými čísly, datum přechodu neznáme. Pro graf: **použij neutrální číslo + poznámku** (summary to vysvětluje doslovně). Nepřepočítávej FX, nehádej datum. Nejbezpečnější: osa bez měnového symbolu + label "figures as shown; $→€ at undetermined date" u n8n.

**6. Klesající quota série je legitimní (Pipedream "Free credits/mo" 300→100).** Tohle NENÍ cena, je to limit — jiná jednotka (credits/mo). Pokud ji dáš do stejného grafu jako ceny, **musí mít vlastní osu/panel nebo jasný unit label**, jinak to čte jako "cena spadla". Doporučuju ji vést jako samostatnou stopu/small-multiple "limits", ne míchat s cenovými řadami.

**7. Série startující uprostřed okna** (Pipedream Connect od 2025-04, n8n Business od 2025-08-07). Čára začíná v den vzniku, vlevo od něj nic — nedokresluj zpětně.

**8. Jednobodové ploché série = většina dat.** Plán s jediným bodem (`Professional: [{2024-06, 19.99}]`) znamená "platí od trackedSince dodnes". Vykresli jako **plnou horizontálu přes celé okno až k `last_reviewed`**, ne jako osamělý bod. Brief sekce 2 to chce zvýraznit jako trust signál ("stable since 2024" badge).

---

## Render pravidla (shrnutí pro QA)

- [ ] Step chart (H/V segmenty), nikdy diagonála.
- [ ] Jednobodová série → horizontála přes celé okno do `last_reviewed`.
- [ ] `usd:null` → čára končí značkou discontinued, žádný pád na 0.
- [ ] "evidence ↗" jen když `evidence.length>0`; tolik odkazů, kolik je v poli.
- [ ] `gap` event = neutrální marker bez odkazu.
- [ ] Per-vendor osa od `trackedSince`; nedokreslovat data před ním.
- [ ] Stálá barva per `slug` napříč webem.
- [ ] Quota série (credits) odděleně od cen / vlastní jednotka.
- [ ] Share card: titulek = pointa ze `summary`; footer date = `_meta.last_reviewed`.
- [ ] Žádný text/číslo needitovat — `summary`/`title`/`detail` jdou doslovně z JSON.

## Co je MOJE odpovědnost (ne tvoje)

Všechna čísla, fakta, evidence URL, `summary`/`title`/`detail` texty, posun `baseline_until`/`last_reviewed`, klasifikace eventů. Když narazíš na číslo nebo formulaci, co podle tebe vypadá špatně — **napiš mi, needituj.** Já to ověřím proti wayback auditu (`calc-test/wayback/<vendor>/verdict.md`) a opravím u zdroje.

## Co je TVOJE odpovědnost

Layout, vizuální systém, step-chart geometrie, anotační styl, index vs detail struktura, share-card design, dark-mode barvy, editorial skin. Nabídka z briefu trvá: pokud chceš skin-neutrální SVG step-chart skeleton s token barvami jako odrazový můstek, řekni a předpřipravím ho.
