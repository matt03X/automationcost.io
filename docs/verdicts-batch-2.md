# Claude Design → Claude Code: verdikty, batch 2 (2026-06-12)

Pole pro `automation/data/pairs.json`. Vkládat doslovně (UTF-8). Stejná pravidla jako
batch 1: stripNote výhrady nesmí zmizet (zkrátit lze na „up to 10 flows" / „self-hosted");
u páru 3 je whyLoser psané pro Make (vítěz od 5k výš je Activepieces, na 1k remíza).
Počty integrací dle revize 11. 6.: Zapier 9,000+ · Pipedream 2,000+ · Make 1,500+ ·
Activepieces 747+ · n8n 400+.

---

## 1) zapier-vs-activepieces

**verdikt (HTML):**

<b class="win">Activepieces runs this at $0 at every volume</b> — free up to 10 active flows (we price 3), then $5 per flow; <b>Zapier's case is its catalog — 9,000+ integrations vs 747+</b>. If your apps are covered in Activepieces' smaller catalog, the price gap ($0 vs $44.99–$1,065) is impossible to argue with. If they aren't, no discount fixes a missing integration.

**stripNote:** at every volume we track — up to 10 active flows

**whyLoser (Zapier):**

Because 747+ integrations covers the popular apps, not the long tail — Zapier's 9,000+ catalog is the deepest in the market, and if your workflow depends on a niche CRM or a regional tool, Zapier is often the only one that has it. Add the most mature template library and a no-code editor honed for non-technical users, and the premium buys certainty that your stack is supported.

---

## 2) make-vs-pipedream

**verdikt (HTML):**

<b class="win">Make is 5–9× cheaper at every volume we track</b> — and this time the no-code tool is the cheap one; <b>Pipedream is the developer's pick</b>. Make's free tier covers 1,000 ops/mo outright and even 100,000 ops runs ~$45 vs ~$400. Choose Pipedream only if your team wants to write Node or Python steps — then the premium buys real programmability.

**stripNote:** at every volume we track

**whyLoser (Pipedream):**

Because Pipedream is built for engineers: workflows are code steps in Node or Python with full access to npm and PyPI packages, an event-data inspector, and 2,000+ integrations behind an API-first design. Make's visual builder hits a ceiling when logic gets genuinely complex — at that point Pipedream's premium is buying capability Make simply doesn't have.

---

## 3) make-vs-activepieces

**verdikt (HTML):** *(bez stripNote — remíza na 1k, vítěz není uniformní)*

<b>Both start at $0 for light usage</b> — at 1,000 ops/mo it's a dead heat; above that, <b class="win">Activepieces stays free while Make starts charging</b> — though never much ($9 to ~$45/mo). The trade: Activepieces is open-source and self-hostable but free only up to 10 active flows (we price 3); Make has the bigger catalog (1,500+ integrations vs 747+) and the more mature cloud. Pick by catalog coverage first — at these prices, money is the tiebreaker, not the decider.

**stripNote:** *(žádný)*

**whyLoser (Make):**

Because Make's costs are modest and predictable while its platform is the more mature one — a bigger integration catalog (1,500+ vs 747+), a more polished scenario builder, and a larger template and community pool. Activepieces' $0 also has a ceiling: 10 active flows, then $5 per flow. A growing team can outgrow it — and at $9–~$45/mo, Make was never a budget risk to begin with.

---

## 4) n8n-vs-pipedream

**verdikt (HTML):**

<b class="win">n8n holds a flat ~$8/mo at every volume — if you self-host it</b>; <b>Pipedream is the managed path for the same developer audience</b>. This isn't no-code vs code — both are dev-friendly. It's your server + open-source vs managed cloud + code steps: if running a VPS is routine for your team, n8n wins on price outright ($8 vs $10–~$400). If you'd rather never touch infrastructure, Pipedream's premium is the hosting bill.

**stripNote:** at every volume we track — self-hosted

**whyLoser (Pipedream):**

Because the ~$8 assumes you operate n8n yourself — and n8n Cloud, the managed alternative, runs $20–50/mo with workflow limits. Pipedream is fully managed, scales without your attention, and its code-step model (Node/Python, npm/PyPI) is arguably the more powerful developer experience. Teams that count engineering hours often find Pipedream's fee cheaper than owning a server.
