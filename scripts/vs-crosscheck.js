#!/usr/bin/env node
/**
 * vs-crosscheck.js — cross-check NAŠICH vs-stránek proti VENDORSKÝM oficiálním
 * „X vs Y" srovnávačkám (n8n.io/vs/*, make.com/en/compare/*, zapier.com/compare/*).
 *
 * !!! ZAUJATÝ SIGNÁL, NE ZDROJ PRAVDY !!!
 * Tyhle stránky jsou MARKETING: navzájem si protiřečí a protiřečí i vlastním
 * integrations stránkám (n8n vs-page „1000+" vs jejich integrations „1868").
 * Smysl tohohle skriptu = (a) chytit, když vendor ZMĚNÍ co o sobě/konkurentovi
 * tvrdí (competitive intel + sanity), (b) dát člověku evidenci k revizi tam, kde
 * se jejich tvrzení liší od našich dat. NIKDY needituje tools.json/pairs.json a
 * NIKDY nepřejímá jejich framing (neutralita vs-stránek se drží jinde).
 *
 * Dva druhy nálezů:
 *   1) changes      = vendor ZMĚNIL své tvrzení od minulého snapshotu (jako price-audit
 *                     diffuje den-proti-dni) → TOHLE spouští alarm (changeCount>0).
 *   2) reviewVsOurData = vendorovo tvrzení ≠ naše tools.json data. EVIDENCE-ONLY,
 *                     NEspouští alarm (hodně z toho je známé marketing rounding /
 *                     zaujatost — řeší lidský úsudek, ne auto-fix).
 *
 * Postup (vzor price-audit / facts-audit): Playwright page.goto (node fetch má
 * rozbité TLS) → snapshot automation/data/vs-crosscheck/<pair>/<YYYY-MM-DD>.{json,html.gz}
 * → diff. Volitelně LLM extrakce (scripts/facts-extract-llm.js) pro lepší atribuci
 * tvrzení k nástroji; bez klíče degraduje na regex.
 *
 * Spuštění:
 *   NODE_PATH=../../calc-test/node_modules node scripts/vs-crosscheck.js
 *   node scripts/vs-crosscheck.js n8n-vs-zapier        # jen vybraný pár
 *   node scripts/vs-crosscheck.js --no-diff --headed
 */
"use strict";
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");
const { extractFacts, llmAvailable } = require("./facts-extract-llm");

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36";
const REPO = path.resolve(__dirname, "..");
const XC_DIR = path.join(REPO, "automation", "data", "vs-crosscheck");
const TOOLS_JSON = path.join(REPO, "automation", "data", "tools.json");
const TODAY = new Date().toISOString().slice(0, 10);
const HEADED = process.argv.includes("--headed");
const NO_DIFF = process.argv.includes("--no-diff");
const NO_LLM = process.argv.includes("--no-llm");
const COUNT_TOL = 0.25;   // |vendor- our|/our > 25 % → do reviewVsOurData (evidence)

// brand → náš slug (pro atribuci tvrzení k nástroji)
const BRAND2SLUG = {
  zapier: "zapier", make: "make", n8n: "n8n", pipedream: "pipedream",
  activepieces: "activepieces", automatisch: "automatisch", "node-red": "node-red", nodered: "node-red",
};

// katalog vendorských srovnávaček. urls = kandidáti (zkusí se po řadě, první OK vyhraje).
// non-OK / 404 = WARN skip (URL se u vendorů mění). source = čí marketing to je.
const PAGES = [
  { id: "n8n-vs-zapier",        source: "n8n",    subjects: ["n8n", "zapier"],    urls: ["https://n8n.io/vs/zapier/"] },
  { id: "n8n-vs-make",          source: "n8n",    subjects: ["n8n", "make"],      urls: ["https://n8n.io/vs/make/"] },
  { id: "n8n-vs-pipedream",     source: "n8n",    subjects: ["n8n", "pipedream"], urls: ["https://n8n.io/vs/pipedream/"] },
  { id: "make-vs-zapier",       source: "make",   subjects: ["make", "zapier"],   urls: ["https://www.make.com/en/compare/make-vs-zapier"] },
  { id: "make-vs-n8n",          source: "make",   subjects: ["make", "n8n"],      urls: ["https://www.make.com/en/compare/make-vs-n8n"] },
  { id: "zapier-vs-make",       source: "zapier", subjects: ["zapier", "make"],   urls: ["https://zapier.com/compare/make-vs-zapier", "https://zapier.com/l/make-vs-zapier"] },
];

function pairDir(id) { const d = path.join(XC_DIR, id); fs.mkdirSync(d, { recursive: true }); return d; }
function previousSnapshot(id) {
  const d = pairDir(id);
  const files = fs.readdirSync(d).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f) && f.slice(0, 10) < TODAY).sort();
  if (!files.length) return null;
  const f = files[files.length - 1];
  try { return { date: f.slice(0, 10), data: JSON.parse(fs.readFileSync(path.join(d, f), "utf8")) }; }
  catch { return null; }
}

