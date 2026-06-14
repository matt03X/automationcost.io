// propose-price-updates.js — z auditních změn navrhne PATCH do tools.json.
// -----------------------------------------------------------------------------
// Pro každou CENOVOU změnu z changes-<date>.json najde v tools.json plán, jehož
// SOUČASNÁ cena == old (a opsIncluded == units, pokud změna nese objem). Když
// přesně JEDEN plán sedí → nastaví monthlyUsd = new. Když match není jednoznačný
// (0 nebo víc plánů) nebo jde o strukturální/billing změnu → NEpatchuje a dá to
// do "k ruční kontrole". Self-validating: auto-aplikuje jen to, čím jsme jistí.
//
// Použití:
//   node propose-price-updates.js                 # dry-run (jen vypíše návrh)
//   node propose-price-updates.js --write         # zapíše návrh do tools.json
//   node propose-price-updates.js --changes <f>   # konkrétní changes soubor
//   node propose-price-updates.js --summary <f>   # markdown shrnutí do souboru (pro PR)
// Exit 0 = něco k aplikování (nebo dry-run), 2 = nic k navržení.
const fs = require("fs");
const path = require("path");

const REPO = path.resolve(__dirname, "..");
const TOOLS = path.join(REPO, "automation", "data", "tools.json");
const AUDIT = path.join(REPO, "automation", "data", "audit");

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : null;
}
const WRITE = process.argv.includes("--write");

// nejnovější changes-*.json, pokud není zadaný --changes
function latestChangesFile() {
  const files = fs.readdirSync(AUDIT).filter((f) => /^changes-\d{4}-\d{2}-\d{2}\.json$/.test(f)).sort();
  return files.length ? path.join(AUDIT, files[files.length - 1]) : null;
}

function money(n) {
  return typeof n === "number" ? "$" + n : String(n);
}

// najdi plán, který bezpečně odpovídá změně (cena==old [+ ops==units])
function matchPlans(tool, change) {
  const old = change.old, units = change.units;
  return (tool.plans || []).filter((p) => {
    if (typeof p.monthlyUsd !== "number") return false;        // custom/null plány ne
    if (p.selfHostOnly) return false;                          // self-host = náš HW náklad, ne scrape
    if (Math.abs(p.monthlyUsd - old) > 0.005) return false;    // SOUČASNÁ cena musí == old
    if (units != null && p.opsIncluded !== units) return false; // objem musí sedět (když je)
    return true;
  });
}

function main() {
  const changesPath = arg("--changes") || latestChangesFile();
  if (!changesPath || !fs.existsSync(changesPath)) {
    console.log("Žádný changes soubor — nic k návrhu.");
    process.exit(2);
  }
  const report = JSON.parse(fs.readFileSync(changesPath, "utf8"));
  const tools = JSON.parse(fs.readFileSync(TOOLS, "utf8"));
  const bySlug = Object.fromEntries(tools.tools.map((t) => [t.slug, t]));

  const applied = [];   // { vendor, plan, units, old, neu }
  const manual = [];    // { vendor, desc, reason }

  for (const c of report.changes || []) {
    // billing pravidla = ne cena → vždy ruční (jen informace)
    if (c.kind === "billing") { manual.push({ vendor: c.vendor, desc: c.desc, reason: "billing pravidlo (ne cena)" }); continue; }
    // strukturální / nemapovatelné na jedno políčko monthlyUsd
    if (c.kind === "perCredit" || c.kind === "bandStructure") { manual.push({ vendor: c.vendor, desc: c.desc, reason: "credit-band sazba (strukturální)" }); continue; }
    if (c.kind === "listedPrices") { manual.push({ vendor: c.vendor, desc: c.desc, reason: "fixní ceník (pole hodnot — nejednoznačné)" }); continue; }
    if (typeof c.old !== "number" || typeof c.neu !== "number") { manual.push({ vendor: c.vendor, desc: c.desc, reason: "nečíselná změna" }); continue; }

    const tool = bySlug[c.vendor];
    if (!tool) { manual.push({ vendor: c.vendor, desc: c.desc, reason: "vendor není v tools.json" }); continue; }

    const hits = matchPlans(tool, c);
    if (hits.length === 1) {
      const p = hits[0];
      applied.push({ vendor: c.vendor, plan: p.name, units: c.units ?? p.opsIncluded, old: p.monthlyUsd, neu: c.neu });
      p.monthlyUsd = c.neu;
    } else {
      manual.push({
        vendor: c.vendor,
        desc: c.desc || `${c.vendor} ${c.plan || ""} @${c.units || "?"}: ${money(c.old)} → ${money(c.neu)}`,
        reason: hits.length === 0
          ? `v tools.json není plán s cenou ${money(c.old)}${c.units != null ? ` @${c.units}` : ""} (tools.json už nesedí / jiný název)`
          : `${hits.length} plánů sedí na ${money(c.old)} — nejednoznačné`,
      });
    }
  }

  // výpis
  console.log(`Zdroj změn: ${path.basename(changesPath)}  (${(report.changes || []).length} změn)`);
  console.log(`\n✅ Auto-aplikovatelné (${applied.length}):`);
  for (const a of applied) console.log(`   • ${a.vendor} "${a.plan}" (${a.units}): ${money(a.old)} → ${money(a.neu)}`);
  console.log(`\n✋ K ruční kontrole (${manual.length}):`);
  for (const m of manual) console.log(`   • ${m.vendor}: ${m.desc}  — ${m.reason}`);

  // markdown shrnutí (pro PR popis)
  const summaryPath = arg("--summary");
  if (summaryPath) {
    const md = [
      `## Auto-návrh cenových změn (audit ${report.date || "?"})`,
      ``,
      `Robot porovnal scrape s \`tools.json\`. Zkontroluj diff a **merge = schváleno**.`,
      ``,
      `### ✅ Aplikováno (${applied.length})`,
      ...(applied.length ? applied.map((a) => `- **${a.vendor}** \`${a.plan}\` (${a.units}): ${money(a.old)} → ${money(a.neu)}`) : ["- _nic_"]),
      ``,
      `### ✋ K ruční kontrole (${manual.length})`,
      ...(manual.length ? manual.map((m) => `- **${m.vendor}**: ${m.desc} — _${m.reason}_`) : ["- _nic_"]),
      ``,
      `> Aplikováno jen tam, kde současná cena v tools.json přesně odpovídala scrapnuté „old" hodnotě (self-check). Zbytek je na tvé posouzení.`,
      ``,
    ].join("\n");
    fs.writeFileSync(summaryPath, md, "utf8");
  }

  if (WRITE && applied.length) {
    tools._meta.last_reviewed = report.date || new Date().toISOString().slice(0, 10);
    fs.writeFileSync(TOOLS, JSON.stringify(tools, null, 2) + "\n", "utf8");
    console.log(`\n📝 Zapsáno do tools.json (${applied.length} cen). Spusť 'python build.py' a zkontroluj diff.`);
  } else if (WRITE) {
    console.log(`\n(nic k zápisu)`);
  } else {
    console.log(`\n(dry-run — nic se nezapsalo; přidej --write pro zápis)`);
  }

  process.exit(applied.length || manual.length ? 0 : 2);
}

main();
