#!/usr/bin/env node
/**
 * integrations-audit.js — týdenní AUDIT katalogu integrací všech sledovaných nástrojů.
 *
 * Sesterský skript k price-audit.js, jen pro INTEGRACE (apps / connectors / nodes)
 * místo cen. Každý běh:
 *   1) stáhne KOMPLETNÍ seznam integrací každého nástroje z jeho strojově čitelného
 *      zdroje (veřejné JSON API, GitHub git-tree, oficiální katalog) → normalizuje
 *      na [{ slug, name, category }]
 *   2) uloží snapshot   → automation/data/integrations/<vendor>/latest.json
 *      (přepisuje se; git historie souboru = evidence vývoje, stejně jako tools.json)
 *   3) zdiffuje proti POSLEDNÍMU commitnutému snapshotu → which apps PŘIBYLY / ZMIZELY
 *      → automation/data/integrations/changes-<YYYY-MM-DD>.json
 *      (+ append do integrations-history.jsonl pro graf/feed změn)
 *   4) zapíše counts.json (vendor → počet integrací) jako rychlou referenci.
 *
 * Notifikace: stejný model jako cenový audit — workflow integrations-audit.yml
 * FAILNE (= mail ownerovi) JEN když changeCount > 0 (reálné přidání/odebrání integrace).
 * Bot-wall / dočasná nedostupnost / podezřele nízký počet = WARN (drží se starý
 * snapshot, žádný alarm, žádná ztráta dat). Audit data jsou EVIDENCE, ne zdroj pravdy.
 *
 * Zdroje (ověřeno 2026-06-23, vše bez auth):
 *   zapier       same-origin fetch /api/v4/apps/?limit=10&offset=N        (~9700, ~970 stran)
 *   make         same-origin fetch /en/integrations/api/get-apps?...      (~2950, 48/stranu)
 *   n8n          api.n8n.io/api/nodes (Strapi, pageSize=100)             (~570, 6 stran)
 *   pipedream    GitHub git-tree PipedreamHQ/pipedream components/        (~3390, 1 strom)
 *   activepieces cloud.activepieces.com/api/v1/pieces (JSON pole)         (~750, 1 call)
 *   automatisch  GitHub contents automatisch .../src/apps                 (~90, 1 call)
 *   node-red     catalogue.nodered.org/catalogue.json                     (~6090, 1 call)
 *
 * Vše přes Playwright (chromium): node fetch má v tomhle prostředí rozbité TLS
 * (poučení z price-audit) a Make je za Cloudflare — headless chromium projde.
 *
 * Spuštění:
 *   node scripts/integrations-audit.js               # všechny vendory, audit + diff
 *   node scripts/integrations-audit.js zapier make   # jen vybrané
 *   node scripts/integrations-audit.js --no-diff      # jen snapshoty, bez porovnání
 *   node scripts/integrations-audit.js --headed       # vidět browser (debug)
 *   node scripts/integrations-audit.js --selftest     # unit test diff/normalize (bez sítě)
 *   NODE_PATH=<calc-test>/node_modules node scripts/integrations-audit.js   # lokálně
 */
"use strict";
const fs = require("fs");
const path = require("path");

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36";
const REPO = path.resolve(__dirname, "..");
const DATA_DIR = path.join(REPO, "automation", "data", "integrations");
const TODAY = new Date().toISOString().slice(0, 10);
const HEADED = process.argv.includes("--headed");
const NO_DIFF = process.argv.includes("--no-diff");

// ── vendor katalog ────────────────────────────────────────────────────────
// Každý vendor má `kind` = mechanismus získání seznamu (viz scrapeVendor níže).
const VENDORS = {
  zapier:       { kind: "zapier",       label: "Zapier",       directory: "https://zapier.com/apps" },
  make:         { kind: "make",         label: "Make",         directory: "https://www.make.com/en/integrations" },
  n8n:          { kind: "n8n",          label: "n8n",          directory: "https://n8n.io/integrations/" },
  pipedream:    { kind: "pipedream",    label: "Pipedream",    directory: "https://pipedream.com/apps" },
  activepieces: { kind: "activepieces", label: "Activepieces", directory: "https://www.activepieces.com/pieces" },
  automatisch:  { kind: "automatisch",  label: "Automatisch",  directory: "https://automatisch.io/integrations" },
  "node-red":   { kind: "node-red",     label: "Node-RED",     directory: "https://flows.nodered.org/" },
};

