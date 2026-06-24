#!/usr/bin/env node
/**
 * llm-benchmark-pull.js — LIVE pull benchmark skóre LLM modelů (capability vrstva).
 *
 * Zrcadlo scripts/llm-price-audit.js, ale pro BENCHMARKY. Vrstva DŮKAZŮ pod
 * llm/data/models.json `benchmarks` bloky. Pro každý zdroj (epoch, …):
 *   1) stáhne LIVE data (Playwright — node fetch má v tomto env rozbité TLS)
 *   2) source modul (scripts/benchmark-sources/<source>.js) je rozparsuje na
 *      [{ extName, metric, value(0..100) }] — JEN skóre, NIKDY text otázek
 *   3) snapshot → llm/data/benchmark-audit/<source>/<YYYY-MM-DD>.json (VŽDY)
 *   4) match extName → náš model přes per-model `benchmarkAliases[source]`
 *      (default = model.name; case-insensitive). NEJEDNOZNAČNÉ/NENAMAPOVANÉ =
 *      skip + report, NIKDY hádaný zápis.
 *   5) matched → append benchmark-audit/benchmarks-history.jsonl
 *   6) diff vs předchozí snapshot → changes-<date>.json (changeCount>0 = alarm)
 *
 * EVIDENCE, NE ZDROJ PRAVDY. Čísla do models.json přesune scripts/propose-benchmark-updates.js
 * (owner gate). Žádné číslo z tréninku — výhradně z live zdroje + asof.
 * ❌ Artificial Analysis ZAKÁZÁNO (hard lint níže).
 *
 * Spuštění:
 *   node scripts/llm-benchmark-pull.js                  # všechny zdroje, snapshot + diff
 *   node scripts/llm-benchmark-pull.js epoch            # jen vybraný zdroj
 *   node scripts/llm-benchmark-pull.js epoch --no-diff  # jen snapshot (dry-run)
 * Lokálně: NODE_PATH=../../calc-test/node_modules node scripts/llm-benchmark-pull.js epoch --no-diff
 * V CI: Playwright v /tmp/pw přes NODE_PATH (viz .github/workflows/llm-benchmark-pull.yml).
 */
"use strict";
const fs = require("fs");
const path = require("path");

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const REPO = path.resolve(__dirname, "..");
const AUDIT_DIR = path.join(REPO, "llm", "data", "benchmark-audit");
const MODELS_PATH = path.join(REPO, "llm", "data", "models.json");
const TODAY = new Date().toISOString().slice(0, 10);
const HEADED = process.argv.includes("--headed");
const NO_DIFF = process.argv.includes("--no-diff");

// ── registr zdrojů ──────────────────────────────────────────────────────────
const SOURCES = {
  epoch: require("./benchmark-sources/epoch.js"),
  // swebench, lmarena, tbench, bfcl, taubench, helm … = follow-up moduly
};

// ❌ HARD legal lint: Artificial Analysis se nesmí objevit jako zdroj (proprietární ToU).
for (const [k, s] of Object.entries(SOURCES)) {
  if (/artificialanalysis/i.test(k) || /artificialanalysis/i.test(s.URL || "")) {
    throw new Error(`ZAKÁZANÝ zdroj (Artificial Analysis): ${k}`);
  }
}

function sourceDir(s) { const d = path.join(AUDIT_DIR, s); fs.mkdirSync(d, { recursive: true }); return d; }

function previousSnapshot(s) {
  const d = sourceDir(s);
  const files = fs.readdirSync(d).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f) && f.slice(0, 10) < TODAY).sort();
  if (!files.length) return null;
  const f = files[files.length - 1];
  try { return { date: f.slice(0, 10), data: JSON.parse(fs.readFileSync(path.join(d, f), "utf8")) }; }
  catch { return null; }
}

const norm = (x) => (x || "").toLowerCase().replace(/\s+/g, " ").trim();

// extName -> { id, name } přes benchmarkAliases[source] (default = name). Case-insensitive.
function buildModelIndex(source) {
  const m = JSON.parse(fs.readFileSync(MODELS_PATH, "utf8"));
  const idx = new Map();
  for (const prov of m.providers || []) {
    for (const mdl of prov.models || []) {
      const alias = mdl.benchmarkAliases && mdl.benchmarkAliases[source];
      idx.set(norm(alias || mdl.name), { id: mdl.id, name: mdl.name });
      // přidej i default name jako záložní klíč (kdyby alias byl jen doplněk)
      idx.set(norm(mdl.name), idx.get(norm(mdl.name)) || { id: mdl.id, name: mdl.name });
    }
  }
  return idx;
}

// ── fetch (Playwright APIRequest; node fetch má rozbité TLS, browser navigace spadne na download) ──
let _api = null;
async function api() {
  if (!_api) {
    const { request } = require("playwright");
    // ignoreHTTPSErrors: lokální CA store neověří řetěz (cert je validní, jen chybí chain).
    // Stahujeme veřejné CC-BY skóre, ne citlivá data. V CI je CA chain kompletní (no-op).
    _api = await request.newContext({ userAgent: UA, ignoreHTTPSErrors: true, timeout: 60000 });
  }
  return _api;
}
async function fetchText(url) {
  const res = await (await api()).get(url, { maxRedirects: 6 });
  if (!res.ok()) throw new Error(`HTTP ${res.status()}`);
  const text = await res.text();
  if (!text || text.length < 200) throw new Error(`příliš krátká odpověď (${text ? text.length : 0} B) — bot wall?`);
  return text;
}

