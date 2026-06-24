#!/usr/bin/env node
/**
 * feature-audit.js — per-plán FEATURES / INCLUDES audit (doplněk price-audit.js, který bere jen ceny).
 *
 * SCOPE (vědomě omezený podle ToS — viz níže): JEN n8n, Make, Activepieces.
 *   Jejich ToS MLČÍ o scrapingu/botech a robots.txt /pricing povoluje → fact-only audit
 *   s atribucí je obhajitelný.
 *
 * ⛔ VYLOUČENO ZÁMĚRNĚ — NEPŘIDÁVAT: Pipedream a Zapier. Jejich ToS automatizovaný přístup
 *   VÝSLOVNĚ ZAKAZUJE:
 *     - Pipedream /terms: „use bots, scrapers, crawlers, spiders … to monitor, collect or copy
 *       information from the Website" + „data mining, robots … to scrape or extract data".
 *     - Zapier legal: „obtain … information through any means not intentionally made available"
 *       + „accessing data not intended for users of the Site" + zákaz „harvest".
 *   Jejich features se doplňují RUČNĚ (člověk čte veřejnou stránku ≠ bot). Stejně jako
 *   Artificial Analysis u LLM vrstvy: ToS > pohodlí.
 *
 * Slušnost: identifikovatelný User-Agent, respekt k robots.txt (per-URL), rate-limit mezi vendory,
 *   ukládá jen FAKTA (krátké feature labely) + source URL + asof — ne dlouhé odstavce verbatim.
 *
 * Output:
 *   automation/data/features/<vendor>/<YYYY-MM-DD>.json   (vždy)
 *   automation/data/features/<vendor>/changes-<date>.json (jen když se features změnily)
 *
 * Usage:
 *   node scripts/feature-audit.js                 # všichni 3 povolení vendoři
 *   node scripts/feature-audit.js n8n             # jeden vendor
 *   PW_EXECUTABLE=/path/chrome.exe node scripts/feature-audit.js   # lokální test s konkrétním browserem
 *
 * NIKDY nepíše do tools.json ani na web — jen audit snapshoty. Faktická změna = owner gate.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const UA = "WizardCostBot/1.0 (+https://wizardcost.com; polite feature audit, robots-respecting)";
const ROOT = path.resolve(__dirname, "..");
const OUT_DIR = path.join(ROOT, "automation", "data", "features");
const TODAY = new Date().toISOString().slice(0, 10);

// ── vendoři (POUZE ToS-mlčící + robots-povolené) ────────────────────────────
const VENDORS = {
  n8n:          { url: "https://n8n.io/pricing/",             plans: ["Starter", "Pro", "Business", "Enterprise"],        mode: "li" },
  make:         { url: "https://www.make.com/en/pricing",     plans: ["Free", "Core", "Pro", "Teams", "Enterprise"],       mode: "li" },
  activepieces: { url: "https://www.activepieces.com/pricing", plans: ["Standard", "Ultimate"],                            mode: "lines" },
};

const ONLY = process.argv.slice(2).filter((a) => !a.startsWith("-"));
const targets = ONLY.length ? ONLY : Object.keys(VENDORS);

// ── robots.txt (per-URL Disallow pro UA *) ──────────────────────────────────
function parseRobots(txt) {
  const rules = []; let active = false;
  for (const raw of (txt || "").split("\n")) {
    const line = raw.replace(/#.*/, "").trim(); if (!line) continue;
    const m = line.match(/^([A-Za-z-]+)\s*:\s*(.*)$/); if (!m) continue;
    const k = m[1].toLowerCase(), v = m[2].trim();
    if (k === "user-agent") active = (v === "*");
    else if (active && k === "disallow" && v) rules.push(v);
  }
  return rules;
}
function pathAllowed(disallows, urlPath) {
  for (const d of disallows) {
    // jednoduchý prefix/glob match (robots-style *): stačí na náš účel
    const rx = new RegExp("^" + d.replace(/[.+?^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*"));
    if (rx.test(urlPath)) return false;
  }
  return true;
}

// ── extrakce featur ze stránky (běží v page kontextu) ───────────────────────
function extractInPage(arg) {
  const plans = arg.plans, mode = arg.mode;
  const txt = (el) => (el.innerText || "").replace(/[ \t]+/g, " ").trim();

  function cardLi(name) {
    const hs = [...document.querySelectorAll("h1,h2,h3,h4,h5,[class*=title],[class*=name]")]
      .filter((e) => txt(e).toLowerCase() === name.toLowerCase());
    for (const h of hs) {
      let el = h;
      for (let i = 0; i < 7 && el; i++) {
        const lis = [...el.querySelectorAll("li")];
        if (lis.length >= 2) return [...new Set(lis.map(txt).filter((t) => t && t.length < 110))];
        el = el.parentElement;
      }
    }
    return null;
  }

  function columnLines(name) {
    const noise = new Set(["usage based", "annual contract", "free", "custom", "start free",
      "contact sales", "show all", "we'll help customize it", "we’ll help customize it"]);
    const hs = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6,[class*=title]")].filter((e) => txt(e) === name);
    for (const h of hs) {
      let el = h;
      for (let i = 0; i < 8 && el; i++) {
        const lines = txt(el).split("\n").map((s) => s.trim()).filter(Boolean);
        if (lines.length >= 5 && lines.length < 60) {
          return lines.filter((l) => {
            const lo = l.toLowerCase();
            if (lo === name.toLowerCase()) return false;
            if (noise.has(lo)) return false;
            if (/\$|per active flow|per month|\/mo/i.test(l)) return false;     // cena/cta
            if (/^[A-Z][A-Z &]{5,}$/.test(l)) return false;                      // ALL-CAPS skupinový nadpis
            return true;
          });
        }
        el = el.parentElement;
      }
    }
    return null;
  }

  const res = {};
  for (const p of plans) {
    const f = mode === "lines" ? columnLines(p) : cardLi(p);
    res[p] = f && f.length ? f : null;
  }
  return res;
}

// ── Make: plná "Compare features" matice (table) — běží v page kontextu ──────
// ✓/✗ jsou nerozlišitelné SVG; rozlišuju tvarem path (kolečko-check má křivku 'C',
// dash/✗ je rovná čára). Název featury je v <strong> (label má nalepený tooltip).
function extractMakeMatrix() {
  const tc = (el) => (el.textContent || "").replace(/\s+/g, " ").trim();
  const t = document.querySelector("table");
  if (!t) return null;
  const trs = [...t.querySelectorAll("tr")];
  if (!trs.length) return null;
  const head = [...trs[0].children].map(tc);
  const cols = head.slice(1).filter(Boolean);
  if (cols.length < 3) return null;
  function val(c) {
    const txt = tc(c);
    if (txt) return txt;
    const svg = c.querySelector("svg");
    if (!svg) return null;
    const d = [...svg.querySelectorAll("path")].map((pp) => pp.getAttribute("d") || "").join("");
    return /C/i.test(d) ? true : false; // ✓ = kolečko (křivka C); ✗ = rovná čára
  }
  // tabulka má duplicitní řádky (responsive: label-only + plná verze). Feature názvy
  // jsou v <strong>, section headery (např. "Make + AI") ne. Dedup: feature beru jen
  // verzi s hodnotami; section header jen když se titulek liší od aktuálního.
  const groups = []; let cur = null;
  for (const r of trs.slice(1)) {
    const cells = [...r.children];
    if (!cells.length) continue;
    const strong = cells[0].querySelector("strong");
    const vc = cells.slice(1);
    const hasVals = vc.some((c) => tc(c) || c.querySelector("svg"));
    if (strong) {
      if (!hasVals) continue; // label-only duplikát → přeskoč
      if (!cur) { cur = { title: "Features", rows: [] }; groups.push(cur); }
      const tiers = {}; cols.forEach((cn, i) => tiers[cn] = val(vc[i]));
      cur.rows.push({ feature: tc(strong), tiers });
    } else {
      const title = tc(cells[0]);
      if (!title) continue; // tagline/prázdné
      if (!cur || cur.title !== title) { cur = { title, rows: [] }; groups.push(cur); }
    }
  }
  return { columns: cols, groups: groups.filter((g) => g.rows.length) };
}

// ── diff předchozího snapshotu ──────────────────────────────────────────────
function previousSnapshot(dir) {
  if (!fs.existsSync(dir)) return null;
  const files = fs.readdirSync(dir).filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f) && f.slice(0, 10) < TODAY).sort();
  if (!files.length) return null;
  try { return JSON.parse(fs.readFileSync(path.join(dir, files[files.length - 1]), "utf8")); } catch { return null; }
}
function diffPlans(oldSnap, newSnap) {
  const changes = [];
  const plans = new Set([...Object.keys(oldSnap.plans || {}), ...Object.keys(newSnap.plans || {})]);
  for (const p of plans) {
    const o = new Set((oldSnap.plans && oldSnap.plans[p]) || []);
    const n = new Set((newSnap.plans && newSnap.plans[p]) || []);
    const added = [...n].filter((x) => !o.has(x));
    const removed = [...o].filter((x) => !n.has(x));
    for (const x of removed) changes.push({ plan: p, change: "removed", feature: x });
    for (const x of added) changes.push({ plan: p, change: "added", feature: x });
  }
  return changes;
}

// ── main ────────────────────────────────────────────────────────────────────
(async () => {
  const { chromium } = require("playwright");
  const browser = await chromium.launch(
    process.env.PW_EXECUTABLE ? { executablePath: process.env.PW_EXECUTABLE } : { headless: true }
  );
  let failures = 0, totalChanges = 0;

  for (const v of targets) {
    const cfg = VENDORS[v];
    if (!cfg) { console.log(`· skip ${v} (není v povolených vendorech — ToS!)`); continue; }
    const ctx = await browser.newContext({ userAgent: UA });
    try {
      const u = new URL(cfg.url);
      // robots.txt gate
      let disallows = [];
      try {
        const r = await ctx.request.get(u.origin + "/robots.txt", { timeout: 20000, ignoreHTTPSErrors: true });
        if (r.ok()) disallows = parseRobots(await r.text());
      } catch { /* robots nedostupný → pokračuj opatrně */ }
      if (!pathAllowed(disallows, u.pathname)) {
        console.log(`✗ ${v}: robots.txt zakazuje ${u.pathname} → PŘESKAKUJI (slušnost)`);
        await ctx.close(); continue;
      }

      const page = await ctx.newPage();
      const resp = await page.goto(cfg.url, { waitUntil: "networkidle", timeout: 60000 });
      if (!resp || !resp.ok()) throw new Error(`HTTP ${resp ? resp.status() : "?"}`);
      await page.waitForTimeout(1200);
      const plansObj = await page.evaluate(extractInPage, { plans: cfg.plans, mode: cfg.mode });

      const got = Object.values(plansObj).filter(Boolean).length;
      const partial = got < cfg.plans.length;
      const snap = { vendor: v, url: cfg.url, asof: TODAY, fetchedBy: UA, partial, plans: plansObj };

      // plná feature matice (zatím jen Make — čistá tabulka; n8n/AP se plní offline)
      if (v === "make") {
        try {
          const mx = await page.evaluate(extractMakeMatrix);
          if (mx && mx.groups && mx.groups.length) snap.matrix = { source: cfg.url, asof: TODAY, columns: mx.columns, groups: mx.groups };
        } catch { /* matrix best-effort — nesmí shodit card audit */ }
      }

      const dir = path.join(OUT_DIR, v);
      fs.mkdirSync(dir, { recursive: true });
      const prev = previousSnapshot(dir);
      const ch = prev ? diffPlans(prev, snap) : [];

      // snapshot ukládáme jen při PRVNÍM běhu nebo když se features změnily → žádný denní spam.
      let changeNote = "";
      if (!prev || ch.length) {
        fs.writeFileSync(path.join(dir, `${TODAY}.json`), JSON.stringify(snap, null, 2) + "\n");
        if (ch.length) {
          fs.writeFileSync(path.join(dir, `changes-${TODAY}.json`),
            JSON.stringify({ vendor: v, from: prev.asof, to: TODAY, changeCount: ch.length, changes: ch }, null, 2) + "\n");
          totalChanges += ch.length;
          changeNote = ` · ${ch.length} změn vs ${prev.asof}`;
        }
      } else {
        changeNote = " · beze změny (snapshot nepřepisuji)";
      }
      const counts = cfg.plans.map((p) => `${p}:${plansObj[p] ? plansObj[p].length : "∅"}`).join(" ");
      console.log(`✓ ${v.padEnd(12)} ${counts}${partial ? " (PARTIAL)" : ""}${changeNote}`);
    } catch (e) {
      failures++;
      console.log(`✗ ${v}: ERROR ${e.message}`);
    }
    await ctx.close();
    await new Promise((r) => setTimeout(r, 1500)); // polite pauza mezi vendory
  }

  await browser.close();
  if (totalChanges) console.log(`\n${totalChanges} feature změn — viz changes-${TODAY}.json (owner gate na případnou aktualizaci tools.json).`);
  process.exit(failures > 0 ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
