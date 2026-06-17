# WizardCost / AutomationCost — akční roadmapa

> Vznikla z 5-proudové rešerše (legalita · konkurence · trh · zisk/strop · promoce).
> Jednostránkový přehled: priorita × efort × dopad. Řazeno tak, aby levné blockery
> šly první a drahé škálování až po ověření. **Není to právní ani daňová rada** —
> položky 🔴 vyžadují účetního/advokáta.

## Klíčové závěry rešerše
- **Legalita:** žádný blocker; 3 levné opravy + DPH „identifikovaná osoba" u 1. zahraniční provize.
- **Moat:** neutrální ověřený kalkulátor je reálná mezera proti zaujatým vendor/SaaS srovnávačům.
- **Strop:** automation sama ~$5–15k/měs za 2–3 roky; rok+ ztrátový. Strop se láme jen DALŠÍMI vertikálami.
- **Promoce:** interaktivní formát + llms.txt = na správné straně AI posunu; cesta = GEO + Reddit/PH.

---

## FÁZE 0 — Legální must-fix (PŘED jakoukoli promocí) — efort: nízký · dopad: blocker
- [ ] **Cookie consent banner + GA4 Consent Mode v2** — GA4 se nesmí načíst před souhlasem (EEA). MEZERA.
- [ ] **Impressum v patičce** — jméno/IČO/e-mail (pokuta až 50k Kč). MEZERA.
- [ ] **Affiliate disclosure** u odkazů + stránka (FTC až $51k/porušení + EU UCPD).
- [ ] **Živnost volná** (reklama/marketing, 1000 Kč) + počítat s **identifikovanou osobou k DPH** do 15 dní od 1. zahraniční provize.
- [ ] Projít **ToS + affiliate ToS** všech 6 vendorů (zákaz scrapingu / brand-biddingu).
- 🔴 Pro účetní/advokáta: paušál vs identifikovaná osoba · timing OSVČ→s.r.o. · finální ToS/Privacy/disclaimer.

## FÁZE 1 — Datová integrita = moat + právní štít — efort: střední · dopad: vysoký
- [ ] **vs-claims.json registry** — vytáhnout každé faktické tvrzení z pairs.json + tools.json.
- [ ] **Ověřit NE-cenová fakta** (integrace count, self-host, limity) proti živým vendor stránkám; priorita = chyby ve směru „nadhodnocuje konkurenta".
- [ ] **Ověřit LLM ceny** (models.json) proti oficiálním ceníkům — chybí audit, je to nejslabší místo.
- [ ] **Pipedream monthly** ceny (45/74/150) ručně přepárovat.
- [ ] **facts-audit pipeline** (analogie price-audit) — evidence-only, člověk schvaluje.
- Pozn.: „ověřitelné a objektivní" je zákonný test srovnávací reklamy (§2980 OZ) → tahle fáze je i právní pojistka.

## FÁZE 2 — GEO / AI-readiness — efort: nízký–střední · dopad: vysoký upside
- [ ] **schema.org structured data** na vs/pricing stránkách.
- [ ] **Povolit GPTBot/PerplexityBot** v robots.txt; doladit **llms.txt** (už existuje).
- [ ] Sledovat „AI share of voice" (citace v ChatGPT/Perplexity vs konkurence).
- Důvod: LLM referral konvertuje ~25× líp, +800 % YoY; interaktivní kalkulátor AI Overviews přežije.

## FÁZE 3 — Launch & distribuce — efort: střední · dopad: traffic
- [ ] **Reddit první** (relevantní subreddity, udržitelný traffic + AI citace).
- [ ] **Product Hunt** ~týden po Redditu (špička + testimonials).
- [ ] Budovat **brand WizardCost** (brandovaný search izoluje od AI ztrát).

## FÁZE 4 — Škálovat vertikály = prolomit strop — efort: vysoký · dopad: zvýšení stropu
- [ ] **Dotáhnout LLMCost** (LLM API trh > automation, rychlejší růst) — po ověření cen z Fáze 1.
- [ ] Další vertikála (platební brány / email API / OSVČ daňový kalkulátor lokálně).
- Princip: 1 nika = strop ~$5–15k/měs; N vertikál = N× strop.

---

## Jak měřit postup
- **Fáze 0:** cookie banner blokuje GA4 do souhlasu; impressum v patičce; disclosure u odkazů (vizuální kontrola živého webu).
- **Fáze 1:** vs-claims.json má status u každého tvrzení; 0 mismatchů ve směru „favors_us"; LLM ceny 1:1 s ceníky.
- **Fáze 2:** GPTBot povolen, schema validní (Rich Results Test), test citací přes 50 promptů.
- **Fáze 3/4:** GA4 traffic křivka, affiliate konverze, počet aktivních vertikál.
