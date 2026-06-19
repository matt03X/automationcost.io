# WizardCost Alerts — odesílání price-alert mailů z iPhonu (Apple Shortcut)

Soukromé tlačítko na iPhonu, kterým z mobilu odešleš subscriberům price-alert
kampaň (draft, který založí `scripts/send_price_alerts.py` při revizi). Statistiky
(odběratelé, open/click rate, historie) vidíš v **MailerLite appce / mobilním webu**.

```
iPhone Shortcut ──tap──► Cloudflare Worker (drží token) ──► MailerLite (odešle)
   (potvrzení)            auth = SHORTCUT_SECRET            stats v ML appce
```

**Proč Worker:** MailerLite token NESMÍ být v telefonu/frontendu (kdokoli by ho
viděl). Worker ho drží jako šifrovaný secret a Shortcut volá jen jeho.

Celý tok:
1. Audit najde změnu → přijde ti GitHub mail „běž ověřit".
2. U PC ověříš reálnou cenu, upravíš `tools.json`, build + deploy.
3. U PC spustíš `python scripts/send_price_alerts.py` → vznikne **draft** v MailerLite.
4. Z iPhonu ťukneš Shortcut → potvrdíš → **draft se odešle** subscriberům.
5. Statistiky sleduješ v MailerLite appce.

---

## 1) Deploy Workeru — přes web (bez programování, doporučeno)

1. Založ si free účet na **cloudflare.com**.
2. **Workers & Pages → Create → Workers → Create Worker.** Jméno: `wizardcost-alerts` → **Deploy**.
3. **Edit code** → smaž vzorový kód → vlož celý obsah [`worker.js`](worker.js) → **Deploy**.
4. **Settings → Variables and Secrets → Add**, typ **Secret** (Encrypted):
   - `MAILERLITE_API_TOKEN` = token z MailerLite (*Integrations → API → Generate new token*)
   - `SHORTCUT_SECRET` = tvůj náhodný řetězec (vygenerovaný, viz níže)
   - `LLM_GROUP_ID` *(volitelné)* = id MailerLite skupiny pro LLM, až ji založíš
5. **Deploy** znovu (aby se secrets načetly). Worker URL bude:
   `https://wizardcost-alerts.<tvuj-subdomain>.workers.dev`
6. **Rychlý test:** otevři `…/status` v prohlížeči → musí přijít `{"error":"unauthorized"}`
   (401). To je správně = je to chráněné, bez klíče nikdo nic neudělá.

### Deploy přes CLI (alternativa)
```bash
npm i -g wrangler
wrangler login
cd scripts/alerts-worker
wrangler deploy
wrangler secret put MAILERLITE_API_TOKEN
wrangler secret put SHORTCUT_SECRET
# volitelně: wrangler secret put LLM_GROUP_ID
```

---

## 2) Apple Shortcut „WizardCost Alert"

