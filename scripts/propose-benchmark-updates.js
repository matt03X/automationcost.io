// propose-benchmark-updates.js — z benchmark-audit snapshotů navrhne PATCH do benchmarks.json.
// -----------------------------------------------------------------------------
// Vezme `matched` řádky z NEJNOVĚJŠÍHO snapshotu každého zdroje
// (llm/data/benchmark-audit/<source>/<date>.json), aplikuje precedenci
// (nezávislý zdroj > vendor) a zapíše do llm/data/benchmarks.json:
//     byModel[<model id>][<metric>] = { value, source, asof }
// models.json (cenový moat) se NEDOTÝKÁ — capability data žijí ve vlastním souboru
// (jiný zdroj, jiná kadence, čistý diff). Píše JEN jednoznačně namatchované řádky —
// NIKDY hádané/ručně vymyšlené číslo. Idempotentní. Self-check: čísla z LIVE snapshotu.
//
// Použití:
//   node scripts/propose-benchmark-updates.js                 # dry-run
//   node scripts/propose-benchmark-updates.js --write         # zapíše benchmarks.json
//   node scripts/propose-benchmark-updates.js --summary <f>   # markdown shrnutí (PR popis)
// Exit 0 = něco k aplikování / dry-run; 2 = nic.
"use strict";
const fs = require("fs");
const path = require("path");

const REPO = path.resolve(__dirname, "..");
const MODELS = path.join(REPO, "llm", "data", "models.json");   // jen čtení (validace id + jména)
const BENCH = path.join(REPO, "llm", "data", "benchmarks.json"); // zápis
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
  const sources = fs.readdirSync(AUDIT).filter((d) => { try { return fs.statSync(path.join(AUDIT, d)).isDirectory(); } catch { return false; } });

  const rows = []; // {id, model, metric, value, source, asof}
  for (const s of sources) {
    const snap = latestSnapshot(path.join(AUDIT, s));
    if (snap && Array.isArray(snap.matched)) rows.push(...snap.matched);
  }
  if (!rows.length) { console.log("Žádné matched řádky."); process.exit(2); }

  // precedence per (id, metric): nezávislý > vendor; mezi stejnou třídou nejvyšší value (leaderboard best)
  const best = new Map();
  for (const r of rows) {
    const k = r.id + "||" + r.metric, cur = best.get(k);
    if (!cur) { best.set(k, r); continue; }
    const rV = r.source === "vendor", cV = cur.source === "vendor";
    if (cV && !rV) best.set(k, r);
    else if (rV && !cV) { /* keep */ }
    else if (r.value > cur.value) best.set(k, r);
  }

  const models = JSON.parse(fs.readFileSync(MODELS, "utf8"));
  const byId = {};
  for (const p of models.providers || []) for (const m of p.models || []) byId[m.id] = m.name;

  const bench = fs.existsSync(BENCH) ? JSON.parse(fs.readFileSync(BENCH, "utf8")) : {};
  if (!bench.byModel) bench.byModel = {};

  const applied = [], unchanged = [], orphan = [];
  for (const r of best.values()) {
    if (!byId[r.id]) { orphan.push(r); continue; }
    const slot = bench.byModel[r.id] || (bench.byModel[r.id] = {});
    const cur = slot[r.metric];
    const next = { value: r.value, source: r.source, asof: r.asof };
    if (cur && cur.value === next.value && cur.source === next.source && cur.asof === next.asof) { unchanged.push(r); continue; }
    if (cur && cur.source !== "vendor" && r.source === "vendor") { unchanged.push(r); continue; } // independent nepřepisovat vendorem
    slot[r.metric] = next;
    applied.push({ ...r, model: byId[r.id], old: cur ? cur.value : null });
  }

  console.log(`Zdroje: ${sources.join(", ")} | matched ${rows.length} | unikátní (id,metric) ${best.size}`);
  console.log(`\n✅ Aplikováno (${applied.length}):`);
  for (const a of applied.sort((x, y) => x.model.localeCompare(y.model))) console.log(`   • ${a.model} ${a.metric} = ${a.value} (${a.source}, ${a.asof})${a.old != null ? ` [bylo ${a.old}]` : ""}`);
  if (unchanged.length) console.log(`\n= Beze změny: ${unchanged.length}`);
  if (orphan.length) console.log(`\n✋ id není v models.json (přeskočeno): ${orphan.map((o) => o.id + "/" + o.metric).join(", ")}`);

  const summaryPath = arg("--summary");
  if (summaryPath) {
    const byMetric = {};
    for (const a of applied) (byMetric[a.metric] = byMetric[a.metric] || []).push(a);
    const md = [
      `## Auto-návrh benchmark skóre → \`llm/data/benchmarks.json\` (LIVE pull)`,
      ``,
      `Robot stáhl skóre z veřejných zdrojů (**${sources.join(", ")}**) a zapsal je jako \`{value, source, asof}\`. **Každé číslo je z live zdroje a datované — žádné z tréninku.** Zkontroluj diff a **merge = schváleno** (fact gate).`,
      ``,
      `**Aplikováno: ${applied.length} hodnot** (${Object.keys(byMetric).join(", ")}). models.json (cenový moat) netknutý.`,
      ...Object.entries(byMetric).flatMap(([metric, list]) => [
        ``, `### ${metric} (${list.length})`,
        ...list.sort((a, b) => b.value - a.value).map((a) => `- **${a.model}**: ${a.value} — _${a.source}, ${a.asof}_`),
      ]),
      ``,
      `> Zapsáno jen jednoznačně namatchované (přes \`benchmarkAliases\`); modely bez dat (např. Mistral Large 3, DeepSeek V4 Flash) zůstávají bez hodnoty — **nefabrikuje se**. Inertní do Phase 4 (scoring wiring). ❌ Artificial Analysis nepoužito.`,
      ``,
    ].join("\n");
    fs.writeFileSync(summaryPath, md, "utf8");
    console.log(`\n📄 Shrnutí → ${summaryPath}`);
  }

  if (WRITE && applied.length) {
    bench._meta = { note: "Capability/benchmark skóre LLM modelů. Plní scraper (llm-benchmark-pull.js) + propose-benchmark-updates.js. {value,source,asof}, vše z LIVE zdroje, NIKDY z tréninku. Klíč = model id z models.json. models.json = cenový moat (oddělené).", lastPull: new Date().toISOString().slice(0, 10), sources };
    fs.writeFileSync(BENCH, JSON.stringify(bench, null, 2) + "\n", "utf8");
    console.log(`\n📝 Zapsáno do llm/data/benchmarks.json (${applied.length} skóre).`);
  } else if (!WRITE) {
    console.log(`\n(dry-run — nic se nezapsalo; přidej --write)`);
  }
  process.exit(applied.length || unchanged.length ? 0 : 2);
}
main();
