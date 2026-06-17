#!/usr/bin/env node
/**
 * facts-extract-llm.js — VOLITELNÝ LLM extraktor faktů z nestrukturovaného textu.
 *
 * Vendorské „X vs Y" srovnávačky jsou nestrukturovaný marketing → regex nestačí.
 * Tohle pošle ořezaný text levnému modelu (haiku) a vrátí STRUKTUROVANÝ JSON
 * s tvrzeními. Výstup = EVIDENCE pro lidskou revizi (NE auto-pravda).
 *
 * DESIGN (klíčové):
 *   - NENÍ závislost. Když chybí API klíč / selže síť (lokální TLS je rozbité),
 *     vrátí null a volající degraduje na čistý regex/snapshot. Pipeline běží dál.
 *   - Cache podle sha256(text+model+schema) v automation/data/.llm-cache/ → stejný
 *     text se neúčtuje 2×. (.llm-cache je v .gitignore — viz níže.)
 *   - Minimum tokenů: text se ořízne, max_tokens malé, levný model.
 *   - Klíč JEN z env (ANTHROPIC_API_KEY) nebo engine/.env — NIKDY v repu/logu.
 *
 * Použití (modul):
 *   const { extractFacts, llmAvailable } = require("./facts-extract-llm");
 *   const facts = await extractFacts(pageText, { subjects: ["n8n","zapier"] });
 *   // facts === null  → LLM nedostupné, degraduj
 *
 * CLI (debug):  node scripts/facts-extract-llm.js < some.txt
 */
"use strict";
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const REPO = path.resolve(__dirname, "..");
const CACHE_DIR = path.join(REPO, "automation", "data", ".llm-cache");
const MODEL = process.env.FACTS_LLM_MODEL || "claude-haiku-4-5-20251001";
const MAX_INPUT_CHARS = 12000;   // ořež marketing stránku → drž tokeny dole
const SCHEMA_VERSION = "v1";

// API klíč: env > engine/.env (gitignored). Nikdy hardcoded.
function apiKey() {
  if (process.env.ANTHROPIC_API_KEY) return process.env.ANTHROPIC_API_KEY;
  for (const p of [path.join(REPO, "..", "..", "engine", ".env"), path.join(REPO, ".env")]) {
    try {
      const m = fs.readFileSync(p, "utf8").match(/^\s*ANTHROPIC_API_KEY\s*=\s*(.+)\s*$/m);
      if (m) return m[1].trim().replace(/^["']|["']$/g, "");
    } catch { /* soubor nemusí existovat */ }
  }
  return "";
}
function llmAvailable() { return !!apiKey(); }

function cacheKey(text, extra) {
  return crypto.createHash("sha256").update(`${SCHEMA_VERSION}|${MODEL}|${extra || ""}|${text}`).digest("hex").slice(0, 32);
}
function cacheGet(key) {
  try { return JSON.parse(fs.readFileSync(path.join(CACHE_DIR, key + ".json"), "utf8")); }
  catch { return undefined; }
}
function cachePut(key, val) {
  try { fs.mkdirSync(CACHE_DIR, { recursive: true }); fs.writeFileSync(path.join(CACHE_DIR, key + ".json"), JSON.stringify(val) + "\n"); }
  catch { /* cache best-effort */ }
}

const PROMPT = (text, subjects) => `You extract OBJECTIVE, checkable claims from a vendor marketing page (a biased "X vs Y" comparison). Return ONLY minified JSON, no prose.

Tools mentioned (subjects): ${subjects.join(", ")}.

For EACH subject tool the page makes a claim about, output one object:
{"tool":"<slug>","integration_count":<number|null>,"pricing_model":"<short string|null>","self_host":<true|false|null>,"free_tier":"<short string|null>","claims_about_competitor":"<short verbatim-ish claim the page makes to favor its own tool, or null>"}

Rules: only extract what the TEXT states; use null when unknown; numbers as integers (strip "+"/commas); keep strings under 120 chars. Output shape: {"claims":[ ... ]}.

PAGE TEXT:
${text}`;

/**
 * extractFacts(text, opts) → { claims: [...] } | null
 *  opts.subjects : string[]  (tool slugs na stránce)
 *  opts.noCache  : bool      (přeskoč cache)
 */
async function extractFacts(text, opts = {}) {
  const key = apiKey();
  if (!key) return null;                          // degrade: žádný klíč
  const subjects = opts.subjects || [];
  const clipped = String(text || "").replace(/\n{3,}/g, "\n\n").slice(0, MAX_INPUT_CHARS);
  if (!clipped.trim()) return null;
  const ck = cacheKey(clipped, subjects.join(","));
  if (!opts.noCache) { const hit = cacheGet(ck); if (hit !== undefined) return hit; }

  try {
    const res = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": key,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: 800,
        messages: [{ role: "user", content: PROMPT(clipped, subjects) }],
      }),
    });
    if (!res.ok) { console.error(`  (LLM HTTP ${res.status} — degraduji na regex)`); return null; }
    const data = await res.json();
    const raw = (data.content && data.content[0] && data.content[0].text) || "";
    const jsonStr = (raw.match(/\{[\s\S]*\}/) || [null])[0];
    if (!jsonStr) return null;
    const parsed = JSON.parse(jsonStr);
    const result = { claims: Array.isArray(parsed.claims) ? parsed.claims : [], _model: MODEL, _at: new Date().toISOString() };
    cachePut(ck, result);
    return result;
  } catch (e) {
    // lokálně typicky rozbité TLS u node fetch → degrade (CI fetch funguje)
    console.error(`  (LLM nedostupné: ${(e.message || e).toString().slice(0, 60)} — degraduji na regex)`);
    return null;
  }
}

module.exports = { extractFacts, llmAvailable, MODEL };

// CLI debug: text na stdin
if (require.main === module) {
  const chunks = [];
  process.stdin.on("data", (c) => chunks.push(c));
  process.stdin.on("end", async () => {
    const subjects = process.argv.slice(2).filter((a) => !a.startsWith("--"));
    const out = await extractFacts(chunks.join(""), { subjects, noCache: true });
    console.log(JSON.stringify(out, null, 2));
  });
}
