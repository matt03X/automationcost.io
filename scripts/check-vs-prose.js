#!/usr/bin/env node
/**
 * check-vs-prose.js — denní guard: cenová PRÓZA na vs-stránkách nesmí driftovat
 * od cenové TABULKY (= engine output na téže stránce).
 *
 * Próza v pairs.json (verdict/whyLoser) je ručně psaná a obsahuje multiplikátory
 * („Make 5–10× cheaper"). Cenová tabulka na stránce je generovaná z enginu. Když
 * se ceny změní (a próza ne), próza začne LHÁT — a nadhodnocení výhody vítěze je
 * favors_us / nekalá soutěž. Tenhle skript to chytí bez Playwrightu (čte jen repo).
 *
 * NE-cenová fakta (integrace atd.) hlídá scripts/facts-audit.js (scrape).
 * Vzor lokálního guardu: calc-test/test-vs-pages.js (tohle je jeho CI varianta).
 *
 * Spuštění: node scripts/check-vs-prose.js   (exit 1 při driftu → CI fail = alarm)
 */
"use strict";
const fs = require("fs");
const path = require("path");

const AUTO = path.resolve(__dirname, "..", "automation");
const PAIRS = JSON.parse(fs.readFileSync(path.join(AUTO, "data", "pairs.json"), "utf8"));
const TOL_HI = 1.25;  // claim max nesmí přestřelit engine max o víc než 25 % (NADhodnocení = riziko)
const TOL_LO = 0.75;  // claim max nesmí být < 75 % engine min (hrubé PODhodnocení)

let fails = 0, checks = 0;

for (const pair of PAIRS.pairs) {
  const slug = `${pair.a}-vs-${pair.b}`;
  const file = path.join(AUTO, `${slug}.html`);
  if (!fs.existsSync(file)) { console.log(`SKIP ${slug} (stránka neexistuje)`); continue; }
  const html = fs.readFileSync(file, "utf8");

  const prose = pair.verdict + " " + (pair.whyLoser || "");
  const m = prose.match(/([\d.]+)\s*[–-]\s*([\d.]+)\s*×/) || prose.match(/([\d.]+)\s*×/);
  if (!m) continue;  // pár nemá multiplikátorové tvrzení
  const claimLo = parseFloat(m[1]);
  const claimHi = parseFloat(m[2] || m[1]);

  // engine mult range z cenové tabulky stránky (4 objemy × 2 nástroje)
  const rows = [...html.matchAll(/<td class="vol">[\s\S]*?<\/tr>/g)];
  const mults = [];
  for (const r of rows) {
    const prices = [...r[0].matchAll(/<span class="price">~?\$([\d,]+(?:\.\d+)?)/g)]
      .map((x) => parseFloat(x[1].replace(/,/g, "")));
    if (prices.length === 2 && Math.min(...prices) > 0) mults.push(Math.max(...prices) / Math.min(...prices));
  }
  if (!mults.length) continue;  // např. AP $0 ve všech řádcích → multiplikátor nedefinován

  checks++;
  const eLo = Math.min(...mults), eHi = Math.max(...mults);
  const ok = claimHi <= eHi * TOL_HI && claimLo <= eHi * 1.05 && claimHi >= eLo * TOL_LO;
  if (ok) {
    console.log(`OK   ${slug}: próza ${claimLo}–${claimHi}× vs engine ${eLo.toFixed(1)}–${eHi.toFixed(1)}×`);
  } else {
    fails++;
    console.log(`DRIFT ${slug}: próza tvrdí ${claimLo}–${claimHi}×, ale cenová tabulka dává ${eLo.toFixed(1)}–${eHi.toFixed(1)}× — uprav pairs.json (viz docs/vs-audit-report.md)`);
  }
}

console.log(`\nvs-prose guard: ${checks - fails}/${checks} OK${fails ? `, ${fails} DRIFT` : ""}`);
process.exit(fails ? 1 : 0);
