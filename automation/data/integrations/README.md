# Integrations audit — dataset

Týdenní snapshot **kompletního katalogu integrací** (apps / connectors / nodes) všech
7 sledovaných automatizačních nástrojů. Sesterský systém k cenovému auditu
(`automation/data/audit/`), jen pro integrace místo cen.

Generuje **`scripts/integrations-audit.js`**, spouští **`.github/workflows/integrations-audit.yml`**
(cron: pondělí 05:30 UTC). Vše přes Playwright/chromium (node `fetch` má v prostředí
rozbité TLS; Make je navíc za Cloudflare — headless chromium projde).

## Soubory

| Soubor | Co je |
|---|---|
| `<vendor>/latest.json` | Aktuální kompletní seznam integrací nástroje: `{ vendor, scrapedAt, source, count, integrations: [{slug, name, category?}] }`. **Přepisuje se** každý běh; git historie souboru = evidence vývoje (1 záznam/řádek → čisté diffy). |
| `counts.json` | Rychlá reference: vendor → počet integrací (+ datum). |
| `changes-<YYYY-MM-DD>.json` | Change report jednoho běhu: `changeCount`, `addedCount`, `removedCount`, per-vendor `added`/`removed`, `warnings`, plochý `changes[]`. Řídí alarm. |
| `integrations-history.jsonl` | Append-only log událostí (1 řádek = 1 přidání/odebrání): `{d, vendor, change, slug, name}`. Zdroj pro budoucí graf/feed změn. |

## Zdroje (ověřeno 2026-06-23, vše bez auth)

| Vendor | Zdroj | Mechanismus |
|---|---|---|
| zapier | `zapier.com/api/v4/apps/?offset=N` | same-origin fetch z app directory, 10/stránku (~970 stran) |
| make | `make.com/en/integrations/api/get-apps?offset=N` | same-origin fetch, 48/stránku (za Cloudflare) |
| n8n | `api.n8n.io/api/nodes` | oficiální Strapi, pageSize=100 |
| pipedream | GitHub git-tree `PipedreamHQ/pipedream` `components/` | REST `/v1/apps` je OAuth-only; contents API capped na 1000 → git-tree |
| activepieces | `cloud.activepieces.com/api/v1/pieces` | veřejné JSON pole, bez paginace |
| automatisch | GitHub contents `automatisch/.../src/apps` | seznam podsložek (konektorů) |
| node-red | `catalogue.nodered.org/catalogue.json` | oficiální komunitní katalog |

## Notifikace (alarm)

Stejný model jako cenový audit: workflow **failne (= mail ownerovi) JEN když
`changeCount > 0`** — tedy reálně přibyla/zmizela integrace u některého nástroje.
Bot-wall, dočasná nedostupnost a **podezřelý propad počtu** (nový počet < 60 %
předchozího → nejspíš částečný scrape) = **WARN**: drží se předchozí snapshot,
žádný alarm, žádná ztráta dat. Robustnost před hlučností.

## Princip

**Audit data jsou EVIDENCE, ne zdroj pravdy** — stejně jako u cen, wayback auditu a
drift-reportu. Číslo `integrations` v `tools.json` (a jakákoli veřejná tvrzení o
počtu/pokrytí integrací) aktualizuje **člověk po revizi** change reportu, ne tento
scraper automaticky.

## Spuštění lokálně

```bash
# z hlavního checkoutu, Playwright z calc-test:
NODE_PATH=<calc-test>/node_modules node scripts/integrations-audit.js            # vše
NODE_PATH=<calc-test>/node_modules node scripts/integrations-audit.js automatisch # jen jeden
node scripts/integrations-audit.js --selftest                                    # diff/normalize bez sítě
```

> **Pozn.:** budoucí krok (samostatný PR) = veřejná stránka „integration finder",
> kde uživatel vybere integraci a vyfiltruje nástroje, co ji nemají. Tento dataset
> (per-tool katalogy + normalizace) je její datová vrstva.
