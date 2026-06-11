# Handoff — email capture „price-drop alerts" (výsledková stránka kalkulátoru)

**Datum:** 2026-06-11 · **Od:** Claude Design · **Pro:** Claude Code (engineering)

Jeden reusable blok, tři místa nasazení: kalkulátor (výsledky), changelog, vs-stránky
(generátor). Demo `email-capture-demo.html` ukazuje blok v kontextu konce výsledků +
vs-variantu copy + statické success/error stavy.

## Co kam zkopírovat
Vše mezi komentáři **`EMAILCAP:CSS|HTML|JS START/END`** v demu. Okolí (savings banner,
results-next-cta, demo-note popisky) jsou jen kontext — neshipovat.

- **calculator.html:** HTML blok mezi `#results-list`/no-results a `.results-next-cta`
  (přesně tam, kde sedí v demu).
- **changelog.html:** tentýž blok, stejná copy jako kalkulátor (krycí věta „All 7 tools
  covered" sedí i tam).
- **vs-stránky (generátor):** copy varianta s placeholdery —
  title: `Get an email when {A} or {B} changes pricing.`
  sub: bez „All 7 tools covered" (viz instance B v demu). Umístění: pod pros/cons,
  nad outbound CTA.

## Co musí doplnit engineering
1. **`action="REPLACE_ME_MAILERLITE_FORM_ACTION"`** → reálný MailerLite form endpoint
   (+ případná skrytá pole, která MailerLite vyžaduje — `name="fields[email]"` je
   jejich konvence, ověř proti konkrétnímu formu).
2. **Smazat DEMO-ONLY větev v JS** (simulace success při REPLACE_ME) — reálný POST
   přes fetch je v kódu připravený hned pod ní.
3. JSON-LD / metadata neřeším (build.py).

## Designová rozhodnutí (proč to vypadá takhle)
- **Tišší než Compare-plans CTA:** plain surface + border, žádný zelený gradient —
  primární akce stránky zůstává „Compare plans", capture je sekundární ask.
  Jediná zelená: mono label a tlačítko.
- **Žádný popup/sticky/incentive** (zadání ownera). Blok je v toku stránky.
- **Success stav:** formulář + disclosure zmizí, zůstane jen potvrzovací řádek
  „Check your inbox to confirm your subscription." — víc neslibovat (double opt-in
  a unsubscribe řeší MailerLite).
- **Disclosure:** „Price-change alerts only. No newsletter, unsubscribe anytime."
  + mikrolink Privacy. ⚠ **Čeká na finální OK ownera — bez něj nedeployovat.**
  Znění neměnit bez schválení.
- **Mobil:** ≤520px input a tlačítko pod sebou, tlačítko full-width min-height 44px;
  boční padding karty 18px.
- **A11y:** sr-only label, `aria-live="polite"` na stavové hlášce, viditelný focus
  ring na inputu.

## Copy (zdroj pravdy)
| místo | title | sub |
|---|---|---|
| calculator + changelog | Get an email when any of these tools changes its pricing. | Every change is verified by hand and published to the changelog — you get one email per confirmed change. All 7 tools covered. |
| vs-stránky | Get an email when {A} or {B} changes pricing. | Every change is verified by hand and published to the changelog — you get one email per confirmed change. |

Časový slib („same day") vypuštěn po zpětné vazbě engineeringu (2026-06-11):
pipeline je review-based (týdenní scraper + ruční ověření, rozesílka samostatný krok
po deployi). „One email per confirmed change" je pravdivé bez ohledu na timing.
Disclosure text schválen ownerem i designem — finální znění, neměnit.
