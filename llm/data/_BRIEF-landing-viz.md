# Zadání pro Claude Design: LLM vizualizace do landingu

**Od Claude Code (data/engine/research). Pro Claude Design.** Branch `llm-quality-swebench`.

Rozhodnutí padlo (owner): **dot-plot cen v heru + scatter cena × kvalita jako deep-dive.**
Tvůj díl = vizuál/layout/skin obojího. Můj díl = data + jaká pravidla viz nesmí porušit (research). Data jsou v `llm/data/models.json` (pole níže), tahle čísla jdou do viz doslovně.

---

## ⚠️ Research anti-vzory — TOHLE viz nesmí udělat (A7 playbook, peer-review)

LLM ceny mají **3 řády rozsahu** ($0,42 → $210/M = **500×**). To je past:
1. **NIKDY jedna lineární osa cen** — levné modely se slijí do nuly u dna (nečitelné).
2. **NIKDY log osa pro laiky** — Romano 2020: log graf správně přečte jen ~50 % lidí.
3. **Řešení = multi-magnitude faceting** (panely/pásy po cenových třídách, každý s vlastní škálou) + **ratio labely** jako primární sdělení.
4. **Virální BAN:** samotný extrémní poměr je nejsilnější sdělení — `500× rozdíl` vytlač jako velké číslo.

---

## (A) DOT-PLOT cen — hero

Cíl: „at-a-glance" rozsah cen + jedno komentovatelné číslo. Tiery už jsou v datech (`tier`), použij je jako faceting pásy (řeší 3 řády bez log osy):

| pás (`tier`) | rozsah blended ($ in+out /M) | modelů |
|---|---|---|
| budget | $0,42 – $6 | 4 |
| mid | $1,31 – $18 | 6 |
| frontier | $3,75 – **$210** | 8 |

- **1D pozice na škále = nejpřesnější percepční úloha** (Cleveland & McGill) — proto dot-plot, ne bar.
- Každý pás vlastní škála (frontier nesmí zploštit budget).
- **BAN nad grafem:** „GPT-5.5 Pro stojí **500× víc** než DeepSeek V4 Flash" (nebo obecně „500× rozdíl napříč modely").
- Barva = provider (paleta níž), pozice = cena. Hover = název + přesná cena.
- Data: všech 18 modelů (každý má cenu). Blended = `inputPerM + outputPerM` (nebo si zvol in/out zvlášť — ber to jako návrh).

## (B) SCATTER cena × kvalita — deep-dive (níž na stránce)

Osa X = cena ($/M blended), osa Y = **SWE-bench Verified %** (zvolená quality metrika — coding/agentic, sedí dev publiku). Ukazuje „value-for-money" (vlevo nahoře = levné + dobré).

**Dostupných 6 bodů** (zbytek modelů quality NEMÁ — `swebenchVerified: null` — do scatteru nedávej, nebo zóna „data pending"):

| cena $/M | SWE-bench | jistota | model |
|---|---|---|---|
| $6 | 73,3 % | ✅ direct | Claude Haiku 4.5 |
| $14 | 80,6 % | ✅ direct | Gemini 3.1 Pro |
| $18 | 80,2 % | ✅ direct | Claude Sonnet 4.6 |
| $30 | 88,6 % | ~ 2nd-hand | Claude Opus 4.8 |
| $35 | 88,7 % | ~ 2nd-hand | GPT-5.5 |
| $60 | 95,0 % | ~ 2nd-hand | Claude Fable 5 |

- **`qualityVerified` flag** rozlišuje jistotu zdroje: `true` = čteno přímo z vendor stránky (3 modely), `false` = z vendor blogu přes druhou ruku (3 modely). **Body s `false` odliš vizuálně** (slabší obrys / tečkovaný / menší) — transparentnost zdroje.
- **Evidence-first:** každý bod má `qualitySource` URL → klikací „source ↗" (jako u history evidence). Neodstraňovat.
- **Disclaimer u grafu (povinný):** „SWE-bench Verified, self-reported by each vendor — not our independent test. See source." Skóre je proxy, ne náš test.
- Sweet-spot story, kterou data vyprávějí: **Haiku 73 % za $6** a **Gemini 81 % za $14** jsou value vítězové vlevo; **Fable 5 95 % za $60** je špička vpravo nahoře. Klidně to v copy zvýrazni (ale čísla ode mě).

## Sdílení (oba grafy)
Statický export 1200×675 + 4:5 mobil. Titulek = pointa („LLM API prices range 500× — here's what you actually pay"). Footer watermark „wizardcost.com · source: vendor pricing + SWE-bench · {date}". Faceless.

---

## Datový kontrakt (z `llm/data/models.json`)

Per model: `id`, `name`, `tier` (budget/mid/frontier), `inputPerM`, `outputPerM`, `cachedInputPerM`, `batchDiscount`, `contextWindow`.
Quality (jen 6 modelů, jinak chybí): `swebenchVerified` (number %), `qualitySource` (vendor URL), `qualityVerified` (bool).
Metodika a pravidla v `_meta.quality_methodology` — přečti, je tam disclaimer i pokrytí.

## Vendor paleta (per provider, sjednoť s automation history)
Návrh — uprav v editorial skinu, ale drž konzistenci s history sadou:
OpenAI, Anthropic, Google, DeepSeek, xAI, Mistral. (Pozn: history sada zavedla oficiální brand barvy pro automation vendory; pro LLM providery si urči vlastní konzistentní sadu — žádná zatím v repu není.)

## Co je MOJE / co je TVOJE
- **Moje:** všechna čísla (ceny i quality), `swebenchVerified` hodnoty, evidence URL, metrika, doplnění dalších modelů (scout dozraje), disclaimer text. Když číslo vypadá špatně → napiš, needituj.
- **Tvoje:** layout obou grafů, faceting/dot geometrie, scatter vizuál, jak odlišit `qualityVerified:false`, BAN styl, dark-mode, share export, editorial skin. Engine generuje data bloky z models.json + parity test (jako provider stránky).
