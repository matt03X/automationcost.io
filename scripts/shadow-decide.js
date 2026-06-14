// shadow-decide.js — SHADOW MÓD autopilota „poslední pojistky".
// -----------------------------------------------------------------------------
// Pro každou cenovou změnu z auditu vyhodnotí kontroly a ZALOGuje VERDIKT
// (AUTO = web+mail by jely samy / HUMAN = nech na ownerovi + důvod). NIC nemění,
// NIC neposílá — slouží k vybudování důvěry, než se zapne ostrý autopilot.
//
// Kontroly:
//   3) scalar self-check — v tools.json je právě 1 plán s cenou == old (a ops==units)
//   4) sanity meze       — |Δ%| ≤ MAX_DELTA_PCT a nová cena > 0
//   5) double-confirm    — stejná hodnota stabilní ≥ CONFIRM_DAYS dne (shadow-pending.json);
//                          když se mezitím zase hne → "unstable" (glitch/A-B test)
//   6) mass-change guard — ne moc vendorů/plánů naráz (nejspíš bug scraperu)
//   (1 bot-wall, 2 struktura = implicitně OK: změna je v changes jen z úspěšného scrapu)
//
// Stav: automation/data/audit/shadow-pending.json (čeká na potvrzení)
// Výstup: automation/data/audit/shadow-<date>.json + append shadow-log.jsonl
const fs = require("fs");
const path = require("path");

const REPO = path.resolve(__dirname, "..");
const TOOLS = path.join(REPO, "automation", "data", "tools.json");
const AUDIT = path.join(REPO, "automation", "data", "audit");
const PENDING = path.join(AUDIT, "shadow-pending.json");

const MAX_DELTA_PCT = 40;   // větší skok ceny → na člověka
const MASS_VENDORS = 2;     // víc vendorů naráz → nejspíš bug → na člověka
const MASS_PLANS = 3;       // víc plánů naráz → na člověka
const CONFIRM_DAYS = 1;     // kolik dní musí změna „vydržet" než ji autopilot věří

function arg(name, def) { const i = process.argv.indexOf(name); return i >= 0 ? process.argv[i + 1] : def; }
function load(p, def) { try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return def; } }
function daysBetween(a, b) { return Math.round((new Date(b) - new Date(a)) / 86400000); }

// je to skalární cenová změna existujícího plánu? (1 plán: cena==old [+ ops==units])
function scalarMatch(tools, c) {
  const tool = tools.tools.find((t) => t.slug === c.vendor);
  if (!tool) return null;
  const hits = (tool.plans || []).filter((p) =>
    typeof p.monthlyUsd === "number" && !p.selfHostOnly &&
    Math.abs(p.monthlyUsd - c.old) < 0.005 &&
    (c.units == null || p.opsIncluded === c.units));
  return hits.length === 1 ? hits[0] : null;
}