// ── deterministická extrakce z (zaujatého) marketing textu ─────────────────────
const COUNT_RE = /([\d][\d,\.]{1,})\s*\+?\s*(apps|integrations|connectors|connections|nodes)\b/gi;
function extractCounts(text) {
  const out = [], seen = new Set();
  let m;
  while ((m = COUNT_RE.exec(text))) {
    const n = Number(m[1].replace(/[,\.]/g, ""));
    if (!Number.isFinite(n) || n < 30) continue;
    const key = n + "|" + m[2].toLowerCase();
    if (seen.has(key)) continue; seen.add(key);
    out.push({ num: n, noun: m[2].toLowerCase(), evidence: m[0].replace(/\s+/g, " ").trim().slice(0, 50) });
  }
  return out.slice(0, 12);
}
function extractPrices(text) {
  const out = new Set();
  for (const m of text.matchAll(/\$\s?([\d,]+(?:\.\d{2})?)\s*(?:\/\s*(?:mo|month|yr|year))?/gi)) {
    const n = Number(m[1].replace(/,/g, ""));
    if (n > 0 && n < 100000) out.add(n);
  }
  return [...out].sort((a, b) => a - b).slice(0, 20);
}
// atribuce počtu k nástroji: nejbližší count k výskytu názvu značky (okno ±70 znaků)
function attributeCounts(text, subjects) {
  const lower = text.toLowerCase();
  const attributed = {};
  for (const subj of subjects) {
    const brand = subj.replace(/-/g, "").toLowerCase();
    const probe = subj === "node-red" ? "node-red" : brand;
    let best = null, bestDist = Infinity;
    let idx = -1;
    while ((idx = lower.indexOf(probe, idx + 1)) !== -1) {
      const win = text.slice(Math.max(0, idx - 70), idx + probe.length + 70);
      let m;
      const re = new RegExp(COUNT_RE.source, "gi");
      while ((m = re.exec(win))) {
        const n = Number(m[1].replace(/[,\.]/g, ""));
        if (!Number.isFinite(n) || n < 30) continue;
        const pos = win.toLowerCase().indexOf(probe);
        const d = Math.abs(m.index - pos);
        if (d < bestDist) { bestDist = d; best = n; }
      }
    }
    if (best !== null) attributed[subj] = best;
  }
  return attributed;
}

let _browser = null;
async function browser() {
  if (!_browser) { const { chromium } = require("playwright"); _browser = await chromium.launch({ headless: !HEADED }); }
  return _browser;
}
async function newPage() { return await (await (await browser()).newContext({ userAgent: UA })).newPage(); }

async function scrapePage(pg) {
  const page = await newPage();
  try {
    let okUrl = null, html = null, text = null;
    for (const url of pg.urls) {
      try {
        const res = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
        if (res && res.ok()) { okUrl = url; await page.waitForTimeout(3500); html = await page.content(); text = await page.evaluate(() => document.body.innerText); break; }
      } catch { /* zkus další kandidát */ }
    }
    if (!okUrl) throw new Error("žádná z kandidátních URL nevrátila OK (404 / přesun / bot wall)");
    const counts = extractCounts(text);
    const prices = extractPrices(text);
    const attributed = attributeCounts(text, pg.subjects);
    let llm = null;
    if (!NO_LLM && llmAvailable()) {
      const r = await extractFacts(text, { subjects: pg.subjects });
      if (r) {
        llm = r;
        // LLM atribuce je lepší — přebij regex tam, kde LLM dá číslo
        for (const c of r.claims || []) {
          const slug = BRAND2SLUG[(c.tool || "").replace(/-/g, "").toLowerCase()] || c.tool;
          if (slug && pg.subjects.includes(slug) && Number.isFinite(c.integration_count))
            attributed[slug] = c.integration_count;
        }
      }
    }
    return { okUrl, html, snap: { id: pg.id, source: pg.source, url: okUrl, subjects: pg.subjects, counts, prices, attributed, llm } };
  } finally { await page.close(); }
}

// ── diff #1: vendor ZMĚNIL své tvrzení od minulého snapshotu (→ alarm) ─────────
function diffPrev(id, oldS, newS) {
  const changes = [];
  if (!oldS) return changes;
  for (const subj of newS.subjects) {
    const o = (oldS.attributed || {})[subj], n = (newS.attributed || {})[subj];
    if (Number.isFinite(o) && Number.isFinite(n) && o !== n)
      changes.push({ id, source: newS.source, subject: subj, field: "integration_count", old: o, neu: n,
        desc: `${newS.source} vs-page: tvrzení o ${subj} integracích ${o} → ${n} (vendor změnil marketing — competitive intel)` });
  }
  const op = JSON.stringify(oldS.prices || []), np = JSON.stringify(newS.prices || []);
  if (op !== np)
    changes.push({ id, source: newS.source, field: "prices", old: oldS.prices, neu: newS.prices,
      desc: `${newS.source} vs-page: zmíněné ceny se změnily ${op} → ${np} — ověřit, jestli nereflektuje reálnou změnu ceníku` });
  return changes;
}

