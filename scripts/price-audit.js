#!/usr/bin/env node
/**
 * price-audit.js — denní AUDIT cen všech sledovaných nástrojů.
 *
 * Tohle je vrstva DŮKAZŮ pod price-watch.js. Každý den:
 *   1) stáhne syrové HTML každého ceníku  → automation/data/audit/<vendor>/<YYYY-MM-DD>.html
 *   2) vytáhne normalizovaná cenová data   → automation/data/audit/<vendor>/<YYYY-MM-DD>.json
 *   3) diff proti POSLEDNÍMU předchozímu snapshotu → automation/data/audit/changes-<YYYY-MM-DD>.json
 *      (+ append do automation/data/audit/price-history.jsonl pro grafy změn)
 *
 * Volume-based ceníky (Make, Zapier) se scrapují CELOU maticí (slider/HTML-JSON),
 * fixní ceníky (Pipedream, n8n, Activepieces, Automatisch, Node-RED) se ukládají
 * jako syrové HTML + parsnuté plány. Vše bez jediného screenshotu — pro GH Actions cron.
 *
 * Audit data jsou EVIDENCE, ne zdroj pravdy. tools.json updatuje člověk po revizi
 * change reportu — stejný princip jako wayback audit a drift-report.
 *
 * Spuštění:
 *   node scripts/price-audit.js                 # všechny vendory, plný audit + diff
 *   node scripts/price-audit.js make zapier     # jen vybrané
 *   node scripts/price-audit.js --no-diff       # jen snapshoty, bez porovnání
 *   node scripts/price-audit.js --headed        # vidět browser (debug)
 */
"use strict";
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36";
const REPO = path.resolve(__dirname, "..");
const AUDIT_DIR = path.join(REPO, "automation", "data", "audit");
const TODAY = new Date().toISOString().slice(0, 10);
const HEADED = process.argv.includes("--headed");
const NO_DIFF = process.argv.includes("--no-diff");

// ── vendor katalog ────────────────────────────────────────────────────────
// model: "slider" = volume matice (scrape přes engine níže)
//        "fixed"  = pevné plány (uloží HTML + hrubý parse cen z textu)
const VENDORS = {
  zapier:       { url: "https://zapier.com/pricing",                 model: "slider", unit: "tasks" },
  make:         { url: "https://www.make.com/en/pricing",            model: "slider", unit: "credits" },
  pipedream:    { url: "https://pipedream.com/pricing",              model: "fixed",  unit: "credits" },
  n8n:          { url: "https://n8n.io/pricing/",                    model: "fixed",  unit: "executions" },
  activepieces: { url: "https://www.activepieces.com/pricing",       model: "fixed",  unit: "flows" },
  automatisch:  { url: "https://automatisch.io/",                    model: "fixed",  unit: "self-host" },
};

function vendorDir(v) {
  const d = path.join(AUDIT_DIR, v);
  fs.mkdirSync(d, { recursive: true });
  return d;
}

// poslední JSON snapshot PŘED dneškem (pro diff)
function previousSnapshot(v) {
  const d = vendorDir(v);
  const files = fs.readdirSync(d)
    .filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f) && f.slice(0, 10) < TODAY)
    .sort();
  if (!files.length) return null;
  const f = files[files.length - 1];
  try { return { date: f.slice(0, 10), data: JSON.parse(fs.readFileSync(path.join(d, f), "utf8")) }; }
  catch { return null; }
}

// ── scrape jednotlivých vendorů ─────────────────────────────────────────────
let _browser = null;
async function browser() {
  if (!_browser) {
    const { chromium } = require("playwright");
    _browser = await chromium.launch({ headless: !HEADED });
  }
  return _browser;
}
async function newPage() {
  return await (await (await browser()).newContext({ userAgent: UA })).newPage();
}

