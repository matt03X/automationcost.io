# WizardCost — pravidla repa

Umbrella web **wizardcost.com** (GitHub Pages z `master`, CNAME v rootu — push = deploy, CDN cache ~10 min).
Root = homepage WizardCost. `/automation/` = AutomationCost (kalkulátor, compare, pricing stránky, changelog).
Každá úroveň má vlastní `build.py` + `data/site.json`.

## Zdroj pravdy a generované bloky

- **`automation/data/tools.json` je JEDINÝ zdroj cenových dat.** Root `data/tools.json` neexistuje záměrně (smazán kvůli drift hazardu) — neobnovovat.
- Bloky mezi markery se **nikdy needitují ručně** — přepisuje je build:
  - `/* DATA:TOOLS:START|END */` v `automation/calculator.html` + `compare.html` → `automation/build.py`
  - `/* DATA:DEMO:START|END */` v root `index.html` (hero price demo) → root `build.py` (čte automation data)
  - `/* DATA:CHANGELOG:START|END */` v `automation/changelog.html` → `automation/build.py` (generuje z **git historie** tools.json)
- Po změně tools.json spusť **oba** buildy: `python automation/build.py` i `python build.py` (root), commitni výsledek. `--check` = CI guard (exit 1 při zastaralých blocích).
- Changelog vzniká z git diffů tools.json → do tools.json patří jen **ověřené** změny. Drift report ze scraperu (`automation/data/drift-report.md`, netrackovaný) = neověřené nálezy, ne potvrzená fakta. Datum commitu = veřejné datum záznamu v changelogu.
- Při změně cen aktualizuj i `_meta.last_reviewed` a nav badge „Updated <Month Year>" na stránkách.

## Cost engine (automation/calculator.html)

- `calcCost`: custom/„contact sales" plány (`monthlyUsd: null`, flag `custom: true` z buildu) se oceňují odhadem — kotva = největší veřejný cloud plán, škálování exponentem **0.7** (kalibrováno na veřejný Zapier ceník), minimum 1.3× kotvy, zaokrouhlení na $5. Odhad se použije, když veřejné plány objem nepokryjí, nebo nad 2× kotvy, když je levnější než lineární overage (čisté `min()` → cenová křivka je monotónní). Odhady se zobrazují `~$X` + „estimate" + disclaimer.
- `estimateVolumeBudget`: workflow multiplikátor = `clamp((Σ defaultOps / 5000)^0.8, 0.5, 5)` — záměrně **monotónní** (přidání workflow nikdy nesníží odhad) a **nezávislý na pořadí** kliknutí. Neměnit bez spuštění test sady.
- **Python port** enginu žije v root `build.py` (`cheapest_monthly`) kvůli generování DATA:DEMO. Při změně JS enginu uprav i port — paritu hlídá `calc-test/verify-demo.js` (musí být 16/16).
- `goStep(4)` re-estimuje slidery jen při změně profilu (signature guard) — ruční úpravy uživatele přežívají navigaci.

## Testy (`../../calc-test`, mimo repo)

| Skript | Kdy spustit |
|---|---|
| `verify-demo.js` | po každé změně enginu, dat nebo Python portu (parita DEMO ↔ JS engine) |
| `test-ops-estimate.js`, `test-200-firem.js` | po změně estimate matematiky (plausibilita doporučení, monotonie, pořadí) |
| `test-smoke-flow.js` | po změně wizardu (end-to-end přes DOM stub) |
| `test-homepage-smoke.js`, `test-changelog-smoke.js` | po změně homepage dema / changelogu |
| `e2e-live.js` | po deployi (Playwright proklik živého webu, screenshoty do `calc-test/screenshots/`) |
| `check-ui-live.js` | po změně nav/headeru (dropdown Pricing Guides, logo →`/`, favicon — live) |
| `check-jsonld.js` | po změně head sekcí (validita JSON-LD bloků) |

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
