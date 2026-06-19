---
description: Týdenní SEO digest z čerstvého marketing snapshotu (GSC + Cloudflare) přes marketing-specialist agenta — read-only, výstup pro tebe
allowed-tools: Bash, Read, Grep, Glob, Agent, WebSearch, WebFetch
---

Vyrob **týdenní SEO digest** webu wizardcost.com z reálných dat. **Read-only** — nic neměň,
nic nepublikuj (čísla/ceny/affiliate jsou stop-and-confirm). Tohle volá i cloud routine.

1. **Načti čerstvá data** (oddělená větev `marketing-data`, Pages ji neservíruje):
   ```
   git -C . fetch origin marketing-data
   git -C . show origin/marketing-data:latest.json
   ```
   Když snapshot chybí / je prázdný, řekni to a navrhni screenshot jako fallback
   (živé natažení `scripts/marketing/gsc_pull.py` / `cf_pull.py` jen pokud máš tokeny).

2. **Spusť analýzu** přes subagenta `marketing-specialist` (Agent tool, subagent_type
   `marketing-specialist`) — předej mu poslední snapshot a požádej o jeho standardní výstup.

3. **Výstup digestu** (krátce, akčně):
   - **(1) Co data říkají** — s čísly (top dotazy + pozice, stránky bez impressions, trend, země).
   - **(2) 3–5 konkrétních úprav** seřazených dle dopadu/námahy.
   - **(3) Co z toho je stop-and-confirm** (ceny/affiliate/tvrzení) vs. co jde rovnou (vizuál/copy/meta).
   - Nakonec **jeden řádek shrnutí + top-3 akce** (vhodí se pro ping na telefon).

Pozn.: nízký traffic = SEO náběh (6–12 měs dle STRATEGY.md), ne panika. Cíl je US/UK/globální
anglická organika; CZ-heavy traffic ber jako vlastní/známé, ne organiku.