function vendorDir(v) {
  const d = path.join(DATA_DIR, v);
  fs.mkdirSync(d, { recursive: true });
  return d;
}

// poslední commitnutý snapshot (pro diff). Vrací { count, integrations:[{slug,name,...}] } | null
function previousSnapshot(v) {
  const f = path.join(vendorDir(v), "latest.json");
  if (!fs.existsSync(f)) return null;
  try {
    const data = JSON.parse(fs.readFileSync(f, "utf8"));
    return Array.isArray(data.integrations) ? data : null;
  } catch { return null; }
}

// ── normalizace ─────────────────────────────────────────────────────────────
// Slug = stabilní identifikátor integrace v rámci jednoho nástroje (z jeho zdroje).
// `slug` musí být napříč běhy STABILNÍ (jinak by diff hlásil falešné add/remove).
function clean(s) { return (s == null ? "" : String(s)).replace(/\s+/g, " ").trim(); }

// poskládá normalizovaný záznam; zahodí prázdné slugy
function entry(slug, name, category) {
  slug = clean(slug);
  if (!slug) return null;
  return { slug, name: clean(name) || slug, category: clean(category) || undefined };
}

// deduplikace podle slugu + setřídění (deterministický výstup → čisté git diffy)
function normalizeList(rows) {
  const map = new Map();
  for (const r of rows) {
    if (!r) continue;
    if (!map.has(r.slug)) map.set(r.slug, r);
  }
  return [...map.values()].sort((a, b) => a.slug.localeCompare(b.slug));
}

// ── Playwright fetch vrstva ──────────────────────────────────────────────────
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

// Naviguje rovnou na JSON URL a naparsuje tělo. Robustní proti rozbitému node TLS
// (chromium má vlastní TLS) i proti Cloudflare (browser projde tam, kde raw fetch ne).
async function gotoJSON(page, url) {
  const res = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  const status = res ? res.status() : 0;
  const txt = await page.evaluate(() => document.body.innerText);
  if (status >= 400) throw new Error(`HTTP ${status} @ ${url}`);
  let json;
  try { json = JSON.parse(txt); }
  catch { throw new Error(`nevalidní JSON (bot-wall / změna formátu?) @ ${url}`); }
  return json;
}

// Same-origin fetch z už načtené stránky (obejde CORS i TLS) — pro stránkované
// interní API (Zapier, Make). Vrací naparsované JSON tělo.
async function sameOriginJSON(page, pathWithQuery) {
  return await page.evaluate(async (p) => {
    const r = await fetch(p, { headers: { accept: "application/json" } });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return await r.json();
  }, pathWithQuery);
}

// ── scrape jednotlivých vendorů → [{slug,name,category}] ──────────────────────

// Zapier: veřejné /api/v4/apps/ — limit se ignoruje (vždy 10/stranu), stránkuj offset.
async function scrapeZapier() {
  const page = await newPage();
  try {
    await page.goto(VENDORS.zapier.directory, { waitUntil: "domcontentloaded", timeout: 60000 });
    const rows = [];
    let offset = 0, total = null, empty = 0;
    const STEP = 10, MAX_PAGES = 1500;
    for (let i = 0; i < MAX_PAGES; i++) {
      let body;
      try { body = await sameOriginJSON(page, `/api/v4/apps/?limit=${STEP}&offset=${offset}`); }
      catch (e) {
        // ojedinělý výpadek stránky — zkus jednou znovu po krátké prodlevě
        await page.waitForTimeout(800);
        body = await sameOriginJSON(page, `/api/v4/apps/?limit=${STEP}&offset=${offset}`);
      }
      if (total == null && typeof body.count === "number") total = body.count;
      const list = body.results || body.objects || [];
      if (!list.length) { if (++empty >= 2) break; }
      for (const a of list) {
        const cat = (a.categories && a.categories[0] && (a.categories[0].slug || a.categories[0].title)) || "";
        rows.push(entry(a.slug, a.title || a.name, cat));
      }
      offset += STEP;
      if (total != null && offset >= total + STEP) break;
      await page.waitForTimeout(40); // šetrný throttle (~970 stran)
    }
    const out = normalizeList(rows);
    if (out.length < 100) throw new Error(`jen ${out.length} apps (API změna?)`);
    return { integrations: out, source: "https://zapier.com/api/v4/apps/", reportedTotal: total };
  } finally { await page.close(); }
}

