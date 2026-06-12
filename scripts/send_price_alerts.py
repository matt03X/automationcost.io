#!/usr/bin/env python3
"""send_price_alerts.py — pošle email alert subscriberům po cenové revizi.

Součást revizního workflow (viz CLAUDE.md): po commitu změn a deployi spusť
    python scripts/send_price_alerts.py                 # automation, DRAFT (bezpečné)
    python scripts/send_price_alerts.py --site llm      # LLM feed/skupina
    python scripts/send_price_alerts.py --send          # draft rovnou odešle (instant)
    python scripts/send_price_alerts.py --dry-run       # jen vypíše, co by se poslalo

Zdroj položek: <site>/alerts.xml (JEN ceny + limity — slib "price-change alerts
only", slib je scoped per seznam/skupinu). Stav odeslaného drží per-site
scripts/.alerts-sent*.json (gitignored) přes GUIDy položek.

Šablona: scripts/email-template.html (design 2026-06-12) — klonuje se blok mezi
<!-- ITEMS:START --> a <!-- ITEMS:END --> s {title}/{meta} placeholdery. Pro llm
se použije email-template-llm.html, pokud existuje (dodá design — magenta
varianta); jinak sdílená šablona s přepsanou changelog URL.

Token: MAILERLITE_API_TOKEN z env, fallback engine/.env (mimo tohle repo).
NIKDY ho necommitovat. LLM skupina: env/engine/.env MAILERLITE_GROUP_LLM
(doplní owner po založení skupiny price-drop-alerts-llm).
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
SCRIPTS = Path(__file__).resolve().parent
ENGINE_ENV = REPO.parents[1] / "engine" / ".env"  # workspace layout: root/engine/.env

API = "https://connect.mailerlite.com/api"
FROM_EMAIL = "alerts@wizardcost.com"
FROM_NAME = "WizardCost"

AUTOMATION_CLOG = "https://wizardcost.com/automation/changelog.html"

SITES = {
    "automation": {
        "feed": REPO / "automation" / "alerts.xml",
        "state": SCRIPTS / ".alerts-sent.json",
        "template": SCRIPTS / "email-template.html",
        "group": "190009381054580705",  # price-drop-alerts
        "group_env": None,
        "noun": "tools",                 # subject: "2 tools changed their pricing"
        "changelog_url": AUTOMATION_CLOG,
    },
    "llm": {
        "feed": REPO / "llm" / "alerts.xml",
        "state": SCRIPTS / ".alerts-sent-llm.json",
        # llm variantu šablony dodá design; do té doby fallback na sdílenou
        "template": SCRIPTS / "email-template-llm.html",
        "template_fallback": SCRIPTS / "email-template.html",
        "group": None,                   # doplní owner: skupina price-drop-alerts-llm
        "group_env": "MAILERLITE_GROUP_LLM",
        "noun": "models",                # tituly llm feedu začínají názvem modelu
        "changelog_url": "https://wizardcost.com/llm/changelog.html",
    },
}

ITEMS_START = "<!-- ITEMS:START"
ITEMS_END = "<!-- ITEMS:END -->"


def _env_value(key: str) -> str:
    v = os.environ.get(key, "").strip()
    if not v and ENGINE_ENV.exists():
        for line in ENGINE_ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}="):
                v = line.split("=", 1)[1].strip()
                break
    return v


def token() -> str:
    t = _env_value("MAILERLITE_API_TOKEN")
    if not t:
        sys.exit("CHYBA: MAILERLITE_API_TOKEN nenalezen (env ani engine/.env).")
    return t


def group_id(site: dict) -> str:
    if site["group"]:
        return site["group"]
    g = _env_value(site["group_env"])
    if not g:
        sys.exit(f"CHYBA: skupina nenastavena — doplň {site['group_env']} do engine/.env "
                 "(owner: MailerLite → Subscribers → Groups → id skupiny price-drop-alerts-llm).")
    return g


def api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token()}",
                 "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def load_alerts(feed: Path) -> list[dict]:
    """Položky z alerts.xml: [{guid, title, meta}] od nejnovějších."""
    root = ET.parse(feed).getroot()
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


def render(items: list[dict], site: dict) -> str:
    tpl_path = site["template"]
    if not tpl_path.exists() and "template_fallback" in site:
        tpl_path = site["template_fallback"]
    tpl = tpl_path.read_text(encoding="utf-8")
    if site["changelog_url"] != AUTOMATION_CLOG:
        tpl = tpl.replace(AUTOMATION_CLOG, site["changelog_url"])
    start = tpl.index(ITEMS_START)
    block_start = tpl.index("-->", start) + 3
    end = tpl.index(ITEMS_END)
    block = tpl[block_start:end]
    rendered = "".join(
        block.replace("{title}", html_escape(i["title"])).replace("{meta}", html_escape(i["meta"]))
        for i in items)
    return tpl[:start] + rendered + tpl[end + len(ITEMS_END):]


def subject(items: list[dict], noun: str) -> str:
    # název nástroje/modelu = prefix titulku před první " — " (formát z build_feeds)
    names = []
    for i in items:
        name = i["title"].split(" — ")[0].strip()
        if name not in names:
            names.append(name)
    if len(names) == 1:
        return f"{names[0]} changed its pricing — verified"
    return f"{len(names)} {noun} changed their pricing — verified"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", choices=sorted(SITES), default="automation",
                    help="který feed/skupina (default automation)")
    ap.add_argument("--send", action="store_true", help="kampaň rovnou odeslat (jinak jen draft)")
    ap.add_argument("--dry-run", action="store_true", help="jen vypsat, nic nevytvářet")
    ap.add_argument("--include-sent", action="store_true",
                    help="ignorovat stav a vzít všechny položky feedu (testovací send)")
    args = ap.parse_args()
    site = SITES[args.site]

    state_path = site["state"]
    sent = set(json.loads(state_path.read_text(encoding="utf-8"))) if state_path.exists() else set()
    items = [i for i in load_alerts(site["feed"]) if args.include_sent or i["guid"] not in sent]
    if not items:
        print(f"Nic k odeslání — žádné nové položky v {site['feed'].name} ({args.site}).")
        return 0

    print(f"Položky ({len(items)}, site={args.site}):")
    for i in items:
        print(f"  · {i['title']}  [{i['meta']}]")
    subj = subject(items, site["noun"])
    print(f"Subject: {subj}")

    if args.dry_run:
        print("(dry-run — nic se nevytváří)")
        return 0

    html = render(items, site)
    created = api("/campaigns", "POST", {
        "name": f"Price alert ({args.site}) — {subj}",
        "type": "regular",
        "groups": [group_id(site)],
        "emails": [{"subject": subj, "from_name": FROM_NAME, "from": FROM_EMAIL, "content": html}],
    })
    cid = created["data"]["id"]
    print(f"Kampaň vytvořena: id={cid} (draft)")

    if args.send:
        api(f"/campaigns/{cid}/schedule", "POST", {"delivery": "instant"})
        print("ODESLÁNO (instant).")
        state_path.write_text(json.dumps(sorted(sent | {i['guid'] for i in items}), indent=1), encoding="utf-8")
        print(f"Stav zapsán: {state_path.name} ({len(items)} nových GUIDů)")
    else:
        print("Draft čeká v MailerLite — zkontroluj a pošli tam, nebo spusť znovu s --send.")
        print(f"POZOR: stav ({state_path.name}) se zapisuje až při --send.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
