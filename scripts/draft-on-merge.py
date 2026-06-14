#!/usr/bin/env python3
"""draft-on-merge.py — po mergi cenového PR vytvoří MailerLite DRAFT z NOVÝCH
alert položek (těch, jejichž GUID nebyl v alerts.xml předchozího commitu).

Dedup je BEZSTAVOVÝ přes git: GUID = "datum-tool-plán" (deterministický, viz
build _feed_xml), takže stačí porovnat aktuální feed s `git show HEAD~1:<feed>`.
Žádný stavový soubor, žádné smyčky.

NEODESÍLÁ — vytvoří jen draft. Owner ho pošle send tlačítkem (lidská brána pro
odchozí mail = stop-and-confirm). Token z env MAILERLITE_API_TOKEN (GitHub secret)
nebo fallback engine/.env (lokálně). Reusuje send_price_alerts (šablona, from, api).

Použití:
  python scripts/draft-on-merge.py                 # automation, vytvoří draft
  python scripts/draft-on-merge.py --site llm      # llm feed/skupina
  python scripts/draft-on-merge.py --dry-run       # jen vypíše nové položky
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import send_price_alerts as s  # noqa: E402


def feed_guids(xml_text: str) -> set[str]:
    if not (xml_text or "").strip():
        return set()
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return set()
    return {it.findtext("guid", "") for it in root.iter("item")}


def prev_committed(relpath: str) -> str:
    """Obsah souboru v předchozím commitu (HEAD~1), nebo "" když není."""
    try:
        r = subprocess.run(["git", "show", f"HEAD~1:{relpath}"],
                           capture_output=True, text=True, cwd=s.REPO)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", choices=sorted(s.SITES), default="automation")
    ap.add_argument("--dry-run", action="store_true", help="jen vypsat nové položky")
    args = ap.parse_args()
    site = s.SITES[args.site]
    feed: Path = site["feed"]
    if not feed.exists():
        print(f"Feed {feed.name} neexistuje — nic k draftu.")
        return 0

    relpath = str(feed.relative_to(s.REPO)).replace("\\", "/")
    old_guids = feed_guids(prev_committed(relpath))
    items = [i for i in s.load_alerts(feed) if i["guid"] not in old_guids]

    if not items:
        print("Žádné nové alert položky vs předchozí commit — žádný draft.")
        return 0

    print(f"Nové alert položky ({len(items)}):")
    for i in items:
        print(f"  · {i['title']}  [{i['meta']}]")
    if args.dry_run:
        print("(dry-run — draft se nevytváří)")
        return 0

    subj = s.subject(items, site["noun"])
    html = s.render(items, site)
    created = s.api("/campaigns", "POST", {
        "name": f"Price alert ({args.site}) — {subj}",
        "type": "regular",
        "groups": [s.group_id(site)],
        "emails": [{"subject": subj, "from_name": s.FROM_NAME, "from": s.FROM_EMAIL, "content": html}],
    })
    print(f"✅ DRAFT vytvořen: id={created['data']['id']}  from={s.FROM_EMAIL}  subject={subj!r}")
    print("   Owner: ťukni send tlačítko (WizardCost Alert) pro odeslání odběratelům.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
