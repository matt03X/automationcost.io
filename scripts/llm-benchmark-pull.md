# LLM benchmark ingestion — plán pullu

Plní per-model `benchmarks` bloky v `llm/data/models.json` z **otevřených / citovatelných** zdrojů.
Schéma a registr zdrojů žijí v `llm/data/models.json` → `_meta.benchmarks`.
Váhy capability skóre v `llm/data/scoring-model.json` → `benchmarkWeights`.

Tento dokument je **plán**; runnable skript je samostatný follow-up PR (viz „Stav" níže).

## Golden rule (legální hranice)

Ukládáme **jen** `value` + `source` + `asof` (skóre / Elo / %). **Nikdy text otázek.**
Skóre je měřený fakt (Feist v. Rural Telephone) → volně citovatelné s atribucí, nezávisle
na licenci otázkové sady. Reprodukce otázek/odpovědí je naopak licenčně riziková
(GPQA gated/NDA, MATH DMCA, AIME = MAA copyright) → nikdy.

## Metriky (v1)

| key | benchmark | jednotka | primární zdroj |
|---|---|---|---|
| `mmlu_pro` | MMLU-Pro | % | epoch |
| `gpqa_diamond` | GPQA Diamond | % | epoch |
| `swe_bench_verified` | SWE-bench Verified | % | swebench |
| `arena_elo` | LMArena Elo | Elo | lmarena |

AIME / LiveBench / MMMU = snadný pozdější add (viz `benchmarkWeights._note`).

## Zdroje a přístup

| source | licence | přístup | pozn. |
|---|---|---|---|
| `epoch` | CC-BY | CSV export / `pip install epochai` | **ověřit přesný endpoint při ingestu** (hub: epoch.ai/data/ai-benchmarking-dashboard) |
| `helm` | Apache-2.0 | `gs://crfm-helm-public` (per-run JSON) | |
| `lmarena` | CC-BY-4.0 | HF dataset `lmarena-ai/leaderboard-dataset` | **ber z HF, NESCRAPOVAT web**; conversation dataset je CC-BY-NC → nepoužívat |
| `swebench` | skóre = fakt (kód MIT) | `swe-bench.github.io/data/leaderboards.json` | |
| `vendor` | fakt (Feist) | model card / tech report | self-reported → UI flag (i) + ×0.85 discount |

❌ **Artificial Analysis** — proprietární ToU zakazuje scraping, republikaci i stavbu
konkurenčního webu. Pouze placený Commercial API kontrakt. Nepoužívat.

## Matching modelů

Externí zdroje jmenují modely jinak. Pull napáruje přes per-model `benchmarkAliases`
(`{ <sourceKey>: <ext. jméno> }`) v `models.json`; default = `model.name`.
Nejasný / nejednoznačný match → **přeskočit a nahlásit** (nezapisovat hádaný řádek).

## Precedence a důvěra

1. Nezávislý zdroj (epoch / helm / lmarena / swebench) **přebíjí** `vendor` pro stejnou metriku.
2. `vendor` se zapíše jen jako fallback, vždy s `source: "vendor"` (UI to vyrenderuje s ⓘ).
3. Capability scoring dává vendor příspěvkům ×0.85 (viz `frontier_v2_plan`).

## Výstupní tvar (zápis do models.json)

```jsonc
"benchmarks": {
  "mmlu_pro":           { "value": 87.2, "source": "epoch",    "asof": "2026-06-01" },
  "gpqa_diamond":       { "value": 79.4, "source": "epoch",    "asof": "2026-06-01" },
  "swe_bench_verified": { "value": 61.3, "source": "swebench", "asof": "2026-05-20" },
  "arena_elo":          { "value": 1342, "source": "lmarena",  "asof": "2026-06-10" }
}
```

## Cron + alarm (pattern)

Týdenní GitHub Action (vzor `.github/workflows/llm-price-audit.yml` + `scripts/llm-price-audit.js`):
pull → diff `value`/`asof` → PR s návrhem + alarm při změně. Cenové/faktické změny
se **nemergují automaticky** — eskalace majiteli (fact gate).

## Stav

- [x] Schéma + registr zdrojů (`_meta.benchmarks`) + konvence — **tento PR**
- [x] `benchmarkWeights` + `frontier_v2_plan` (dokumentace blendu) — **tento PR**
- [ ] Runnable pull skript (Epoch CC-BY → reálná čísla, ověřený matching) — follow-up
- [ ] Wiring `_model_dims` v `llm/build.py` (frontier blend 0.7/0.3 + fallback + vendor ×0.85)
- [ ] Render benchmark řádku/tabulky na model stránky + atribuce z registru
- [ ] Týdenní cron + alarm
