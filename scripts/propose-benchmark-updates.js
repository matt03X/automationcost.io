// propose-benchmark-updates.js — z benchmark-audit snapshotů navrhne PATCH do models.json.
// -----------------------------------------------------------------------------
// Vezme `matched` řádky z NEJNOVĚJŠÍHO snapshotu každého zdroje
// (llm/data/benchmark-audit/<source>/<date>.json), aplikuje precedenci
// (nezávislý zdroj > vendor) a zapíše per-model `benchmarks[metric] = {value,source,asof}`.
// Píše JEN to, co scraper jednoznačně namatchoval — NIKDY hádané/ručně vymyšlené číslo.
// Idempotentní: stejná hodnota+zdroj = beze změny. Self-check: čísla z LIVE snapshotu, ne z hlavy.
//
// Použití:
//   node scripts/propose-benchmark-updates.js                 # dry-run (vypíše návrh)
//   node scripts/propose-benchmark-updates.js --write         # zapíše do models.json
//   node scripts/propose-benchmark-updates.js --summary <f>   # markdown shrnutí (PR popis)
// Exit 0 = něco k aplikování / dry-run; 2 = nic.
"use strict";
const fs = require("fs");
const path = require("path");

const REPO = path.resolve(__dirname, "..");
const MODELS = path.join(REPO, "llm", "data", "models.json");
const AUDIT = path.join(REPO, "llm", "data", "benchmark-audit");
const WRITE = process.argv.includes("--write");
const arg = (n) => { const i = process.argv.indexOf(n); return i >= 0 ? process.argv[i + 1] : null; };

function latestSnapshot(srcDir) {
  const files = fs.readdirSync(srcDir).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f)).sort();
  if (!files.length) return null;
  try { return JSON.parse(fs.readFileSync(path.join(srcDir, files[files.length - 1]), "utf8")); }
  catch { return null; }
}

function main() {
  if (!fs.existsSync(AUDIT)) { console.log("Žádné benchmark-audit snapshoty — nic k návrhu."); process.exit(2); }
  const sources = fs.readdirSync(AUDIT).filter((d) => fs.statSync(path.join(AUDIT, d)).isDirectory());

  // posbírej matched řádky ze všech zdrojů (nejnovější snapshot)
  const rows = []; // {id, model, metric, value, source, asof}
  for (const s of sources) {
    const snap = latestSnapshot(path.join(AUDIT, s));
    if (snap && Array.isArray(snap.matched)) rows.push(...snap.matched);
  }
  if (!rows.length) { console.log("Žádné matched řádky ve snapshotech."); process.exit(2); }

  // precedence per (id, metric): nezávislý zdroj přebíjí vendor; mezi nezávislými ber nejvyšší value (leaderboard best)
  const best = new Map(); // id||metric -> row
  for (const r of rows) {
    const k = r.id + "||" + r.metric;
    const cur = best.get(k);
    if (!cur) { best.set(k, r); continue; }
    const rVendor = r.source === "vendor", cVendor = cur.source === "vendor";
    if (cVendor && !rVendor) best.set(k, r);                 // nezávislý přebíjí vendor
    else if (rVendor && !cVendor) { /* keep independent */ }
    else if (r.value > cur.value) best.set(k, r);            // stejná třída -> nejvyšší
  }

  const models = JSON.parse(fs.readFileSync(MODELS, "utf8"));
  const byId = {};
  for (const p of models.providers || []) for (const m of p.models || []) byId[m.id] = m;

  const applied = [], unchanged = [], orphan = [];
  for (const r of best.values()) {
    const m = byId[r.id];
    if (!m) { orphan.push(r); continue; }
    if (!m.benchmarks) m.benchmarks = {};
    const cur = m.benchmarks[r.metric];
    const next = { value: r.value, source: r.source, asof: r.asof };
    if (cur && cur.value === next.value && cur.source === next.source && cur.asof === next.asof) { unchanged.push(r); continue; }
    // independent nepřepisovat vendorem
    if (cur && cur.source !== "vendor" && r.source === "vendor") { unchanged.push(r); continue; }
    m.benchmarks[r.metric] = next;
    applied.push({ ...r, old: cur ? cur.value : null });
  }

  console.log(`Zdroje: ${sources.join(", ")} | matched ${rows.length} | unikátní (id,metric) ${best.size}`);
  console.log(`\n✅ Aplikováno (${applied.length}):`);
  for (const a of applied.sort((x, y) => x.model.localeCompare(y.model))) console.log(`   • ${a.model} ${a.metric} = ${a.value} (${a.source}, ${a.asof})${a.old != null ? ` [bylo ${a.old}]` : ""}`);
  if (unchanged.length) console.log(`\n= Beze změny: ${unchanged.length}`);
  if (orphan.length) console.log(`\n✋ Bez modelu v models.json (přeskočeno): ${orphan.map((o) => o.id + "/" + o.metric).join(", ")}`);

  const summaryPath = arg("--summary");
  if (summaryPath) {
    const byMetric = {};
    for (const a of applied) (byMetric[a.metric] = byMetric[a.metric] || []).push(a);
    const md = [
      `## Auto-návrh benchmark skóre → models.json (LIVE pull)`,
      ``,
      `Robot stáhl skóre z veřejných zdrojů (${sources.join(", ")}) a zapsal je do per-model \`benchmarks\` bloků jako \`{value, source, asof}\`. **Každé číslo je z live zdroje + datováno — žádné z tréninku.** Zkontroluj diff a **merge = schváleno** (fact gate).`,
      ``,
      `**Aplikováno: ${applied.length} hodnot** (${Object.keys(byMetric).join(", ")}).`,
      ...Object.entries(byMetric).flatMap(([metric, list]) => [
        ``, `### ${metric} (${list.length})`,
        ...list.sort((a, b) => b.value - a.value).map((a) => `- **${a.model}**: ${a.value} — _${a.source}, ${a.asof}_`),
      ]),
      ``,
      `> Zapsáno jen to, co scraper jednoznačně namatchoval přes \`benchmarkAliases\`; unmatched modely (i naše bez dat, např. Mistral Large 3) zůstávají bez hodnoty (nefabrikuje se). Inertní do Phase 4 (scoring wiring). ❌ Artificial Analysis nepoužito.`,
      ``,
    ].join("\n");
    fs.writeFileSync(summaryPath, md, "utf8");
    console.log(`\n📄 Shrnutí → ${summaryPath}`);
  }

  if (WRITE && applied.length) {
    fs.writeFileSync(MODELS, JSON.stringify(models, null, 2) + "\n", "utf8");
    console.log(`\n📝 Zapsáno do models.json (${applied.length} skóre). Spusť 'python llm/build.py --check'.`);
  } else if (!WRITE) {
    console.log(`\n(dry-run — nic se nezapsalo; přidej --write)`);
  }
  process.exit(applied.length || unchanged.length ? 0 : 2);
}
main();
