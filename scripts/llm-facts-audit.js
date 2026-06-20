#!/usr/bin/env node
/**
 * llm-facts-audit.js — denní AUDIT NE-cenových faktů LLM modelů (subsite /llm/).
 *
 * Sourozenec scripts/llm-price-audit.js: zatímco llm-price-audit hlídá CENY
 * (inputPerM/outputPerM/cachedInputPerM…), tohle hlídá NE-cenová fakta, která se
 * v models.json drží vedle cen a propisují do kalkulačky / model karet:
 *   - contextWindow   — max kontext v tokenech (drift-prone; provideři ho zvedají)
 *   - caching         — je publikovaná cached/read cena? (cachedInputPerM != null)
 *   - batch           — existuje Batch API / batchDiscount? (batchDiscount != null)
 *   - maxOutput       — max output tokenů (limit completion; mění se mezi generacemi)
 *   - deprecation     — deprecation / EOL / sunset notices (např. DeepSeek aliasy
 *                       deprecation 2026-07-24) — čistá evidence, vždy jako note/alarm
 *
 * Stejný princip jako llm-price-audit / automation facts-audit: EVIDENCE, NE ZDROJ
 * PRAVDY. models.json updatuje ČLOVĚK po revizi change reportu. Cíl = detekovat DRIFT
 * mezi oficiálními model docs/pricing stránkami a NAŠÍMI daty (models.json), ne být
 * kanonickým ceníkem. Diffuje se proti models.json (ne proti včerejšímu snapshotu —
 * models.json je zdroj pravdy pro non-price fakta).
 *
 * Postup (vzor llm-price-audit):
 *   1) stáhne oficiální model docs/pricing stránku providera (Playwright, alt URL
 *      fallback; node fetch má v tomhle prostředí rozbité TLS → vše přes page.goto)
 *      → llm/data/facts-audit/<provider>/<YYYY-MM-DD>.html.gz  (gzip raw HTML/text,
 *        ukládá se JEN poprvé nebo při změně faktu — jinak repo nabobtná)
 *   2) deterministická/heuristická extrakce non-price faktů z vyrenderovaného textu
 *      → llm/data/facts-audit/<provider>/<YYYY-MM-DD>.json
 *   3) diff proti CLAIMED hodnotám v models.json (per model, mapováno přes name)
 *      → llm/data/facts-audit/<provider>/changes-<YYYY-MM-DD>.json (jen changeCount>0)
 *      + append do llm/data/facts-audit/facts-history.jsonl
 *
 * EXIT/ALARM 1:1 jako llm-price-audit.js:
 *   - exit 1 (= mail ownerovi) JEN při reálné změně faktu (changeCount>0) NEBO tvrdé
 *     chybě scrapu. Bot-wall / 403 / 429 / 503 / timeout / krátká stránka = WARN +
 *     retry; po vyčerpání retry = blocked (neshazuje exit). Předchozí snapshot
 *     zůstává platný; reálný drift se chytí, až stránka projde.
 *
 * Spuštění:
 *   node scripts/llm-facts-audit.js                       # všichni provideři, plný audit + diff
 *   node scripts/llm-facts-audit.js openai anthropic      # jen vybraní
 *   node scripts/llm-facts-audit.js --no-diff             # jen snapshoty, bez porovnání
 *   node scripts/llm-facts-audit.js --headed              # vidět browser (debug)
 *
 * Lokálně (Playwright je v calc-test/node_modules, mimo repo):
 *   NODE_PATH=../../calc-test/node_modules node scripts/llm-facts-audit.js
 * V CI: Playwright v /tmp/pw přes NODE_PATH (viz .github/workflows/llm-facts-audit.yml).
 * POZN.: node fetch má v tomhle prostředí rozbité TLS → VŠE přes Playwright page.goto.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

// userAgent + viewport stejné jako llm-price-audit.js (ověřeno na provider WAFech;
// CI datacenter IP občas dostane bot-wall → tolerujeme jako WARN).
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const VIEWPORT = { width: 1440, height: 2000 };

const REPO = path.resolve(__dirname, "..");
const FACTS_DIR = path.join(REPO, "llm", "data", "facts-audit");
const MODELS_PATH = path.join(REPO, "llm", "data", "models.json");
const TODAY = new Date().toISOString().slice(0, 10);
const HEADED = process.argv.includes("--headed");
const NO_DIFF = process.argv.includes("--no-diff");

// ── provider katalog ────────────────────────────────────────────────────────
// Stejné slugy + URL jako llm-price-audit.js (openai/anthropic/google/deepseek/
// xai/mistral), aby se snapshoty drasaly ze stejných oficiálních model docs/pricing
// stránek. Pro non-price fakta se hodí i dedikované "models" docs stránky (limity,
// context, deprecation), proto kde to dává smysl prioritizujeme docs URL jako alt.
// Klíč = audit slug = providers[].slug v models.json (kvůli mapování modelů při diffu).
const PROVIDERS = {
  openai:    { url: "https://platform.openai.com/docs/pricing",                  alt: "https://platform.openai.com/docs/models" },
  anthropic: { url: "https://platform.claude.com/docs/en/about-claude/pricing",  alt: "https://platform.claude.com/docs/en/about-claude/models/overview" },
  google:    { url: "https://ai.google.dev/gemini-api/docs/pricing",             alt: "https://ai.google.dev/gemini-api/docs/models" },
  deepseek:  { url: "https://api-docs.deepseek.com/quick_start/pricing",         alt: "https://api-docs.deepseek.com/news/news" },
  xai:       { url: "https://docs.x.ai/docs/models",                             alt: "https://x.ai/api" },
  mistral:   { url: "https://mistral.ai/pricing",                                alt: "https://docs.mistral.ai/getting-started/models/models_overview/" },
};

function providerDir(p) {
  const d = path.join(FACTS_DIR, p);
  fs.mkdirSync(d, { recursive: true });
  return d;
}

// poslední JSON snapshot PŘED dneškem (jen pro „uložit html.gz až při změně" logiku;
// diff faktů jde proti models.json, ne proti včerejšku). Filtruje changes-*.json.
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

// načti modely providera z models.json (zdroj pravdy pro non-price fakta)
function loadKnownModels(slug) {
  try {
    const m = JSON.parse(fs.readFileSync(MODELS_PATH, "utf8"));
    const prov = (m.providers || []).find((x) => x.slug === slug);
    return prov ? (prov.models || []) : [];
  } catch { return []; }
}

// ── extrakce non-price faktů z textu (best-effort, volná) ────────────────────
// LLM docs/pricing = převážně tabulky/listy s modely. Strategie: projet řádky,
// na model-like řádcích vytáhnout context/maxOutput/cached/batch signály a posbírat
// globální deprecation notices napříč celou stránkou. ZÁMĚRNĚ tolerantní — chybějící
// hodnota (null) NENÍ změna; reálný drift poznáme až podle stejnojmenného modelu
// s jinou hodnotou než v models.json.

const NUM = (s) => Number(String(s).replace(/,/g, ""));   // "1,250" → 1250

// vypadá řádek jako řádek modelu? (stejná heuristika jako llm-price-audit)
function looksLikeModelLine(line) {
  if (!/[a-z]/i.test(line)) return false;
  return /(gpt|claude|gemini|deepseek|grok|mistral|opus|sonnet|haiku|fable|flash|pro|mini|nano|lite|large|turbo|magistral|codestral|ministral|v\d|[a-z]+-?\d)/i.test(line);
}

// kontext z řádku: "1M context", "200K", "1,000,000 tokens", "context window 400K"
// (sdíleno s llm-price-audit extractContext)
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

// max output tokenů z řádku: "max output 64K", "output: 128,000 tokens",
// "max_output_tokens 16384", "8K output". Vrací počet tokenů nebo null.
function extractMaxOutput(line) {
  const m = line.match(/(?:max(?:imum)?[\s_-]*)?output(?:[\s_-]*tokens?)?[^0-9]{0,16}([\d.,]+)\s*([KM])?\b/i) ||
            line.match(/([\d.,]+)\s*([KM])?\s*(?:max(?:imum)?[\s_-]*)?output\s*tokens?/i);
  if (!m) return null;
  const v = parseFloat(m[1].replace(/,/g, ""));
  if (!Number.isFinite(v) || v < 1) return null;
  const unit = (m[2] || "").toUpperCase();
  const n = unit === "M" ? v * 1e6 : unit === "K" ? v * 1e3 : v;
  // sanity: max output bývá 1K–1M; mimo to = falešný match (např. cena/kontext)
  if (n < 256 || n > 2e6) return null;
  return Math.round(n);
}

// caching signál na řádku/stránce: zmínka cached/cache read input tokenu.
// Boolean evidence (publikuje provider cached cenu?), ne částka.
function detectCachingLine(line) {
  return /\bcach(?:e|ed|ing)\b|cache\s*read|cached\s*input|prompt\s*cach/i.test(line);
}

// batch signál na řádku/stránce: existuje Batch API / batch discount?
function detectBatchLine(line) {
  return /\bbatch\b/i.test(line);
}

// deprecation / EOL / sunset notice na řádku. Vrací útržek (slice) nebo null.
// Chytá i konkrétní datum (DeepSeek aliasy deprecation 2026-07-24).
function extractDeprecation(line) {
  if (!/\b(deprecat|end[\s-]?of[\s-]?life|\bEOL\b|sunset|retir(?:e|ed|ement)|shut[\s-]?down|discontinu|will be removed|no longer (?:available|supported)|legacy)\b/i.test(line)) {
    return null;
  }
  return line.replace(/\s+/g, " ").trim().slice(0, 160);
}

/**
 * Vytáhne per-model non-price fakta + globální deprecation notices z textu stránky.
 * Vrací: { models: [{ name, contextWindow, maxOutput, caching, batch, matchedId, raw }],
 *          deprecations: [string], pageCaching: bool, pageBatch: bool }
 *  - models = řádky, které se podařilo namapovat na known model name (jen ty diffujeme)
 *  - caching/batch jsou per-model jen pokud signál stojí PŘÍMO na model řádku; jinak
 *    se použije page-level signál (pageCaching/pageBatch) jako fallback při diffu
 *  - deprecations = všechny EOL/sunset útržky z celé stránky (čistá evidence)
 */
