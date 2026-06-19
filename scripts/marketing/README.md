# Marketing konektory — setup

Stálý „marketingový analytik": stáhne živá data o webu (SEO + traffic), abychom je
mohli číst a optimalizovat web. Týdenní snapshot commituje workflow
`.github/workflows/marketing-snapshot.yml` do **větve `marketing-data`** (Pages ji
NEservíruje → tvoje keyword/traffic data zůstanou privátní, ale verzovaná).

| Konektor | Soubor | Co vrací | Setup |
|---|---|---|---|
| Google Search Console | `gsc_pull.py` | dotazy, stránky, pozice, impressions, CTR, vývoj (28 d) | service account |
| Cloudflare Web Analytics | `cf_pull.py` | pageviews, země, referrery, cesty, vývoj (28 d) | API token |
| orchestrátor | `snapshot.py` | spojí oba → `<datum>.json` + `latest.json` | — |

Tokeny: `os.environ` → fallback `engine/.env` (gitignored, **nikdy do repa**).
V GitHub Actions přidej stejné klíče jako **repo secrets**.

---

## 1) Google Search Console (service account)

1. [console.cloud.google.com](https://console.cloud.google.com) → vytvoř/zvol projekt.
2. **APIs & Services → Library** → zapni **„Google Search Console API"**.
3. **APIs & Services → Credentials → Create credentials → Service account** → vytvoř.
4. U service accountu **Keys → Add key → JSON** → stáhne se `*.json`.
5. V [Search Console](https://search.google.com/search-console) → **Settings → Users and permissions
   → Add user** → vlož e-mail service accountu (`…@….iam.gserviceaccount.com`), role **Restricted**.
6. Klíč zpřístupni skriptu:
   - **Lokálně** (`engine/.env`): `GSC_SA_JSON_PATH=C:\cesta\k\klici.json`
   - **GitHub secret**: `GSC_SA_JSON` = celý obsah toho JSON souboru.
7. (Volitelné) `GSC_SITE_URL` — default `sc-domain:wizardcost.com`. Pokud máš v GSC
   URL-prefix property místo domain property, dej `https://wizardcost.com/`.

## 2) Cloudflare Web Analytics (API token)

1. [dash.cloudflare.com](https://dash.cloudflare.com) → **My Profile → API Tokens → Create Token**.
2. Šablona **„Read analytics and logs"** (nebo custom: *Account → Account Analytics → Read*).
3. **Account ID**: na úvodní stránce účtu (vpravo) nebo v URL dashboardu.
4. Do env / secrets:
   - `CLOUDFLARE_API_TOKEN=…`
   - `CLOUDFLARE_ACCOUNT_ID=…`
   - `CLOUDFLARE_SITE_TAG` — volitelné, default je site token z `beacon.min.js`.

---

## Spuštění lokálně

```bash
pip install google-auth requests truststore
python scripts/marketing/gsc_pull.py        # jen GSC → JSON
python scripts/marketing/cf_pull.py         # jen Cloudflare → JSON
python scripts/marketing/snapshot.py --out _marketing-out   # oba → snapshot
```

## Automaticky (týdně)

Workflow `marketing-snapshot` běží **po → 07:00 UTC** (i ručně přes *Run workflow*).
Commit jde do větve `marketing-data`. Čtení agentem:
`git fetch origin marketing-data && git show origin/marketing-data:latest.json`.

> **První běh:** Cloudflare GraphQL schéma RUM je citlivé na názvy dimenzí. Když
> `cf_pull.py` vrátí `errors`, doladíme názvy polí podle hlášky (countryName / refererHost
> / requestPath). GSC je stabilní.
