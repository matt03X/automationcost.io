#!/usr/bin/env node
/**
 * llm-price-audit.js — denní AUDIT cen LLM API ceníků (subsite /llm/).
 *
 * Zrcadlo automation/scripts/price-audit.js, ale pro LLM providery. Tohle je
 * vrstva DŮKAZŮ pod llm/data/models.json. Každý den, pro každého providera:
 *   1) stáhne ceníkovou stránku (Playwright, alt URL fallback)
 *      → llm/data/audit/<provider>/<YYYY-MM-DD>.html.gz  (gzip raw text+HTML,
 *        ukládá se JEN poprvé nebo při změně — jinak repo nabobtná)
 *   2) vytáhne NORMALIZOVANÉ ceny (best-effort regex/heuristika z textu)
 *      → llm/data/audit/<provider>/<YYYY-MM-DD>.json
 *   3) diff proti POSLEDNÍMU předchozímu snapshotu téhož providera
 *      → llm/data/audit/<provider>/changes-<YYYY-MM-DD>.json  (jen když changeCount>0)
 *      + append do llm/data/audit/price-history.jsonl  (zdroj grafů o vývoji cen)
 *
 * EVIDENCE, NE ZDROJ PRAVDY. models.json updatuje člověk po revizi change reportu
 * (stejný princip jako automation price-audit / wayback). Cíl auditu = detekovat
 * DRIFT proti našim datům, ne být kanonickým ceníkem. Když se model name z ceníku
 * nepodaří namapovat na models.json, uloží se do snapshotu STEJNĚ (čistá evidence).
 *
 * LLM ceníky jsou většinou STATICKÉ tabulky (žádné slidery jako Make/n8n) → žádná
 * interakce s controly, jen goto + read + parse. Normalizace je proto VOLNÁ:
 * vytáhneme řádky modelů s ≥2 cenami a heuristicky přiřadíme input/cached/output.
 *
 * Spuštění:
 *   node scripts/llm-price-audit.js                       # všichni provideři, plný audit + diff
 *   node scripts/llm-price-audit.js openai anthropic      # jen vybraní
 *   node scripts/llm-price-audit.js --no-diff             # jen snapshoty, bez porovnání
 *   node scripts/llm-price-audit.js --headed              # vidět browser (debug)
 *
 * Lokálně (Playwright je v calc-test/node_modules, mimo repo):
 *   NODE_PATH=../../calc-test/node_modules node scripts/llm-price-audit.js
 * V CI: Playwright v /tmp/pw přes NODE_PATH (viz .github/workflows/llm-price-audit.yml).
 * POZN.: node fetch má v tomhle prostředí rozbité TLS → VŠE přes Playwright page.goto.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

// userAgent + viewport převzaty ze scout-llm-pricing.js (ověřeno, projde přes
// většinu provider WAFů; CI datacenter IP občas dostane bot-wall → tolerujeme).
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const VIEWPORT = { width: 1440, height: 2000 };

const REPO = path.resolve(__dirname, "..");
const AUDIT_DIR = path.join(REPO, "llm", "data", "audit");
const MODELS_PATH = path.join(REPO, "llm", "data", "models.json");
const TODAY = new Date().toISOString().slice(0, 10);
const HEADED = process.argv.includes("--headed");
const NO_DIFF = process.argv.includes("--no-diff");

// ── provider katalog ────────────────────────────────────────────────────────
// URL z models.json _meta.sources (kanonické) + alt fallback ze scout-llm-pricing.js.
// Klíč = audit slug (openai/anthropic/google/deepseek/xai/mistral) = stejný jako
// providers[].slug v models.json (kvůli mapování modelů při diffu). gemini/grok jsou
// produktové názvy, ale slug v models.json je google/xai → držíme se modelového slugu.
const PROVIDERS = {
  openai:    { url: "https://platform.openai.com/docs/pricing",                       alt: "https://openai.com/api/pricing/" },
  anthropic: { url: "https://platform.claude.com/docs/en/about-claude/pricing",        alt: "https://www.anthropic.com/pricing" },
  google:    { url: "https://ai.google.dev/gemini-api/docs/pricing",                   alt: null },
  deepseek:  { url: "https://api-docs.deepseek.com/quick_start/pricing",               alt: null },
  xai:       { url: "https://docs.x.ai/docs/models",                                   alt: "https://x.ai/api" },
  mistral:   { url: "https://mistral.ai/pricing",                                      alt: "https://docs.mistral.ai/getting-started/models/models_overview/" },
};

function providerDir(p) {
  const d = path.join(AUDIT_DIR, p);
  fs.mkdirSync(d, { recursive: true });
  return d;
}

// poslední JSON snapshot PŘED dneškem (pro diff). Filtruje changes-*.json (ty mají
// jiný prefix) přes striktní regex na čistý datumový název.
function previousSnapshot(p) {
  const d = providerDir(p);
  const files = fs.readdirSync(d)
    .filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f) && f.slice(0, 10) < TODAY)
    .sort();
  if (!files.length) return null;
  const f = files[files.length - 1];
  try { return { date: f.slice(0, 10), data: JSON.parse(fs.readFileSync(path.join(d, f), "utf8")) }; }
  catch { return null; }
}

// načti models.json (pro mapování names → naše modely; čistě informativní v snapshotu)
function loadKnownModels(slug) {
  try {
    const m = JSON.parse(fs.readFileSync(MODELS_PATH, "utf8"));
    const prov = (m.providers || []).find((x) => x.slug === slug);
    return prov ? (prov.models || []) : [];
  } catch { return []; }
}

// ── normalizace cen z textu (best-effort, volná) ────────────────────────────
// LLM ceníky = převážně tabulky "Model name … $X / 1M input … $Y / 1M output".
// Strategie: projet řádky, na každém najít $ čísla. Když řádek obsahuje model-like
// jméno a ≥1 cenu, vytvoř záznam. Cached/batch/context se chytají vedlejšími regexy.
// Tohle je ZÁMĚRNĚ tolerantní — falešné/přebytečné záznamy jsou OK (evidence),
// chybějící záznam je horší. Diff níže porovnává jen modely, které matchnou.

const PRICE_RE = /\$\s?([\d]+(?:[.,]\d+)?)/g;            // $5  $0.50  $1,250
const NUM = (s) => Number(String(s).replace(/,/g, ""));   // "1,250" → 1250

// heuristika: vypadá řádek jako řádek modelu? (obsahuje písmena + číslici verze
// nebo známé prefixy). Nechytáme nadpisy typu "Pricing" bez $.
function looksLikeModelLine(line) {
  if (!/[a-z]/i.test(line)) return false;
  return /(gpt|claude|gemini|deepseek|grok|mistral|opus|sonnet|haiku|fable|flash|pro|mini|nano|lite|large|turbo|v\d|[a-z]+-?\d)/i.test(line);
}

// kontext z řádku: "1M context", "200K", "1,000,000 tokens", "context window 400K"
function extractContext(line) {
  const m = line.match(/([\d.,]+)\s*([KM])\b\s*(?:tokens?|context|window)?/i) ||
            line.match(/context[^0-9]{0,12}([\d.,]+)\s*([KM])\b/i);
  if (!m) {
    const raw = line.match(/(\d{6,})\s*(?:tokens?|context)/i);
    return raw ? Number(raw[1]) : null;
  }
  const v = parseFloat(m[1].replace(/,/g, ""));
  return Math.round(v * (m[2].toUpperCase() === "M" ? 1e6 : 1e3));
}

// batch discount z řádku: "50% off batch", "batch -50%", "Batch API 0.5x"
function extractBatch(line) {
  if (!/batch/i.test(line)) return null;
  const pm = line.match(/(\d{1,3})\s*%/);
  if (pm) { const d = Number(pm[1]); return d > 0 && d < 100 ? Math.round((1 - d / 100) * 100) / 100 : null; }
  const xm = line.match(/(0?\.\d+)\s*x/i);
  return xm ? Number(xm[1]) : null;
}

/**
 * Vytáhne pole normalizovaných modelů z textu stránky.
 * Vrací: [{ name, input, output, cached, batch?, context?, raw }]
 *  - input/output = první/druhá cena na řádku (heuristika; výjimky řešíme dle keywords)
 *  - cached = cena u "cache"/"cached"/"read" tokenu pokud rozpoznána
 *  - matched = name z modelů, na který se podařilo namapovat (nebo null)
 */
