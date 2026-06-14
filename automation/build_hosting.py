"""build_hosting.py — sdílená expanze hosting variant (Cloud / VPS / vlastní server).

KONTRAKT (zmražený — F/R/C i build.py na něm staví):

`expand_hosting_variants(tools) -> list[dict]` vezme syrový seznam toolů z
tools.json a self-hostovatelné tooly rozloží na 2–3 "variant tooly". Každý
variant je MĚLKÁ KOPIE původního toolu (všechna pole zachována kvůli enginu i
feature matici) s upravenými poli:

  slug:        "<base>" (cloud) | "<base>-vps" | "<base>-own"
  variantOf:   "<base>"  (pro seskupení variant jednoho nástroje na pricing str.)
  name:        zobrazované jméno ("n8n Cloud", "n8n (self-host · VPS)", …)
  hostingKind: "saas"  — nemá self-host (Make/Pipedream/Zapier), beze změny
               "cloud" — cloudová varianta self-hostovatelného nástroje
               "vps"   — self-host na pronajatém VPS (měsíční = selfHostHw.usd)
               "own"   — self-host na vlastním HW (měsíční = elektřina; +jednorázové HW)
  plans:       cloud → jen ne-selfHostOnly plány; vps/own → [Self-hosted plán]
  selfHostHw:  cloud/saas → None;  vps → původní tiery (usd=VPS);
               own → tiery s usd:=home (engine vrátí elektřinu), navíc home/hwOneOff/spec

MAPPING (dle cloudu): nástroj s cloudem (n8n, activepieces) → 3 varianty
(cloud+vps+own); bez cloudu (automatisch, node-red) → 2 (vps+own). Ne-self-host
(make/pipedream/zapier) → 1 (saas, beze změny).

CENA: spočítej přes engine — `_root_engine().cheapest_monthly(variant, runs, steps)`
(čte variant["plans"] + variant["selfHostHw"]). Pro "own" varianta vrátí měsíční
ELEKTŘINU. Jednorázové HW = `hw_tier_for(variant, runs)["hwOneOff"]` + `["spec"]`
(zobraz zvlášť, NEmíchat do měsíčního). Calculator NEexpanduj (řeší módy interně).
"""
from __future__ import annotations
import copy
import json
from pathlib import Path


def load_fx() -> float:
    """EUR→USD kurz z automation/data/fx.json (aktualizuje denní audit). Fallback 1.0."""
    try:
        p = Path(__file__).resolve().parent / "data" / "fx.json"
        return float(json.loads(p.read_text(encoding="utf-8")).get("eur_usd", 1.0))
    except Exception:
        return 1.0


def apply_fx(tools: list[dict], eur_usd: float | None = None) -> list[dict]:
    """Převede ceny EUR-účtujících toolů (currency=='EUR') na USD kurzem eur_usd.
    JEN cloud plány (ne selfHostOnly) a JEN monthlyUsd/annualUsd — self-host (VPS,
    elektřina, HW) jsou naše USD odhady, nemění se. Mutuje in-place; volej JEDNOU
    po načtení (jinak dvojí konverze). Idempotenci hlídá _fxApplied flag."""
    rate = eur_usd if eur_usd is not None else load_fx()
    for t in tools:
        if t.get("currency") != "EUR" or t.get("_fxApplied"):
            continue
        for p in t.get("plans", []):
            if p.get("selfHostOnly"):
                continue
            for k in ("monthlyUsd", "annualUsd"):
                if isinstance(p.get(k), (int, float)):
                    p[k] = round(p[k] * rate, 2)
        t["_fxApplied"] = True
    return tools


def cloud_plans(tool: dict) -> list[dict]:
    """Plány, které NEjsou výhradně self-host (= cloud/SaaS nabídka nástroje)."""
    return [p for p in tool.get("plans", []) if not p.get("selfHostOnly")]


def self_host_plan(tool: dict) -> dict | None:
    """První selfHostOnly plán (jednotný 'Self-hosted' řádek)."""
    for p in tool.get("plans", []):
        if p.get("selfHostOnly"):
            return p
    return None


def hw_tier_for(tool: dict, runs: int) -> dict | None:
    """selfHostHw tier pokrývající daný objem (první s upTo >= runs; jinak poslední)."""
    tiers = tool.get("selfHostHw") or []
    for t in tiers:
        if t.get("upTo") is None or runs <= t["upTo"]:
            return t
    return tiers[-1] if tiers else None


def _own_selfhosthw(tiers: list[dict]) -> list[dict]:
    """Pro 'own' variantu: usd := home (engine pak vrátí měsíční elektřinu).
    home/hwOneOff/spec zůstávají pro zobrazení (jednorázové HW + požadavky)."""
    out = []
    for t in tiers:
        c = dict(t)
        c["usd"] = t.get("home", t["usd"])  # měsíční = elektřina
        out.append(c)
    return out


def _variant(base: dict, *, slug: str, name: str, kind: str,
             plans: list[dict], selfhosthw) -> dict:
    v = copy.deepcopy(base)
    v["slug"] = slug
    v["variantOf"] = base["slug"]
    v["name"] = name
    v["hostingKind"] = kind
    v["plans"] = plans
    v["selfHostHw"] = selfhosthw
    v["selfHostable"] = kind in ("vps", "own")
    return v


def expand_hosting_variants(tools: list[dict]) -> list[dict]:
    """Viz KONTRAKT v hlavičce modulu."""
    out: list[dict] = []
    for t in tools:
        if not t.get("selfHostable") or not t.get("selfHostHw"):
            v = copy.deepcopy(t)
            v.setdefault("variantOf", t["slug"])
            v["hostingKind"] = "saas"
            out.append(v)
            continue

        base = t
        cl = cloud_plans(base)
        sh = self_host_plan(base)
        hw = base["selfHostHw"]
        name = base["name"]

        if cl:  # má cloud → cloudová varianta (drží base slug + pricing stránku)
            out.append(_variant(base, slug=base["slug"], name=f"{name} Cloud",
                                 kind="cloud", plans=cl, selfhosthw=None))
        if sh:
            out.append(_variant(base, slug=f'{base["slug"]}-vps',
                                 name=f"{name} (self-host · VPS)", kind="vps",
                                 plans=[sh], selfhosthw=hw))
            out.append(_variant(base, slug=f'{base["slug"]}-own',
                                 name=f"{name} (self-host · own server)", kind="own",
                                 plans=[sh], selfhosthw=_own_selfhosthw(hw)))
    return out