function extractFacts(text, knownModels) {
  const knownNames = (knownModels || []).map((m) => ({
    id: m.id, name: m.name,
    needle: (m.name || "").toLowerCase().replace(/\s+/g, " ").trim(),
  })).filter((k) => k.needle);

  const lines = (text || "").split("\n").map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean);

  const models = [];
  const deprecations = [];
  let pageCaching = false;
  let pageBatch = false;

  for (const line of lines) {
    if (line.length > 240) continue;                        // dlouhé = marketing copy

    // page-level caching/batch signál (stačí kdekoli na stránce)
    if (detectCachingLine(line)) pageCaching = true;
    if (detectBatchLine(line)) pageBatch = true;

    // deprecation/EOL notices (globální evidence)
    const dep = extractDeprecation(line);
    if (dep && deprecations.length < 40 && !deprecations.includes(dep)) deprecations.push(dep);

    if (!looksLikeModelLine(line)) continue;
    const lower = line.toLowerCase();

    // namapuj na known model name (nejdelší match vyhrává — bereme první needle,
    // co je substring; known names jsou specifické "GPT-5.5 Pro" ap.)
    let name = null, matchedId = null;
    for (const k of knownNames) {
      if (lower.includes(k.needle)) { name = k.name; matchedId = k.id; break; }
    }
    if (!matchedId) continue;                                // jen namapované modely diffujeme

    const rec = {
      name,
      matchedId,
      contextWindow: extractContext(line),
      maxOutput: extractMaxOutput(line),
      caching: detectCachingLine(line) ? true : null,       // null = signál není přímo na řádku
      batch: detectBatchLine(line) ? true : null,
      raw: line.slice(0, 160),
    };
    models.push(rec);
  }

  // dedup per model (stejný matchedId se může na stránce objevit víckrát; slij signály:
  // ber první ne-null context/maxOutput, OR pro caching/batch)
  const byId = new Map();
  for (const r of models) {
    const ex = byId.get(r.matchedId);
    if (!ex) { byId.set(r.matchedId, r); continue; }
    if (ex.contextWindow == null && r.contextWindow != null) ex.contextWindow = r.contextWindow;
    if (ex.maxOutput == null && r.maxOutput != null) ex.maxOutput = r.maxOutput;
    if (r.caching) ex.caching = true;
    if (r.batch) ex.batch = true;
  }

  return { models: [...byId.values()], deprecations, pageCaching, pageBatch };
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

