---
description: Build + check + relevantní testy + deploy aktuální branche do master (stage jen explicitní soubory; push až po potvrzení)
allowed-tools: Bash, Read, Grep, Glob
argument-hint: "[volitelně: cesty souborů ke stage, jinak se vezmou z git status]"
---

Bezpečně vydej (deploy = push do `master` → GitHub Pages) změny z **aktuální branche**.
Drž se workflow z `CLAUDE.md`. **NIKDY `git add -A` ani `git commit -am`** — stageuj jen
jmenované soubory.

Postup:

1. **Zjisti změny.** `git -C . status --porcelain` + `git -C . branch --show-current`.
   - Soubory ke commitu = `$ARGUMENTS`, pokud byly zadané; jinak změněné soubory z `git status`
     (vyjma generovaných výstupů, které doženou buildy v kroku 2).
   - Ověř, že NEjsi na `master` přímo bez branche — pokud ano, řekni to a zeptej se.

2. **Build + check** (dle toho, co se měnilo):
   - automation/data nebo automation/* nebo root build → `python automation/build.py && python build.py`
   - llm/* → `python llm/build.py`
   - pak vždy `--check` varianty (`python automation/build.py --check && python build.py --check`,
     resp. `python llm/build.py --check`). `--check` musí projít (exit 0).

3. **Testy z tabulky v `CLAUDE.md`** — pusť jen relevantní podle změny
   (např. data/engine → `verify-landing.js`; pairs/tools/vs → `test-vs-pages.js`;
   wizard → `test-smoke-flow.js`; llm → `test-llm-*`). Testy jsou v `../../calc-test`.

4. **Stage + commit (jen explicitní soubory).** `git -C . add <soubor> …` (vyjmenuj je),
   pak commit s krátkou výstižnou zprávou. Ukaž `git -C . status` před commitem.

5. **DEPLOY = STOP-AND-CONFIRM.** Shrň, co se vydá (diff přehled + na jakou branch), a
   **zeptej se na potvrzení**, než provedeš:
   `git -C . checkout master && git -C . merge --no-ff <branch> && git -C . push`.
   Push neprováděj bez explicitního OK uživatele (deploy je outward-facing).

6. **Po deploy:** připomeň ~10 min CDN cache a nabídni live check (PowerShell `Invoke-WebRequest`
   nebo `e2e-live.js`).

Pozn.: cenové/affiliate/data změny jsou stop-and-confirm (guard.mjs je v autonomním běhu blokuje) —
do `tools.json`/`models.json` patří jen ověřené hodnoty po revizi.