// diff: porovná value per (extName, metric). Nový/změněný = alarm. (Mizení neřešíme — zdroj přidává.)
function diffRows(source, oldSnap, newSnap) {
  const changes = [];
  const key = (r) => norm(r.extName) + "|" + r.metric;
  const oldMap = new Map((oldSnap && oldSnap.rows || []).map((r) => [key(r), r.value]));
  for (const r of newSnap.rows || []) {
    const ov = oldMap.get(key(r));
    if (ov === undefined) changes.push({ source, extName: r.extName, metric: r.metric, old: null, neu: r.value, desc: `${source} NOVÉ ${r.extName} ${r.metric}=${r.value}` });
    else if (ov !== r.value) changes.push({ source, extName: r.extName, metric: r.metric, old: ov, neu: r.value, desc: `${source} ${r.extName} ${r.metric}: ${ov} → ${r.value}` });
  }
  return changes;
}

if (require.main !== module) { module.exports = { diffRows, buildModelIndex, norm }; }

// ── runner ───────────────────────────────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const targets = args.length ? args : Object.keys(SOURCES);
  fs.mkdirSync(AUDIT_DIR, { recursive: true });
  const allChanges = [];
  let failures = 0, blocked = 0;

  for (const s of targets) {
    const src = SOURCES[s];
    if (!src) { console.error(`✗ neznámý zdroj: ${s}`); failures++; continue; }
    process.stdout.write(`→ ${s} … `);
    try {
      const prev = NO_DIFF ? null : previousSnapshot(s);
      const text = await fetchText(src.URL);
      const rows = src.pull(text);                       // [{extName, metric, value}]
      if (!rows.length) throw new Error("0 řádků (změna formátu? bot wall?)");

      // match na naše modely
      const idx = buildModelIndex(s);
      const matched = [], unmatched = new Set();
      for (const r of rows) {
        const hit = idx.get(norm(r.extName));
        if (hit) matched.push({ model: hit.name, id: hit.id, metric: r.metric, value: r.value, source: s, asof: TODAY });
        else unmatched.add(r.extName);
      }

      const snapshot = { source: s, scrapedAt: new Date().toISOString(), url: src.URL, license: src.LICENSE || null,
        rowCount: rows.length, matchedCount: matched.length, unmatchedCount: unmatched.size,
        rows, matched, unmatched: [...unmatched].sort() };
      const dir = sourceDir(s);
      fs.writeFileSync(path.join(dir, `${TODAY}.json`), JSON.stringify(snapshot, null, 2) + "\n", "utf8");

      let changed = [];
      if (prev) { changed = diffRows(s, prev.data, snapshot); allChanges.push(...changed); }
      if (changed.length) {
        fs.writeFileSync(path.join(dir, `changes-${TODAY}.json`),
          JSON.stringify({ source: s, date: TODAY, generatedAt: new Date().toISOString(), changeCount: changed.length, changes: changed }, null, 2) + "\n", "utf8");
      }
      if (matched.length) {
        const line = matched.map((mm) => JSON.stringify({ d: TODAY, source: s, model: mm.model, metric: mm.metric, value: mm.value })).join("\n") + "\n";
        fs.appendFileSync(path.join(AUDIT_DIR, "benchmarks-history.jsonl"), line, "utf8");
      }
      console.log(`OK (${rows.length} řádků · ${matched.length} matched · ${unmatched.size} unmatched · ${changed.length} změn vs ${prev ? prev.date : "—"})`);
      if (unmatched.size) console.log(`   ⓘ unmatched (nezapsáno): ${[...unmatched].slice(0, 12).join(", ")}${unmatched.size > 12 ? " …" : ""}`);
    } catch (e) {
      const msg = e.message || String(e);
      const isBotWall = /bot|403|429|503|timeout|Timeout|krátk|net::|ERR_|odpověď/i.test(msg);
      if (isBotWall) { console.log(`⚠ WARN (nedostupné / bot wall, ne změna): ${msg.slice(0, 90)}`); blocked++; }
      else { console.log(`SELHALO: ${msg}`); failures++; }
    }
  }

  if (_api) await _api.dispose().catch(() => {});
  console.log(`\n📋 ${allChanges.length} změn celkem na ${TODAY}`);
  for (const c of allChanges.slice(0, 40)) console.log(`   • ${c.desc}`);
  if (blocked) console.log(`⚠ ${blocked} zdroj(ů) nedostupných — neověřeno, ne fail.`);
  // exit 1 (mail ownerovi → fact gate) jen při reálné změně NEBO tvrdé chybě. Bot-wall = exit 0.
  process.exit(failures || allChanges.length ? 1 : 0);
}
if (require.main === module) main();
