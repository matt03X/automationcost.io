#!/usr/bin/env node
/**
 * facts-audit.js — periodický AUDIT NE-cenových faktů (autoritativní vrstva).
 *
 * Sourozenec scripts/price-audit.js: zatímco price-audit hlídá CENY, tohle hlídá
 * fakta, která se na vs-stránkách berou z tools.json a opisují do pairs.json prózy.
 * Zdroje jsou AUTORITATIVNÍ (oficiální integrations/pricing stránky + GitHub LICENSE),
 * NE vendorské „X vs Y" marketingové srovnávačky — ty řeší scripts/vs-crosscheck.js
 * jako ZAUJATÝ signál.
 *
 * Auditovaná pole:
 *   - integrations  — počet integrací (nejvíc drift-prone, prominentní „N 000+")
 *   - license       — pro OSS nástroje čteno PŘÍMO z GitHub API (spdx_id) = 100% spolehlivé
 *   - selfHostable  — potvrzeno existencí veřejného GitHub repa (+ open-source signál na webu)
 *   - freeTier      — evidence z pricing stránky (volné kvóty) + konzervativní flag
 *
 * Postup (vzor price-audit):
 *   1) page.goto oficiální stránky vendora (node fetch má v tomhle prostředí
 *      rozbité TLS → vše přes Playwright, vč. GitHub API)
 *   2) deterministická extrakce (regex nad vyrenderovaným textem / JSON z API)
 *   3) snapshot → automation/data/facts-audit/<vendor>/<YYYY-MM-DD>.json
 *      (+ <YYYY-MM-DD>.html.gz jen poprvé / při změně)
 *   4) diff proti claimed hodnotám v tools.json → facts-audit/changes-<YYYY-MM-DD>.json
 *
 * EVIDENCE-ONLY: NIKDY needituje tools.json. Workflow failne (= mail) jen při reálném
 * rozporu (changeCount>0); bot-wall = WARN (neshodí). Skript sám exit 1 jen při tvrdé chybě.
 *
 * LLM booster (volitelný, NENÍ závislost): když regex číslo nenajde (změněný layout),
 * lze text poslat levnému modelu na extrakci — viz scripts/facts-extract-llm.js.
 *
 * Spuštění:
 *   NODE_PATH=../../calc-test/node_modules node scripts/facts-audit.js            # všichni
 *   NODE_PATH=../../calc-test/node_modules node scripts/facts-audit.js n8n make   # vybraní
 *   node scripts/facts-audit.js --no-diff           # jen snapshoty
 *   node scripts/facts-audit.js --headed            # vidět browser
 */
"use strict";
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36";
const REPO = path.resolve(__dirname, "..");
const FACTS_DIR = path.join(REPO, "automation", "data", "facts-audit");
const TOOLS_JSON = path.join(REPO, "automation", "data", "tools.json");
const TODAY = new Date().toISOString().slice(0, 10);
const HEADED = process.argv.includes("--headed");
const NO_DIFF = process.argv.includes("--no-diff");
const DELTA_TOL = 0.15;   // |scraped-claimed|/claimed > 15 % → flag (integrace rostou pomalu)
const GH_TOKEN = process.env.GITHUB_TOKEN || process.env.GH_TOKEN || "";

