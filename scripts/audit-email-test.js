// JEDNORÁZOVÝ TEST e-mailového řetězce (detekce změny → fail jobu → mail ownerovi).
// NEZAPISUJE NIC do automation/data — reálná audit data se nemůžou dotknout.
// Použije REÁLNOU diffPrices() na SYNTETICKÝCH datech (require nespustí scraper
// díky require.main guardu v price-audit.js) → ověří i nové "co se mění" desc.
// Vloží 2 vymyšlené změny (1 billing + 1 cena), obě označené [TEST]. exit 1 =
// GitHub pošle mail. Po ověření se tenhle soubor + workflow + trigger smažou.
const { diffPrices } = require("./price-audit.js");

const changes = [];

// 1) BILLING změna (nové sledování pravidel účtování)
changes.push(...diffPrices(
  "make",
  { model: "slider", monthly: [], annually: [], billingLines: ["10 active workflows"] },
  { model: "slider", monthly: [], annually: [], billingLines: ["10 active workflows", "[TEST] 5 credits per 1 sec of code execution time"] },
));

// 2) CENOVÁ změna (klasický alarm)
changes.push(...diffPrices(
  "zapier",
  { model: "slider", monthly: [{ units: 2000, plans: { "Professional (TEST)": 73.5 } }], annually: [], billingLines: [] },
  { model: "slider", monthly: [{ units: 2000, plans: { "Professional (TEST)": 80 } }], annually: [], billingLines: [] },
));

// každý desc jasně označit [TEST], ať je v mailu nezaměnitelné že je to zkouška
const lines = changes.map((c) => `[TEST] ${c.desc || JSON.stringify(c)}`);

console.log(`📧 TEST e-mailového alarmu — ${changes.length} vymyšlených změn (žádná reálná data se nezměnila):`);
for (const l of lines) console.log(`   • ${l}`);

// zapsat do step summary (= tělo, které owner uvidí v notifikaci/CI)
const sum = process.env.GITHUB_STEP_SUMMARY;
if (sum) {
  const fs = require("fs");
  const md = [
    "## 📧 TEST e-mailového alarmu (žádná reálná data nezměněna)",
    "",
    "Tohle je úmyslná zkouška, jestli ti dorazí mail. Vendoři nic nezměnili.",
    "",
    "**Co by alarm hlásil:**",
    ...lines.map((l) => `- ${l}`),
    "",
    "_Po ověření se test workflow + skript smažou; audit data zůstávají beze změny._",
    "",
  ].join("\n");
  fs.appendFileSync(sum, md + "\n");
}

// exit 1 → job selže → GitHub pošle mail ownerovi (stejný kanál jako reálný alarm)
process.exit(changes.length ? 1 : 0);
