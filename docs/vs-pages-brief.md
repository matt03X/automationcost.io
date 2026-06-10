# Brief: X-vs-Y pricing stránky (pro Claude Design)

Cíl: šablona pro programatické srovnávací stránky typu **„Zapier vs Make: Pricing Comparison"**.
Ze 7 nástrojů vygeneruje build.py až 21 párových stránek — největší nevyužitá SEO páka webu
(keywords s nejvyšším nákupním intentem). Design dodá **jednu hotovou vzorovou stránku**,
engineering ji převede na šablonu + generátor.

## Co dodat

Jeden soubor `automation/_vs-example.html` — kompletně nadesignovaná stránka pro pár
**Zapier vs Make** s reálnými daty níže. Podtržítko v názvu = build ji ignoruje (není
v sitemap, nedostane analytics). Handoff **přes tuto branch (`vs-pages`), ne chatem**
(chat rozbíjí kódování — viz CLAUDE.md).

## URL a meta vzory

- URL: `automation/zapier-vs-make.html` (pořadí slugů podle search volume, určuje engineering)
- Title: `Zapier vs Make: Pricing & Cost Comparison 2026 | AutomationCost.io`
- H1: `Zapier vs Make — which costs less?`
- Canonical: `https://wizardcost.com/automation/zapier-vs-make.html`
- og:image: zatím sdílený `https://wizardcost.com/automation/og-image.png` (PNG 1200×630, ne SVG)
- Nav: standardní automation nav (14 stránek), aktivní položka **Compare**

## Povinné bloky stránky (shora dolů)

1. **Hero verdikt** — jedna věta s vítězem podle kontextu, ne absolutně
   („Make is 8–17× cheaper per operation; Zapier wins on integration count — 7,000+ vs 2,000+").
2. **Cena podle objemu** — tabulka 4 objemů, oba nástroje, levnější zvýrazněn.
   Statická data z buildu (žádný JS engine na stránce!). Reálná čísla pro Zapier vs Make
   (3 workflows, monthly, nejlevnější plán):

   | ops/měsíc | Zapier | plán | Make | plán |
   |---|---|---|---|---|
   | 1 000 | $25 | Free +ops | **$0** | Free |
   | 5 000 | ~$95 | Enterprise (estimate) | **$9** | Core |
   | 20 000 | ~$245 | Enterprise (estimate) | **$18** | Core +ops |
   | 100 000 | ~$760 | Enterprise (estimate) | **$45** | Enterprise (estimate) |

   `~` = odhad custom tieru (konvence webu: tilda + „estimate" + disclaimer).
3. **CTA na kalkulátor** — „Get the number for *your* exact volume" → calculator.html
   (stejný vzor jako results-next-cta na kalkulátoru).
4. **Feature diff** — JEN řádky, kde se nástroje liší (self-host, code steps, GDPR,
   integrations, free tier, overage model…). Shodné řádky vynechat nebo sbalit.
5. **Pros/cons** obou nástrojů (data existují per-role v tools.json / TOOL_WHY).
6. **FAQ 4–5 otázek** (accordion pattern `faq-item`/`toggleFaq` z pricing stránek) —
   např. „Is Make cheaper than Zapier?", „What does an operation cost on each?",
   „Can I self-host either?". Engineering doplní FAQPage JSON-LD se stejným zněním.
7. **Outbound CTA** — pravidla: affiliate link + `rel="sponsored"` + „Try free →" má
   **jen Make**; ostatní nástroje plain link + `rel="noopener"` + „Visit →".
8. **Cross-linky** — na obě `*-pricing.html` stránky, compare.html a 2–3 další vs-stránky.
9. **Footer** — standardní (verified month, privacy/terms/affiliate disclosure).

## Data k dispozici (tools.json, vkládá build)

Per nástroj: `name, tagline, plans[{name, monthlyUsd, opsIncluded, workflowLimit}], overage,
integrations, selfHostable, aiFeatures, license, freeOps, maxSteps, timeout, logHistory,
gdprFriendly, multiUser, apiAccess, webhooks, codeSteps, pros/cons, homepage, affiliateUrl,
hasAffiliate`. Spočtená cena při libovolném objemu = Python port enginu (root build.py).

## Pasti (z CLAUDE.md — neopakovat)

- Nikdy literál `</head>` v komentáři/stringu (GA4 injektor vkládá před první výskyt).
- og:image jen PNG. Encoding UTF-8, žádný chat přenos.
- Vizuální styl = automation subsite (zelený accent #10b981, tmavé pozadí, stejné fonty).
