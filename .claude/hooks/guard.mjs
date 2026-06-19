#!/usr/bin/env node
// WizardCost repo guard — Guards 2–4. Commitnutý → dědí ho i cloud routine.
//   PreToolUse  → Guard 2 (GA4 / e-mail formuláře) + Guard 3 (cena / affiliate)
//   PostToolUse → Guard 4 (build --check po editu generovaných zdrojů)
//
// Exit kódy (Claude Code hooks):
//   0 = OK (pokračuj)   1 = pokračuj, ale ukaž poznámku (warn)   2 = BLOK (stderr → Claude)
//
// Lokální vs autonomní (routine) běh řešíme env flagem, který je JEN v
// .claude/settings.local.json (gitignored) → routine ho NIKDY nemá:
//   WIZARDCOST_ALLOW_SENSITIVE  → cena/affiliate: warn místo blok (tvoje legitimní edity)
//   WIZARDCOST_ALLOW_GA4        → vědomé povolení re-enable GA4/formulářů (po revizi)

import { execSync } from "node:child_process";

function readStdin() {
  return new Promise((resolve) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (c) => (data += c));
    process.stdin.on("end", () => resolve(data));
    setTimeout(() => resolve(data), 2000);
  });
}

const norm = (s) => String(s).replace(/\\/g, "/");
const base = (p) => norm(p).split("/").pop() || "";

// ---- vstup -----------------------------------------------------------------
const raw = await readStdin();
let payload;
try {
  payload = JSON.parse(raw || "{}");
} catch {
  process.exit(0); // malformed → fail-open
}
const event = payload.hook_event_name || "";
const tool = payload.tool_name || "";
const input = payload.tool_input || {};

function paths() {
  const out = [];
  if (typeof input.file_path === "string") out.push(input.file_path);
  if (Array.isArray(input.edits)) for (const e of input.edits) if (e?.file_path) out.push(e.file_path);
  return out;
}
function newText() {
  let t = "";
  if (typeof input.content === "string") t += "\n" + input.content;
  if (typeof input.new_string === "string") t += "\n" + input.new_string;
  if (Array.isArray(input.edits)) for (const e of input.edits) if (typeof e?.new_string === "string") t += "\n" + e.new_string;
  return t;
}

// ---- detektory -------------------------------------------------------------
const SENSITIVE_FILES = [
  "automation/data/tools.json",
  "llm/data/models.json",
  "automation/data/scoring-model.json",
  "automation/data/pairs.json",
];
const isSensitiveFile = (p) => SENSITIVE_FILES.some((s) => norm(p).endsWith(s));

