# Security review — wizardcost.com (2026-06-11)

Audit přiměřený povaze projektu: statický web na GitHub Pages, žádný server,
žádná DB, žádný uživatelský vstup na backend. Hlavní aktiva: GitHub účet
(push = deploy), doména, affiliate příjem, demo účty na captury.

## Nálezy — kód a web (zkontrolováno, čisté)

- **XSS přes URL parametry:** calculator.html (share URL ?s/r/w/…) i
  compare.html (?tools/view) validují všechny hodnoty proti whitelistům
  (SHARE_SIZES/ROLES, WORKFLOWS, INTEGRATIONS, TOOLS) — žádná cesta
  k vložení neauditovaného řetězce do DOM. Čísla přes parseInt s clampem.
- **target="_blank":** všechny externí odkazy mají `rel="noopener"` (sweep
  napříč všemi HTML).
- **Tajemství v repu:** sken (api key/secret/password/Bearer/ghp_/AKIA)
  čistý. GA4 measurement ID je public-by-design. `assets/brand/logo.html`
  (1,45 MB brand kit export s embednutým editorem) — bez tajemství, jen
  hygiena; není v sitemapě.
- **HTTPS:** http→https redirect funguje (Enforce HTTPS na Pages zapnuto).

## Platformové limity (GitHub Pages) — vědomě akceptováno

- **Žádné vlastní security headers** (HSTS, CSP, X-Frame-Options,
  X-Content-Type-Options) — Pages je neumí. CSP přes `<meta>` by kvůli
  inline skriptům všude vyžadovala 'unsafe-inline' → divadlo, neimplementuje
  se. Plnohodnotné řešení = Cloudflare proxy před Pages (volitelné,
  rozhodnutí ownera — přidá headers, WAF, cache control; mění CDN chování).
- Risk akceptovatelný: web nemá přihlašování, formuláře ani cookies vlastní
  domény — XSS/clickjacking plocha minimální.

## Nálezy — okolí (vyřešeno / checklist ownera)

- **VYŘEŠENO: capture browser profil** s živými sessions demo účtů ležel
  v OneDrive-synchronizované složce → přesunut do
  `%LOCALAPPDATA%\wizardcost-capture-profile` (mimo cloud sync); skript
  aktualizován. Pozn.: OneDrive mohl stihnout sessions synchronizovat —
  demo účty jsou ale bez platebních dat a bez hodnoty (free tiery).
- **Checklist ownera (nelze ověřit/udělat za něj):**
  1. **2FA na GitHub účtu matt03X** — nejdůležitější jediný krok: push do
     masteru = deploy na wizardcost.com.
  2. **GitHub → Settings → Pages → verified domain** pro wizardcost.com
     (brání domain-takeoveru, kdyby Pages někdy byly vypnuté).
  3. **2FA u registrátora domény** a na Google účtu wizardcost.test@gmail.com.
  4. Volitelné: Cloudflare proxy (viz výše) — až bude řešen analytics token,
     dává smysl rozhodnout obojí najednou.
  5. Volitelné: `.well-known/security.txt` s kontaktem — vyžaduje zveřejnit
     e-mail (outward-facing, rozhodne owner).

## Co se NEdělá a proč

- SRI pro GA4/fonts: GA4 skript je dynamický (SRI nelze), Google Fonts CSS
  se mění per-UA (SRI nelze). Riziko = důvěra v Google, akceptováno.
- Branch protection na masteru: solo-developer workflow s lokálním CI
  (testy před push) — protection by blokovala vlastní flow bez přínosu,
  dokud nepřibude druhý přispěvatel s push právy.