// Make: interní /en/integrations/api/get-apps (same-origin), 48/stranu, stránkuj offset.
async function scrapeMake() {
  const page = await newPage();
  try {
    await page.goto(VENDORS.make.directory, { waitUntil: "domcontentloaded", timeout: 60000 });
    await page.waitForTimeout(2500); // nech projít případnou CF challenge
    const rows = [];
    let offset = 0, total = null;
    const STEP = 48, MAX_PAGES = 400;
    for (let i = 0; i < MAX_PAGES; i++) {
      const body = await sameOriginJSON(page, `/en/integrations/api/get-apps?limit=${STEP}&offset=${offset}&sort=most_popular`);
      if (total == null && typeof body.totalApps === "number") total = body.totalApps;
      const list = body.apps || body.data || [];
      if (!list.length) break;
      for (const a of list) {
        // isThirdPartyApp=true → komunitní/3rd-party app; uložíme jako category hint
        rows.push(entry(a.slug, a.name, a.isThirdPartyApp ? "community" : "verified"));
      }
      offset += STEP;
      await page.waitForTimeout(40);
    }
    const out = normalizeList(rows);
    if (out.length < 100) throw new Error(`jen ${out.length} apps (CF / API změna?)`);
    return { integrations: out, source: "https://www.make.com/en/integrations/api/get-apps", reportedTotal: total };
  } finally { await page.close(); }
}

// n8n: oficiální Strapi api.n8n.io/api/nodes, pageSize=100, čti meta.pagination.
async function scrapeN8n() {
  const page = await newPage();
  try {
    const rows = [];
    let pageNo = 1, pageCount = 1;
    const SIZE = 100, MAX_PAGES = 50;
    for (; pageNo <= pageCount && pageNo <= MAX_PAGES; pageNo++) {
      const body = await gotoJSON(page, `https://api.n8n.io/api/nodes?pagination[pageSize]=${SIZE}&pagination[page]=${pageNo}`);
      const meta = body.meta && body.meta.pagination;
      if (meta && meta.pageCount) pageCount = meta.pageCount;
      for (const n of (body.data || [])) {
        const a = n.attributes || n; // Strapi v4 může mít atributy zploštělé i pod attributes
        const grp = Array.isArray(a.group) ? a.group[0] : (a.codex && a.codex.categories && a.codex.categories[0]);
        rows.push(entry(a.name, a.displayName, grp));
      }
      await page.waitForTimeout(40);
    }
    const out = normalizeList(rows);
    if (out.length < 50) throw new Error(`jen ${out.length} nodů (API změna?)`);
    return { integrations: out, source: "https://api.n8n.io/api/nodes" };
  } finally { await page.close(); }
}

// Pipedream: GitHub git-tree — root tree → sha složky components/ → její strom.
// (REST /v1/apps je OAuth-only; contents API je capnuté na 1000; git-tree limit nemá.)
async function scrapePipedream() {
  const page = await newPage();
  try {
    const root = await gotoJSON(page, "https://api.github.com/repos/PipedreamHQ/pipedream/git/trees/master");
    const comp = (root.tree || []).find((t) => t.path === "components" && t.type === "tree");
    if (!comp) throw new Error("components/ nenalezeno v root tree");
    const tree = await gotoJSON(page, `https://api.github.com/repos/PipedreamHQ/pipedream/git/trees/${comp.sha}`);
    if (tree.truncated) throw new Error("git-tree truncated (neúplný seznam)");
    const rows = (tree.tree || [])
      .filter((x) => x.type === "tree")
      .map((x) => {
        const slug = x.path.replace(/^_/, ""); // Pipedream prefixuje "_" u slugů začínajících číslem
        return entry(slug, slug);
      });
    const out = normalizeList(rows);
    if (out.length < 100) throw new Error(`jen ${out.length} komponent (repo struktura?)`);
    return { integrations: out, source: "https://github.com/PipedreamHQ/pipedream/tree/master/components" };
  } finally { await page.close(); }
}