const RE_GA4 = [/\bgtag\s*\(/, /\bG-[A-Z0-9]{8,}\b/, /googletagmanager\.com/i, /google-analytics\.com/i, /\bga\(\s*['"]create['"]/i];
const RE_FORM = [/ml-submit/i, /anticsrf\s*=\s*true/i, /assets\.mailerlite\.com/i, /<form[^>]+mailerlite/i];
const hasGA4 = (t) => RE_GA4.some((r) => r.test(t));
const hasFormEnable = (t) => RE_FORM.some((r) => r.test(t));
// GA4/forms hlídáme jen na HTML stránkách a v build*.py (kde žije injektor + EMAILCAP_ACTION);
// scripts/** (alerts-worker, send_price_alerts) legitimně volají mailerlite API → vynecháno.
const guard2Applies = (p) => /\.html$/i.test(p) || /(^|\/)build[\w-]*\.py$/i.test(norm(p));

// affiliate: Make partner/ref odkaz přidaný do obsahu
const RE_AFFIL = /make\.com\/[^"'\s)]*[?&](?:pc|aff|aff_id|ref|partner)=/i;
const addsAffiliate = (t) => RE_AFFIL.test(t);

// Bash zápis do citlivého souboru (čtení je OK, hlídáme jen write-verby)
function bashTouchesSensitive(cmd) {
  const c = String(cmd);
  if (!SENSITIVE_FILES.some((s) => c.includes(base(s)))) return false;
  return /(>>?|tee\b|sed\s+-i|truncate\b|dd\b|cp\s|mv\s)/.test(c);
}

// build --check: které edity mají dopad na generované soubory
function affectsBuild(p) {
  const n = norm(p);
  if (/(^|\/)build[\w-]*\.py$/i.test(n)) return true;
  if (/\/(automation|llm)\/data\//i.test(n)) return true;
  if (/\/automation\/.*\.(html|py)$/i.test(n) && !/\/data\//.test(n)) return true;
  if (/\/llm\/.*\.(html|py)$/i.test(n)) return true;
  if (/(^|\/)build\.py$/i.test(n)) return true; // root build
  return false;
}
const isLlm = (p) => /\/llm\//i.test(norm(p));
const isAutomation = (p) => /\/automation\//i.test(norm(p)) || /(^|\/)build\.py$/i.test(norm(p));

// ===========================================================================
if (event === "PreToolUse") {
  const text = newText();
  const ps = paths();

  // --- Guard 2: GA4 / e-mail formuláře ---
  if (ps.some(guard2Applies) && (hasGA4(text) || hasFormEnable(text))) {
    if (process.env.WIZARDCOST_ALLOW_GA4) {
      process.stderr.write("⚠️ GA4/formulář re-enable POVOLEN (WIZARDCOST_ALLOW_GA4). Ověř, že je to po revizi.\n");
      process.exit(1);
    }
    process.stderr.write(
      "⛔ COMPLIANCE: tento edit znovu zavádí GA4 / e-mail formulář. Compliance overhaul (2026-06-16) je " +
        "záměrně vypnul (faceless, cookieless). NEZNOVUZAPÍNAT bez revize. Blok. " +
        "Pokud to po revizi opravdu chceš, nastav env WIZARDCOST_ALLOW_GA4=1.\n"
    );
    process.exit(2);
  }

  // --- Guard 3: cena / affiliate stop-and-confirm ---
  const sensitive =
    ps.some(isSensitiveFile) ||
    addsAffiliate(text) ||
    (tool === "Bash" && typeof input.command === "string" && bashTouchesSensitive(input.command));
  if (sensitive) {
    if (process.env.WIZARDCOST_ALLOW_SENSITIVE) {
      process.stderr.write(
        "⚠️ STOP-AND-CONFIRM (cena/affiliate): edit povolen lokálně, ale čísla/affiliate měň jen po " +
          "ověření a veď je přes commit/PR k revizi. (Audit = evidence, tools.json updatuje člověk.)\n"
      );
      process.exit(1);
    }
    process.stderr.write(
      "⛔ STOP-AND-CONFIRM: edit cen/affiliate/scoring dat v autonomním běhu zablokován. " +
        "Ceny a affiliate NIKDY neměň přímo — navrhni změnu přes feature branch / PR " +
        "(propose-price-updates.js) a nech ji schválit člověkem. " +
        "(Lokálně se to povolí přes WIZARDCOST_ALLOW_SENSITIVE v .claude/settings.local.json.)\n"
    );
    process.exit(2);
  }

  process.exit(0);
}

// ===========================================================================
if (event === "PostToolUse") {
  if (!["Edit", "Write", "MultiEdit"].includes(tool)) process.exit(0);
  const ps = paths().filter(affectsBuild);
  if (ps.length === 0) process.exit(0);

  const cmds = [];
  if (ps.some(isAutomation)) cmds.push("python automation/build.py --check", "python build.py --check");
  if (ps.some(isLlm)) cmds.push("python llm/build.py --check");
  // dedup zachovává pořadí
  const run = [...new Set(cmds)];

  const failures = [];
  for (const cmd of run) {
    try {
      execSync(cmd, { stdio: ["ignore", "pipe", "pipe"], timeout: 90000 });
    } catch (e) {
      if (e && (e.code === "ENOENT" || /not recognized|není rozpoznán/i.test(String(e.message)))) {
        // python není dostupné → neblokuj, jen upozorni
        process.stderr.write(`⚠️ build --check přeskočen (python nedostupný): ${cmd}\n`);
        process.exit(1);
      }
      const out = `${e.stdout || ""}${e.stderr || ""}`.toString().slice(-1500);
      failures.push(`$ ${cmd}\n${out}`);
    }
  }

  if (failures.length) {
    process.stderr.write(
      "⛔ BUILD DRIFT: generované bloky jsou po editu zastaralé (build --check selhal). " +
        "Edituj ZDROJ (data/šablony) a spusť build, ne generované soubory. Detail:\n\n" +
        failures.join("\n\n") +
        "\n"
    );
    process.exit(2);
  }
  process.exit(0);
}

process.exit(0);