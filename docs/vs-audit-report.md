# VS-stránky — audit faktických tvrzení (2026-06-16)

**Rozsah:** 9 generovaných `/automation/*-vs-*.html` stránek; zdroje
`automation/data/tools.json` (ne-cenová fakta) + `automation/data/pairs.json`
(editorial próza). Strukturovaná evidence: [`automation/data/vs-claims.json`](../automation/data/vs-claims.json).
**Metoda:** cenová tvrzení deterministicky proti enginu (`build.py cheapest_monthly`,
steps=3, wf=3, prefer_cloud=False — shodně s `render_vs_page`); objektivní fakta proti
oficiálním stránkám vendorů. **EVIDENCE-ONLY — žádná data jsem neměnil.** Opravy níže
jsou návrhy ke schválení.

## Souhrn
- **30 registry položek (~50 atomických tvrzení): 11 match, 12 mismatch, 2 unverifiable, 5 opinion.**
- **6 mismatchů je `favors_us`** (dělají konkurenta horším / náš pick lepším) = **právní priorita** (nekalá soutěž / zavádějící reklama).
- **Hlavní nález:** veškerá **cenová PRÓZA v pairs.json je systematicky zastaralá** — psaná pro starý cenový model (steps=1 / před overhaulem). Cenové **tabulky** na stránkách jsou z enginu **správně**, ale **próza jim přímo odporuje** na téže stránce (poškozuje důvěryhodnost) a místy nadhodnocuje výhodu našeho vítěze.
- **Integrace:** všechny nesrovnalosti jsou **PODhodnocení** (Make, n8n, Pipedream) = `favors_competitor`, právně neškodné, ale věcně špatné a podstřelují naše vlastní vítěze (hlavně **n8n 400 → reálně 1 868**).

---

## A) MISMATCH — opravit (řazeno: favors_us → severity)

### A1. `favors_us` HIGH — cenové nadhodnocení výhody (právní riziko)

**PRC-zap-make** (zapier-vs-make) — verdict + faq
- Tvrdíme: „Make **14–24×** cheaper"; „$0 vs $58.50 @1k → $116.47 vs $733.50 @100k".
- Engine: **5.4–10.3×**; Zapier **$73.50→$1149**, Make **$10.59→$214.31** (@1k/5k/20k/100k = 6.9× / 10.3× / 6.7× / 5.4×).
- Próza odporuje cenové tabulce na stránce. **Návrh:** verdict „Make is **5–10× cheaper** at paid volumes"; faq čísla „$10.59 vs $73.50 at 1,000 … $214.31 vs $1,149 at 100,000" (nebo generovat z enginu — viz §D).

**PRC-make-pd** (make-vs-pipedream) — verdict
- Tvrdíme: „Make **5–9×** cheaper at every volume"; „100k **~$45 vs ~$400**".
- Engine: **1.4–4.2×**; Make 100k **$214.31**, PD 100k **$309.60**.
- **Návrh:** „Make is **1.4–4× cheaper** (gap se s objemem zmenšuje)"; „100,000 runs $214 vs $310".

**PRC-zap-pd** (zapier-vs-pipedream) — verdict, MEDIUM
- Tvrdíme: „Pipedream **3–4×** cheaper **at every volume**".
- Engine: **1.6–3.7×** (při 1k jen 1.6×, roste s objemem).
- **Návrh:** „Pipedream is **~2–4× cheaper**, and the gap widens with volume".

**PRC-n8n-pd** (n8n-vs-pipedream) — verdict, MEDIUM (smíšené)
- Tvrdíme: „PD **$29**–~$400+"; n8n VPS „$8–66"; n8n Cloud „$20–50".
- Engine: PD **$45–$309.60**; n8n self-host $8–45 (1k–100k); n8n Cloud ~$27.80–69.51.
- `favors_us` část = „~$400+" nadhodnocuje PD strop (reálně $309.60). „$29" je stará PD base (opraveno na $45). **Návrh:** „Pipedream $45–~$310"; sjednotit n8n Cloud „$28–70".

**PRC-make-ap** (make-vs-activepieces) — verdict, MEDIUM
- Tvrdíme: „at 1,000 runs/mo **dead heat**"; Make „$9 → ~$45/mo".
- Engine (steps=3, jako tabulka): @1k **NENÍ remíza** — AP $0 vs **Make $10.59**; Make rozsah **$10.59–$214.31**.
- **Návrh:** „at 1,000 runs Activepieces is free vs Make ~$11; Make runs $11–$214/mo across our volumes".

