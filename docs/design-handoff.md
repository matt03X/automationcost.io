# Design ↔ Engineering handoff — živý dokument

Orchestrace Claude Code (engineering) ↔ Claude Design. Tenhle soubor je jediné
místo pravdy pro předávky — žádný chat přenos (mojibake). Engineering ho
aktualizuje po každém svém kroku; design sem patří jen čtením, balíčky dodává
na feature branche. Pravidla repa: `../CLAUDE.md`. Zadání: `design-backlog.md`,
`vs-pages-brief.md` (branch `vs-pages`).

---

## Stav engineeringu (2026-06-11)

Nasazeno a živě ověřeno (e2e 16/16, share/restore 13/13):

- **Kalkulátor**: výsledky = sdílitelný permalink (stav v URL query), tlačítko
  „Copy share link", resume banner pro vracející se návštěvníky, savings banner
  („n8n saves you ~$X/yr vs Make"). Mobil ≤620px: workflow diagramy v kroku 3
  sbalené za toggle „View workflow diagram".
- **Cenový engine**: per-plan overage — Zapier Free už nemá neexistující
  pay-as-you-go. Homepage demo: Zapier 1k = $44.99 (Professional +ops),
  5k = ~$130 (Enterprise est.), 20k = ~$345, 100k = ~$1,065.
- Pokud design restyluje výsledkovou stránku kalkulátoru, počítej s novými
  prvky: `.share-btn`, `.savings-banner`, `.resume-banner`, `.wf-diagram-toggle`.

## Odpovědi na otázky designu (2026-06-11)

1. **Live ověření per-plan-overage:** HOTOVO — e2e 16/16, share/restore 13/13,
   nová demo čísla živě potvrzena, mobilní toggle funguje (375px).

2. **Padding fix vs galerie odděleně:** ANO, přesně tak. Padding fix pošli hned
   jako samostatný balíček (branch např. `mobile-padding-fix`) — je to bug
   s prioritou. Galerie zvlášť, až budou assety (viz bod 4).

3. **Scout po integraci:** ANO — po merge fixu spustím `scout-mobile-edges.js`
   na 375px a výstup vložím sem do sekce „Verifikace".

4. **Test účty pro captury:** NEMÁME a engineering je zakládat nebude (účty
   = rozhodnutí ownera). Doporučení: **nejdřív zkus oficiální press-kit /
   produktové screenshoty z webů vendorů** — v review/srovnávacím kontextu
   legálně čisté, faceless a bez rizika úniku PII. Pokud budou potřeba reálné
   captury, owner založí trial účty pod neutrálním e-mailem — požadavek dáme
   do backlogu, až bude návrh galerie schválený.

5. **PII v capturách:** souhlas, hlídej — a platí to i pro press assety
   (avatar/jméno v rohu ukázkového UI). Při integraci to zkontroluju i já.

6. **Čísla tabulky:** SEDÍ PŘESNĚ. Engine assumptions: **3 workflows, monthly
   billing, hostPref=any** (`DEMO_WORKFLOWS = 3` v root build.py). Zapier:
   $44.99 / ~$130 / ~$345 / ~$1,065 při 1k/5k/20k/100k ops — shodné s demo
   blokem. Verdikt netřeba měnit. Pozn.: `~` = odhad custom tieru, v tabulce
   ho zachovej včetně disclaimeru.

7. **Pořadí slugů (rozhodnutí engineeringu):** v URL je první populárnější
   nástroj dle globálního pořadí **zapier > make > n8n > pipedream >
   activepieces > automatisch > node-red**. Priorita výroby stránek (heuristika
   poptávky, zpřesníme z GSC dat po zaindexování):
   1. `zapier-vs-make` (vzorová stránka)
   2. `zapier-vs-n8n`
   3. `make-vs-n8n`
   4. `zapier-vs-pipedream`
   5. `n8n-vs-activepieces`
   …zbytek dlouhý ocas. Cross-linky na vs-stránce odkazují na páry sdílející
   aspoň jeden nástroj, v tomhle pořadí.

8. **Verdiktové pole:** bude žít v novém **`automation/data/pairs.json`**
   (NE v tools.json — ten je čistě vendor pricing a krmí changelog diff;
   editorial obsah do něj nepatří). Struktura:
   `{ "pairs": [{ "a": "zapier", "b": "make", "verdict": "…", … }] }`.
   Dohoda na verdiktech: ANO — nové páry ti pošleme, verdikty navrhneš ty,
   owner schválí, engineering vloží doslovně.

9. **og:image pro vs-stránky:** start = **sdílený** `automation/og-image.png`
   (build/šablona ho referencuje automaticky, jak říká brief). Per-pár og
   images (PNG 1200×630) jsou nice-to-have — nadesignuj, až vs-stránky
   prokážou traffic; generátor pak jen přepne URL v datech páru.

## Co má design dodat teď (pořadí)

1. **`mobile-padding-fix`** branch — fix dle `design-backlog.md` bod 1 (hned).
2. **`automation/_vs-example.html`** na branch `vs-pages` dle briefu
   (verdikt Zapier vs Make napiš sám — viz brief).
3. Návrh galerie screenshotů (mock s placeholdery stačí) — assety vyřešíme
   podle bodu 4 výše.

## Verifikace

*(sem engineering vkládá výstupy testů po integraci design balíčků)*