// Activepieces: veřejné cloud API — JSON pole pieces, bez paginace.
async function scrapeActivepieces() {
  const page = await newPage();
  try {
    const body = await gotoJSON(page, "https://cloud.activepieces.com/api/v1/pieces");
    const arr = Array.isArray(body) ? body : (body.data || []);
    const rows = arr.map((p) => {
      const slug = clean(p.name).replace(/^@activepieces\/piece-/, "");
      const cat = Array.isArray(p.categories) ? p.categories[0] : p.category;
      return entry(slug, p.displayName, cat);
    });
    const out = normalizeList(rows);
    if (out.length < 50) throw new Error(`jen ${out.length} pieces (API změna?)`);
    return { integrations: out, source: "https://cloud.activepieces.com/api/v1/pieces" };
  } finally { await page.close(); }
}

// Automatisch: GitHub contents složky apps/ (92 < 1000 → contents API stačí).
async function scrapeAutomatisch() {
  const page = await newPage();
  try {
    const body = await gotoJSON(page, "https://api.github.com/repos/automatisch/automatisch/contents/packages/backend/src/apps?ref=main");
    if (!Array.isArray(body)) throw new Error("contents API nevrátilo pole");
    const rows = body.filter((x) => x.type === "dir").map((x) => entry(x.name, x.name));
    const out = normalizeList(rows);
    if (out.length < 20) throw new Error(`jen ${out.length} konektorů (repo struktura?)`);
    return { integrations: out, source: "https://github.com/automatisch/automatisch/tree/main/packages/backend/src/apps" };
  } finally { await page.close(); }
}

// Node-RED: oficiální komunitní katalog — jeden JSON soubor {modules:[…]}.
async function scrapeNodeRed() {
  const page = await newPage();
  try {
    const body = await gotoJSON(page, "https://catalogue.nodered.org/catalogue.json");
    const mods = body.modules || [];
    const rows = mods.map((m) => {
      const cat = Array.isArray(m.categories) ? m.categories[0]
        : (Array.isArray(m.keywords) ? m.keywords.find((k) => k !== "node-red") : undefined);
      return entry(m.id, m.id, cat);
    });
    const out = normalizeList(rows);
    if (out.length < 100) throw new Error(`jen ${out.length} modulů (katalog změna?)`);
    return { integrations: out, source: "https://catalogue.nodered.org/catalogue.json" };
  } finally { await page.close(); }
}

async function scrapeVendor(v) {
  switch (VENDORS[v].kind) {
    case "zapier":       return scrapeZapier();
    case "make":         return scrapeMake();
    case "n8n":          return scrapeN8n();
    case "pipedream":    return scrapePipedream();
    case "activepieces": return scrapeActivepieces();
    case "automatisch":  return scrapeAutomatisch();
    case "node-red":     return scrapeNodeRed();
    default: throw new Error(`neznámý vendor: ${v}`);
  }
}

// Retry proti dočasnému bot-wallu / síťovému výpadku (3 pokusy, narůstající prodleva).
async function scrapeVendorRetry(v, attempts = 3) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    if (i) await new Promise((r) => setTimeout(r, 4000 * i));
    try { return await scrapeVendor(v); }
    catch (e) { lastErr = e; }
  }
  throw lastErr;
}

// ── diff dvou snapshotů (množinový rozdíl podle slugu) ────────────────────────
function diffIntegrations(vendor, oldList, newList) {
  const oldMap = new Map((oldList || []).map((x) => [x.slug, x]));
  const newMap = new Map((newList || []).map((x) => [x.slug, x]));
  const added = [], removed = [];
  for (const [slug, x] of newMap) if (!oldMap.has(slug)) added.push(x);
  for (const [slug, x] of oldMap) if (!newMap.has(slug)) removed.push(x);
  added.sort((a, b) => a.slug.localeCompare(b.slug));
  removed.sort((a, b) => a.slug.localeCompare(b.slug));
  const changes = [];
  for (const x of added)   changes.push({ vendor, change: "added",   slug: x.slug, name: x.name, desc: `${vendor}: PŘIBYLA integrace → ${x.name} (${x.slug})` });
  for (const x of removed) changes.push({ vendor, change: "removed", slug: x.slug, name: x.name, desc: `${vendor}: ZMIZELA integrace → ${x.name} (${x.slug})` });
  return { added, removed, changes };
}

