# Drift report — automationcost.io pricing

Nástrojů ke kontrole: **3** (activepieces, node-red, zapier)

> Review-based: tenhle report data webu NEMĚNÍ. Ověř ⚠ položky na webu nástroje, schválené změny zapiš do `data/tools.json` a spusť `python build.py`.

### activepieces — ⚠ REVIEW

| field | site (data/tools.json) | scraped |
|---|---|---|
| integrations | 200 | 700 | ⚠
| cheapest cloud $/mo | 10 | 5.0 | ⚠

<details><summary>scraped plans (raw)</summary>

- Standard: $5.0/mo, ops=—, wf=—
- Ultimate: $—/mo, ops=—, wf=—

</details>

_Cenu zmiňují stránky k ruční kontrole:_ activepieces-pricing.html

### automatisch — ✓ looks current

| field | site (data/tools.json) | scraped |
|---|---|---|
| integrations | 50 | — |
| cheapest cloud $/mo | 20 | — |

### make
- ℹ v datech webu, ale poslední scrape chybí.

### n8n — ✓ looks current

| field | site (data/tools.json) | scraped |
|---|---|---|
| integrations | 400 | — |
| cheapest cloud $/mo | 20 | 20.0 |

<details><summary>scraped plans (raw)</summary>

- Starter: $20.0/mo, ops=2500, wf=—
- Pro: $50.0/mo, ops=10000, wf=—
- Business: $667.0/mo, ops=40000, wf=—
- Enterprise: $—/mo, ops=—, wf=—

</details>

### node-red — ⚠ REVIEW

| field | site (data/tools.json) | scraped |
|---|---|---|
| integrations | 1000 | 5000 | ⚠
| cheapest cloud $/mo | — | — |

_Cenu zmiňují stránky k ruční kontrole:_ node-red-pricing.html

### pipedream — ✓ looks current

| field | site (data/tools.json) | scraped |
|---|---|---|
| integrations | 2000 | — |
| cheapest cloud $/mo | 29 | — |

### zapier — ⚠ REVIEW

| field | site (data/tools.json) | scraped |
|---|---|---|
| integrations | 7000 | 9000 | ⚠
| cheapest cloud $/mo | 20 | 19.99 | ⚠

<details><summary>scraped plans (raw)</summary>

- Free: $0.0/mo, ops=100, wf=—
- Professional: $19.99/mo, ops=—, wf=—
- Team: $69.0/mo, ops=—, wf=—
- Enterprise: $—/mo, ops=—, wf=—

</details>

_Cenu zmiňují stránky k ruční kontrole:_ zapier-pricing.html