// stáhni stránku providera (alt URL fallback jako llm-price-audit). Vrací
// { url, status, text, html }. Krátká stránka (<500 B textu) = bot-wall signál
// → zkusí alt, jinak hodí chybu (runner ji ošetří jako WARN, ne fail).
async function fetchProvider(p) {
  const cfg = PROVIDERS[p];
  const ctx = await (await browser()).newContext({ userAgent: UA, viewport: VIEWPORT });
  const page = await ctx.newPage();
  let lastErr = null;
  try {
    for (const url of [cfg.url, cfg.alt].filter(Boolean)) {
      try {
        const res = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
        await page.waitForTimeout(6000);                     // JS render + lazy tabulky
        const text = await page.evaluate(() => document.body.innerText);
        if (!text || text.length < 500) {
          lastErr = new Error(`příliš krátká stránka (${text ? text.length : 0} B) na ${url} — možný bot wall`);
          continue;                                          // zkus alt
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

// scrape + extrakce faktů jednoho providera
async function scrapeProvider(p) {
  const { url, status, text, html } = await fetchProvider(p);
  const known = loadKnownModels(p);
  const facts = extractFacts(text, known);
  if (!facts.models.length && !facts.deprecations.length) {
    throw new Error("žádné modely/fakta nenalezeny (změna formátu? bot wall?)");
  }
  return {
    raw: html || text,                                       // co gzipnout (preferuj HTML)
    snapshot: {
      provider: p, scrapedAt: new Date().toISOString(), url, httpStatus: status,
      pageCaching: facts.pageCaching, pageBatch: facts.pageBatch,
      modelCount: facts.models.length, models: facts.models,
      deprecations: facts.deprecations,
    },
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

// ── diff: scrape vs claimed (models.json) → changes (alarm) ──────────────────
// Klíč = matchedId (mapování proběhlo už při extrakci). Porovnává:
//   contextWindow — number↔number, alarm při neshodě
//   maxOutput     — number↔number, alarm při neshodě (models.json maxOutput nemá →
//                   zatím jen evidence: pokud claimed chybí, je to note „doplnit")
//   caching       — má model cachedInputPerM != null? vs publikuje stránka cached?
//   batch         — má model batchDiscount != null? vs existuje Batch API?
//   deprecation   — JAKÁKOLI deprecation/EOL zmínka pro náš model = alarm (revidovat)
// ZÁMĚRNĚ VOLNÉ: null/neznámá hodnota ze scrapu NENÍ změna (jen chybějící evidence).
// caching/batch: alarm jen jednosměrně — když models.json říká „máme cached/batch",
// ale oficiální stránka o tom NEMÁ ŽÁDNOU zmínku (ani per-model, ani page-level) →
// možná jsme pozadu / feature zrušena. Opačně (stránka má, my ne) = note (evidence).
function diffFacts(provider, snap, claimModels) {
  const changes = [];   // reálné rozpory → alarm
  const notes = [];     // evidence-only → bez alarmu
  const claimById = new Map((claimModels || []).map((m) => [m.id, m]));
  const pageCaching = !!snap.pageCaching;
  const pageBatch = !!snap.pageBatch;

  for (const sm of snap.models || []) {
    const cm = claimById.get(sm.matchedId);
    if (!cm) continue;                                       // model bez záznamu v models.json

    // contextWindow — alarm při číselné neshodě (obě strany known)
    if (typeof sm.contextWindow === "number" && typeof cm.contextWindow === "number" &&
        sm.contextWindow !== cm.contextWindow) {
      changes.push({ provider, model: cm.name, field: "contextWindow",
        claimed: cm.contextWindow, scraped: sm.contextWindow,
        desc: `${provider} ${cm.name}: contextWindow models.json ${cm.contextWindow} → stránka ${sm.contextWindow} — revidovat` });
    } else if (typeof sm.contextWindow === "number" && cm.contextWindow == null) {
      notes.push({ provider, model: cm.name, field: "contextWindow", claimed: null, scraped: sm.contextWindow,
        desc: `${provider} ${cm.name}: contextWindow v models.json null, stránka uvádí ${sm.contextWindow} — doplnit` });
    }

    // maxOutput — models.json toto pole zatím nemá → evidence/note (doplnit do v1.x).
    // Pokud by se pole přidalo, číselná neshoda → alarm.
    if (typeof sm.maxOutput === "number") {
      const claimedMax = (cm.maxOutput != null) ? cm.maxOutput : null;
      if (typeof claimedMax === "number" && claimedMax !== sm.maxOutput) {
        changes.push({ provider, model: cm.name, field: "maxOutput",
          claimed: claimedMax, scraped: sm.maxOutput,
          desc: `${provider} ${cm.name}: maxOutput models.json ${claimedMax} → stránka ${sm.maxOutput} — revidovat` });
      } else if (claimedMax == null) {
        notes.push({ provider, model: cm.name, field: "maxOutput", claimed: null, scraped: sm.maxOutput,
          desc: `${provider} ${cm.name}: maxOutput stránka uvádí ${sm.maxOutput}, models.json pole nemá — zvážit doplnění` });
      }
    }

    // caching — models.json claim = cachedInputPerM != null. Stránka publikuje cached?
    const claimCaching = cm.cachedInputPerM != null;
    const scrapedCaching = sm.caching === true || pageCaching;
    if (claimCaching && !scrapedCaching) {
      changes.push({ provider, model: cm.name, field: "caching", claimed: true, scraped: false,
        desc: `${provider} ${cm.name}: models.json má cached cenu, ale oficiální stránka caching nezmiňuje — ověřit (zrušeno? jsme pozadu?)` });
    } else if (!claimCaching && sm.caching === true) {
      notes.push({ provider, model: cm.name, field: "caching", claimed: false, scraped: true,
        desc: `${provider} ${cm.name}: stránka zmiňuje caching, models.json cached cenu nemá (cachedInputPerM null) — doplnit?` });
    }

    // batch — models.json claim = batchDiscount != null. Existuje Batch API?
    const claimBatch = cm.batchDiscount != null;
    const scrapedBatch = sm.batch === true || pageBatch;
    if (claimBatch && !scrapedBatch) {
      changes.push({ provider, model: cm.name, field: "batch", claimed: true, scraped: false,
        desc: `${provider} ${cm.name}: models.json má batchDiscount, ale stránka Batch API nezmiňuje — ověřit (zrušeno? jsme pozadu?)` });
    } else if (!claimBatch && scrapedBatch) {
      notes.push({ provider, model: cm.name, field: "batch", claimed: false, scraped: true,
        desc: `${provider} ${cm.name}: stránka zmiňuje Batch API, models.json batchDiscount=null — doplnit po ověření násobitele?` });
    }
  }

  // deprecation / EOL — JAKÁKOLI zmínka, která se týká NĚKTERÉHO z našich modelů
  // (substring na name nebo id), je alarm: model, který nabízíme, má oznámený konec.
  // Obecné deprecation notices, co se netýkají našich modelů = note (evidence).
  for (const dep of snap.deprecations || []) {
    const lower = dep.toLowerCase();
    let hitModel = null;
    for (const cm of claimModels || []) {
      const n = (cm.name || "").toLowerCase();
      const id = (cm.id || "").toLowerCase();
      if ((n && lower.includes(n)) || (id && lower.includes(id))) { hitModel = cm; break; }
    }
    if (hitModel) {
      changes.push({ provider, model: hitModel.name, field: "deprecation", claimed: null, scraped: dep,
        desc: `${provider} ${hitModel.name}: oznámena deprecation/EOL → "${dep}" — revidovat models.json/kalkulačku` });
    } else {
      notes.push({ provider, field: "deprecation", scraped: dep,
        desc: `${provider}: deprecation/EOL notice (netýká se přímo našich modelů) → "${dep}"` });
    }
  }

  return { changes, notes };
}

// export pro unit testy (diff + extrakce bez scrapingu); runner běží jen při přímém
// spuštění (node llm-facts-audit.js), ne při require z testu.
if (require.main !== module) {
  module.exports = { diffFacts, extractFacts, extractContext, extractMaxOutput, extractDeprecation, detectCachingLine, detectBatchLine };
}

// ── runner ───────────────────────────────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const targets = args.length ? args : Object.keys(PROVIDERS);
  fs.mkdirSync(FACTS_DIR, { recursive: true });
  const allChanges = [];
  const allNotes = [];
  let failures = 0;   // tvrdé chyby → exit 1
  let blocked = 0;    // bot-wall po retry → jen WARN, neshazuje exit

  for (const p of targets) {
    if (!PROVIDERS[p]) { console.error(`✗ neznámý provider: ${p}`); failures++; continue; }
    process.stdout.write(`→ ${p} … `);
    try {
      const prev = previousSnapshot(p);
      const { raw, snapshot } = await scrapeProviderRetry(p);
      const dir = providerDir(p);

      // normalizovaný snapshot — VŽDY (malý)
      fs.writeFileSync(path.join(dir, `${TODAY}.json`), JSON.stringify(snapshot, null, 2) + "\n", "utf8");

      // diff proti CLAIMED hodnotám v models.json (TOHLE je smysl auditu)
      let changed = [], noted = [];
      if (!NO_DIFF) {
        const claim = loadKnownModels(p);
        const r = diffFacts(p, snapshot, claim);
        changed = r.changes; noted = r.notes;
        allChanges.push(...changed);
        allNotes.push(...noted);
      }

      // syrový HTML/text JEN když je co dokazovat: poprvé (prev===null) nebo při změně
      // faktu. Gzip → ~10× menší. Neměnné dny repo nezatěžují.
      let htmlNote = "HTML přeskočeno (beze změn)";
      if (!prev || changed.length) {
        const gz = zlib.gzipSync(Buffer.from(raw, "utf8"));
        fs.writeFileSync(path.join(dir, `${TODAY}.html.gz`), gz);
        htmlNote = `HTML uloženo ${Math.round(gz.length / 1024)} KB gz`;
      }

      // per-provider change report (jen když changeCount>0)
      if (changed.length) {
        const report = { provider: p, date: TODAY, generatedAt: new Date().toISOString(),
          changeCount: changed.length, changes: changed,
          noteCount: noted.length, notes: noted };
        fs.writeFileSync(path.join(dir, `changes-${TODAY}.json`), JSON.stringify(report, null, 2) + "\n", "utf8");
      }

      console.log(`OK (${snapshot.modelCount} modelů · ${snapshot.deprecations.length} EOL útržků · ${htmlNote} · ${changed.length} změn · ${noted.length} pozn.)`);
    } catch (e) {
      // bot-wall signatury: krátká stránka, HTTP 403/429/503, timeout, "nenalezeno"
      // = neznámý stav z CI IP, ne chyba dat → WARN (neshodí exit). Předchozí
      // snapshot zůstává platný; reálný drift se chytí, až stránka projde.
      const msg = e.message || String(e);
      const isBotWall = /bot|403|429|503|timeout|Timeout|krátká|krátk|nenalezen|žádné|žádn|net::|ERR_/i.test(msg);
      if (isBotWall) {
        console.log(`⚠ WARN (bot wall / nedostupné po retry, ne změna faktu): ${msg.slice(0, 90)}`);
        blocked++;
      } else {
        console.log(`SELHALO: ${msg}`);
        failures++;
      }
    }
  }

  if (_browser) await _browser.close().catch(() => {});

  // globální history (pro audit trail) + souhrn
  if (!NO_DIFF && allChanges.length) {
    const line = allChanges.map((c) => JSON.stringify({ d: TODAY, ...c })).join("\n") + "\n";
    fs.appendFileSync(path.join(FACTS_DIR, "facts-history.jsonl"), line, "utf8");
  }
  console.log(`\n📋 ${allChanges.length} faktických změn (alarm) · ${allNotes.length} poznámek (evidence) na ${TODAY} (LLM non-price fakta)`);
  for (const c of allChanges) console.log(`   • ${c.desc || JSON.stringify(c)}`);
  for (const n of allNotes) console.log(`   · ${n.desc || JSON.stringify(n)}`);
  if (blocked) console.log(`⚠ ${blocked} provider(ů) nedostupných (bot wall / CI IP) — neověřeno, ne fail.`);

  // exit 1 (= mail ownerovi) JEN při reálné změně faktu NEBO tvrdé chybě scrapu.
  // Bot-wall (blocked) = exit 0 → cron nekřičí falešně; až provider zítra projde,
  // audit doběhne normálně. Snapshoty se commitnou vždy (workflow řeší git).
  process.exit(failures || allChanges.length ? 1 : 0);
}

if (require.main === module) main();
