# Claude Design → Claude Code: verdikty, batch 1 (2026-06-11)

Pole pro `automation/data/pairs.json`. Vkládat doslovně (UTF-8). U párů 1 a 4 nese
výhradu i stripNote — kdyby byl moc dlouhý, zkrať na `self-hosted` / `up to 10 flows`,
ale výhrada nesmí zmizet. U páru 2 pohlídej, koho FAQ označí za „loser" — whyLoser
je psané pro Make. Počty integrací pro n8n/Pipedream/Activepieces záměrně neuvádím
(nemám aktuální čísla) — kdyby je generátor potřeboval, pošlete hodnoty.

---

## 1) zapier-vs-n8n

**verdikt (HTML):**

<b class="win">n8n runs at a flat ~$8/mo at every volume</b> — but only if you self-host it; <b>Zapier is the no-code path with 9,000+ integrations</b>. The $8 is Community Edition on a VPS you maintain yourself — if nobody on your team wants to own a server, compare against n8n Cloud ($20–50/mo, with workflow limits) instead: still cheaper than Zapier's ~$130–$1,065, but no longer a rout.

**stripNote:** at every volume we track — self-hosted

**whyLoser (Zapier):**

Because n8n's $8 assumes you run it yourself — installing, updating, backing up and monitoring your own server. If that's not your team, the realistic alternative is n8n Cloud at $20–50/mo with workflow limits. Zapier's no-code editor and 9,000+ integrations mean a non-technical person can build and own automations without engineering — that convenience is what the premium buys.

---

## 2) make-vs-n8n

**verdikt (HTML):** *(bez stripNote — vítěz se střídá)*

<b>Price barely separates these two</b> — Make's free tier wins at 1,000 ops, n8n's flat ~$8/mo self-hosted wins above it, and at 5,000 ops the gap is exactly $1. <b class="win">The real decision is whether you want to run a server</b>: happy to self-host → n8n; want a managed cloud with a visual builder → Make. Either way, you won't overpay by much.

**stripNote:** *(žádný)*

**whyLoser (Make):**

Because self-hosting isn't free in practice — n8n's $8 is a VPS you patch, back up and monitor yourself. Make is fully managed, its free tier covers 1,000 ops/mo outright, and even at 100,000 ops it's ~$45/mo. If nobody on the team wants server keys, Make is the sane default — you're paying a few dollars for zero ops burden.

---

## 3) zapier-vs-pipedream

**verdikt (HTML):**

<b class="win">Pipedream is roughly 3–4× cheaper at every volume we track</b>; <b>the catch is who it's built for</b> — Pipedream is code-first (Node/Python steps), Zapier is no-code. If your team writes code, Pipedream gives you more power for a fraction of the price. If "add a code step" sounds like a blocker, Zapier's 9,000+ integrations and point-and-click editor are what you're paying for.

**stripNote:** at every volume we track

**whyLoser (Zapier):**

Because Pipedream's price assumes someone on the team is comfortable in code — workflows lean on Node/Python steps and the whole UI is aimed at developers. With Zapier, a marketer or ops person can ship an automation alone: no-code editor, 9,000+ integrations, huge template library. If that's who's building, Zapier earns its premium.

---

## 4) n8n-vs-activepieces

**verdikt (HTML):**

<b class="win">Activepieces Cloud runs this at $0</b> — unlimited runs, free up to 10 active flows (we price 3); <b>n8n is the deeper toolkit once automations get complex</b>. Both are open-source and self-hostable, so philosophy doesn't decide this one: start free on Activepieces if 10 flows is enough, move to n8n (~$8/mo self-hosted) when you need its bigger node ecosystem and heavier workflow logic.

**stripNote:** at every volume we track — up to 10 active flows

**whyLoser (n8n):**

Because the $0 has a ceiling: 10 active flows on Activepieces Cloud, then $5 per extra flow. n8n self-hosted stays ~$8/mo no matter how many workflows you run, and its larger ecosystem and more mature advanced logic (branching, error handling, code nodes) start to matter once automations get serious. Heavy or complex usage tips the math back to n8n.