Appka **Zkratky** (Shortcuts) → **+** → pojmenuj `WizardCost Alert`. Přidej akce
v tomhle pořadí (každou najdeš přes „Add Action" / lupu):

1. **Get Contents of URL**
   - URL: `https://wizardcost-alerts.<tvuj-subdomain>.workers.dev/status`
   - rozbal **Show More**: Method = `GET`
   - **Headers → Add**: klíč `Authorization`, hodnota `Bearer <SHORTCUT_SECRET>`
2. **Get Dictionary Value** → Get `Value` for key **`draft`** (z výstupu kroku 1)
3. **If** → `Dictionary Value` **has no value**
   - uvnitř: **Show Alert** „Žádný draft k odeslání." → **Stop Shortcut**
   - **Otherwise** (zbytek dáš sem, nebo nech If skončit a pokračuj dál):
4. **Get Dictionary Value** → Get `Value` for key **`subscribers`** (z kroku 1) → to je počet odběratelů
5. **Get Dictionary Value** → Get `Value` for key **`subject`** (z `draft` dictionary z kroku 2)
6. **Show Alert**
   - Title: `Odeslat alert?`
   - Message: `„[Subject]" → [Subscribers] odběratelům` (vlož proměnné z kroků 5 a 4)
   - Nech zapnuté **Show Cancel Button** → při Cancel se Shortcut zastaví
7. **Get Contents of URL**
   - URL: `https://wizardcost-alerts.<tvuj-subdomain>.workers.dev/send`
   - Method = `POST`
   - Headers → `Authorization` = `Bearer <SHORTCUT_SECRET>`
8. **Get Dictionary Value** → key **`sent`**
9. **Show Notification** → text např. `Odesláno ✅` (klidně přidej Subject)

Pak **Shortcut → sdílet → Add to Home Screen** = ikona jako appka. Funguje i z
Apple Watch a přes Siri („Hej Siri, WizardCost Alert").

> Tip: pro LLM site přidej do obou URL `?site=llm` (a v Cloudflare nastav `LLM_GROUP_ID`).
> Můžeš mít dva Shortcuty (automation / llm), nebo jeden s „Choose from Menu".

---

## 3) Týdenní SEO digest — „ping na iPhone" (cloud routine → telefon)

Druhý tok, opačný směr než alerty: **cloud routine** (Claude Code na Anthropic cloudu,
běží i s vypnutým noťasem) jednou týdně vyrobí SEO digest a uloží ho do Workeru; telefon
ho ráno vyzvedne a ukáže notifikaci.

```
Cloud routine ──POST /digest──► Worker (KV, za authem) ◄──GET /digest── iPhone Shortcut
 (machine-off)   shrnutí+akce                                            (Po ráno → notifikace)
```

### a) Zapni KV storage (jednorázově)
- **Dashboard:** Workers & Pages → **KV** → *Create namespace* (název třeba `wizardcost-digest`).
  Pak Worker `wizardcost-alerts` → **Settings → Variables → KV Namespace Bindings → Add**:
  Variable name = `DIGEST`, vyber namespace → **Deploy**.
- **Nebo CLI:** `wrangler kv namespace create DIGEST` → vypsané `id` vlož do `wrangler.toml`
  (placeholder `REPLACE_WITH_KV_NAMESPACE_ID`) → `wrangler deploy`.
- **Test:** `GET …/digest` bez klíče → 401; s klíčem a prázdným KV → `{"site":"automation","digest":null}`.

### b) iPhone Shortcut „WizardCost Digest" + týdenní automatizace
Nový Shortcut (akce v pořadí):
1. **Get Contents of URL** → `https://wizardcost-alerts.<subdomain>.workers.dev/digest`,
   Method `GET`, Header `Authorization` = `Bearer <SHORTCUT_SECRET>`.
2. **Get Dictionary Value** → key `summary` (a volitelně `date`, `actions`).
3. **If** `summary` *has any value* → **Show Notification** s textem `Summary` (+ `Date`).
   Jinak **Show Notification** „Digest zatím není".

Pak **Zkratky → Automatizace → +** → spouštěč **Čas** (např. Po 09:30) → akce *Spustit zkratku*
„WizardCost Digest" → vypni „Před spuštěním se zeptat". Telefon ti tak v pondělí sám bzikne digest.

### c) Cloud routine, která digest plní
Viz runbook [`docs/architect-mode.md`](../../docs/architect-mode.md) — sekce „Fáze 3". V kostce:
routine přes `/schedule` (Po ~08:00 UTC, po `marketing-snapshot`) spustí `/seo-digest` a na konci
udělá `POST /digest` se `summary` + `actions`. Read-only, nic veřejného.

---

## Bezpečnost
- **Token** je jen v Cloudflare secret — nikdy v repu ani v telefonu.
- **Digest** je v KV jen za `SHORTCUT_SECRET` authem → privátní (žádná veřejná raw URL).
- Bez správného `SHORTCUT_SECRET` Worker vrátí **401** a nic neudělá.
- Shortcut se **ptá na potvrzení** (předmět + počet odběratelů) → žádné omylem
  odeslané maily. Sedí to s pravidlem „ceny = stop-and-confirm".
- Worker pošle jen **existující draft** pojmenovaný `Price alert (<site>)` —
  nemůže omylem poslat cizí kampaň.