// Zapier: celá matice je inline JSON v HTML.
async function scrapeZapier() {
  const page = await newPage();
  const res = await page.goto(VENDORS.zapier.url, { waitUntil: "domcontentloaded", timeout: 60000 });
  if (!res || !res.ok()) throw new Error(`HTTP ${res ? res.status() : "?"}`);
  const html = await page.content();
  await page.close();
  const re = /\{"planType":"([^"]+)","tasks":(\d+),"id":\d+,"name":"[^"]*","shortName":"[^"]*","amount":(\d+),"actions":\d+,"interval":"([^"]+)"\}/g;
  const byI = { month: {}, year: {} };
  let m, n = 0;
  while ((m = re.exec(html))) {
    const [, plan, tasks, cents, interval] = m;
    if (!byI[interval]) continue;
    (byI[interval][Number(tasks)] ||= {})[plan] = Number(cents) / 100;
    n++;
  }
  if (!n) throw new Error("matice nenalezena (změna formátu?)");
  const rows = (o) => Object.keys(o).map(Number).sort((a, b) => a - b).map((u) => ({ units: u, plans: o[u] }));
  return { html, prices: { unit: "tasks", monthly: rows(byI.month), annually: rows(byI.year), points: n } };
}

// Make: slider 0..18, ceny generuje JS lokálně → projet pozice pro monthly i annually.
const MAKE_TIERS = [10000, 20000, 40000, 80000, 150000, 300000, 500000, 750000, 1000000,
  1500000, 2000000, 2500000, 3000000, 4000000, 5000000, 6000000, 7000000, 8000000, null];
