# Design backlog — WizardCost (2026-06-11)

Zadání pro Claude Design. Handoff jako vždy: **balíček přes repo branch, ne chatem**
(chat přenos rozbíjí kódování — mojibake). Design nemá push práva do masteru;
integraci, head metadata a deploy dělá engineering. Pravidla repa: `../CLAUDE.md`.

---

## 1) BUG (priorita): mobil — obsah jde od kraje ke kraji, buttony se dotýkají hran displeje

**Nahlásil uživatel z iPhone SE 2020 (viewport 375×667).** Změřeno Playwrightem na 375px:

```
/  (root homepage)
  .btn-primary  "Try the Automation wizard"  left=0px  right=0px
  .btn-secondary "See all wizards ↓"          left=0px  right=0px
```

**Příčina:** `.hero` v root `index.html` má `padding: 104px 0 56px` (na ≤620px
`68px 0 40px`) — **nulový horizontální padding** — a `.hero-cta` na ≤520px přepíná na
`flex-direction: column; align-items: stretch`, takže CTA buttony sahají přesně na
hrany displeje. Boční padding `.wrap { padding: 0 18px }` (≤760px) se na hero
neaplikuje.

**Zadání:**
- Přidat hero sekci boční padding (≈18–20px) na mobilních šířkách, konzistentně
  se `.wrap`.
- Projít **celou root homepage na 375px** (ne jen hero) — stats řádek, demo karta,
  wizards grid, edge-row — a sjednotit minimální boční odsazení; nic interaktivního
  nesmí být blíž než ~16px od hrany.
- `/automation/` stránky jsou na 375px OK (`.wrap` padding funguje) — neřešit.
  Vodorovně scrollující nav-bottom je záměr, nechat být.
- Ověření: `calc-test/scout-mobile-edges.js` (375px sweep, musí vrátit „nic se
  nedotýká krajů" pro `/`).

## 2) Screenshoty nástrojů na homepage (desktop)

Nápad uživatele: ukázat **jak nástroje reálně vypadají** (UI n8n, Make, Zapier…)
podél root homepage na desktopu — vizuální důkaz, že srovnáváme skutečné produkty.

**Zadání:**
- Navrhnout sekci/galerii pro desktop (≥1024px); na mobilu skrýt nebo silně
  zredukovat (viz bod 1 — mobil už teď trpí hustotou).
- Obrázky: **vlastní screenshoty produktových UI nebo oficiální press/brand assety**
  — žádné fotky lidí, žádný stock (faceless brand). Pozor na trademark: logo +
  screenshot v review/srovnávacím kontextu je OK, nesmí to vypadat jako endorsement.
- Výkon: lazy-load, WebP/AVIF, žádný layout shift (rezervovat aspect-ratio).
  Homepage má LCP v hero — galerie nesmí soutěžit o bandwidth nad foldem.
- Dodat jako statické soubory v balíčku (`assets/…`) + HTML/CSS blok; integraci
  provede engineering.

---

*Stav repa: root homepage v2 + `/automation/` subsite, vše live na wizardcost.com.
Paralelně běží zadání vs-pages (branch `vs-pages`, `docs/vs-pages-brief.md`).*
