#!/usr/bin/env node
/**
 * price-audit.js — denní AUDIT cen všech sledovaných nástrojů.
 *
 * Tohle je vrstva DŮKAZŮ pod price-watch.js. Každý den:
 *   1) stáhne syrové HTML každého ceníku  → automation/data/audit/<vendor>/<YYYY-MM-DD>.html
 *   2) vytáhne normalizovaná cenová data   → automation/data/audit/<vendor>/<YYYY-MM-DD>.json
 *   3) diff proti POSLEDNÍMU předchozímu snapshotu → automation/data/audit/changes-<YYYY-MM-DD>.json
 *      (+ append do automation/data/audit/price-history.jsonl pro grafy změn)
 *
 * Volume-based ceníky (Make, Zapier) se scrapují CELOU maticí (slider/HTML-JSON),
 * fixní ceníky (Pipedream, n8n, Activepieces, Automatisch, Node-RED) se ukládají
 * jako syrové HTML + parsnuté plány. Vše bez jediného screenshotu — pro GH Actions cron.
 *
 * Audit data jsou EVIDENCE, ne zdroj pravdy. tools.json updatuje člověk po revizi
 * change reportu — stejný princip jako wayback audit a drift-report.
 *
 * Spuštění:
 *   node scripts/price-audit.js                 # všechny vendory, plný audit + diff
 *   node scripts/price-audit.js make zapier     # jen vybrané
 *   node scripts/price-audit.js --no-diff       # jen snapshoty, bez porovnání
 *   node scripts/price-audit.js --headed        # vidět browser (debug)
 */
"use strict";
const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
           "(KHTML, like Gecko) Chrome/120.0 Safari/537.36";
const REPO = path.resolve(__dirname, "..");
const AUDIT_DIR = path.join(REPO, "automation", "data", "audit");
const TODAY = new Date().toISOString().slice(0, 10);
const HEADED = process.argv.includes("--headed");
const NO_DIFF = process.argv.includes("--no-diff");

// ── vendor katalog ────────────────────────────────────────────────────────
// model: "slider" = volume matice (scrape přes engine níže)
//        "fixed"  = pevné plány (uloží HTML + hrubý parse cen z textu)
const VENDORS = {
  zapier:       { url: "https://zapier.com/pricing",                 model: "slider", unit: "tasks" },
  make:         { url: "https://www.make.com/en/pricing",            model: "slider", unit: "credits" },
  pipedream:    { url: "https://pipedream.com/pricing",              model: "slider", unit: "credits" },
  n8n:          { url: "https://n8n.io/pricing/",                    model: "slider", unit: "executions" },
  activepieces: { url: "https://www.activepieces.com/pricing",       model: "fixed",  unit: "flows" },
  automatisch:  { url: "https://automatisch.io/",                    model: "fixed",  unit: "self-host" },
};

function vendorDir(v) {
  const d = path.join(AUDIT_DIR, v);
  fs.mkdirSync(d, { recursive: true });
  return d;
}

// poslední JSON snapshot PŘED dneškem (pro diff)
function previousSnapshot(v) {
  const d = vendorDir(v);
  const files = fs.readdirSync(d)
    .filter((f) => /^\d{4}-\d{2}-\d{2}\.json$/.test(f) && f.slice(0, 10) < TODAY)
    .sort();
  if (!files.length) return null;
  const f = files[files.length - 1];
  try { return { date: f.slice(0, 10), data: JSON.parse(fs.readFileSync(path.join(d, f), "utf8")) }; }
  catch { return null; }
}

// ── Billing fingerprint (zachytí změny BILLINGU mimo cenu) ──────────────────
// Kurátované billing-relevantní řádky z vyrenderované stránky: zahrnuté kvóty,
// limity (workflows, concurrency, users), AI tokeny, overage, A PRAVIDLA účtování
// ("2 credits per 1 sec of code execution", "1 module = 1 credit"). Ověřeno
// empiricky: dva běhy = 0 šumu → stabilní, vhodné na alarm. Diff den-proti-dni
// → přesně řekne, co se v billingu změnilo, i když se cena nezměnila.
const BILLING_KW = /credit|task|execution|workflow|operation|module|\bGB\b|\bMB\b|user|seat|project|token|included|unlimited|active|concurrent|per |\/mo|month|retention|insight|overage|API|webhook|SSO|SAML|RBAC|audit/i;
function extractBillingLines(text) {
  const out = new Set();
  for (const raw of (text || "").split("\n")) {
    const l = raw.replace(/\s+/g, " ").trim();
    if (!l || l.length > 60) continue;                       // dlouhé = marketing copy
    if (!BILLING_KW.test(l)) continue;                       // jen billing-relevantní
    if (!/\d/.test(l) && !/unlimited/i.test(l)) continue;    // číslo nebo "unlimited"
    out.add(l.toLowerCase());
  }
  return [...out].sort();
}
async function billingLines(page) {
  try { return extractBillingLines(await page.evaluate(() => document.body.innerText)); }
  catch { return []; }
}
// fullPage PNG ceníku vendora — vizuální důkaz změny do PR (starý vs nový).
// Vrací Buffer | null (selhání screenshotu nesmí shodit scrape).
async function shoot(page) {
  try { return await page.screenshot({ fullPage: true, type: "png" }); }
  catch { return null; }
}