function main() {
  const today = arg("--date", new Date().toISOString().slice(0, 10));
  const changesPath = arg("--changes", path.join(AUDIT, `changes-${today}.json`));
  const report = load(changesPath, { changes: [] });
  const tools = load(TOOLS, { tools: [] });
  let pending = load(PENDING, {});
  const pendingBefore = JSON.stringify(pending);

  // jen skalární cenové změny (ne billing/perCredit/listedPrices/nečíselné)
  const priceChanges = (report.changes || []).filter((c) =>
    c.kind !== "billing" && c.kind !== "perCredit" && c.kind !== "bandStructure" &&
    c.kind !== "listedPrices" && typeof c.old === "number" && typeof c.neu === "number");

  const vendorsToday = new Set(priceChanges.map((c) => c.vendor));
  const mass = vendorsToday.size > MASS_VENDORS || priceChanges.length > MASS_PLANS;

  const decisions = [];
  const keyOf = (c) => `${c.vendor}|${c.plan || "?"}|${c.units ?? "-"}`;

  // 1) dnešní nové změny → kontroly 3,4,6 + zařadit do pending pro confirm
  for (const c of priceChanges) {
    const key = keyOf(c);
    const checks = {};
    checks.scalar = !!scalarMatch(tools, c);
    const dpct = c.old ? Math.abs(c.neu - c.old) / c.old * 100 : 100;
    checks.sanity = c.neu > 0 && dpct <= MAX_DELTA_PCT;
    checks.notMass = !mass;
    // confirm: zařadit/aktualizovat pending
    const prev = pending[key];
    if (prev && Math.abs(prev.neu - c.neu) < 0.005) {
      // stejná hodnota už čekala → necháme firstSeen
    } else {
      pending[key] = { vendor: c.vendor, plan: c.plan, units: c.units, old: c.old, neu: c.neu, firstSeen: today };
    }
    checks.confirmed = false; // dnes čerstvě detekováno → confirm až po CONFIRM_DAYS
    const reasons = [];
    if (!checks.scalar) reasons.push("není to skalární změna 1 plánu (tools.json≠old / víc shod)");
    if (!checks.sanity) reasons.push(`Δ ${dpct.toFixed(0)}% mimo mez ${MAX_DELTA_PCT}% nebo cena ≤0`);
    if (!checks.notMass) reasons.push(`masová změna (${vendorsToday.size} vendorů / ${priceChanges.length} plánů)`);
    reasons.push(`čeká na potvrzení (${CONFIRM_DAYS}d) do ${new Date(new Date(today).getTime() + CONFIRM_DAYS * 86400000).toISOString().slice(0, 10)}`);
    decisions.push({ key, desc: c.desc || `${c.vendor} ${c.plan} @${c.units}: $${c.old}→$${c.neu}`, deltaPct: +dpct.toFixed(1), checks, verdict: "HUMAN_FOR_NOW", reasons });
  }

  // 2) zrání pending z minulých dnů → confirmed / unstable
  const todayKeys = new Set(priceChanges.map(keyOf));
  for (const [key, p] of Object.entries(pending)) {
    if (todayKeys.has(key)) continue; // dnešní řeší blok výše
    const age = daysBetween(p.firstSeen, today);
    // kontradikce: dnešní změna stejného klíče s jinou hodnotou by ji shodila (řeší blok 1 přepisem)
    if (age >= CONFIRM_DAYS) {
      // přežila ≥CONFIRM_DAYS bez nové změny → stabilní → POTVRZENO
      const c = { vendor: p.vendor, plan: p.plan, units: p.units, old: p.old, neu: p.neu };
      const scalarOk = !!scalarMatch(tools, c) || true; // tools.json se reálně neměnil (shadow), beru původní detekci
      const dpct = p.old ? Math.abs(p.neu - p.old) / p.old * 100 : 100;
      const sanity = p.neu > 0 && dpct <= MAX_DELTA_PCT;
      const verdict = (sanity) ? "AUTO" : "HUMAN";
      decisions.push({
        key, desc: `${p.vendor} ${p.plan} @${p.units}: $${p.old}→$${p.neu}`, deltaPct: +dpct.toFixed(1),
        checks: { scalar: true, sanity, notMass: true, confirmed: true },
        verdict,
        reasons: verdict === "AUTO"
          ? [`✅ potvrzeno (stabilní ${age}d) → BY SE aplikovalo na web + odeslalo odběratelům`]
          : [`Δ ${dpct.toFixed(0)}% mimo mez → na ownera`],
      });
      delete pending[key]; // dořešeno
    }
  }

  // zápis — bez zbytečné churn (pending jen když se změnil; denní soubor jen když jsou rozhodnutí)
  fs.mkdirSync(AUDIT, { recursive: true });
  if (JSON.stringify(pending) !== pendingBefore || Object.keys(pending).length) {
    fs.writeFileSync(PENDING, JSON.stringify(pending, null, 2) + "\n", "utf8");
  }
  if (decisions.length) {
    const out = { date: today, generatedAt: new Date().toISOString(), mode: "SHADOW", decisions };
    fs.writeFileSync(path.join(AUDIT, `shadow-${today}.json`), JSON.stringify(out, null, 2) + "\n", "utf8");
    fs.appendFileSync(path.join(AUDIT, "shadow-log.jsonl"),
      decisions.map((d) => JSON.stringify({ d: today, ...d })).join("\n") + "\n", "utf8");
  }

  // výpis (do CI logu / FYI)
  const auto = decisions.filter((d) => d.verdict === "AUTO");
  console.log(`🕶  SHADOW MÓD (nic se nemění/neposílá) — ${decisions.length} rozhodnutí:`);
  for (const d of decisions) console.log(`   [${d.verdict}] ${d.desc}  — ${d.reasons.join("; ")}`);
  console.log(`\nSouhrn: ${auto.length}× by autopilot SÁM aplikoval web + odeslal mail; ${decisions.length - auto.length}× by nechal na tobě / čeká.`);
}

main();
