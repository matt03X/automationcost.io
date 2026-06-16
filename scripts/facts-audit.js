#!/usr/bin/env node
/**
 * facts-audit.js — periodický AUDIT NE-cenových faktů (PoC).
 *
 * Sourozenec scripts/price-audit.js: zatímco price-audit hlídá CENY, tohle hlídá
 * fakta, která se na vs-stránkách berou z tools.json a opisují do pairs.json prózy:
 *   - počet integrací (nejvíc drift-prone, prominentní „N 000+")
 *   - open-source / self-host signál
 * Postup (vzor price-audit):
 *   1) page.goto oficiální stránky vendora (node fetch má v tomhle prostředí
 *      rozbité TLS → vše přes Playwright)
 *   2) deterministická extrakce (regex nad vyrenderovaným textem)
 *   3) snapshot → automation/data/facts-audit/<vendor>/<YYYY-MM-DD>.json
 *      (+ <YYYY-MM-DD>.html.gz jen poprvé / při změně)
 *   4) diff proti claimedValue v tools.json → facts-audit/changes-<YYYY-MM-DD>.json
 *
 * EVIDENCE-ONLY: NIKDY needituje tools.json. Workflow failne (= mail) jen při reálném
 * rozporu (changeCount>0); bot-wall = WARN (neshodí). Skript sám exit 1 jen při tvrdé chybě.
 *
 * LLM booster (volitelný, NENÍ závislost): když regex číslo nenajde (změněný layout),
 * lze text poslat levnému modelu na extrakci — viz scripts/facts-extract-llm.js (návrh).
 *
 * Spuštění:
 *   NODE_PATH=../../calc-test/node_modules node scripts/facts-audit.js            # všichni
 *   NODE_PATH=../../calc-test/node_modules node scripts/facts-audit.js n8n make   # vybraní
 *   node scripts/facts-audit.js --no-diff           # jen snapshoty
 *   node scripts/facts-audit.js --headed            # vidět browser
 */
"use strict";
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36";
const REPO = path.resolve(__dirname, "..");
const FACTS_DIR = path.join(REPO, "automation", "data", "facts-audit");
const TOOLS_JSON = path.join(REPO, "automation", "data", "tools.json");
const TODAY = new Date().toISOString().slice(0, 10);
const HEADED = process.argv.includes("--headed");
const NO_DIFF = process.argv.includes("--no-diff");
const DELTA_TOL = 0.15;   // |scraped-claimed|/claimed > 15 % → flag (integrace rostou pomalu)

// ── vendor katalog: kde a jak číst počet integrací ──────────────────────────
// keywords = slova za číslem; bereme NEJVĚTŠÍ plausibilní shodu (integrace = velké číslo)
const VENDORS = {
  zapier:       { url: "https://zapier.com/apps",                 kw: ["apps", "integrations"] },
  make:         { url: "https://www.make.com/en/integrations",    kw: ["Integration Apps", "integrations", "apps"] },
  n8n:          { url: "https://n8n.io/integrations/",            kw: ["integrations", "nodes"] },
  pipedream:    { url: "https://pipedream.com/apps",              kw: ["apps", "APIs", "integrations"] },
  activepieces: { url: "https://www.activepieces.com/pieces",     kw: ["Integrations", "pieces"] },
  automatisch:  { url: "https://automatisch.io/",                 kw: ["integrations", "apps"] },
  "node-red":   { url: "https://flows.nodered.org/",              kw: ["nodes", "flows"] },
};

function vendorDir(v) { const d = path.join(FACTS_DIR, v); fs.mkdirSync(d, { recursive: true }); return d; }

function previousSnapshot(v) {
  const d = vendorDir(v);
  const files = fs.readdirSync(d).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f) && f.slice(0, 10) < TODAY).sort();
  if (!files.length) return null;
  const f = files[files.length - 1];
  try { return { date: f.slice(0, 10), data: JSON.parse(fs.readFileSync(path.join(d, f), "utf8")) }; }
  catch { return null; }
}

