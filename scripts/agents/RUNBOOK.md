# Horda agentů — runbook (jak pustit v terminálu)

Agenti jsou definovaní v `.claude/agents/<name>.md` → invokovatelní jako subagent (Claude Code je vidí podle `name`). Píšící agenti běží ve **vlastním git worktree off origin/master** → **PR** (= lidská brána). Plný plán + delší prompty: `~/.claude/plans/krok-0-sync-shiny-diffie.md`.

## Předpoklady (jednorázově)
- Terminál = **VS Code integrovaný, shell PowerShell**. `gh` přihlášený, na masteru.
- `git push` JEN přes PowerShell (Bash TLS na tomhle stroji rozbité).
- Povolit spouštění `.ps1` (jednou): `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
  (nebo ad-hoc: `powershell -ExecutionPolicy Bypass -File scripts\agents\wt-new.ps1 ...`).

## Worktree helper
- Nový:  `.\scripts\agents\wt-new.ps1 <agent> <slug>`  → vytvoří `..\.worktrees\<agent>-<slug>` off origin/master, vrátí cestu.
- Úklid (po mergi):  `.\scripts\agents\wt-cleanup.ps1 <agent> <slug>`

## Pořadí + jak spustit (v Claude Code session)
Stačí říct Claude Code větu níže; podle `name` vybere agenta z `.claude/agents/`. Detailní misi má každý agent ve své definici.

1. **niche-research** (PRVNÍ, read-only — rozhodne sekvenci):
   `> Spusť niche-research agenta.`
   → dostaneš skórovaný report + 90-denní roadmap. Podle něj pokračuj.
2. **content-builder** (nová stránka z clusteru):
   `> Spusť content-builder na keyword cluster "<cluster z roadmapu>".`
   → agent si založí worktree → build+--check → PR k review.
3. **tool-onboarding** (přidat tool/model):
   `> Spusť tool-onboarding, přidej <tool> do automation (zdroj: <ceník URL>).`
4. **seo-optimizer** (až ~3 týdny GSC dat, cca 12.7.):
   `> Spusť seo-optimizer.`
5. **ops-triage** (denně/týdně, audit PRs):
   `> Spusť ops-triage.`
6. **bookkeeping** (měsíčně, read-only Wise):
   `> Spusť bookkeeping za <měsíc>.`
7. **orchestrator** (až běží 2-3 agenti — rozdá úkoly sám):
   `> Spusť orchestrátora.`

## Neměnné brány (stop-and-confirm)
Ceny / affiliate / ads / peníze / legal = **vždy přes PR/draft, schvaluje člověk**. Žádný agent je nemerguje sám (vynuceno `guard.mjs` + PR + read-only Wise scope). Faceless: žádné jméno/tvář/outreach/prodej.

## Cost
Agenti jen na úsudek; deterministika = crony/skripty. Rozumná kadence, NE always-on. Triage/bookkeeping běží na haiku.
