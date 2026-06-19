# Architect mode — autonomní, machine-off vrstva (runbook)

Cíl: Level 5 z „5 úrovní Clauda" = vždy-zapnutá autonomní infrastruktura, která pracuje,
i když máš zavřený noťas. WizardCost už má deterministickou cron vrstvu (5 GitHub Actions),
tohle přidává **agentní** vrstvu + **enforcement hooky**, které autonomní běh dělají
důvěryhodným. Bloker Level 5 je **důvěra, ne technika** — proto guardraily první.

Co je hotové v repu (kód) vs. co zapneš ručně (UI/telefon) je označené 🟢 / 🟦.

---

## Fáze 1 — enforcement hooky (trust foundation) 🟢 hotové

Deterministické vynucení tvrdých pravidel (platí i v autonomním běhu, ne jen jako paměť).
PreToolUse hook umí edit/příkaz **tvrdě zablokovat** (exit 2), PostToolUse spustí build-check.

| Guard | Co dělá | Soubor |
|---|---|---|
| 1 off-limits | blok editů/příkazů do `JOB/`, `suno NEONGHOST/`, `PLAN-AI-pasivni-byznys.md` | workspace root `.claude/{settings.json, hooks/offlimits.mjs}` (3 úrovně nad repem) |
| 2 GA4/formuláře | blok re-enable GA4 (`gtag`, `G-…`) nebo e-mail formulářů na HTML/`build*.py` | `.claude/hooks/guard.mjs` |
| 3 cena/affiliate | stop-and-confirm na `tools.json`, `models.json`, `scoring-model.json`, `pairs.json`, Make affiliate odkazy | `.claude/hooks/guard.mjs` |
| 4 build --check | po editu generovaných zdrojů spustí `build.py --check` → ohlásí drift hned | `.claude/hooks/guard.mjs` (PostToolUse) |

**Lokální vs. autonomní (routine) běh:** rozlišuje se env flagem, který je **jen** ve
`.claude/settings.local.json` (gitignored → routine ho nikdy nedostane):
- `WIZARDCOST_ALLOW_SENSITIVE` — lokálně tvoje cenové edity jen **warnují** (exit 1) místo blok;
  v routine (bez flagu) **blok** (exit 2).
- `WIZARDCOST_ALLOW_GA4` — vědomé povolení re-enable GA4/formulářů po revizi (jinak vždy blok).
  `SENSITIVE` ho **neobchází** — GA4 má vlastní, přísnější flag.

**Ověření** (14/14 prošlo při buildu): nakrm guard přes stdin ukázkovým `tool_input` JSON,
zkontroluj exit kód (2=blok, 1=warn, 0=ok). Reálně: zkus edit do `JOB/` → musí být odmítnut.

> Pozn.: repo hooky (`.claude/settings.json`) se aktivují, když session/routine běží
> uvnitř repa. Off-limits guard je na úrovni workspace (kryje i složky mimo repo).

---

## Fáze 2 — slash commandy (Level 4 → krmí routine) 🟢 hotové

V `.claude/commands/` (commitnuté → fungují i v routine):

- **`/ship [soubory]`** — build + `--check` + relevantní testy + deploy do `master`.
  Stage **jen explicitní soubory** (nikdy `git add -A`); push je stop-and-confirm.
- **`/seo-digest`** — týdenní SEO digest přes `marketing-specialist` z `marketing-data`
  snapshotu (read-only). Tohle volá i routine.
- **`/verify-prices <slug>`** — ověř ceny proti živému ceníku přes `calc-test/verify-pricing-live.js`.

---

## Fáze 3 — první cloud routine: týdenní SEO digest → iPhone 🟦 zapneš ručně

Low-stakes „start na prázdném parkovišti": read-only, jde jen tobě, nic ven.

### 1) Worker `/digest` + KV 🟢 kód hotový / 🟦 KV zapni
Worker (`scripts/alerts-worker/worker.js`) má nové `GET/POST /digest` (KV binding `DIGEST`,
auth `SHORTCUT_SECRET`). Zapni KV namespace dle `scripts/alerts-worker/README.md` → sekce 3a.

### 2) iPhone Shortcut „WizardCost Digest" 🟦
Po-ranní pull `GET /digest` → notifikace. Kroky v `scripts/alerts-worker/README.md` → sekce 3b.

### 3) Cloud routine přes `/schedule` 🟦 (beta)
V Claude Code session **připoj GitHub** (routine si naklonuje `cost.io/wizardcost`).
Do routine settings přidej env/secrety: `WORKER_URL` (= URL Workeru) a `SHORTCUT_SECRET`.

- **Cadence:** týdně, **Po ~08:00 UTC** (po `marketing-snapshot` v 07:00 Po → data čerstvá).
- **Nejdřív one-off dry-run** (`/schedule` nabídne; one-off se nepočítá do denního capu).
- **Prompt routiny** (vlož):

  > Spusť `/seo-digest`. Z jeho výstupu vezmi jednořádkové shrnutí a top-3 akce a pošli je na
  > telefon: `curl -s -X POST "$WORKER_URL/digest?site=automation" -H "Authorization: Bearer $SHORTCUT_SECRET" -H "Content-Type: application/json" -d '{"summary":"<shrnutí>","actions":["<a1>","<a2>","<a3>"],"full":"<celý digest>"}'`.
  > Digest ulož i jako `seo-digest-<datum>.md` na větev `marketing-data`. NIC neměň na webu,
  > NEcommituj do master, neposílej nic e-mailem. (Guardy v repu tě stejně udrží read-only.)

### Trust ladder (z videa — ber vážně)
Nech routinu běžet **týdny bez zásahu**. Sleduj, jestli digest dává smysl. Teprve až jí věříš,
přidej vyšší-hodnotové routiny (Fáze 4).

---

## Fáze 4 — později (až po vybudování důvěry) 🟦

- **Reviewer cenových PR** (GitHub-event routine na `auto/price-update-*` PR) — okomentuje diff
  vs. audit evidence. **Jen komentuje, nikdy nemerguje** (Guard 3 to jistí).
- **Digest audit změn** (facts-audit / vs-crosscheck evidence → čitelné doporučení).
- **Agent teams** na paralelní research, až bude session budget.

---

## Caveaty
- **Cloud routines = beta** (research preview): denní cap na běhy, GitHub webhook má hodinové
  capy, API/limity se můžou měnit.
- **`channels`** (Telegram/Discord/iMessage) fungují **jen pro lokální session**, ne pro routine
  — proto ping řešíme přes Worker, ne přes channel.
- **Faceless:** digest jde jen tobě (KV za authem), žádný veřejný výstup, žádný e-mail sběr, cookieless.
- Mýty z videa, které **nepoužíváme** (neexistují jako shipping featura): `autodream`, `task budgets`.
