#!/usr/bin/env python3
"""integration_counts.py — jediný zdroj pravdy pro POČTY integrací + jejich TYP.

Rozhodnutí ownera (migrace 2026-06): `integrations/index.json` je jediný zdroj pravdy
pro počty napříč webem a každé číslo se prezentuje **s typovým labelem** (různá metodika
per nástroj — n8n „official nodes" vs Node-RED „community modules" vs Zapier „app
connectors"). Komparace se NEpíše jako holé „X > Y" mezi nástroji s jinou bází.

Použití v rendererech:
    from integration_counts import count, label, same_basis
    label("zapier")            -> "9,725+ app connectors"
    label("n8n", plus=False)   -> "572 official nodes"
    label("make", with_type=False) -> "2,594+"
    same_basis("n8n","node-red")   -> False   (official nodes vs community modules)
"""
import functools
import json
from pathlib import Path

_IDX = Path(__file__).resolve().parent / "data" / "integrations" / "index.json"

# Typ počtu per nástroj — editorial, owner-tunable. Žije v kódu (NE v auto-generovaném
# counts.json, který přepisuje týdenní audit). build_integrations.py si to importuje a
# zrcadlí do generovaného index.json (aby to měl i client-side finder).
COUNT_TYPE = {
    "zapier": "app connectors",
    "make": "app connectors",
    "pipedream": "app connectors",
    "activepieces": "pieces",
    "n8n": "official nodes",
    "automatisch": "connectors",
    "node-red": "community modules",
}


@functools.lru_cache(maxsize=1)
def _idx() -> dict:
    return json.loads(_IDX.read_text(encoding="utf-8"))


def count(slug: str) -> int:
    """Počet integrací nástroje z kanonické matice (index.json -> counts)."""
    return int(_idx()["counts"][slug])


def count_type(slug: str) -> str:
    """Typ počtu (label). Z index.json.count_types, fallback na modulovou konstantu."""
    return _idx().get("count_types", {}).get(slug) or COUNT_TYPE.get(slug, "integrations")


def label(slug: str, plus: bool = True, with_type: bool = True) -> str:
    """Lidský label, např. „9,725+ app connectors"."""
    s = f"{count(slug):,}" + ("+" if plus else "")
    return f"{s} {count_type(slug)}" if with_type else s


def same_basis(a: str, b: str) -> bool:
    """True když mají oba nástroje stejnou metodiku počtu (lze férově srovnat „X > Y")."""
    return count_type(a) == count_type(b)