// ── scrape jednotlivých vendorů ─────────────────────────────────────────────
let _browser = null;
async function browser() {
  if (!_browser) {
    const { chromium } = require("playwright");
    _browser = await chromium.launch({ headless: !HEADED });
  }
  return _browser;
}
async function newPage() {
  return await (await (await browser()).newContext({ userAgent: UA })).newPage();
}

// Zapier: celá matice je inline JSON v HTML.
async function scrapeZapier() {
  const page = await newPage();
  const res = await page.goto(VENDORS.zapier.url, { waitUntil: "domcontentloaded", timeout: 60000 });
  if (!res || !res.ok()) throw new Error(`HTTP ${res ? res.status() : "?"}`);
  const html = await page.content();
  const bl = await billingLines(page);
  const shot = await shoot(page);
  await page.close();
  const re = /\{"planType":"([^"]+)","tasks":(\d+),"id":\d+,"name":"[^"]*","shortName":"[^"]*","amount":(\d+),"actions":\d+,"interval":"([^"]+)"\}/g;
  const byI = { month: {}, year: {} };
  let m, n = 0;
  while ((m = re.exec(html))) {
    const [, plan, tasks, cents, interval] = m;
    if (!byI[interval]) continue;
    (byI[interval][Number(tasks)] ||= {})[plan] = Number(cents) / 100;
    n++;
  }
  if (!n) throw new Error("matice nenalezena (změna formátu?)");
  const rows = (o) => Object.keys(o).map(Number).sort((a, b) => a - b).map((u) => ({ units: u, plans: o[u] }));
  return { html, prices: { unit: "tasks", monthly: rows(byI.month), annually: rows(byI.year), points: n, billingLines: bl }, shot };
}

// Make: slider 0..18, ceny generuje JS lokálně → projet pozice pro monthly i annually.
const MAKE_TIERS = [10000, 20000, 40000, 80000, 150000, 300000, 500000, 750000, 1000000,
  1500000, 2000000, 2500000, 3000000, 4000000, 5000000, 6000000, 7000000, 8000000, null];