**FEA-pd-credit** (pipedream opDef, propisuje se do faq) — MEDIUM
- Tvrdíme: „one credit ≈ 30 seconds of compute **per step** — multi-step typically consumes several credits per run".
- Realita (pipedream.com/docs/pricing): „1 credit = 30 s compute @256 MB; Pipedream **neúčtuje per step** — 20-step a 2-step workflow stojí stejně, závisí na čase." Navíc náš **engine** modeluje PD jako 1 credit/run (steps zdarma) → próza si protiřečí s enginem.
- **Návrh:** „one credit ≈ 30 seconds of compute time (at 256 MB), **regardless of step count** — billed on execution time, not steps".

### A2. `favors_competitor` / neutral MEDIUM — zastaralé, ale ne rizikové (sjednotit s enginem)

| id | stránka | tvrdíme | engine | návrh |
|---|---|---|---|---|
| PRC-zap-n8n | zapier-vs-n8n | „Zapier $73–$733" | $73.50–**$1149** | „$73–$1,149" |
| PRC-zap-ap | zapier-vs-activepieces | „Zapier $58–$733" | $73.50–$1149 | „$74–$1,149" |
| PRC-make-n8n | make-vs-n8n | „@5k gap ~$1"; Make 100k „~$45" | @5k gap ~**$11**; Make 100k **$214** | „@5k ~$11 gap; Make 100k ~$214" |

### A3. Integrace — PODhodnocení (favors_competitor, věcná oprava)

| id | vendor | tvrdíme | reálně (oficiální) | návrh |
|---|---|---|---|---|
| **INT-n8n** | n8n | **400** | **1 868** (n8n.io/integrations) | 1 800 (nebo přesný scrape) |
| INT-make | Make | 1 500 | **3 000+** (make.com/en/integrations) | 3 000 |
| INT-pipedream | Pipedream | 2 000 | **3 000+** (pipedream.com/apps + docs) | 3 000 |

→ Pozn.: oprava INT-make/INT-pipedream/INT-n8n **zvětší** náš argument tam, kde jsou vítězi,
a u „Zapier vyhrává na integracích" zmenší magnitudu na realitu (9 000 vs 3 000, ne vs 1 500).
**Opravit i prózu** v pairs.json, která cituje stará čísla („1,500+", „2,000+").

---

## B) UNVERIFIABLE — chybí spolehlivý primární zdroj (doověřit ručně před změnou)

- **FT-make-freeops** (`favors_us`, MEDIUM): tvrdíme Make free = „**unlimited scenarios**" (+ 1,000 ops/mo).
  Sekundární zdroje 2026 uvádí free = **2 active scenarios**. Pokud platí, NADhodnocujeme štědrost
  Make (našeho vítěze) → ověřit primárně na make.com/pricing. 1,000 ops/mo je potvrzeno.
- **FT-pipedream-free** (low): „100 credits/mo na 3 workflows" — doověřit aktuální PD free (počítadlo creditů + limit aktivních workflows) na pipedream.com/pricing.

---

## C) OPINION — subjektivní, ověřit obhajitelnost (ne „správnost")

| id | tvrzení | verdikt |
|---|---|---|
| OP-value-verdicts | „X is the value pick / winner" | **Obhajitelné** — vítěz = levnější dle enginu. ALE závisí na opravě cenové prózy (A1); jinak verdikt stojí na zastaralých číslech. |
| OP-zapier-deepest | „Zapier 9,000+ deepest catalog in the market" | **Obhajitelné** — 9 000+ je nejvíc mezi sledovanými. Pochvala konkurenta. |
| OP-n8n-deeper | „n8n deeper toolkit / bigger ecosystem / more mature logic" | **Obhajitelné** — podpořeno daty (1 868 integrací, code nodes). |
| OP-pd-dev | „Pipedream developer's pick / more powerful DX" | **Obhajitelné** — odpovídá pozici PD. |
| OP-make-ceiling | „Make's visual builder hits a ceiling when logic gets complex" | **Hraniční** — tvrzení o slabině konkurenta. Držet jako **názor** („we find / tends to"), ne jako fakt. |

---

