// Denní hlídač cen (GitHub Actions cron + lokálně) — NÍZKOŠUMOVÝ sentinel check.
//
// Princip: pro každý vendor držíme "sentinely" = přesné cenové řetězce, které
// na oficiálním ceníku MUSÍ být, dokud jsou naše data (tools.json) aktuální.
// Vendor změní cenu → sentinel zmizí → exit 1 → GitHub pošle ownerovi mail o failu.
// Změny marketingových textů sentinely nezasáhnou → žádné plané poplachy.
//
// Co sentinely NEchytí: nové plány (nic nezmizí) → kryje měsíční deep audit
// calc-test/verify-pricing-live.js. Verdikt a oprava dat = vždy člověk.
//
// PRAVIDLO: při každé cenové revizi tools.json aktualizuj i sentinely níže
// (jinak druhý den přijde falešný poplach). Viz CLAUDE.md.
//
// Spuštění: node scripts/price-watch.js  (CI: NODE_PATH na playwright instalaci)
"use strict";
const path = require("path");
let chromium;
try { ({ chromium } = require("playwright")); }
catch { ({ chromium } = require(path.resolve(__dirname, "../../../calc-test/node_modules/playwright"))); }

// Sentinely odpovídají tools.json @ last_reviewed 2026-06-12 (revize cenova-revize-2026-06-12).
// `expect` = regexy, které v normalizovaném textu (whitespace → mezera) musí být.
// `forbid` = regexy, které tam být NESMÍ (vendor začal publikovat něco, co nevedeme).
const WATCH = [
  {
    slug: "zapier", url: "https://zapier.com/pricing",
    expect: [/\$0\s*\/mo/, /19[.,]99/, /\$69\s*\/mo/, /100 tasks/i],
  },
  {
    slug: "make", url: "https://www.make.com/en/pricing",
    expect: [/\$\s?0\s*\/mo/, /\$\s?9\s*\/mo/, /\$\s?16\s*\/mo/, /\$\s?29\s*\/mo/,
             /1,000 credits/i, /10k credits/i],
  },
  {
    slug: "n8n", url: "https://n8n.io/pricing",
    // výchozí stav stránky = annual billing (20/50/667 €)
    expect: [/20\s?€/, /50\s?€/, /667\s?€/, /2\.5k\s*workflow executions/i,
             /40k\s*workflow executions/i, /unlimited users & workflows/i],
  },
  {
    slug: "pipedream", url: "https://pipedream.com/pricing",
    expect: [/\$0\/mo/, /\$29\/mo/, /\$49\/mo/, /\$99\/mo/, /100 credits/i,
             /Includes 2,000\s*credits/i, /Includes 10,000\s*credits/i],
  },
  {
    slug: "activepieces", url: "https://www.activepieces.com/pricing",
    expect: [/\$5/, /per active flow/i, /free active flows/i],
  },
  {
    slug: "automatisch", url: "https://automatisch.io/",
    // cena není veřejná (Cloud plán jsme 2026-06-12 odebrali) — kdyby se cena
    // znovu objevila, chceme to vědět → inverzní kontrola
    expect: [], forbid: [/[€$]\s?\d/],
  },
];

// Načte normalizovaný text stránky s RETRY proti dočasnému bot-wallu. CI běží
// z datacenter IP, kde vendoři (Cloudflare/WAF) občas servírují krátkou/prázdnou
// stránku. Vrací { text } při úspěchu, nebo { blocked, len } když i po retry
// vyjde podezřele krátká stránka (= neznámý stav, NE potvrzená změna ceny).
async function fetchText(ctx, url, { attempts = 3, minLen = 500 } = {}) {
  let lastLen = 0, lastErr = null;
  for (let i = 0; i < attempts; i++) {
    if (i) await new Promise(r => setTimeout(r, 2500 * i)); // narůstající prodleva
    const page = await ctx.newPage();
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForTimeout(6000);
      const text = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, " ");
      lastLen = text.length;
      if (text.length >= minLen) return { text };
    } catch (e) {
      lastErr = e.message.split("\n")[0];
    } finally {
      await page.close();
    }
  }
  return { blocked: true, len: lastLen, err: lastErr };
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1366, height: 900 },
    userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
  });
  const problems = [];   // skutečný DRIFT — shodí exit 1 (mail ownerovi)
  const warnings = [];   // bot-wall / fetch fail — jen hlásí, NEshodí exit
  const lines = [];
  for (const w of WATCH) {
    const res = await fetchText(ctx, w.url);
    if (res.blocked) {
      // bot-wall / nedorenderováno i po retry = NEZNÁMÝ stav, ne potvrzená změna
      // ceny → WARN, ne fail. Falešný poplach z CI datacenter IP nesmí budit owner.
      warnings.push(`${w.slug}: nedostupné po 3 pokusech (${res.len} znaků${res.err ? ", " + res.err : ""}) — bot wall / CI IP?`);
      lines.push(`WARN  ${w.slug} — bot wall / fetch (neověřeno, ne fail)`);
      continue;
    }
    const text = res.text;
    const missing = (w.expect || []).filter(re => !re.test(text));
    const present = (w.forbid || []).filter(re => re.test(text));
    if (missing.length || present.length) {
      for (const re of missing) problems.push(`${w.slug}: chybí sentinel ${re} — cena se nejspíš změnila`);
      for (const re of present) problems.push(`${w.slug}: objevil se zakázaný vzor ${re} — vendor publikuje něco, co nevedeme`);
      lines.push(`DRIFT ${w.slug} — ${missing.length} chybějících, ${present.length} zakázaných`);
    } else {
      lines.push(`OK    ${w.slug}`);
    }
  }
  await browser.close();

  console.log("price-watch " + new Date().toISOString());
  for (const l of lines) console.log("  " + l);
  if (problems.length) {
    console.log("\nPROBLÉMY (cenový drift):");
    for (const p of problems) console.log("  · " + p);
    console.log("\nDalší krok: node calc-test/verify-pricing-live.js <slug> → ověřit, pak revize tools.json (commit dat PŘED buildem).");
  } else if (warnings.length) {
    console.log("\nVarování (neověřeno, NE změna ceny — žádná akce nutná):");
    for (const w of warnings) console.log("  ⚠ " + w);
  } else {
    console.log("\nVšechny ceníky odpovídají tools.json sentinelům.");
  }
  if (process.env.GITHUB_STEP_SUMMARY) {
    const summ = `## price-watch\n\n\`\`\`\n${lines.join("\n")}` +
      (problems.length ? "\n\nPROBLÉMY:\n" + problems.map(p => "· " + p).join("\n") : "") +
      (warnings.length ? "\n\nVAROVÁNÍ (ne fail):\n" + warnings.map(w => "⚠ " + w).join("\n") : "") +
      (!problems.length && !warnings.length ? "\nvše OK" : "") + "\n\`\`\`\n";
    require("fs").appendFileSync(process.env.GITHUB_STEP_SUMMARY, summ);
  }
  // exit 1 JEN při skutečném driftu na úspěšně načtené stránce. Bot-wall = exit 0.
  process.exit(problems.length ? 1 : 0);
})();