// Sanity guard: scrape, který vrátí podezřele málo položek vs předchozí snapshot,
// je nejspíš částečný (bot-wall / API výpadek) → NEpřepiš snapshot, NEhlásí alarm.
// Práh 60 % předchozího počtu (a předchozí musí být netriviální).
function suspectShrink(prevCount, newCount) {
  return prevCount >= 50 && newCount < prevCount * 0.6;
}

// export pro --selftest a unit testy (čistá logika bez sítě)
module.exports = { diffIntegrations, normalizeList, entry, clean, suspectShrink };

// ── self-test (bez sítě) ──────────────────────────────────────────────────────
function selftest() {
  let fails = 0;
  const eq = (a, b, msg) => { const A = JSON.stringify(a), B = JSON.stringify(b); if (A !== B) { console.error(`✗ ${msg}\n   got: ${A}\n   exp: ${B}`); fails++; } else console.log(`✓ ${msg}`); };

  // normalize: dedup + sort
  const n = normalizeList([entry("b", "B"), entry("a", "A"), entry("b", "B2"), null, entry("", "x")]);
  eq(n.map((x) => x.slug), ["a", "b"], "normalize dedupuje a třídí, zahazuje prázdné");

  // diff: add + remove
  const oldL = [entry("slack", "Slack"), entry("gmail", "Gmail")];
  const newL = [entry("slack", "Slack"), entry("notion", "Notion")];
  const d = diffIntegrations("zapier", oldL, newL);
  eq(d.added.map((x) => x.slug), ["notion"], "diff zachytí přidanou integraci");
  eq(d.removed.map((x) => x.slug), ["gmail"], "diff zachytí odebranou integraci");
  eq(d.changes.length, 2, "diff: 2 změny celkem");

  // diff: beze změny
  const d0 = diffIntegrations("make", oldL, oldL.slice());
  eq(d0.changes.length, 0, "stejný seznam = 0 změn");

  // diff: první běh (prev=null) = vše jako baseline, žádné removed
  const dFirst = diffIntegrations("n8n", null, newL);
  eq(dFirst.removed.length, 0, "první běh nehlásí removed");
  eq(dFirst.added.length, 2, "první běh: vše added (baseline)");

  // sanity guard
  eq(suspectShrink(1000, 200), true, "sanity: 200 z 1000 je podezřelé");
  eq(suspectShrink(1000, 950), false, "sanity: 950 z 1000 je OK");
  eq(suspectShrink(10, 3), false, "sanity: malé počty se neguardují");

  console.log(fails ? `\n${fails} selhání` : "\nvše OK");
  process.exit(fails ? 1 : 0);
}

// ── zápis snapshotu (setříděný, 1 záznam/řádek → čisté git diffy) ──────────────
function writeSnapshot(v, scraped) {
  const dir = vendorDir(v);
  const lines = scraped.integrations.map((x) => "    " + JSON.stringify(x));
  const body =
    "{\n" +
    `  "vendor": ${JSON.stringify(v)},\n` +
    `  "scrapedAt": ${JSON.stringify(new Date().toISOString())},\n` +
    `  "source": ${JSON.stringify(scraped.source)},\n` +
    `  "count": ${scraped.integrations.length},\n` +
    `  "integrations": [\n` + lines.join(",\n") + "\n  ]\n}\n";
  fs.writeFileSync(path.join(dir, "latest.json"), body, "utf8");
}