## D) Doporučení k DURABILITĚ (aby próza znovu nezdriftovala)
Cenové multiplikátory/rozsahy v próze jsou ručně psané → driftují při každé cenové revizi.
Dvě možnosti (doporučuji obě):
1. **Okamžitě:** opravit čísla v `pairs.json` dle §A (návrh diffu po schválení).
2. **Durable guard:** rozšířit `calc-test/test-vs-pages.js` o **„prose price guard"** — vytáhne z
   verdict/faq čísla `$X` a multiplikátory `N×` a porovná s `cheapest_monthly` na volumech;
   fail při driftu (tolerance na „~"/zaokrouhlení). Pak CI chytí každý budoucí rozpor próza↔engine.
3. (volitelně) nahradit konkrétní čísla v próze **placeholdery** (`{{a_low}}`/`{{mult_range}}`),
   které `render_vs_page` vyplní z enginu — próza pak nemůže zastarat.

---

## E) Navržené datové změny (DIFF — ke schválení; NEMĚNÍM sám)
> Po schválení: editace `pairs.json` (próza) + `tools.json` (integers) → `python automation/build.py`
> + `python build.py` → `node calc-test/test-vs-pages.js`. tools.json integer změny (integrace)
> NEjsou cenové → changelog je nediffuje; přesto patří do revize člověkem.

**tools.json (integers):** `n8n.integrations 400 → 1868`, `make.integrations 1500 → 3000`,
`pipedream.integrations 2000 → 3000`. (Zapier 9000, Activepieces 747, Automatisch 50,
Node-RED 5000 ponechat — match/obhajitelné; u Node-RED zvážit label „community nodes".)

**pairs.json (próza):** přepsat cenové multiplikátory/čísla v `verdict`/`whyLoser`/`faq` dle §A1–A2;
opravit integrace „1,500+/2,000+" na „3,000+"; přeformulovat PD credit opDef (§A1, FEA-pd-credit);
ověřit+opravit Make „unlimited scenarios" (§B).

---

## F) Pozn. k metodě
- Cenová tabulka i `.winner` karta na stránkách jsou generované z enginu → **správné**; problém je
  jen ručně psaná **próza** kolem nich. Priorita: nejdřív 6 `favors_us` (A1), pak zbytek.
- Průběžné hlídání ne-cenových faktů řeší navržená **facts-audit pipeline** (`scripts/facts-audit.js`
  + `.github/workflows/facts-audit.yml`) — viz samostatný PoC, EVIDENCE-ONLY (vzor price-audit).
- **PoC ověřen lokálně 2026-06-16:** `node scripts/facts-audit.js make n8n activepieces` → správně
  flagnul make (1500 vs 3000) a n8n (400 vs 1868), a **neflagnul** activepieces (claim 747 vs scrape
  749, v toleranci). Tj. nezávisle potvrzuje nálezy §A3. Diff je proti `claimedValue` v tools.json
  (chytá NAŠI zastaralost), ne jen proti minulému snapshotu → alarmuje, dokud člověk tools.json neopraví.

## G) Kde je potřeba AI API (Fáze 5 — LLM = volitelný booster, NE závislost)
Většina auditu je **deterministická** (regex/DOM nad vyrenderovaným textem) → auditovatelná, zdarma,
běží i bez LLM. PoC `facts-audit.js` to dokazuje (integration counts ze 3 vendorů bez jediného tokenu).
LLM přidat **pouze** na dvě místa, kde deterministika selhává:
1. **Extrakce čísla z měnícího se layoutu** — když regex vrátí `null` i po retry (např. pipedream.com/apps
   je plně JS-rendered a i WebFetch vrátil prázdno). Fallback: pošli ořezaný text stránky levnému modelu
   (haiku-class) s promptem „vrať počet integrací jako celé číslo, jinak null" → JSON. Volá se JEN při
   regex-null; výstup = EVIDENCE (člověk ověří), cachovaný dle hashe textu.
2. **Sémantická kontrola prózy** — zda editorial tvrzení v `pairs.json` (např. „Make's visual builder
   hits a ceiling", „Pipedream is code-first") stále odpovídá realitě vendora. Pošli {claim + výřez docs}
   → „platí stále? ano/ne/nejisté + proč". Tohle regex neumí; LLM dává jen *flag k revizi*, nikdy nemění text.
- **Pravidla:** výstup je vždy EVIDENCE (nikdy auto-edit tools.json/pairs.json); **cachovat** (hash→výsledek);
  **minimalizovat tokeny** (posílat jen relevantní výřez, žádat strict JSON); pipeline **musí běžet i bez LLM**
  (booster gated `if (process.env.ANTHROPIC_API_KEY)`, jinak fakt = `unverifiable`, ne chyba). Token z env
  (`engine/.env` / GitHub secret `ANTHROPIC_API_KEY`), **NIKDY do repa**. Model: `claude-haiku-4-5` (levný).
- Návrh modulu: `scripts/facts-extract-llm.js` exportující `extractCountLLM(text)` + `claimStillHolds(claim, docText)`,
  volaný z `facts-audit.js` jen na regex-null a z budoucího prose-check kroku. (Mimo PoC — zapojit po schválení.)
