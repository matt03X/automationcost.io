# Handoff — HTML email šablona „price-drop alert" (MailerLite API kampaň)

**Datum:** 2026-06-12 · **Od:** Claude Design · **Pro:** Claude Code (engineering)

`email-template.html` — kompletní kampaňový HTML dle specu (plán C, custom HTML přes API).

## Plnění
- **`<!-- ITEMS:START --> … <!-- ITEMS:END -->`** — uvnitř jedna vzorová položka
  (celý `<tr>` blok s vnořenou tabulkou). Klonuj per záznam; divider je součástí
  položky (border-top), takže klonování dá oddělovače samo.
- **`{title}`** — s oddělovači tisíců („2,000 → 750", jednotku neopakovat v hodnotách).
- **`{meta}`** — „Price change · verified June 11, 2026" / „Plan limit change · …".
  Formát data srovnej s changelog stránkou (jednotnost po prokliku).
- **`{$unsubscribe}`** — MailerLite merge tag na místě, nech beze změny.
- Sender řádek je statický „WizardCost · Czech Republic"; v komentáři je
  alternativa `{$account_address}`, kdyby měl jít z účtu.
- Subject + preheader řešíš přes API; v šabloně je skrytý fallback preheader
  („We only email when something changes…").

## Technika
- Čistě tabulkový layout, vše kritické inline, `role="presentation"`, 600px,
  mobilní fallback přes jedinou media query (full-width + 20px boční padding).
- Žádná čistá černá/bílá; `color-scheme: dark` meta + CSS hint — Gmail tmavý
  email nepřebarvuje, Outlook dostává bgcolor atributy.
- Tlačítko = padded `<td bgcolor>` + block link (bez VML; Outlook desktop ho
  vykreslí hranaté, což je přijatelná degradace).
- Border-radius karty ignoruje Outlook — taky OK degradace.
- Žádné obrázky, žádné webfonty (Arial/Helvetica stack) → nic k blokování,
  nulový dopad na spam skóre z assetů.

## Před ostrým odesláním
1. Test kampaň na vlastní schránky: Gmail web + Gmail Android/iOS (light i dark),
   Outlook desktop, Seznam.cz (český kontext).
2. Zkontroluj, že `{$unsubscribe}` se v testu nahradil reálným odkazem —
   v custom HTML kampaních je povinný, MailerLite bez něj odmítne odeslat.
3. Položky: jen ceny + limity plánů (alerts.xml filtr) — pravidlo trvá.
