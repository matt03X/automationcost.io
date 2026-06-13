# WizardCost — pravidla repa

Umbrella web **wizardcost.com** (GitHub Pages z `master`, CNAME v rootu — push = deploy, CDN cache ~10 min).
Root = homepage WizardCost. `/automation/` = AutomationCost (kalkulátor, compare, pricing stránky, changelog).
`/llm/` = LLMCost (wizard #2 — kalkulátor LLM API cen, compare, 6 provider stránek, changelog; LIVE od 2026-06-12). Každá úroveň má vlastní `build.py` + `data/`.
LLM zdroj pravdy = `llm/data/models.json` (ceny ověřené scoutem, dumpy v calc-test/llm-pricing-dumps/), marker blok `DATA:MODELS:START|END`, engine přímo v `llm/index.html` (cost(): per-model cached ceny, cache gating per use case, batch jen ověření provideři).
LLM provider stránky (`llm/<provider>-pricing.html`, slugy gemini/grok = produkt, ne provider) jsou **CELÉ generované** — `build_provider_pages()` v llm/build.py ze šablony `llm/_provider-template.html` (mimo sitemap); poznámkové karty (caching/batch/context) se generují z models.json → v1.1 backfill je aktualizuje sám. Nikdy needitovat vygenerované soubory ručně. Capture action = konstanta `EMAILCAP_ACTION_LLM` v llm/build.py — OSTRÁ od 2026-06-12: MailerLite formulář „LLM price alerts" id 190087424470157211 → skupina `price-drop-alerts-llm` id 190087503473018215 (env `MAILERLITE_GROUP_LLM` v engine/.env pro send skript `--site llm`). Stejná action ručně v EMAILCAP blocích na llm/index.html (wizard, pod results footnote — launch review blocker 2026-06-12) a llm/changelog.html — měnit synchronně. LLM alerty = oddělený seznam od automation (slib disclosure je scoped per skupina).

## Zdroj pravdy a generované bloky

- **`automation/data/tools.json` je JEDINÝ zdroj cenových dat.** Root `data/tools.json` neexistuje záměrně (smazán kvůli drift hazardu) — neobnovovat.
- Bloky mezi markery se **nikdy needitují ručně** — přepisuje je build:
  - `/* DATA:TOOLS:START|END */` v `automation/calculator.html` + `compare.html` → `automation/build.py`
  - `/* DATA:DEMO:START|END */` v root `index.html` (hero price demo) → root `build.py` (čte automation data)
  - `/* DATA:CHANGELOG:START|END */` v `automation/changelog.html` → `automation/build.py` (generuje z **git historie** tools.json)
- Po změně tools.json spusť **oba** buildy: `python automation/build.py` i `python build.py` (root), commitni výsledek. `--check` = CI guard (exit 1 při zastaralých blocích).
- **X-vs-Y stránky** (`automation/<a>-vs-<b>.html`) jsou **CELÉ generované** — `build_vs_pages()` v automation/build.py z tools.json (čísla přes root `cheapest_monthly`, import — žádná třetí kopie enginu) + `automation/data/pairs.json` (editorial: verdikt/stripNote/whyLoser/faq — ručně psané, vkládané doslovně; design navrhuje, owner schvaluje). Nikdy needitovat vygenerované soubory ručně. Pořadí slugů v URL: zapier > make > n8n > pipedream > activepieces > automatisch > node-red. Cross-linky generátor omezuje na existující páry. Vzor šablony: `_vs-example.html` (mimo sitemap).
- **Pořadí u cenových změn:** changelog/RSS se generují z **git historie** tools.json → nejdřív commitni samotný tools.json, pak teprve buildy (jinak nový diff v changelogu nebude). Cenová změna se propisuje i do ručních textů (meta descriptions, FAQ, tabulky, TOOL_WHY v kalkulátoru, BEST_FOR v compare) — po změně grepni staré hodnoty napříč stránkami. Ověřování drift reportu: `calc-test/scout-vendor-pricing.js` / `scout-vendor-detail.js` (Playwright čte oficiální ceníky).
- Changelog vzniká z git diffů tools.json → do tools.json patří jen **ověřené** změny. **Oprava našich dat ≠ vendor změna**: `data/changelog-overrides.json` (`baseline_until`) vylučuje bootstrap-éru diffy z changelogu i feedů — Wayback audit 2026-06-12 prokázal, že záznamy z 11.–12. 6. byly korekce chybných výchozích dat (Zapier $19.99 stabilní od 2024, Pipedream 2k/10wf od 2025-04, n8n limity zrušeny už 2025-08-07). Skutečná data vendor změn s archive evidencí patří do history vrstvy (wayback backtesting, calc-test/wayback/). Baseline posouvat jen s auditním důkazem. Drift report ze scraperu (`automation/data/drift-report.md`, netrackovaný) = neověřené nálezy, ne potvrzená fakta. Datum commitu = veřejné datum záznamu v changelogu.
- Při změně cen aktualizuj i `_meta.last_reviewed`, nav badge „Updated <Month Year>" na stránkách **a sentinely v `scripts/price-watch.js`** (jinak druhý den falešný poplach).
- **Denní hlídač cen:** `.github/workflows/price-watch.yml` (cron 06:00 UTC) spouští `scripts/price-watch.js` — sentinel check oficiálních ceníků proti tools.json (nízkošumový: hlídá jen naše čísla, marketing změny ignoruje; automatisch inverzně — alert, kdyby cena znovu byla veřejná). Fail = GitHub mail ownerovi → ověřit `node calc-test/verify-pricing-live.js <slug>` → revize dat. Nové plány sentinely nechytí → měsíční deep audit verify-pricing-live.js zůstává.
- **Denní cenový AUDIT (vrstva důkazů + historie):** `.github/workflows/price-audit.yml` (cron 06:30 UTC) spouští `scripts/price-audit.js` — stáhne všech 6 ceníků a uloží do `automation/data/audit/<vendor>/<datum>.json` (normalizované ceny, vždy) + `<datum>.html.gz` (syrové HTML, gzip, **jen poprvé nebo při změně** — repo by jinak rostlo ~1 GB/rok). Zdiffuje proti poslednímu předchozímu snapshotu → `changes-<datum>.json` + append do `price-history.jsonl` (= zdroj grafů o vývoji cen). Workflow změny **commitne** zpět (`contents: write`). **Volume-based ceníky se scrapují CELOU maticí:** Zapier = inline JSON v HTML (`{planType,tasks,amount,interval}`, monthly i annually, ~35+64 bodů); Make = JS slider (`input[type=range]`, 19 pozic 10k→8M, ceny generuje lokálně bez API → projet pozice nastavením `.value`+input event; přepínač monthly/annually = div „Pay monthly/annually"; objem z pevné sekvence `MAKE_TIERS`, ne z DOM nadpisu). Ostatní 4 jsou fixní plány → jen HTML + hrubý parse `$N`. **Audit = EVIDENCE, ne zdroj pravdy** — tools.json updatuje člověk po revizi change reportu (stejný princip jako wayback audit / drift-report). Playwright se v CI instaluje do `/tmp/pw` a běží přes `NODE_PATH` (vzor z price-watch.yml); lokálně `NODE_PATH=<calc-test>/node_modules node scripts/price-audit.js`. **POZOR:** node `fetch` má v tomhle prostředí rozbité TLS → i Zapier (jinak čistý HTTP) se tahá přes Playwright `page.goto`.

## Cost engine (automation/calculator.html)

- `calcCost`: custom/„contact sales" plány (`monthlyUsd: null`, flag `custom: true` z buildu) se oceňují odhadem — kotva = největší veřejný cloud plán, škálování exponentem **0.7** (kalibrováno na veřejný Zapier ceník), minimum 1.3× kotvy, zaokrouhlení na $5. Odhad se použije, když veřejné plány objem nepokryjí, nebo nad 2× kotvy, když je levnější než lineární overage (čisté `min()` → cenová křivka je monotónní). Odhady se zobrazují `~$X` + „estimate" + disclaimer.
- **Overage je per-tool s per-plan overridem:** volitelný klíč `overage` na plánu v tools.json přebíjí tool-level; `null` = plán nemá pay-as-you-go a engine ho při překročení `opsIncluded` přeskočí (Zapier Free). Logika žije na **4 místech** — calcCost (calculator), cheapestPlan (compare), cheapest_monthly (root build.py), render_plan (oba build.py) — měnit synchronně. Cena s overagem se zaokrouhluje na centy ($19.99 + $25 jinak dá 44.9899…). POZOR: changelog plan-level overage záměrně nediffuje (oprava našeho modelu ≠ změna vendor ceníku) — případnou reálnou změnu vendor PAYG zapiš do changelogu ručně úpravou tool-level overage.
- `estimateVolumeBudget`: workflow multiplikátor = `clamp((Σ defaultOps / 5000)^0.8, 0.5, 5)` — záměrně **monotónní** (přidání workflow nikdy nesníží odhad) a **nezávislý na pořadí** kliknutí. Neměnit bez spuštění test sady.
- **Python port** enginu žije v root `build.py` (`cheapest_monthly`) kvůli generování DATA:DEMO. Při změně JS enginu uprav i port — paritu hlídá `calc-test/verify-demo.js` (musí být 16/16).
- `goStep(4)` re-estimuje slidery jen při změně profilu (signature guard) — ruční úpravy uživatele přežívají navigaci.

## Testy (`../../calc-test`, mimo repo)

| Skript | Kdy spustit |
|---|---|
| `verify-demo.js` | po každé změně enginu, dat nebo Python portu (parita DEMO ↔ JS engine) |
| `test-ops-estimate.js`, `test-200-firem.js` | po změně estimate matematiky (plausibilita doporučení, monotonie, pořadí) |
| `test-smoke-flow.js` | po změně wizardu (end-to-end přes DOM stub) |
| `test-share-restore.js` | po změně share URL / restore logiky kalkulátoru (round-trip, resume banner, validace) |
| `test-homepage-smoke.js`, `test-changelog-smoke.js` | po změně homepage dema / changelogu |
| `e2e-live.js` | po deployi (Playwright proklik živého webu, screenshoty do `calc-test/screenshots/`) |
| `check-ui-live.js` | po změně nav/headeru (dropdown Pricing Guides, logo →`/`, favicon — live) |
| `check-jsonld.js` | po změně head sekcí (validita JSON-LD bloků) |
| `test-vs-pages.js` | po změně pairs.json, tools.json nebo vs šablony (JSON-LD 1:1, affiliate pravidla, čísla z enginu, per-řádkové cheap, cross-linky) |
| `test-llm-engine.js` | po změně llm/index.html enginu nebo models.json (ruční kontrolní příklady, cache/batch gating; `--table` = referenční tabulka pro design) |
| `test-llm-provider-pages.js` | po změně models.json, llm/build.py nebo _provider-template.html (ceny/≈$/mo 1:1 s enginem, žádné sloty, cross-linky, EMAILCAP; `--launch` = REPLACE_ME action je FAIL — pustit v launch checklistu) |
| `check-llm-links.js` | po změně nav/odkazů na llm stránkách (žádný mockup placeholder href="#", relativní cíle existují) — poučení z launche: mrtvé nav odkazy na index+changelog |
| `verify-pricing-live.js` | plošný audit tools.json proti oficiálním ceníkům (Playwright; dumpy do `vendor-pricing-dumps/` = evidence, verdikt dělá člověk) — měsíčně a před každou cenovou revizí |
| `check-jsonld-pricing.js` | po ruční editaci JSON-LD na pricing stránkách (parse všech bloků) |

## Email capture (price-drop alerts)

- Blok mezi `EMAILCAP:CSS|HTML|JS START/END` anchory žije na 3 místech: calculator.html, changelog.html, šablona vs-stránek v automation/build.py (`EMAILCAP_ACTION`). Měnit synchronně.
- Backend = **MailerLite** (účet ownera wizardcost.test@gmail.com, sender alerts@wizardcost.com přes Cloudflare Email Routing). Form action + povinná skrytá pole `ml-submit=1`, `anticsrf=true`. Double opt-in zapnutý.
- **Disclosure „Price-change alerts only. No newsletter, unsubscribe anytime." je závazek ownera (2026-06-11) — NEMĚNIT a na seznam NIKDY neposílat newsletter bez nového souhlasu subscriberů.**
- **Automatizované testy NIKDY nesubmitují formulář** (= reální subscribeři + DOI maily). Live testy kontrolují jen přítomnost bloku/action URL.
- **Dva RSS feedy** (build_feed): `feed.xml` = plný changelog (RSS čtečky); `alerts.xml` = JEN ceny + limity plánů (`_is_alert_entry` vylučuje Integrations) → zdroj MailerLite RSS kampaně. Nikdy nemířit kampaň na feed.xml — porušila by slib „price-change alerts only". Kampaň: denně 9:00 UTC, „New posts" ON.
- **Rozesílka alertů = `python scripts/send_price_alerts.py`** (po commitu a deployi cenové revize): čte alerts.xml, GUID stav v gitignored `.alerts-sent.json`, renderuje `scripts/email-template.html` (design), vytvoří kampaň přes MailerLite API; bez flagu jen draft, `--send` odešle. Token z env/`engine/.env` — NIKDY v repu. RSS kampaň v MailerLite je placená (jede jen do konce trialu ~25. 6.) → pak ji vypnout, skript je náhrada. Žádné testovací sendy na seznam, jakmile obsahuje cizí subscribery.

## Pasti (poučení z historie, neopakovat)

- GA4/analytics injektor v build.py vkládá snippet před **první výskyt** `</head>` v souboru → nikdy nepiš literál `</head>` do HTML komentářů ani stringů.
- Handoffy od designu přijímej **přes repo branch, ne chatem** — chat přenos rozbíjí kódování (mojibake `â`/`Â·` místo `—`/`·`). Design nemá push práva; head metadata (canonical, og/twitter, GA4 poznámka) jsou práce inženýra.
- `og:image` vždy **PNG 1200×630** (`og-image.png`, `automation/og-image.png`) — sociální sítě SVG ignorují. SVG verze zůstávají v repu jen jako editovatelný zdroj.
- Utility stránky (`privacy/terms/affiliate`) mají záměrně **redukovanou nav** — nepřidávat Tools/Changelog.
- Git Bash `curl` má v tomhle prostředí rozbité TLS (exit 35 i na github.io) → live checky dělej přes PowerShell `Invoke-WebRequest`.
- `findClosestIdx` snapuje na kroky slideru (`CALC_OPS_STEPS` končí 1M ops, budget $500) — odhady nad strop se clampují.

## Workflow změn

1. Feature branch (`git checkout -b <nazev>`).
2. Změna → buildy → relevantní testy z tabulky výš.
3. `git merge --no-ff` do `master` → push (= deploy).
4. Live check přes PowerShell (počítej s ~10 min CDN cache), ideálně `e2e-live.js`.
