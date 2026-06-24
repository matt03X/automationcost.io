#!/usr/bin/env node
/**
 * seat-drift-check.js — strážce SEAT/TEAM dat v automation/data/tools.json.
 *
 * PROČ: ceny škálujeme podle „Team size (users)" (calcCost seat filtr + per-seat
 * cost). Ta seat data jsou KURÁTOVANÁ ručně z živých pricing stránek
 * (n8n shared projects, Pipedream $2/user, Zapier Team/25 users). Tahle kontrola
 * je PROAKTIVNÍ: porovná, co tools.json TVRDÍ, s posledním scrapnutým
 * `billingLines` snapshotem (price-audit.js) a alarmuje, když živá stránka už ten
 * důkaz neobsahuje → čas seat data v tools.json aktualizovat.
 *
 * (price-audit.js diffPrices už alarmuje na ZMĚNU billing řádků den-proti-dni;
 * tohle navíc hlídá, že naše curated čísla pořád MAJÍ oporu v posledním scrapu.)
 *
 * Usage:
 *   node scripts/seat-drift-check.js          # human report, exit 1 při driftu
 *   node scripts/seat-drift-check.js --json    # strojový výstup
 *
 * NIKDY nepíše do tools.json — jen reportuje. Čísla mění owner (gated).
 */
"use strict";
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const TOOLS_JSON = path.join(ROOT, "automation", "data", "tools.json");
const AUDIT_DIR = path.join(ROOT, "automation", "data", "audit");
const JSON_OUT = process.argv.includes("--json");

function latestBillingLines(slug) {
  const d = path.join(AUDIT_DIR, slug);
  if (!fs.existsSync(d)) return { date: null, lines: null };
  const files = fs.readdirSync(d)
    .filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f))
    .sort();
  if (!files.length) return { date: null, lines: null };
  const f = files[files.length - 1];
  try {
    const data = JSON.parse(fs.readFileSync(path.join(d, f), "utf8"));
    const bl = data.billingLines || (data.prices && data.prices.billingLines) || [];
    return { date: f.slice(0, 10), lines: bl.map((x) => String(x).toLowerCase()) };
  } catch {
    return { date: null, lines: null };
  }
}

// najdi plán dle jména
const tools = JSON.parse(fs.readFileSync(TOOLS_JSON, "utf8")).tools;
const bySlug = Object.fromEntries(tools.map((t) => [t.slug, t]));

/**
 * Co od posledního scrapu OČEKÁVÁME, odvozené z curated seat dat v tools.json.
 * Každé pravidlo: { label, test(linesJoined) } — test vrací true když je důkaz přítomen.
 * Pravidla se generují z dat, takže když se tools.json změní, kontrola se přizpůsobí.
 */
function rulesFor(slug) {
  const t = bySlug[slug];
  if (!t) return [];
  const rules = [];

  // 1) per-seat add-on cost (Pipedream $2/user) → očekávej řádek s tou cenou
  const perSeat = (t.plans || []).map((p) => p.perSeatUsd).find((x) => x != null);
  if (perSeat != null) {
    const re = new RegExp("\\$?" + perSeat + "\\s*per additional user", "i");
    rules.push({ label: `$${perSeat}/additional user`, test: (s) => re.test(s) });
  }

  // 2) shared projects ladder (n8n 1/3/6) → každá konečná hodnota musí mít řádek
  const projVals = [...new Set((t.plans || []).map((p) => p.sharedProjects).filter((v) => typeof v === "number" && isFinite(v)))];
  for (const v of projVals) {
    const re = new RegExp("\\b" + v + " shared project", "i"); // "1 shared project" / "6 shared projects"
    rules.push({ label: `${v} shared project(s)`, test: (s) => re.test(s) });
  }

  // 3) seat-tier cap (Zapier Team maxUsers=25) → očekávej "<N> users"
  const caps = [...new Set((t.plans || []).map((p) => p.maxUsers).filter((v) => typeof v === "number" && isFinite(v) && v > 1))];
  for (const v of caps) {
    const re = new RegExp("\\b" + v + " users\\b", "i");
    rules.push({ label: `${v} users (seat tier)`, test: (s) => re.test(s) });
  }

  // 4) "unlimited users" tvrdíme JEN u nástroje s EXPLICITNÍM maxUsers:null tierem
  //    (Zapier Enterprise). Neodvozovat z absence omezení — ne každý tu frázi tiskne
  //    (activepieces má "unlimited runs", ne "unlimited users") → vyhneme se false alarmu.
  //    Nově zaváděné per-seat účtování u "flat" nástrojů chytí reaktivní diff
  //    (price-audit.js BILLING_KW hlídá user|seat řádky).
  if (t.multiUser === true && (t.plans || []).some((p) => p.maxUsers === null)) {
    rules.push({ label: "unlimited users", test: (s) => /unlimited users/i.test(s) });
  }

  return rules;
}

const SLUGS = ["n8n", "make", "pipedream", "zapier", "activepieces"]; // self-host (automatisch/node-red) nemají pricing scrape
const report = [];
let drift = 0, checked = 0, noSnapshot = 0;

for (const slug of SLUGS) {
  const rules = rulesFor(slug);
  if (!rules.length) continue;
  const { date, lines } = latestBillingLines(slug);
  if (!lines) {
    noSnapshot++;
    report.push({ slug, snapshot: null, status: "no-snapshot", rules: rules.map((r) => ({ label: r.label, ok: null })) });
    continue;
  }
  const joined = lines.join(" \n ");
  const rr = rules.map((r) => {
    const ok = r.test(joined);
    checked++;
    if (!ok) drift++;
    return { label: r.label, ok };
  });
  report.push({ slug, snapshot: date, status: rr.every((x) => x.ok) ? "ok" : "DRIFT", rules: rr });
}

if (JSON_OUT) {
  console.log(JSON.stringify({ checked, drift, noSnapshot, report }, null, 2));
} else {
  console.log("seat-drift-check — curated seat data vs latest live billingLines\n");
  for (const t of report) {
    const head = t.snapshot ? `(${t.snapshot})` : "(no snapshot)";
    console.log(`${t.status === "ok" ? "✓" : t.status === "DRIFT" ? "✗ DRIFT" : "· skip"}  ${t.slug.padEnd(12)} ${head}`);
    for (const r of t.rules) {
      const mark = r.ok === true ? "    ✓" : r.ok === false ? "    ✗ MISSING" : "    ? (no data)";
      console.log(`${mark}  ${r.label}`);
    }
  }
  console.log(`\n${checked} evidence checks · ${drift} missing · ${noSnapshot} tools without snapshot`);
  if (drift) console.log("→ Live pages no longer back some curated seat data. Re-verify and update tools.json (owner gate).");
}

process.exit(drift > 0 ? 1 : 0);
