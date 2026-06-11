#!/usr/bin/env python3
"""send_price_alerts.py — pošle email alert subscriberům po cenové revizi.

Součást revizního workflow (viz CLAUDE.md): po commitu změn a deployi spusť
    python scripts/send_price_alerts.py            # vytvoří DRAFT kampaň (bezpečné)
    python scripts/send_price_alerts.py --send     # draft rovnou odešle (instant)
    python scripts/send_price_alerts.py --dry-run  # jen vypíše, co by se poslalo

Zdroj položek: automation/alerts.xml (JEN ceny + limity plánů — slib
"price-change alerts only"). Stav odeslaného drží scripts/.alerts-sent.json
(gitignored) přes GUIDy položek — co je v něm, se znovu neposílá.

Šablona: scripts/email-template.html (design 2026-06-12) — klonuje se blok
mezi <!-- ITEMS:START --> a <!-- ITEMS:END --> s {title}/{meta} placeholdery.

Token: MAILERLITE_API_TOKEN z env, fallback engine/.env (mimo tohle repo).
NIKDY ho necommitovat. Skupina price-drop-alerts id viz GROUP_ID.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALERTS_XML = REPO / "automation" / "alerts.xml"
TEMPLATE = Path(__file__).resolve().parent / "email-template.html"
STATE = Path(__file__).resolve().parent / ".alerts-sent.json"
ENGINE_ENV = REPO.parents[1] / "engine" / ".env"  # workspace layout: root/engine/.env

API = "https://connect.mailerlite.com/api"
GROUP_ID = "190009381054580705"  # price-drop-alerts
FROM_EMAIL = "alerts@wizardcost.com"
FROM_NAME = "WizardCost"

ITEMS_START = "<!-- ITEMS:START"
ITEMS_END = "<!-- ITEMS:END -->"


def token() -> str:
    t = os.environ.get("MAILERLITE_API_TOKEN", "").strip()
    if not t and ENGINE_ENV.exists():
        for line in ENGINE_ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith("MAILERLITE_API_TOKEN="):
                t = line.split("=", 1)[1].strip()
                break
    if not t:
        sys.exit("CHYBA: MAILERLITE_API_TOKEN nenalezen (env ani engine/.env).")
    return t


def api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token()}",
                 "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def load_alerts() -> list[dict]:
    """Položky z alerts.xml: [{guid, title, meta}] od nejnovějších."""
    root = ET.parse(ALERTS_XML).getroot()
    out = []
    for item in root.iter("item"):
        out.append({
            "guid": item.findtext("guid", ""),
            "title": item.findtext("title", ""),
            "meta": item.findtext("description", ""),
        })
    return out


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(items: list[dict]) -> str:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    start = tpl.index(ITEMS_START)
    block_start = tpl.index("-->", start) + 3
    end = tpl.index(ITEMS_END)
    block = tpl[block_start:end]
    rendered = "".join(
        block.replace("{title}", html_escape(i["title"])).replace("{meta}", html_escape(i["meta"]))
        for i in items)
    return tpl[:start] + rendered + tpl[end + len(ITEMS_END):]


def subject(items: list[dict]) -> str:
    # název nástroje = prefix titulku před první " — " (formát z build_feed)
    tools = []
    for i in items:
        name = i["title"].split(" — ")[0].strip()
        if name not in tools:
            tools.append(name)
    if len(tools) == 1:
        return f"{tools[0]} changed its pricing — verified"
    return f"{len(tools)} tools changed their pricing — verified"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="kampaň rovnou odeslat (jinak jen draft)")
    ap.add_argument("--dry-run", action="store_true", help="jen vypsat, nic nevytvářet")
    ap.add_argument("--include-sent", action="store_true",
                    help="ignorovat stav a vzít všechny položky feedu (testovací send)")
    args = ap.parse_args()

    sent = set(json.loads(STATE.read_text(encoding="utf-8"))) if STATE.exists() else set()
    items = [i for i in load_alerts() if args.include_sent or i["guid"] not in sent]
    if not items:
        print("Nic k odeslání — žádné nové položky v alerts.xml.")
        return 0

    print(f"Položky ({len(items)}):")
    for i in items:
        print(f"  · {i['title']}  [{i['meta']}]")
    subj = subject(items)
    print(f"Subject: {subj}")

    if args.dry_run:
        print("(dry-run — nic se nevytváří)")
        return 0

    html = render(items)
    created = api("/campaigns", "POST", {
        "name": f"Price alert — {subj}",
        "type": "regular",
        "groups": [GROUP_ID],
        "emails": [{"subject": subj, "from_name": FROM_NAME, "from": FROM_EMAIL, "content": html}],
    })
    cid = created["data"]["id"]
    print(f"Kampaň vytvořena: id={cid} (draft)")

    if args.send:
        api(f"/campaigns/{cid}/schedule", "POST", {"delivery": "instant"})
        print("ODESLÁNO (instant).")
        STATE.write_text(json.dumps(sorted(sent | {i['guid'] for i in items}), indent=1), encoding="utf-8")
        print(f"Stav zapsán: {STATE.name} ({len(items)} nových GUIDů)")
    else:
        print("Draft čeká v MailerLite — zkontroluj a pošli tam, nebo spusť znovu s --send.")
        print("POZOR: stav (.alerts-sent.json) se zapisuje až při --send.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