function normalizePrices(text, knownModels) {
  const knownNames = (knownModels || []).map((m) => ({
    id: m.id, name: m.name,
    needle: (m.name || "").toLowerCase().replace(/\s+/g, " ").trim(),
  })).filter((k) => k.needle);

  const out = [];
  const lines = (text || "").split("\n").map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean);

  for (const line of lines) {
    if (line.length > 200) continue;                       // dlouhé = marketing copy
    if (!looksLikeModelLine(line)) continue;
    const prices = [...line.matchAll(PRICE_RE)].map((m) => NUM(m[1]));
    if (prices.length < 1) continue;

    // input/output heuristika: pokud řádek explicitně značí input/output, použij to;
    // jinak ber 1. cenu = input, poslední = output (typické pořadí v tabulce).
    let input = null, output = null, cached = null;
    const lower = line.toLowerCase();
    const inM = lower.match(/input[^$]{0,20}\$\s?([\d.,]+)/);
    const outM = lower.match(/output[^$]{0,20}\$\s?([\d.,]+)/);
    const cacM = lower.match(/(?:cache|cached|read)[^$]{0,20}\$\s?([\d.,]+)/);
    if (inM) input = NUM(inM[1]);
    if (outM) output = NUM(outM[1]);
    if (cacM) cached = NUM(cacM[1]);
    if (input === null && prices.length) input = prices[0];
    if (output === null && prices.length >= 2) output = prices[prices.length - 1];

    // jméno modelu = nejdelší namapovatelný known name, jinak text před první cenou
    let name = null, matchedId = null;
    for (const k of knownNames) {
      if (lower.includes(k.needle)) { name = k.name; matchedId = k.id; break; }
    }
    if (!name) {
      const beforePrice = line.split("$")[0].trim();
      name = beforePrice.slice(0, 60) || line.slice(0, 60);
    }

    const rec = { name, input, output, cached };
    const batch = extractBatch(line);
    if (batch !== null) rec.batch = batch;
    const ctx = extractContext(line);
    if (ctx !== null) rec.context = ctx;
    if (matchedId) rec.matchedId = matchedId;
    rec.raw = line.slice(0, 160);
    out.push(rec);
  }

  // dedup podle (name+input+output) — tabulky občas duplikují řádky (sticky header ap.)
  const seen = new Set();
  const deduped = [];
  for (const r of out) {
    const key = `${(r.name || "").toLowerCase()}|${r.input}|${r.output}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(r);
  }
  return deduped;
}

// ── Playwright scrape ───────────────────────────────────────────────────────
let _browser = null;
async function browser() {
  if (!_browser) {
    const { chromium } = require("playwright");
    _browser = await chromium.launch({ headless: !HEADED });
  }
  return _browser;
}

// stáhni stránku providera (alt URL fallback jako scout). Vrací { url, text, html }.
// Krátká stránka (<500 B textu) = bot-wall signál → zkusí alt, jinak hodí chybu
// (runner ji ošetří jako WARN, ne fail).
async function fetchProvider(p) {
  const cfg = PROVIDERS[p];
  const ctx = await (await browser()).newContext({ userAgent: UA, viewport: VIEWPORT });
  const page = await ctx.newPage();
  let lastErr = null;
  try {
    for (const url of [cfg.url, cfg.alt].filter(Boolean)) {
      try {
        const res = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
        await page.waitForTimeout(6000);                   // JS render + lazy tabulky
        const text = await page.evaluate(() => document.body.innerText);
        if (!text || text.length < 500) {
          lastErr = new Error(`příliš krátká stránka (${text ? text.length : 0} B) na ${url} — možný bot wall`);
          continue;                                        // zkus alt
        }
        const status = res ? res.status() : 0;
        const html = await page.content();
        return { url, status, text, html };
      } catch (e) {
        lastErr = e;
      }
    }
    throw lastErr || new Error("žádné dostupné URL");
  } finally {
    await page.close().catch(() => {});
    await ctx.close().catch(() => {});
  }
}

// scrape + normalizace jednoho providera
async function scrapeProvider(p) {
  const { url, status, text, html } = await fetchProvider(p);
  const known = loadKnownModels(p);
  const models = normalizePrices(text, known);
  if (!models.length) throw new Error("žádné modely/ceny nenalezeny (změna formátu? bot wall?)");
  return {
    raw: html || text,                                     // co gzipnout (preferuj HTML)
    snapshot: { provider: p, scrapedAt: new Date().toISOString(), url, httpStatus: status, modelCount: models.length, models },
  };
}

// retry proti dočasnému bot-wallu (CI datacenter IP → WAF občas vrátí krátkou
// stránku). 3 pokusy s narůstající prodlevou; po vyčerpání runner → WARN.
async function scrapeProviderRetry(p, attempts = 3) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    if (i) await new Promise((r) => setTimeout(r, 3000 * i));
    try { return await scrapeProvider(p); }
    catch (e) { lastErr = e; }
  }
  throw lastErr;
}

// ── diff dvou snapshotů ─────────────────────────────────────────────────────
// Klíč = lowercase model name (LLM modely jsou pojmenované, ne objemové). Porovnává
// input/output/cached/batch/context. Nový/zmizelý model = změna (drift v lineupu).
// Záměrně VOLNÉ: jen modely, které lze podle jména spárovat. Nespárované = evidence
// v snapshotu, ne falešný alarm (jména se mezi běhy mohou drobně lišit; reálnou
// změnu ceníku poznáme až podle stejnojmenného modelu s jinou cenou).
function diffPrices(provider, oldSnap, newSnap) {
  const changes = [];
  if (!oldSnap || !newSnap) return changes;
  const key = (m) => (m.name || "").toLowerCase().replace(/\s+/g, " ").trim();
  const oldMap = new Map((oldSnap.models || []).map((m) => [key(m), m]));
  const newMap = new Map((newSnap.models || []).map((m) => [key(m), m]));

  const FIELDS = ["input", "output", "cached", "batch", "context"];
  for (const [k, nm] of newMap) {
    const om = oldMap.get(k);
    if (!om) {
      changes.push({ provider, model: nm.name, kind: "model-added",
        desc: `${provider}: NOVÝ model v ceníku → "${nm.name}" (in $${nm.input} / out $${nm.output})` });
      continue;
    }
    for (const f of FIELDS) {
      const ov = om[f], nv = nm[f];
      // ignoruj null↔undefined šum a oboustranné null (neznámá hodnota není změna)
      const oHas = ov !== undefined && ov !== null;
      const nHas = nv !== undefined && nv !== null;
      if (!oHas && !nHas) continue;
      if (ov !== nv) {
        changes.push({ provider, model: nm.name, field: f, old: ov ?? null, neu: nv ?? null,
          desc: `${provider} ${nm.name}: ${f} ${oHas ? "$" + ov : "—"} → ${nHas ? "$" + nv : "—"}` });
      }
    }
  }
  for (const [k, om] of oldMap) {
    if (!newMap.has(k)) {
      changes.push({ provider, model: om.name, kind: "model-removed",
        desc: `${provider}: model ZMIZEL z ceníku → "${om.name}"` });
    }
  }
  return changes;
}

// export pro unit testy (diff + normalizace bez scrapingu); runner běží jen při
// přímém spuštění (node llm-price-audit.js), ne při require z testu.
if (require.main !== module) {
  module.exports = { diffPrices, normalizePrices, extractContext, extractBatch };
}

// ── runner ───────────────────────────────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const targets = args.length ? args : Object.keys(PROVIDERS);
  fs.mkdirSync(AUDIT_DIR, { recursive: true });
  const allChanges = [];
  let failures = 0;   // tvrdé chyby → exit 1
  let blocked = 0;    // bot-wall po retry → jen WARN, neshazuje exit

  for (const p of targets) {
    if (!PROVIDERS[p]) { console.error(`✗ neznámý provider: ${p}`); failures++; continue; }
    process.stdout.write(`→ ${p} … `);
    try {
      const prev = NO_DIFF ? null : previousSnapshot(p);
      const { raw, snapshot } = await scrapeProviderRetry(p);
      const dir = providerDir(p);

      // normalizovaný snapshot — VŽDY (malý)
      fs.writeFileSync(path.join(dir, `${TODAY}.json`), JSON.stringify(snapshot, null, 2) + "\n", "utf8");

      // diff proti předchozímu
      let changed = [];
      if (prev) {
        changed = diffPrices(p, prev.data, snapshot);
        allChanges.push(...changed);
      }

      // syrový HTML/text JEN když je co dokazovat: poprvé (prev===null) nebo při změně.
      // Gzip → ~10× menší. Neměnné dny repo nezatěžují.
      let htmlNote = "HTML přeskočeno (beze změn)";
      if (!prev || changed.length) {
        const gz = zlib.gzipSync(Buffer.from(raw, "utf8"));
        fs.writeFileSync(path.join(dir, `${TODAY}.html.gz`), gz);
        htmlNote = `HTML uloženo ${Math.round(gz.length / 1024)} KB gz`;
      }

      // per-provider change report (jen když changeCount>0)
      if (changed.length) {
        const report = { provider: p, date: TODAY, generatedAt: new Date().toISOString(),
          changeCount: changed.length, changes: changed };
        fs.writeFileSync(path.join(dir, `changes-${TODAY}.json`), JSON.stringify(report, null, 2) + "\n", "utf8");
      }

      console.log(`OK (${snapshot.modelCount} modelů · ${htmlNote} · ${changed.length} změn vs ${prev ? prev.date : "—"})`);
    } catch (e) {
      // bot-wall signatury: krátká stránka, HTTP 403/429/503, timeout, "nenalezeno"
      // = neznámý stav z CI IP, ne chyba dat → WARN (neshodí exit). Předchozí
      // snapshot zůstává platný; reálný drift se chytí, až stránka projde.
      const msg = e.message || String(e);
      const isBotWall = /bot|403|429|503|timeout|Timeout|krátká|krátk|nenalezen|žádné|žádn|net::|ERR_/i.test(msg);
      if (isBotWall) {
        console.log(`⚠ WARN (bot wall / nedostupné po retry, ne změna ceny): ${msg.slice(0, 90)}`);
        blocked++;
      } else {
        console.log(`SELHALO: ${msg}`);
        failures++;
      }
    }
  }

  if (_browser) await _browser.close().catch(() => {});

  // globální history (pro grafy) + souhrn
  if (!NO_DIFF && allChanges.length) {
    const line = allChanges.map((c) => JSON.stringify({ d: TODAY, ...c })).join("\n") + "\n";
    fs.appendFileSync(path.join(AUDIT_DIR, "price-history.jsonl"), line, "utf8");
  }
  console.log(`\n📋 ${allChanges.length} změn celkem (LLM ceníky) na ${TODAY}`);
  for (const c of allChanges) console.log(`   • ${c.desc || JSON.stringify(c)}`);
  if (blocked) console.log(`⚠ ${blocked} provider(ů) nedostupných (bot wall / CI IP) — neověřeno, ne fail.`);

  // exit 1 (= mail ownerovi) JEN při reálné cenové změně NEBO tvrdé chybě scrapu.
  // Bot-wall (blocked) = exit 0 → cron nekřičí falešně; až provider zítra projde,
  // audit doběhne normálně. Snapshoty se commitnou vždy (workflow řeší git).
  process.exit(failures || allChanges.length ? 1 : 0);
}

if (require.main === module) main();