// největší číslo, které v textu stojí těsně před některým z klíčových slov
function extractCount(text, keywords) {
  let best = null, evidence = null;
  for (const kw of keywords) {
    const re = new RegExp("([\\d][\\d,\\.]{1,})\\s*\\+?\\s*" + kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    let m;
    while ((m = re.exec(text))) {
      const n = Number(m[1].replace(/[,\.]/g, ""));
      if (Number.isFinite(n) && n >= 30 && (best === null || n > best)) { best = n; evidence = m[0].trim().slice(0, 60); }
    }
  }
  return { count: best, evidence };
}

let _browser = null;
async function browser() {
  if (!_browser) { const { chromium } = require("playwright"); _browser = await chromium.launch({ headless: !HEADED }); }
  return _browser;
}

async function scrapeVendor(v) {
  const page = await (await (await browser()).newContext({ userAgent: UA })).newPage();
  try {
    const res = await page.goto(VENDORS[v].url, { waitUntil: "domcontentloaded", timeout: 60000 });
    if (!res || !res.ok()) throw new Error(`HTTP ${res ? res.status() : "?"}`);
    await page.waitForTimeout(3500);  // JS-rendered počítadla (n8n/pipedream/activepieces)
    const html = await page.content();
    const text = await page.evaluate(() => document.body.innerText);
    const { count, evidence } = extractCount(text, VENDORS[v].kw);
    const openSource = /open[\s-]?source|self[\s-]?host|github\.com/i.test(text);
    if (count === null) throw new Error("počet integrací nenalezen (změna layoutu / bot wall)");
    return { vendor: v, url: VENDORS[v].url, integrations: count, openSourceSignal: openSource, evidence, html };
  } finally { await page.close(); }
}

(async () => {
  const only = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const vendors = only.length ? only : Object.keys(VENDORS);
  const claimed = {};
  for (const t of JSON.parse(fs.readFileSync(TOOLS_JSON, "utf8")).tools) claimed[t.slug] = t.integrations;

  let failures = 0, blocked = 0;
  const allChanges = [];

  for (const v of vendors) {
    if (!VENDORS[v]) { console.log(`(přeskakuji neznámého vendora: ${v})`); continue; }
    try {
      const snap = await scrapeVendor(v);
      const dir = vendorDir(v);
      const prev = previousSnapshot(v);
      const out = { date: TODAY, vendor: v, url: snap.url, integrations: snap.integrations,
        openSourceSignal: snap.openSourceSignal, evidence: snap.evidence };
      fs.writeFileSync(path.join(dir, `${TODAY}.json`), JSON.stringify(out, null, 2) + "\n", "utf8");
      // html.gz jen poprvé / při změně počtu (repo by jinak rostlo)
      if (!prev || prev.data.integrations !== snap.integrations)
        fs.writeFileSync(path.join(dir, `${TODAY}.html.gz`), zlib.gzipSync(snap.html));

      // diff proti claimedValue v tools.json (TOHLE je smysl auditu)
      const claim = claimed[v];
      if (typeof claim === "number" && claim > 0) {
        const delta = Math.abs(snap.integrations - claim) / claim;
        if (delta > DELTA_TOL) {
          allChanges.push({ vendor: v, field: "integrations", claimed: claim, scraped: snap.integrations,
            deltaPct: Math.round(delta * 100),
            desc: `${v}: tools.json uvádí ${claim} integrací, oficiální stránka ${snap.integrations} (${Math.round(delta*100)} % rozdíl) — revidovat` });
        }
      }
      console.log(`✓ ${v}: ${snap.integrations} integrací (claim ${claim ?? "?"})${snap.openSourceSignal ? " · open-source signal" : ""}`);
    } catch (e) {
      const msg = e.message || String(e);
      const isBotWall = /bot|403|429|503|timeout|Timeout|nenalezen|HTTP \?/i.test(msg);
      if (isBotWall) { console.log(`⚠ WARN ${v} (bot wall / layout, ne změna faktu): ${msg.slice(0, 70)}`); blocked++; }
      else { console.log(`SELHALO ${v}: ${msg}`); failures++; }
    }
  }

  if (_browser) await _browser.close();

  if (!NO_DIFF) {
    fs.mkdirSync(FACTS_DIR, { recursive: true });
    const report = { date: TODAY, generatedAt: new Date().toISOString(), changeCount: allChanges.length, changes: allChanges };
    fs.writeFileSync(path.join(FACTS_DIR, `changes-${TODAY}.json`), JSON.stringify(report, null, 2) + "\n", "utf8");
    if (allChanges.length) {
      const line = allChanges.map((c) => JSON.stringify({ d: TODAY, ...c })).join("\n") + "\n";
      fs.appendFileSync(path.join(FACTS_DIR, "facts-history.jsonl"), line, "utf8");
    }
    console.log(`\n📋 ${allChanges.length} faktických rozporů → facts-audit/changes-${TODAY}.json`);
    for (const c of allChanges) console.log(`   • ${c.desc}`);
  }
  if (blocked) console.log(`⚠ ${blocked} vendor(ů) neověřeno (bot wall / layout) — ne fail.`);
  process.exit(failures ? 1 : 0);   // exit 1 jen tvrdá chyba; alarm na changeCount řeší workflow
})();