// ── vendor katalog ───────────────────────────────────────────────────────────
// url       = integrations/apps stránka (počet integrací; keywords = slova ZA číslem)
// repo      = GitHub owner/repo → čteme LICENSE (spdx) a potvrzujeme self-host
// pricingUrl+freeKw = pro cloud nástroje: free-tier evidence z ceníku
// bereme NEJVĚTŠÍ plausibilní shodu pro počet (integrace = velké číslo)
const VENDORS = {
  zapier:       { url: "https://zapier.com/apps",                 kw: ["apps", "integrations"],
                  pricingUrl: "https://zapier.com/pricing",        freeKw: ["task", "tasks"] },
  make:         { url: "https://www.make.com/en/integrations",    kw: ["Integration Apps", "integrations", "apps"],
                  pricingUrl: "https://www.make.com/en/pricing",   freeKw: ["operation", "operations", "credit", "credits", "ops"] },
  n8n:          { url: "https://n8n.io/integrations/",            kw: ["integrations", "nodes"],
                  repo: "n8n-io/n8n" },
  pipedream:    { url: "https://pipedream.com/apps",              kw: ["apps", "APIs", "integrations"],
                  pricingUrl: "https://pipedream.com/pricing",     freeKw: ["credit", "credits"] },
  activepieces: { url: "https://www.activepieces.com/pieces",     kw: ["Integrations", "pieces"],
                  repo: "activepieces/activepieces" },
  automatisch:  { url: "https://automatisch.io/",                 kw: ["integrations", "apps"],
                  repo: "automatisch/automatisch" },
  "node-red":   { url: "https://flows.nodered.org/",              kw: ["nodes", "flows"],
                  repo: "node-red/node-red" },
};

function vendorDir(v) { const d = path.join(FACTS_DIR, v); fs.mkdirSync(d, { recursive: true }); return d; }

function previousSnapshot(v) {
  const d = vendorDir(v);
  const files = fs.readdirSync(d).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f) && f.slice(0, 10) < TODAY).sort();
  if (!files.length) return null;
  const f = files[files.length - 1];
  try { return { date: f.slice(0, 10), data: JSON.parse(fs.readFileSync(path.join(d, f), "utf8")) }; }
  catch { return null; }
}