async function scrapeMake() {
  const page = await newPage();
  await page.goto(VENDORS.make.url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(4000);
  const html = await page.content();

  async function readPlans() {
    return await page.evaluate(() => {
      const plans = {};
      document.querySelectorAll("*").forEach((el) => {
        const h = (el.textContent || "").trim();
        if (/^(Core|Pro|Teams)$/.test(h) && el.children.length === 0 && plans[h] === undefined) {
          let card = el.parentElement;
          for (let hop = 0; hop < 5 && card; hop++) {
            const txt = card.innerText || "";
            if (/not available/i.test(txt)) { plans[h] = null; break; }
            const pm = txt.match(/\$\s?([\d,]+)\s*(?:\.\s*(\d{2}))?/);
            if (pm) { const d = Number(pm[1].replace(/,/g, "")); plans[h] = pm[2] ? Number(`${d}.${pm[2]}`) : d; break; }
            card = card.parentElement;
          }
        }
      });
      return plans;
    });
  }
  async function setPeriod(label) {
    const ok = await page.evaluate((want) => {
      const e = [...document.querySelectorAll("div,button,[role=tab]")]
        .filter((x) => (x.textContent || "").trim().toLowerCase() === want && x.offsetParent !== null)[0];
      if (e) { e.click(); return true; } return false;
    }, label);
    await page.waitForTimeout(1500);
    return ok;
  }
  async function sweep() {
    const slider = await page.$("input[type=range]");
    if (!slider) throw new Error("slider nenalezen");
    const max = Number(await slider.getAttribute("max")) || 18;
    const rows = [], seen = new Set();
    for (let pos = 0; pos <= max; pos++) {
      await page.evaluate((p) => {
        const el = document.querySelector("input[type=range]");
        const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        set.call(el, String(p));
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }, pos);
      await page.waitForTimeout(450);
      const units = MAKE_TIERS[pos] !== undefined ? MAKE_TIERS[pos] : null;
      const key = units === null ? `pos${pos}` : units;
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push({ units, plans: await readPlans() });
    }
    if (rows.length < 5) throw new Error(`jen ${rows.length} pozic`);
    return rows;
  }
  await setPeriod("pay monthly");
  const monthly = await sweep();
  let annually = [];
  if (await setPeriod("pay annually")) annually = await sweep();
  await page.close();
  return { html, prices: { unit: "credits", monthly, annually } };
}

// Fixní ceníky: ulož HTML + vytáhni $N /mo ceny z viditelného textu jako hrubý otisk.
async function scrapeFixed(v) {
  const page = await newPage();
  await page.goto(VENDORS[v].url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(3500);
  const html = await page.content();
  const text = await page.evaluate(() => document.body.innerText);
  await page.close();
  const prices = [...new Set([...text.matchAll(/\$\s?([\d,]+(?:\.\d{2})?)/g)].map((m) => Number(m[1].replace(/,/g, ""))))]
    .filter((n) => n > 0).sort((a, b) => a - b);
  return { html, prices: { unit: VENDORS[v].unit, model: "fixed", listedPrices: prices } };
}

async function scrapeVendor(v) {
  if (v === "zapier") return scrapeZapier();
  if (v === "make") return scrapeMake();
  return scrapeFixed(v);
}

// ── diff dvou cenových snapshotů ────────────────────────────────────────────
function diffPrices(vendor, oldP, newP) {
  const changes = [];
  if (!oldP) return changes;
  const model = newP.model || (newP.monthly ? "slider" : "fixed");
  if (model === "fixed") {
    const a = JSON.stringify(oldP.listedPrices || []);
    const b = JSON.stringify(newP.listedPrices || []);
    if (a !== b) changes.push({ vendor, kind: "listedPrices", old: oldP.listedPrices, neu: newP.listedPrices });
    return changes;
  }
  // slider: porovnej cenu per (interval, units, plan)
  for (const interval of ["monthly", "annually"]) {
    const oldRows = Object.fromEntries((oldP[interval] || []).map((r) => [r.units, r.plans]));
    for (const row of newP[interval] || []) {
      const prev = oldRows[row.units];
      if (!prev) continue;
      for (const plan of Object.keys(row.plans)) {
        if (prev[plan] !== undefined && prev[plan] !== row.plans[plan]) {
          changes.push({ vendor, interval, units: row.units, plan, old: prev[plan], neu: row.plans[plan] });
        }
      }
    }
  }
  return changes;
}

// ── runner ───────────────────────────────────────────────────────────────────
(async () => {
  const args = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const targets = args.length ? args : Object.keys(VENDORS);
  fs.mkdirSync(AUDIT_DIR, { recursive: true });
  const allChanges = [];
  let failures = 0;

  for (const v of targets) {
    if (!VENDORS[v]) { console.error(`✗ neznámý vendor: ${v}`); failures++; continue; }
    process.stdout.write(`→ ${v} … `);
    try {
      const prev = NO_DIFF ? null : previousSnapshot(v);
      const { html, prices } = await scrapeVendor(v);
      const dir = vendorDir(v);
      // normalizovaná cenová data — vždy (malé, 24 KB/den celkem)
      const snap = { vendor: v, scrapedAt: new Date().toISOString(), url: VENDORS[v].url, ...prices };
      fs.writeFileSync(path.join(dir, `${TODAY}.json`), JSON.stringify(snap, null, 2) + "\n", "utf8");
      // diff proti předchozímu snapshotu
      let changed = [];
      if (prev) {
        changed = diffPrices(v, prev.data, prices);
        allChanges.push(...changed);
      }
      // syrové HTML jen když je co dokazovat: poprvé (prev===null) nebo při změně.
      // Gzipnuté → ~10× menší. Běžné neměnné dny repo nezatěžují.
      let htmlNote = "HTML přeskočeno (beze změn)";
      if (!prev || changed.length) {
        const gz = zlib.gzipSync(Buffer.from(html, "utf8"));
        fs.writeFileSync(path.join(dir, `${TODAY}.html.gz`), gz);
        htmlNote = `HTML uloženo ${Math.round(gz.length / 1024)} KB gz`;
      }
      console.log(`OK (${htmlNote} · ${changed.length} změn vs ${prev ? prev.date : "—"})`);
    } catch (e) {
      console.log(`SELHALO: ${e.message}`);
      failures++;
    }
  }

  if (_browser) await _browser.close();

  // change report + history (pro grafy)
  if (!NO_DIFF) {
    const report = { date: TODAY, generatedAt: new Date().toISOString(), changeCount: allChanges.length, changes: allChanges };
    fs.writeFileSync(path.join(AUDIT_DIR, `changes-${TODAY}.json`), JSON.stringify(report, null, 2) + "\n", "utf8");
    if (allChanges.length) {
      const line = allChanges.map((c) => JSON.stringify({ d: TODAY, ...c })).join("\n") + "\n";
      fs.appendFileSync(path.join(AUDIT_DIR, "price-history.jsonl"), line, "utf8");
    }
    console.log(`\n📋 ${allChanges.length} cenových změn → audit/changes-${TODAY}.json`);
  }
  process.exit(failures ? 1 : 0);
})();