// ── runner ───────────────────────────────────────────────────────────────────
async function main() {
  if (process.argv.includes("--selftest")) return selftest();

  const args = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const targets = args.length ? args : Object.keys(VENDORS);
  fs.mkdirSync(DATA_DIR, { recursive: true });

  const allChanges = [];
  const byVendor = {};
  const counts = {};
  const warnings = [];
  let failures = 0;   // tvrdá chyba → exit 1
  let blocked = 0;    // bot-wall / suspect → WARN, neshazuje exit

  for (const v of targets) {
    if (!VENDORS[v]) { console.error(`✗ neznámý vendor: ${v}`); failures++; continue; }
    process.stdout.write(`→ ${v} … `);
    const prev = NO_DIFF ? null : previousSnapshot(v);
    let scraped;
    try { scraped = await scrapeVendorRetry(v); }
    catch (e) {
      const msg = (e && e.message) || String(e);
      console.log(`⚠ WARN (nedostupné/bot-wall po retry — držím starý snapshot): ${msg.slice(0, 90)}`);
      warnings.push(`${v}: scrape selhal (${msg.slice(0, 80)}) — ponechán předchozí snapshot`);
      if (prev) counts[v] = prev.count;
      blocked++;
      continue;
    }

    const newCount = scraped.integrations.length;
    // sanity: podezřelý propad → nepřepisuj, nehlásí
    if (prev && suspectShrink(prev.count, newCount)) {
      console.log(`⚠ WARN (podezřelý propad ${prev.count}→${newCount} — držím starý snapshot, bez alarmu)`);
      warnings.push(`${v}: počet spadl ${prev.count}→${newCount} (<60 %) — pravděpodobně částečný scrape, snapshot NEpřepsán`);
      counts[v] = prev.count;
      blocked++;
      continue;
    }

    writeSnapshot(v, scraped);
    counts[v] = newCount;

    let changed = { added: [], removed: [], changes: [] };
    if (prev && !NO_DIFF) {
      changed = diffIntegrations(v, prev.integrations, scraped.integrations);
      allChanges.push(...changed.changes);
    }
    byVendor[v] = {
      count: newCount,
      prevCount: prev ? prev.count : null,
      added: changed.added.map((x) => ({ slug: x.slug, name: x.name })),
      removed: changed.removed.map((x) => ({ slug: x.slug, name: x.name })),
    };
    const delta = prev ? ` (+${changed.added.length}/-${changed.removed.length} vs ${prev.count})` : " (baseline)";
    console.log(`OK ${newCount} integrací${delta}`);
  }

  if (_browser) await _browser.close();

  // counts.json — rychlá reference (vendor → počet)
  fs.writeFileSync(path.join(DATA_DIR, "counts.json"),
    JSON.stringify({ _note: "Počet integrací per nástroj z týdenního auditu. Evidence, ne zdroj pravdy.",
                     date: TODAY, generatedAt: new Date().toISOString(), counts }, null, 2) + "\n", "utf8");

  // change report + history
  if (!NO_DIFF) {
    const addedCount = allChanges.filter((c) => c.change === "added").length;
    const removedCount = allChanges.length - addedCount;
    const report = {
      date: TODAY, generatedAt: new Date().toISOString(),
      changeCount: allChanges.length, addedCount, removedCount,
      byVendor, warnings, changes: allChanges,
    };
    fs.writeFileSync(path.join(DATA_DIR, `changes-${TODAY}.json`), JSON.stringify(report, null, 2) + "\n", "utf8");
    if (allChanges.length) {
      const line = allChanges.map((c) => JSON.stringify({ d: TODAY, vendor: c.vendor, change: c.change, slug: c.slug, name: c.name })).join("\n") + "\n";
      fs.appendFileSync(path.join(DATA_DIR, "integrations-history.jsonl"), line, "utf8");
    }
    console.log(`\n📋 ${allChanges.length} změn (${addedCount} přidaných, ${removedCount} odebraných) → integrations/changes-${TODAY}.json`);
    for (const c of allChanges) console.log(`   • ${c.desc}`);
  }
  if (warnings.length) { console.log("\n⚠ Varování:"); warnings.forEach((w) => console.log(`   • ${w}`)); }
  if (blocked) console.log(`\n⚠ ${blocked} vendor(ů) nedostupných/podezřelých — neověřeno, ne fail.`);

  // exit 1 JEN při tvrdé chybě (neznámý vendor). Bot-wall/suspect = exit 0.
  // Alarm (mail) řeší workflow krok podle changeCount, ne exit kód.
  process.exit(failures ? 1 : 0);
}

if (require.main === module) main();