async function scrapeMake() {
  const page = await newPage();
  await page.goto(VENDORS.make.url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(4000);
  const html = await page.content();

  async function readPlans() {
    return await page.evaluate(() => {
      const plans = {};
      document.querySelectorAll("*").forEach((el) => {
        const h = (el.textContent || "").trim();
        if (/^(Core|Pro|Teams)$/.test(h) && el.children.length === 0 && plans[h] === undefined) {
          let card = el.parentElement;
          for (let hop = 0; hop < 5 && card; hop++) {
            const txt = card.innerText || "";
            if (/not available/i.test(txt)) { plans[h] = null; break; }
            const pm = txt.match(/\$\s?([\d,]+)\s*(?:\.\s*(\d{2}))?/);
            if (pm) { const d = Number(pm[1].replace(/,/g, "")); plans[h] = pm[2] ? Number(`${d}.${pm[2]}`) : d; break; }
            card = card.parentElement;
          }
        }
      });
      return plans;
    });
  }
  async function setPeriod(label) {
    const ok = await page.evaluate((want) => {
      const e = [...document.querySelectorAll("div,button,[role=tab]")]
        .filter((x) => (x.textContent || "").trim().toLowerCase() === want && x.offsetParent !== null)[0];
      if (e) { e.click(); return true; } return false;
    }, label);
    await page.waitForTimeout(1500);
    return ok;
  }
  async function sweep() {
    const slider = await page.$("input[type=range]");
    if (!slider) throw new Error("slider nenalezen");
    const max = Number(await slider.getAttribute("max")) || 18;
    const rows = [], seen = new Set();
    for (let pos = 0; pos <= max; pos++) {
      await page.evaluate((p) => {
        const el = document.querySelector("input[type=range]");
        const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        set.call(el, String(p));
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }, pos);
      await page.waitForTimeout(450);
      const units = MAKE_TIERS[pos] !== undefined ? MAKE_TIERS[pos] : null;
      const key = units === null ? `pos${pos}` : units;
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push({ units, plans: await readPlans() });
    }
    if (rows.length < 5) throw new Error(`jen ${rows.length} pozic`);
    return rows;
  }
  await setPeriod("pay monthly");
  const monthly = await sweep();
  let annually = [];
  if (await setPeriod("pay annually")) annually = await sweep();
  const bl = await billingLines(page);
  const shot = await shoot(page);
  await page.close();
  return { html, prices: { unit: "credits", monthly, annually, billingLines: bl }, shot };
}

// Pipedream: 3 slidery (Basic/Advanced/Connect). Cena = STUPŇOVITÁ TARIFNÍ TABULKA
// (ne vzorec — ověřeno hustým sweepem, mocninný fit selhal 667 %). Sazba
// "$X per credit" je konstantní v pásmu a klesá s objemem (množstevní sleva).
// Reprezentace: bands = [{upTo, perCredit}, …], upTo = horní hranice objemu
// (kredity <= upTo → tato sazba); poslední pásmo upTo:null = neomezeno.
// base = měsíční předplatné (billed monthly), baseAnnual = billed-annually $/mo.
// Pipedream má roční slevu ~34–36 % (Basic $45→$29, Advanced $74→$49, Connect $150→$99,
// ověřeno proklikem toggle Monthly/Annual 2026-06-15). Base je hardcoded (scraper
// sweepuje jen credit bands z sliderů, ne subscription base).
const PD_PLANS = [
  { name: "Basic", base: 45, baseAnnual: 29, includedCredits: 2000 },
  { name: "Advanced", base: 74, baseAnnual: 49, includedCredits: 2000 },
  { name: "Connect", base: 150, baseAnnual: 99, includedCredits: 10000 },
];

async function scrapePipedream() {
  const page = await newPage();
  await page.goto(VENDORS.pipedream.url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(4500);
  const html = await page.content();

  const sliderCount = await page.$$eval("input[type=range]", (els) => els.length);
  if (sliderCount < 3) throw new Error(`čekal 3 slidery, našel ${sliderCount}`);

  async function readCard(idx) {
    return await page.evaluate((i) => {
      const s = document.querySelectorAll("input[type=range]")[i];
      let card = s.parentElement;
      for (let h = 0; h < 8 && card; h++) {
        const t = card.innerText || "";
        if (/per\b/.test(t) && /credits?\s*\/mo/i.test(t)) break;
        card = card.parentElement;
      }
      const t = card ? card.innerText : "";
      const credits = (t.match(/([\d,]+)\s*credits?\s*\/mo/i) || [])[1];
      const perCredit = (t.match(/\$([\d.]+)\s*per\b/) || [])[1];
      return {
        credits: credits ? Number(credits.replace(/,/g, "")) : null,
        perCredit: perCredit ? Number(perCredit) : null,
      };
    }, idx).catch(() => null);
  }
  function setSlider(idx, val) {
    return page.evaluate(({ i, v }) => {
      const el = document.querySelectorAll("input[type=range]")[i];
      const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      set.call(el, String(v));
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    }, { i: idx, v: val });
  }
  // HUSTÝ SWEEP každého slideru: projedeme všechny pozice 0..max a sbíráme
  // přechody sazby. `upTo` pásma = POSLEDNÍ objem před změnou sazby (horní
  // hranice). Cílený scrape na "prahy" zaváděl chyby (posun o pásmo, ztráta
  // nejvyššího $0.0003 pásma) — hustý sweep je jediný 100% přesný způsob.
  // Slider má ~1800 pozic; čteme rychle a ukládáme jen přechody.
  const plans = {};
  for (let i = 0; i < PD_PLANS.length; i++) {
    const meta = PD_PLANS[i];
    const max = Number(await (await page.$$("input[type=range]"))[i].getAttribute("max")) || 1800;
    const ascending = []; // {credits, perCredit} jen rostoucí část (slider se na max vrací)
    let lastCredits = -1;
    for (let pos = 0; pos <= max; pos++) {
      await setSlider(i, pos);
      await page.waitForTimeout(14);
      const r = await readCard(i);
      if (!r || !r.credits || !r.perCredit) continue;
      if (r.credits < lastCredits) break; // slider se začal vracet → konec rostoucí části
      lastCredits = r.credits;
      const prev = ascending[ascending.length - 1];
      if (!prev || prev.credits !== r.credits) ascending.push(r);
    }
    // sbal do pásem: každé pásmo = {upTo: poslední objem se sazbou, perCredit}.
    // poslední pásmo dostane upTo:null (neomezeno). Sazby pod included kredity
    // patří do base plánu, ne do overage → vyfiltruj.
    const bands = [];
    for (let k = 0; k < ascending.length; k++) {
      const cur = ascending[k];
      const next = ascending[k + 1];
      if (!next || next.perCredit !== cur.perCredit) {
        if (cur.credits > meta.includedCredits) {
          bands.push({ upTo: next ? cur.credits : null, perCredit: cur.perCredit });
        }
      }
    }
    if (bands.length < 8) throw new Error(`${meta.name}: jen ${bands.length} pásem (sweep selhal?)`);
    plans[meta.name] = { base: meta.base, baseAnnual: meta.baseAnnual, includedCredits: meta.includedCredits, bands };
  }
  const bl = await billingLines(page);
  const shot = await shoot(page);
  await page.close();
  return { html, prices: { unit: "credits", model: "per-credit-bands", plans, billingLines: bl }, shot };
}

// n8n: Starter má fixní objem, ale Pro a Business mají DROPDOWN selektor objemu
// (role=button aria-haspopup=listbox, options "10K executions 50€/month").
// Ceny v EUR, monthly i annually toggle. Otevřeme každý dropdown přes aria-controls
// a přečteme celou matici objem→cena.
async function scrapeN8n() {
  const page = await newPage();
  await page.goto(VENDORS.n8n.url, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(3000);
  const html = await page.content();

  // přečte options ze všech dropdownů (Pro, Business) → [{plan?, options:[{units,eur}]}]
  async function readDropdowns() {
    const btns = await page.$$("[role=button][aria-haspopup=listbox]");
    const result = [];
    for (const btn of btns) {
      const ctrl = await btn.getAttribute("aria-controls");
      const label = (await btn.innerText()).replace(/\s+/g, " ").trim().slice(0, 30);
      await btn.click();
      await page.waitForTimeout(700);
      const options = await page.evaluate((id) => {
        const lb = document.getElementById(id);
        if (!lb) return [];
        const txts = [...lb.querySelectorAll("[role=option], li, div")]
          .map((o) => o.innerText.replace(/\s+/g, " ").trim());
        const seen = new Set(), out = [];
        for (const t of txts) {
          // "10K executions 50€/month" / "150K executions 1824€/month"
          const m = t.match(/([\d.]+)\s*([KM])\s*executions\s*([\d,]+)\s*€/i);
          if (m) {
            const units = Math.round(parseFloat(m[1]) * (m[2].toUpperCase() === "M" ? 1e6 : 1e3));
            const eur = Number(m[3].replace(/,/g, ""));
            if (!seen.has(units)) { seen.add(units); out.push({ units, eur }); }
          }
        }
        return out;
      }, ctrl);
      await page.keyboard.press("Escape").catch(() => {}); // zavři dropdown
      await page.waitForTimeout(300);
      if (options.length) result.push({ label, options });
    }
    return result;
  }
  // Starter fixní cena (mimo dropdown) z karty — slouží i jako indikátor billing
  // (20€ = annually, 24€ = monthly).
  async function starterEur() {
    return await page.evaluate(() => {
      const m = document.body.innerText.match(/(\d+)€\s*\/mo/);
      return m ? Number(m[1]) : null;
    });
  }
  // Billing je JEDEN switch (Monthly↔Annually), default = annually. Klikneme switch
  // a ověříme dle Starter ceny; když nesedí, klikneme znovu (max 2×).
  async function setBilling(want /* "monthly" | "annually" */) {
    const target = want === "monthly" ? 24 : 20;
    for (let attempt = 0; attempt < 4; attempt++) {
      if (await starterEur() === target) return true;
      // zavři případně otevřený dropdown (přebíjí switch) + klikni switch silově
      await page.keyboard.press("Escape").catch(() => {});
      await page.evaluate(() => {
        const sw = document.querySelector("input[type=checkbox], [role=switch]");
        if (sw) sw.click();
      });
      await page.waitForTimeout(1300);
    }
    return await starterEur() === target;
  }

  const monthlyOk = await setBilling("monthly");
  const monthly = { starter: await starterEur(), billingOk: monthlyOk, dropdowns: await readDropdowns() };
  const annuallyOk = await setBilling("annually");
  const annually = { starter: await starterEur(), billingOk: annuallyOk, dropdowns: await readDropdowns() };
  const bl = await billingLines(page);
  const shot = await shoot(page);
  await page.close();
  if (!monthly.dropdowns.length) throw new Error("n8n: žádné dropdown options (změna struktury?)");
  return { html, prices: { unit: "executions", currency: "EUR", model: "dropdown-volume", monthly, annually, billingLines: bl }, shot };
}

// Fixní ceníky: ulož HTML + vytáhni $N /mo ceny z viditelného textu jako hrubý otisk.
async function scrapeFixed(v) {
  const page = await newPage();
  await page.goto(VENDORS[v].url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(3500);
  const html = await page.content();
  const text = await page.evaluate(() => document.body.innerText);
  const bl = extractBillingLines(text);
  const shot = await shoot(page);
  await page.close();
  const prices = [...new Set([...text.matchAll(/\$\s?([\d,]+(?:\.\d{2})?)/g)].map((m) => Number(m[1].replace(/,/g, ""))))]
    .filter((n) => n > 0).sort((a, b) => a - b);
  return { html, prices: { unit: VENDORS[v].unit, model: "fixed", listedPrices: prices, billingLines: bl }, shot };
}

async function scrapeVendor(v) {
  if (v === "zapier") return scrapeZapier();
  if (v === "make") return scrapeMake();
  if (v === "pipedream") return scrapePipedream();
  if (v === "n8n") return scrapeN8n();
  return scrapeFixed(v);
}

// Probe objemy pro slider vendory (v jejich NATIVNÍ jednotce) — diff počítáme na
// FIXNÍCH bodech (jako Pipedream per-credit-bands), ne na raw slider řádcích, které
// jitterují (pozice) a flapují (chybné čtení billing toggle → uniformní ×posun).
const SLIDER_PROBES = {
  zapier: [750, 2000, 10000, 50000],        // tasks
  make:   [10000, 40000, 150000, 500000],   // credits
};
const _r2 = (x) => Math.round(x * 100) / 100;

// lineární interpolace ceny plánu na daném objemu z [{units, plans:{plan:price}}]
function priceAtVolume(rows, plan, vol) {
  const pts = (rows || [])
    .filter((r) => r.plans && r.plans[plan] != null)
    .map((r) => [Number(r.units), Number(r.plans[plan])])
    .sort((a, b) => a[0] - b[0]);
  if (!pts.length) return null;
  if (vol <= pts[0][0]) return pts[0][1];
  if (vol >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 1; i < pts.length; i++) {
    if (vol <= pts[i][0]) {
      const [x0, y0] = pts[i - 1], [x1, y1] = pts[i];
      return x1 === x0 ? y0 : y0 + (y1 - y0) * (vol - x0) / (x1 - x0);
    }
  }
  return pts[pts.length - 1][1];
}

// ── diff dvou cenových snapshotů ────────────────────────────────────────────
function diffPrices(vendor, oldP, newP) {
  const changes = [];
  if (!oldP) return changes;

  // BILLING diff (mimo cenu): zahrnuté kvóty, limity, AI tokeny, overage A
  // PRAVIDLA účtování — zachycené jako kurátované billing-řádky. Pokryje díru,
  // kterou cenový diff nevidí (Make "operations→credits", změna included quóty,
  // nový limit workflows…). Stabilní (0 šumu ověřeno) → smí spustit alarm.
  const oldBL = oldP.billingLines, newBL = newP.billingLines;
  if (Array.isArray(oldBL) && Array.isArray(newBL)) {
    const oldSet = new Set(oldBL), newSet = new Set(newBL);
    const added = newBL.filter((l) => !oldSet.has(l));
    const removed = oldBL.filter((l) => !newSet.has(l));
    for (const l of removed) changes.push({ vendor, kind: "billing", change: "removed", line: l, desc: `${vendor}: billing řádek ZMIZEL → "${l}"` });
    for (const l of added) changes.push({ vendor, kind: "billing", change: "added", line: l, desc: `${vendor}: billing řádek PŘIBYL → "${l}"` });
  }

  const model = newP.model || (newP.monthly ? "slider" : "fixed");
  if (model === "fixed") {
    const a = JSON.stringify(oldP.listedPrices || []);
    const b = JSON.stringify(newP.listedPrices || []);
    if (a !== b) changes.push({ vendor, kind: "listedPrices", old: oldP.listedPrices, neu: newP.listedPrices, desc: `${vendor}: ceník fixních plánů se změnil → ${b}` });
    return changes;
  }
  if (model === "dropdown-volume") {
    // n8n: porovnej cenu (EUR) per (billing, dropdown, units).
    for (const billing of ["monthly", "annually"]) {
      const oB = (oldP[billing] || {}), nB = (newP[billing] || {});
      if (oB.starter !== nB.starter) changes.push({ vendor, billing, plan: "Starter", old: oB.starter, neu: nB.starter, desc: `n8n Starter (${billing}): €${oB.starter} → €${nB.starter}` });
      for (let di = 0; di < (nB.dropdowns || []).length; di++) {
        const nd = nB.dropdowns[di], od = (oB.dropdowns || [])[di];
        if (!od) continue;
        const oMap = Object.fromEntries(od.options.map((o) => [o.units, o.eur]));
        for (const o of nd.options) {
          if (oMap[o.units] !== undefined && oMap[o.units] !== o.eur) {
            changes.push({ vendor, billing, dropdown: nd.label, units: o.units, old: oMap[o.units], neu: o.eur, desc: `n8n ${nd.label} @${o.units} exec (${billing}): €${oMap[o.units]} → €${o.eur}` });
          }
        }
      }
    }
    return changes;
  }
  if (model === "per-credit-bands") {
    // Pipedream: hustý sweep dává proměnlivý POČET pásem (15 vs 16) i drobný jitter
    // hranic mezi běhy → diff podle raw struktury byl ŠUM (falešný "bandStructure"
    // alarm). Robustní signál = efektivní $/credit na FIXNÍCH probe objemech. Když
    // se sazba na probu nezmění, je to jen jitter pásem (žádný alarm). Když ano,
    // je to reálná cenová změna.
    const PROBES = [25000, 100000, 500000, 2000000, 8000000];
    const rateAt = (bands, c) => {
      for (const b of bands || []) { if (b.upTo === null || c <= b.upTo) return b.perCredit; }
      return (bands && bands.length) ? bands[bands.length - 1].perCredit : null;
    };
    for (const name of Object.keys(newP.plans || {})) {
      const nu = newP.plans[name], od = (oldP.plans || {})[name];
      if (!od) continue;
      // pojistka: starší snapshoty měly jiný formát pásem ({threshold} místo {upTo})
      // → neporovnatelné, NEhlásit jako změnu (jinak by migrace formátu = falešný alarm)
      const fmtOk = (b) => (b || []).length && b.every((x) => "upTo" in x);
      if (!fmtOk(od.bands) || !fmtOk(nu.bands)) continue;
      if (od.base !== nu.base) changes.push({ vendor, plan: name, kind: "base", old: od.base, neu: nu.base, desc: `Pipedream ${name}: základ plánu $${od.base} → $${nu.base}/mo` });
      for (const probe of PROBES) {
        const o = rateAt(od.bands, probe), n = rateAt(nu.bands, probe);
        if (o != null && n != null && o !== n) {
          changes.push({ vendor, plan: name, kind: "perCredit", atCredits: probe, old: o, neu: n, desc: `Pipedream ${name}: sazba @${probe.toLocaleString()} kreditů $${o} → $${n}/credit` });
        }
      }
    }
    return changes;
  }
  // slider (make, zapier): diff na FIXNÍCH probe objemech (interpolace) + detekce
  // uniform-shiftu. Raw řádky jitterují (slider pozice) a flapují (chybné čtení
  // billing toggle → CELÁ matice se posune ~konstantou). Probe body + uniform-shift
  // collapse → konec ~90% šumu (ověřeno: make 25→26 z 84 změn na 1).
  const probes = SLIDER_PROBES[vendor] || [1000, 5000, 20000, 100000];
  for (const interval of ["monthly", "annually"]) {
    const oldRows = oldP[interval] || [], newRows = newP[interval] || [];
    if (!oldRows.length || !newRows.length) continue;
    const plans = [...new Set(newRows.flatMap((r) => Object.keys(r.plans || {})))];
    const pts = []; // {plan, vol, o, n, ratio} — body, co se reálně hnuly nad epsilon
    for (const plan of plans) {
      for (const vol of probes) {
        const o = priceAtVolume(oldRows, plan, vol), n = priceAtVolume(newRows, plan, vol);
        if (o == null || n == null || o <= 0 || n <= 0) continue;
        if (Math.abs(o - n) > Math.max(0.5, 0.02 * o)) pts.push({ plan, vol, o, n, ratio: n / o });
      }
    }
    if (!pts.length) continue;
    // uniform-shift: většina probe bodů se hnula STEJNÝM poměrem ≠ 1 → billing-toggle/
    // state misread, ne reálná cenová změna. Collapse do JEDNÉ poznámky (neitemizuj).
    const ratios = pts.map((p) => p.ratio).sort((a, b) => a - b);
    const med = ratios[Math.floor(ratios.length / 2)];
    const uniform = pts.length >= Math.min(3, probes.length) &&
      ratios.every((r) => Math.abs(r - med) < 0.05 * med) && Math.abs(med - 1) > 0.05;
    if (uniform) {
      changes.push({ vendor, interval, kind: "uniform-shift", ratio: _r2(med),
        desc: `${vendor} (${interval}): celá cenová matice se posunula ~${med.toFixed(2)}× (uniformně) — OVĚŘ: skoro jistě chybné čtení billing toggle / stavu stránky; reálné uniformní zdražení je vzácné. Neitemizováno (1 ověření místo ${pts.length} falešných delt).` });
    } else {
      for (const c of pts) {
        changes.push({ vendor, interval, units: c.vol, plan: c.plan, old: _r2(c.o), neu: _r2(c.n),
          desc: `${vendor} ${c.plan} @${c.vol.toLocaleString()} (${interval}): $${_r2(c.o)} → $${_r2(c.n)}` });
      }
    }
  }
  return changes;
}

// Scrape s RETRY proti dočasnému bot-wallu (CI datacenter IP → vendor WAF občas
// vrátí krátkou/prázdnou stránku → scraper hodí "nenalezeno"). 3 pokusy s
// narůstající prodlevou. Když i pak selže, runner to ošetří jako "blocked"
// (bot-wall = neznámý stav, NE chyba dat) → WARN, neshazuje exit.
async function scrapeVendorRetry(v, attempts = 3) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    if (i) await new Promise(r => setTimeout(r, 3000 * i));
    try { return await scrapeVendor(v); }
    catch (e) { lastErr = e; }
  }
  throw lastErr;
}

// export pro unit testy (diff logika bez scrapingu); IIFE runner běží jen při
// přímém spuštění (node price-audit.js), ne při require z testu.
if (require.main !== module) {
  module.exports = { diffPrices, extractBillingLines };
}

// EUR→USD kurz z free API (open.er-api.com) → automation/data/fx.json. n8n účtuje
// v EUR; build z fx.json převádí na USD. Selže-li (lokální TLS / offline), ponechá
// stávající fx.json (graceful). V CI (node fetch funguje) drží kurz aktuální.
async function refreshFx() {
  try {
    const r = await fetch("https://open.er-api.com/v6/latest/EUR", { headers: { "User-Agent": "wizardcost-fx" } });
    const d = await r.json();
    const eurUsd = d && d.rates && d.rates.USD;        // EUR→USD
    if (!eurUsd) throw new Error("no USD rate");
    const eurCzk = d.rates.CZK;                         // EUR→CZK (pro USD→CZK přepočet)
    const r4 = (x) => Math.round(x * 1e4) / 1e4;
    const out = {
      _note: "EUR→USD FX (free API). Aktualizuje denní audit. Build převádí n8n (EUR)→USD.",
      eur_usd: r4(eurUsd), date: d.time_last_update_utc || "",
      source: "open.er-api.com", fetchedAt: new Date().toISOString(),
      // USD→X multiplikátory pro on-site měnový přepínač (display only, USD = zdroj pravdy).
      // Build injektuje window.AC_FX. Drží se aktuální díky tomuto dennímu auditu.
      display_rates: {
        _note: "USD→X pro měnový přepínač. Konverze = orientační, ne fakturovaná částka.",
        usd: 1,
        eur: r4(1 / eurUsd),                            // USD→EUR = 1/(EUR→USD)
        czk: eurCzk ? r4(eurCzk / eurUsd) : 21.1,       // USD→CZK = (EUR→CZK)/(EUR→USD)
        date: d.time_last_update_utc || "",
      },
    };
    fs.writeFileSync(path.join(REPO, "automation", "data", "fx.json"), JSON.stringify(out, null, 2) + "\n", "utf8");
    console.log(`💱 FX aktualizováno: 1 EUR = ${out.eur_usd} USD · USD→EUR ${out.display_rates.eur} · USD→CZK ${out.display_rates.czk}`);
  } catch (e) { console.log(`💱 FX fetch přeskočen (ponechán starý kurz): ${(e.message || e).toString().slice(0, 60)}`); }
}

// ── runner ───────────────────────────────────────────────────────────────────
async function main() {
  const args = process.argv.slice(2).filter((a) => !a.startsWith("--"));
  const targets = args.length ? args : Object.keys(VENDORS);
  fs.mkdirSync(AUDIT_DIR, { recursive: true });
  await refreshFx();
  const allChanges = [];
  let failures = 0;   // skutečné chyby — shodí exit 1
  let blocked = 0;    // bot-wall po retry — jen WARN, neshazuje exit

  for (const v of targets) {
    if (!VENDORS[v]) { console.error(`✗ neznámý vendor: ${v}`); failures++; continue; }
    process.stdout.write(`→ ${v} … `);
    try {
      const prev = NO_DIFF ? null : previousSnapshot(v);
      const { html, prices, shot } = await scrapeVendorRetry(v);
      const dir = vendorDir(v);
      // normalizovaná cenová data — vždy (malé, 24 KB/den celkem)
      const snap = { vendor: v, scrapedAt: new Date().toISOString(), url: VENDORS[v].url, ...prices };
      fs.writeFileSync(path.join(dir, `${TODAY}.json`), JSON.stringify(snap, null, 2) + "\n", "utf8");
      // diff proti předchozímu snapshotu
      let changed = [];
      if (prev) {
        changed = diffPrices(v, prev.data, prices);
        allChanges.push(...changed);
      }
      // syrové HTML jen když je co dokazovat: poprvé (prev===null) nebo při změně.
      // Gzipnuté → ~10× menší. Běžné neměnné dny repo nezatěžují.
      let htmlNote = "HTML přeskočeno (beze změn)";
      if (!prev || changed.length) {
        const gz = zlib.gzipSync(Buffer.from(html, "utf8"));
        fs.writeFileSync(path.join(dir, `${TODAY}.html.gz`), gz);
        htmlNote = `HTML uloženo ${Math.round(gz.length / 1024)} KB gz`;
        // PNG ceníku vendora = vizuální důkaz pro PR (starý=předchozí snapshot, nový=dnešní)
        if (shot) { fs.writeFileSync(path.join(dir, `${TODAY}.png`), shot); htmlNote += ` + PNG`; }
      }
      console.log(`OK (${htmlNote} · ${changed.length} změn vs ${prev ? prev.date : "—"})`);
    } catch (e) {
      // bot-wall signatury: krátká stránka, HTTP 403/429/503, timeout, "nenalezeno"
      // = neznámý stav z CI IP, ne chyba dat → WARN (neshodí exit). Předchozí
      // snapshot zůstává platný; reálný drift se chytí, až stránka projde.
      const msg = e.message || String(e);
      const isBotWall = /bot|403|429|503|timeout|Timeout|krátká|nenalezen|listbox|slider|matice nenalezena|žádné|options/i.test(msg);
      if (isBotWall) {
        console.log(`⚠ WARN (bot wall / nedostupné po retry, ne změna ceny): ${msg.slice(0, 80)}`);
        blocked++;
      } else {
        console.log(`SELHALO: ${msg}`);
        failures++;
      }
    }
  }

  if (_browser) await _browser.close();

  // change report + history (pro grafy)
  if (!NO_DIFF) {
    const billingChanges = allChanges.filter((c) => c.kind === "billing").length;
    const priceChanges = allChanges.length - billingChanges;
    const report = {
      date: TODAY, generatedAt: new Date().toISOString(),
      changeCount: allChanges.length, priceChanges, billingChanges,
      changes: allChanges,
    };
    fs.writeFileSync(path.join(AUDIT_DIR, `changes-${TODAY}.json`), JSON.stringify(report, null, 2) + "\n", "utf8");
    if (allChanges.length) {
      const line = allChanges.map((c) => JSON.stringify({ d: TODAY, ...c })).join("\n") + "\n";
      fs.appendFileSync(path.join(AUDIT_DIR, "price-history.jsonl"), line, "utf8");
    }
    console.log(`\n📋 ${allChanges.length} změn (${priceChanges} cenových, ${billingChanges} billing) → audit/changes-${TODAY}.json`);
    // čitelný výpis CO se mění (desc) — toto vidí owner v CI logu / mailu
    for (const c of allChanges) console.log(`   • ${c.desc || JSON.stringify(c)}`);
  }
  if (blocked) console.log(`⚠ ${blocked} vendor(ů) nedostupných (bot wall / CI IP) — neověřeno, ne fail.`);
  // exit 1 JEN při skutečné chybě. Bot-wall (blocked) = exit 0 → cron nekřičí
  // falešně. Když vendor zítra projde, audit doběhne normálně.
  process.exit(failures ? 1 : 0);
}

if (require.main === module) main();
