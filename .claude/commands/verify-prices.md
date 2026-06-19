---
description: Ověř ceny nástroje proti oficiálnímu ceníku (Playwright) přes calc-test/verify-pricing-live.js a shrň verdikt
allowed-tools: Bash, Read
argument-hint: "<slug> (zapier|make|n8n|pipedream|activepieces|automatisch|node-red), prázdné = všechny"
---

Ověř, že naše cenová data v `tools.json` sedí s živým oficiálním ceníkem vendora.
**Evidence, ne auto-zápis** — dumpy jsou důkaz, verdikt děláš ty (stop-and-confirm na čísla).

Slug: `$ARGUMENTS` (když prázdný, plošný audit všech).

1. **Najdi a spusť skript.** Žije v `../../calc-test` (mimo repo, tam je i `node_modules`).
   Spusť z té složky, ať sedí závislosti:
   ```
   node ../../calc-test/verify-pricing-live.js $ARGUMENTS
   ```
   (Když selže na chybějící modul, spusť s cwd = `../../calc-test`, tj.
   `node verify-pricing-live.js $ARGUMENTS` odtamtud. Dumpy jdou do `vendor-pricing-dumps/`.)

2. **Shrň verdikt:** pro daný slug porovnej scrape vs. `automation/data/tools.json` — kde
   sedí / kde je rozdíl (plán, cena, jednotka). Rozdíl = **návrh** ke schválení, NE rovnou edit.

3. Když je rozdíl reálná vendor změna: navrhni úpravu `tools.json` přes commit/PR k revizi
   (changelog se generuje z git historie → nejdřív commit tools.json, pak buildy). Přímý edit
   cenových dat je v autonomním běhu blokovaný guardem — to je záměr.