// největší číslo, které v textu stojí těsně před některým z klíčových slov
function extractCount(text, keywords) {
  let best = null, evidence = null;
  for (const kw of keywords) {
    const re = new RegExp("([\\d][\\d,\\.]{1,})\\s*\\+?\\s*" + kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    let m;
    while ((m = re.exec(text))) {
      const n = Number(m[1].replace(/[,\.]/g, ""));
      if (Number.isFinite(n) && n >= 30 && (best === null || n > best)) { best = n; evidence = m[0].trim().slice(0, 60); }
    }
  }
  return { count: best, evidence };
}

// free-tier evidence: posbírá „<číslo> <jednotka>" útržky z ceníku (kde free plán
// uvádí kvótu). EVIDENCE pro člověka/LLM; flag jen konzervativně (viz diff níže).
function extractFreeTier(text, freeKw) {
  const kw = (freeKw || []).map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  if (!kw) return { snippets: [], numbers: [] };
  // slep tisícové oddělovače z mezery/nbsp („1 000" / „10 000" → „1000") — jinak by
  // mezerou formátovaná kvóta dala falešné „000"=0 a tím falešný flag.
  const norm = String(text || "").replace(/(\d)[ \u00A0\u202F](?=\d{3}\b)/g, "$1");
  // (?<![\d.,]) = nezačínej uvnitř většího čísla (jinak „1,000" → falešné „000")
  const re = new RegExp("(?<![\\d.,])([\\d][\\d,\\.]{0,9})\\s*\\+?\\s*(?:" + kw + ")\\b", "gi");
  const snippets = [], numbers = [];
  let m;
  while ((m = re.exec(norm)) && snippets.length < 40) {
    const n = Number(m[1].replace(/[,\.]/g, ""));
    if (!Number.isFinite(n) || n < 1) continue;            // 0 = artefakt, zahoď
    snippets.push(m[0].replace(/\s+/g, " ").trim().slice(0, 40));
    numbers.push(n);
  }
  return { snippets: [...new Set(snippets)], numbers: [...new Set(numbers)] };
}

// ── normalizace licence pro porovnání (tools.json label ↔ GitHub spdx_id) ──────
function normLicense(s) { return String(s || "").toLowerCase().replace(/[^a-z0-9]/g, ""); }
function licenseMatches(claimLabel, spdx) {
  if (!spdx) return null;                                   // GitHub licenci nezná
  const s = spdx.toLowerCase();
  if (s === "noassertion" || s === "other") return null;    // custom/fair-code → neověřitelné spolehlivě (n8n)
  const a = normLicense(claimLabel), b = normLicense(spdx);
  if (!a) return null;
  return a === b || a.startsWith(b) || b.startsWith(a);
}

let _browser = null;
async function browser() {
  if (!_browser) { const { chromium } = require("playwright"); _browser = await chromium.launch({ headless: !HEADED }); }
  return _browser;
}
async function newPage() {
  return await (await (await browser()).newContext({ userAgent: UA })).newPage();
}

// GitHub API přes page.goto (node fetch má rozbité TLS). Vrací { spdx, name } | null.
async function fetchLicense(repo) {
  const page = await newPage();
  try {
    const headers = { Accept: "application/vnd.github+json" };
    if (GH_TOKEN) headers.Authorization = `Bearer ${GH_TOKEN}`;
    await page.setExtraHTTPHeaders(headers);
    const res = await page.goto(`https://api.github.com/repos/${repo}/license`, { waitUntil: "domcontentloaded", timeout: 30000 });
    if (!res || !res.ok()) return null;                     // 404 / rate-limit → neověřeno
    const body = await page.evaluate(() => document.body.innerText);
    const data = JSON.parse(body);
    const lic = data && data.license;
    if (!lic) return null;
    return { spdx: lic.spdx_id || null, name: lic.name || null };
  } catch { return null; }
  finally { await page.close(); }
}

async function scrapeVendor(v) {
  const cfg = VENDORS[v];
  const out = { vendor: v, url: cfg.url, _warnings: [] };
  // 1) integrations + open-source signál z apps/integrations stránky.
  //    NE-fatální: když počet nejde přečíst (bot wall / layout), pokračujeme na
  //    license + free-tier (license je nejspolehlivější signál — nesmí ho shodit
  //    flaky integrations stránka). integrations=null → diff to přeskočí.
  const page = await newPage();
  try {
    const res = await page.goto(cfg.url, { waitUntil: "domcontentloaded", timeout: 60000 });
    if (!res || !res.ok()) throw new Error(`HTTP ${res ? res.status() : "?"}`);
    await page.waitForTimeout(3500);  // JS-rendered počítadla (n8n/pipedream/activepieces)
    out._html = await page.content();
    const text = await page.evaluate(() => document.body.innerText);
    const { count, evidence } = extractCount(text, cfg.kw);
    out.integrations = count;
    out.openSourceSignal = /open[\s-]?source|self[\s-]?host|github\.com/i.test(text);
    out.evidence = evidence;
    if (count === null) out._warnings.push("počet integrací nenalezen (změna layoutu / bot wall)");
  } catch (e) {
    out.integrations = null;
    out._warnings.push("integrations scrape selhal: " + (e.message || e).toString().slice(0, 50));
  } finally { await page.close(); }

  // 2) license z GitHub (jen OSS nástroje s repem) — autoritativní, stabilní
  if (cfg.repo) {
    const lic = await fetchLicense(cfg.repo);
    out.repo = cfg.repo;
    out.selfHostConfirmed = !!lic;                          // veřejné repo → self-host potvrzen
    out.license = lic ? { spdx: lic.spdx, name: lic.name } : null;
  }

  // 3) free-tier evidence z ceníku (jen cloud nástroje) — konzervativní
  if (cfg.pricingUrl && cfg.freeKw) {
    const p2 = await newPage();
    try {
      const res = await p2.goto(cfg.pricingUrl, { waitUntil: "domcontentloaded", timeout: 60000 });
      if (res && res.ok()) {
        await p2.waitForTimeout(3500);
        const ptext = await p2.evaluate(() => document.body.innerText);
        out.freeTier = extractFreeTier(ptext, cfg.freeKw);
      }
    } catch { /* free-tier je best-effort, selhání neshazuje vendor */ }
    finally { await p2.close(); }
  }
  return out;
}

// licence, které GitHub legitimně NEUMÍ rozpoznat (custom/fair-code) → NOASSERTION
// je u nich očekávané, nehlásit ani jako note.
function isKnownCustomLicense(label) { return /sustainable|fair.?code|custom|proprietary/i.test(String(label || "")); }

// ── diff: scrape vs claimed (tools.json) → { changes (alarm), notes (evidence) } ──
function diffVendor(v, snap, claim) {
  const changes = [];   // reálné rozpory → spouští alarm (changeCount)
  const notes = [];     // evidence-only (neověřitelné / měkké) → bez alarmu
  // integrations (číselné, tolerance 15 %)
  if (typeof snap.integrations === "number" && typeof claim.integrations === "number" && claim.integrations > 0) {
    const delta = Math.abs(snap.integrations - claim.integrations) / claim.integrations;
    if (delta > DELTA_TOL) {
      changes.push({ vendor: v, field: "integrations", claimed: claim.integrations, scraped: snap.integrations,
        deltaPct: Math.round(delta * 100),
        desc: `${v}: tools.json uvádí ${claim.integrations} integrací, oficiální stránka ${snap.integrations} (${Math.round(delta*100)} % rozdíl) — revidovat` });
    }
  }
  // license: alarm jen při ROZPOZNANÉ neshodě (GitHub vrátí jiný spdx). Když GitHub
  // licenci neumí potvrdit (NOASSERTION/Other) a my tvrdíme konkrétní spdx
  // (ne known-custom), je to měkký signál „možná stará/dual licence" → note (bez alarmu).
  if (snap.license) {
    const spdx = snap.license.spdx;
    const m = licenseMatches(claim.license, spdx);
    if (m === false) {
      changes.push({ vendor: v, field: "license", claimed: claim.license, scraped: spdx,
        desc: `${v}: tools.json licence "${claim.license}", GitHub spdx "${spdx}" (${snap.license.name || ""}) — revidovat` });
    } else if ((!spdx || /noassertion|other/i.test(spdx)) && claim.license && !isKnownCustomLicense(claim.license)) {
      notes.push({ vendor: v, field: "license", claimed: claim.license, scraped: spdx || "—",
        desc: `${v}: GitHub nepotvrdil licenci "${claim.license}" (hlásí ${snap.license.name || "Other"}) — ověřit LICENSE ručně (možná dual/commercial)` });
    }
  }
  // self-host: veřejné repo potvrzuje self-host. Flag jen když tools.json říká false,
  // ale repo existuje (= podhodnocujeme funkci konkurenta). Opačně neflagujeme
  // (absence repa není důkaz „cloud-only").
  if (snap.selfHostConfirmed === true && claim.selfHostable === false) {
    changes.push({ vendor: v, field: "selfHostable", claimed: false, scraped: true,
      desc: `${v}: tools.json selfHostable=false, ale veřejný repo ${snap.repo} existuje — revidovat` });
  }
  // free-tier: KONZERVATIVNÍ flag. Jen když máme číselnou claimed kvótu a ceník
  // sice nějaké free-tier číslo uvádí, ale NAŠE číslo mezi nimi NENÍ. Jinak
  // (žádná data / shoda) = bez flagu. Marketing ceníky jsou fragile → low severity.
  if (snap.freeTier && Array.isArray(snap.freeTier.numbers) && snap.freeTier.numbers.length) {
    const claimNum = Number(String(claim.freeOps || "").replace(/[^0-9]/g, ""));
    if (Number.isFinite(claimNum) && claimNum > 0 && !snap.freeTier.numbers.includes(claimNum)) {
      changes.push({ vendor: v, field: "freeTier", claimed: claim.freeOps, scraped: snap.freeTier.snippets.slice(0, 6),
        severity: "low",
        desc: `${v}: tools.json free tier "${claim.freeOps}" (${claimNum}) nenalezen na ceníku; ceník uvádí ${snap.freeTier.snippets.slice(0, 4).join(", ")} — ověřit` });
    }
  }
  return { changes, notes };
}

(async () => {
  const only = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const vendors = only.length ? only : Object.keys(VENDORS);
  const claimBySlug = {};
  for (const t of JSON.parse(fs.readFileSync(TOOLS_JSON, "utf8")).tools)
    claimBySlug[t.slug] = { integrations: t.integrations, license: t.license, selfHostable: t.selfHostable, freeOps: t.freeOps };

  let failures = 0, blocked = 0;
  const allChanges = [], allNotes = [];

  for (const v of vendors) {
    if (!VENDORS[v]) { console.log(`(přeskakuji neznámého vendora: ${v})`); continue; }
    try {
      const snap = await scrapeVendor(v);
      const dir = vendorDir(v);
      const prev = previousSnapshot(v);
      // perzistentní snapshot (bez _html)
      const out = { date: TODAY, vendor: v, url: snap.url, integrations: snap.integrations,
        openSourceSignal: snap.openSourceSignal, evidence: snap.evidence };
      if (snap.repo) { out.repo = snap.repo; out.selfHostConfirmed = snap.selfHostConfirmed; out.license = snap.license; }
      if (snap.freeTier) out.freeTier = snap.freeTier;
      if (snap._warnings && snap._warnings.length) out.warnings = snap._warnings;
      fs.writeFileSync(path.join(dir, `${TODAY}.json`), JSON.stringify(out, null, 2) + "\n", "utf8");
      // html.gz jen poprvé / při změně počtu (repo by jinak rostlo); jen když HTML máme
      if (snap._html && (!prev || prev.data.integrations !== snap.integrations))
        fs.writeFileSync(path.join(dir, `${TODAY}.html.gz`), zlib.gzipSync(snap._html));

      // diff proti claimed hodnotám v tools.json (TOHLE je smysl auditu)
      const claim = claimBySlug[v] || {};
      const { changes, notes } = diffVendor(v, snap, claim);
      allChanges.push(...changes);
      allNotes.push(...notes);
      if (snap._warnings && snap._warnings.length) blocked++;   // integrations nepřečteny → WARN (ne fail)

      const bits = [`${snap.integrations == null ? "?" : snap.integrations} integrací (claim ${claim.integrations ?? "?"})`];
      if (snap.license && snap.license.spdx) bits.push(`lic ${snap.license.spdx}`);
      if (snap.selfHostConfirmed) bits.push("self-host✓");
      if (snap.openSourceSignal) bits.push("OSS signal");
      const tail = `${changes.length ? `  ⚠ ${changes.length} rozpor(ů)` : ""}${notes.length ? `  · ${notes.length} pozn.` : ""}${(snap._warnings || []).length ? `  ⚠ ${snap._warnings.join("; ")}` : ""}`;
      console.log(`✓ ${v}: ${bits.join(" · ")}${tail}`);
    } catch (e) {
      const msg = e.message || String(e);
      const isBotWall = /bot|403|429|503|timeout|Timeout|nenalezen|HTTP \?/i.test(msg);
      if (isBotWall) { console.log(`⚠ WARN ${v} (bot wall / layout, ne změna faktu): ${msg.slice(0, 70)}`); blocked++; }
      else { console.log(`SELHALO ${v}: ${msg}`); failures++; }
    }
  }

  if (_browser) await _browser.close();

  if (!NO_DIFF) {
    fs.mkdirSync(FACTS_DIR, { recursive: true });
    const report = { date: TODAY, generatedAt: new Date().toISOString(),
      changeCount: allChanges.length, changes: allChanges,
      noteCount: allNotes.length, notes: allNotes };
    fs.writeFileSync(path.join(FACTS_DIR, `changes-${TODAY}.json`), JSON.stringify(report, null, 2) + "\n", "utf8");
    if (allChanges.length) {
      const line = allChanges.map((c) => JSON.stringify({ d: TODAY, ...c })).join("\n") + "\n";
      fs.appendFileSync(path.join(FACTS_DIR, "facts-history.jsonl"), line, "utf8");
    }
    console.log(`\n📋 ${allChanges.length} faktických rozporů (alarm) · ${allNotes.length} poznámek (evidence) → facts-audit/changes-${TODAY}.json`);
    for (const c of allChanges) console.log(`   • ${c.desc}`);
    for (const n of allNotes) console.log(`   · ${n.desc}`);
  }
  if (blocked) console.log(`⚠ ${blocked} vendor(ů) neúplně ověřeno (bot wall / layout) — ne fail.`);
  process.exit(failures ? 1 : 0);   // exit 1 jen tvrdá chyba; alarm na changeCount řeší workflow
})();
