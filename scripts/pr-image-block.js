// pr-image-block.js — vygeneruje markdown s before/after PNG ceníku vendora
// pro POPIS Pull Requestu. Pro každého vendora se změnou ceny najde dva nejnovější
// <vendor>/<datum>.png (nový = dnešní, starý = předchozí) a vloží je přes raw URL.
//
// node scripts/pr-image-block.js <changesFile> <repo> <branch>
//   repo   = "owner/name" (GITHUB_REPOSITORY)
//   branch = ref, na kterém PNG leží (PR větev)
// Tiskne markdown na stdout (workflow ho připojí k pr-body.md). Nic = nic netiskne.
const fs = require("fs");
const path = require("path");

const [, , changesPath, repo, branch] = process.argv;
const AUDIT = path.resolve(__dirname, "..", "automation", "data", "audit");

function vendorPngs(vendor) {
  const dir = path.join(AUDIT, vendor);
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => /^\d{4}-\d{2}-\d{2}\.png$/.test(f)).sort(); // vzestupně dle data
}

function raw(vendor, file) {
  return `https://raw.githubusercontent.com/${repo}/${branch}/automation/data/audit/${vendor}/${file}`;
}

function main() {
  if (!changesPath || !repo || !branch || !fs.existsSync(changesPath)) return;
  let report;
  try { report = JSON.parse(fs.readFileSync(changesPath, "utf8")); } catch { return; }

  const vendors = [...new Set((report.changes || [])
    .filter((c) => c.kind !== "billing")
    .map((c) => c.vendor))];

  const blocks = [];
  for (const v of vendors) {
    const pngs = vendorPngs(v);
    if (!pngs.length) continue;
    const newPng = pngs[pngs.length - 1];
    const oldPng = pngs.length > 1 ? pngs[pngs.length - 2] : null;
    const lines = [`<details><summary>📸 <b>${v}</b> — ceník vendora (klikni pro before/after)</summary>`, ``];
    if (oldPng) {
      lines.push(`**Starý — ${oldPng.replace(".png", "")}:**`, ``, `![${v} old](${raw(v, oldPng)})`, ``);
    } else {
      lines.push(`_(starý screenshot není — první zaznamenaná změna u tohoto vendora)_`, ``);
    }
    lines.push(`**Nový — ${newPng.replace(".png", "")}:**`, ``, `![${v} new](${raw(v, newPng)})`, ``, `</details>`, ``);
    blocks.push(lines.join("\n"));
  }

  if (blocks.length) {
    process.stdout.write(`\n---\n## 📸 Vizuální before/after (ceníky vendorů)\n\n${blocks.join("\n")}\n`);
  }
}

main();