// ── diff #2: vendorovo tvrzení ≠ naše data (→ evidence-only review, BEZ alarmu) ─
function reviewVsOurs(id, snap, claimBySlug) {
  const review = [];
  for (const subj of snap.subjects) {
    const vendorN = (snap.attributed || {})[subj];
    const ourN = claimBySlug[subj] && claimBySlug[subj].integrations;
    if (Number.isFinite(vendorN) && Number.isFinite(ourN) && ourN > 0) {
      const delta = Math.abs(vendorN - ourN) / ourN;
      if (delta > COUNT_TOL)
        review.push({ id, source: snap.source, subject: subj, field: "integration_count",
          vendorClaims: vendorN, ourData: ourN, deltaPct: Math.round(delta * 100),
          tag: "VENDOR MARKETING — biased; ověřit proti authoritative pricing/docs (facts-audit)",
          desc: `${snap.source} vs-page tvrdí ${subj} ${vendorN} integrací; naše data ${ourN} (${Math.round(delta*100)} % rozdíl) — pravděpodobně marketing rounding/zaujatost, NEopravovat automaticky` });
    }
  }
  return review;
}

(async () => {
  const only = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const pages = only.length ? PAGES.filter((p) => only.includes(p.id)) : PAGES;
  const claimBySlug = {};
  for (const t of JSON.parse(fs.readFileSync(TOOLS_JSON, "utf8")).tools) claimBySlug[t.slug] = { integrations: t.integrations };

  let failures = 0, blocked = 0;
  const allChanges = [], allReview = [];
  if (!NO_LLM) console.log(llmAvailable() ? "🧠 LLM extrakce ZAPNUTA (haiku, evidence-only)" : "🧠 LLM klíč nenalezen → jen regex (degradace OK)");

  for (const pg of pages) {
    try {
      const { html, snap } = await scrapePage(pg);
      const dir = pairDir(pg.id);
      const prev = previousSnapshot(pg.id);
      const out = { date: TODAY, ...snap };
      fs.writeFileSync(path.join(dir, `${TODAY}.json`), JSON.stringify(out, null, 2) + "\n", "utf8");
      // html.gz jen poprvé / při změně atribuovaných počtů (evidence; repo neroste zbytečně)
      const attrChanged = !prev || JSON.stringify(prev.data.attributed) !== JSON.stringify(snap.attributed);
      if (attrChanged) fs.writeFileSync(path.join(dir, `${TODAY}.html.gz`), zlib.gzipSync(Buffer.from(html, "utf8")));

      const changes = NO_DIFF ? [] : diffPrev(pg.id, prev && prev.data, snap);
      const review = reviewVsOurs(pg.id, snap, claimBySlug);
      allChanges.push(...changes); allReview.push(...review);
      const attrStr = Object.entries(snap.attributed).map(([k, v]) => `${k}:${v}`).join(" ") || "—";
      console.log(`✓ ${pg.id} (${snap.source}) attrib[${attrStr}]${snap.llm ? " +LLM" : ""}${changes.length ? `  ⚠ ${changes.length} změn` : ""}${review.length ? `  · ${review.length} review` : ""}`);
    } catch (e) {
      const msg = e.message || String(e);
      const isBotWall = /bot|403|429|503|timeout|Timeout|žádná|HTTP|OK/i.test(msg);
      if (isBotWall) { console.log(`⚠ WARN ${pg.id} (nedostupné / přesun URL, ne změna): ${msg.slice(0, 70)}`); blocked++; }
      else { console.log(`SELHALO ${pg.id}: ${msg}`); failures++; }
    }
  }
  if (_browser) await _browser.close();

  if (!NO_DIFF) {
    fs.mkdirSync(XC_DIR, { recursive: true });
    const report = { date: TODAY, generatedAt: new Date().toISOString(),
      changeCount: allChanges.length, changes: allChanges,
      reviewCount: allReview.length, reviewVsOurData: allReview,
      note: "changeCount = vendor ZMĚNIL marketing od minula (alarm). reviewVsOurData = vendor ≠ naše data (EVIDENCE-ONLY, zaujatý signál, NEopravovat automaticky)." };
    fs.writeFileSync(path.join(XC_DIR, `changes-${TODAY}.json`), JSON.stringify(report, null, 2) + "\n", "utf8");
    console.log(`\n📋 ${allChanges.length} vendor-changes (alarm) · ${allReview.length} review-vs-naše-data (evidence) → vs-crosscheck/changes-${TODAY}.json`);
    for (const c of allChanges) console.log(`   ⚠ ${c.desc}`);
    for (const r of allReview) console.log(`   · ${r.desc}`);
  }
  if (blocked) console.log(`⚠ ${blocked} stránek nedostupných (URL přesun / bot wall) — ne fail.`);
  process.exit(failures ? 1 : 0);   // exit 1 jen tvrdá chyba; alarm na changeCount řeší workflow
})();
