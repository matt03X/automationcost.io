#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""features_registry.py — canonical feature normalisation across the 5 automation
tools + build of the DATA:FEATURES block for home-v6 (feature-constraint filter).

Marketing duplicates (each vendor names the same thing differently) are mapped to
ONE canonical name. Per canonical feature we resolve, per tool, the CHEAPEST plan
TIER that includes it (from automation/data/features/<vendor>/*.json matrices),
then join that tier to the tools.json pricing plans via per-tool tier ordinals.

Output (consumed by build_home_v6 -> DATA:FEATURES in home-v6.html):
  A_FEAT_GROUPS : [{group, items:[{name, tools:[slug,...]}]}]   (modal display)
  A_FEAT_REQ    : { canonicalName: { slug: tierOrdinal } }       (min tier needed)
  A_PLAN_TIER   : { slug: { planName: tierOrdinal } }            (plan -> tier)
  A_TIER_NAME   : { slug: [tierName,...] }                       (ordinal -> name)
  A_ENT_ORD     : { slug: enterpriseOrdinal }                    (contact-sales tier)
"""
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEAT_DIR = ROOT / "automation" / "data" / "features"
TOOLS = ROOT / "automation" / "data" / "tools.json"

# matrix tier columns, cheapest -> priciest (ordinal = index). Enterprise = last.
TIER_ORDER = {
    "zapier": ["Free", "Professional", "Team", "Enterprise"],
    "make": ["Free", "Core", "Pro", "Teams", "Enterprise"],
    "n8n": ["Community", "Starter", "Pro", "Business", "Enterprise"],
    "pipedream": ["Basic", "Advanced", "Connect", "Business"],
    "activepieces": ["Standard", "Ultimate", "Embed"],
}
# tools.json plan.name -> matrix tier (substring match, lowercased). Explicit
# fallbacks where the pricing plan name doesn't contain the tier word.
PLAN_TIER_EXPLICIT = {
    "n8n": {"self-hosted": "Community", "cloud starter": "Starter", "cloud pro": "Pro",
            "business": "Business", "cloud enterprise": "Enterprise"},
}

# canonical registry: (group, [(canonicalName, {slug:[raw matrix feature strings]})]).
# raw strings matched case-insensitively + stripped against matrix feature names.
CANONICAL = [
    ("Security & compliance", [
        ("Single sign-on (SSO / SAML)", {
            "zapier": ["SAML single sign-on (SSO)"], "make": ["Company single sign-on (SSO)"],
            "n8n": ["SSO SAML and LDAP"], "pipedream": ["Single Sign-On (SSO)"], "activepieces": ["SSO"]}),
        ("Enforce two-factor auth (2FA)", {
            "make": ["Two-factor authentication enforcement"], "n8n": ["Enforce 2FA across the instance"],
            "pipedream": ["Require 2FA"]}),
        ("User provisioning (SCIM)", {
            "zapier": ["User provisioning (SCIM)"], "pipedream": ["User provisioning (SCIM)"]}),
        ("Audit log", {
            "zapier": ["Audit log"], "make": ["Audit logs"], "n8n": ["Audit logging"]}),
        ("HIPAA / security compliance", {
            "make": ["Information security compliance support"], "pipedream": ["HIPAA"]}),
        ("External secret store", {"n8n": ["External secret store integration"]}),
        ("Static / dedicated IP", {
            "zapier": ["Static IP"], "pipedream": ["Shared static IP for secure database queries", "Unique egress IPs"]}),
        ("Private networking (VPC)", {
            "pipedream": ["Virtual Private Clouds (VPCs)", "VPC peering"]}),
        ("Custom data retention", {
            "zapier": ["Custom data retention"], "pipedream": ["Data retention controls"]}),
        ("Restrict login methods", {
            "zapier": ["App restrictions", "Action restrictions"], "pipedream": ["Restrict Login Methods"]}),
    ]),
    ("Admin & governance", [
        ("Role-based access control (RBAC)", {
            "make": ["Teams and team roles"], "n8n": ["Project admins", "Project editors", "Project viewers", "Instance admins"],
            "pipedream": ["Access controls for projects", "Access controls for connected accounts"],
            "activepieces": ["Custom RBAC"]}),
        ("Folder / project permissions", {
            "zapier": ["Folder permissions"], "n8n": ["Project admins"]}),
        ("Approval workflows", {"zapier": ["Approval requests"]}),
        ("Advanced admin controls", {
            "zapier": ["Advanced admin permissions", "Super Admin", "Owner access"]}),
        ("Domain capture / claim", {
            "zapier": ["Domain capture"], "make": ["Domain claim"]}),
    ]),
    ("Collaboration & versioning", [
        ("Shared workspace / connections", {
            "zapier": ["Shared app connections", "Shared Zaps"]}),
        ("Git / version control", {
            "n8n": ["Version control using Git"], "pipedream": ["Bi-Directional GitHub Sync", "Merge from GitHub", "Create Pull Requests"]}),
        ("Develop in branches", {"pipedream": ["Develop in branches", "Edit locally"]}),
    ]),
    ("Analytics & monitoring", [
        ("Analytics dashboard", {
            "zapier": ["Analytics"], "make": ["Analytics Dashboard"],
            "n8n": ["Dashboard with evolution over time", "Table with workflow metrics and sorting feature"]}),
        ("Search executions by data", {
            "make": ["Full-text execution log search"], "n8n": ["Search executions by the data they contain"]}),
        ("Stream logs externally (Datadog)", {"n8n": ["Stream logs to external services (e.g. Datadog)"]}),
        ("Observability API", {"zapier": ["Observability API"]}),
    ]),
    ("Advanced execution", [
        ("Concurrency / rate controls", {
            "n8n": ["Queue mode (Multiple instances)"], "pipedream": ["Concurrency controls", "Execution rate controls"]}),
        ("Queue mode / workers", {"n8n": ["Queue mode (Multiple instances)", "Worker view"]}),
        ("Custom functions / code app", {
            "make": ["Custom functions"], "pipedream": ["Custom component development"]}),
        ("Branching (if/else, parallel)", {
            "pipedream": ["If / Else Branching", "Switch Branching", "Parallel Branching"]}),
        ("Custom OAuth clients", {"pipedream": ["Use custom OAuth clients", "Custom OAuth clients"]}),
        ("On-prem / self-host", {"make": ["On-prem agent"], "n8n": ["Run bash scripts"]}),
        ("Enterprise apps access", {"make": ["Access to enterprise apps"], "pipedream": ["Premium apps"]}),
    ]),
    ("Support & commercial", [
        ("SLA-backed support", {"n8n": ["Dedicated support with SLA"], "pipedream": ["SLA"]}),
        ("Priority / premier support", {
            "zapier": ["Premier Support"], "pipedream": ["Dedicated Slack Connect channel", "Dedicated Success Engineer"]}),
        ("Technical account manager", {
            "zapier": ["Technical Account Manager**"], "pipedream": ["Dedicated Success Engineer"]}),
        ("Pay by invoice / custom contract", {
            "n8n": ["Pay by invoice", "Sales assisted procurement"],
            "pipedream": ["Pay by invoice", "Custom contract", "Custom invoicing"]}),
    ]),
]


def _load_matrices():
    mats = {}
    for slug in TIER_ORDER:
        files = sorted(glob.glob(str(FEAT_DIR / slug / "*.json")))
        if not files:
            continue
        d = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
        mx = d.get("matrix") or {}
        feat_tiers = {}  # stripped-lower feature name -> set(tier cols where true)
        for g in mx.get("groups", []):
            for r in g.get("rows", []):
                tiers = r.get("tiers", {})
                yes = {c for c, v in tiers.items() if v is True or (isinstance(v, str) and v.strip().lower() in ("yes", "included", "✓"))}
                if yes:
                    feat_tiers[r["feature"].strip().lower()] = yes
        mats[slug] = feat_tiers
    return mats


def _plan_tier_ordinal(slug, plan_name):
    order = TIER_ORDER[slug]
    nl = plan_name.lower()
    for key, tier in PLAN_TIER_EXPLICIT.get(slug, {}).items():
        if key in nl:
            return order.index(tier)
    # generic: longest tier word contained in the plan name
    for tier in sorted(order, key=len, reverse=True):
        if tier.lower() in nl:
            return order.index(tier)
    return None


def build_features_data():
    mats = _load_matrices()
    tools = json.loads(TOOLS.read_text(encoding="utf-8"))
    tool_by_slug = {t["slug"]: t for t in tools["tools"]}

    A_TIER_NAME = {s: TIER_ORDER[s] for s in mats}
    A_ENT_ORD = {s: len(TIER_ORDER[s]) - 1 for s in mats}

    # plan -> tier ordinal (only tools we have a matrix for)
    A_PLAN_TIER = {}
    for slug in mats:
        t = tool_by_slug.get(slug)
        if not t:
            continue
        pt = {}
        for p in t.get("plans", []):
            ordn = _plan_tier_ordinal(slug, p["name"])
            if ordn is not None:
                pt[p["name"]] = ordn
        A_PLAN_TIER[slug] = pt

    A_FEAT_REQ, groups_out = {}, []
    for group, items in CANONICAL:
        gi = []
        for canon, raws in items:
            req, have_tools = {}, []
            for slug, raw_list in raws.items():
                ft = mats.get(slug)
                if not ft:
                    continue
                tiers = set()
                for raw in raw_list:
                    tiers |= ft.get(raw.strip().lower(), set())
                if not tiers:
                    continue
                order = TIER_ORDER[slug]
                min_ord = min(order.index(c) for c in tiers if c in order)
                req[slug] = min_ord
                have_tools.append(slug)
            if req:
                A_FEAT_REQ[canon] = req
                gi.append({"name": canon, "tools": have_tools})
        if gi:
            groups_out.append({"group": group, "items": gi})

    return {"A_FEAT_GROUPS": groups_out, "A_FEAT_REQ": A_FEAT_REQ,
            "A_PLAN_TIER": A_PLAN_TIER, "A_TIER_NAME": A_TIER_NAME, "A_ENT_ORD": A_ENT_ORD}


if __name__ == "__main__":
    data = build_features_data()
    nfeat = sum(len(g["items"]) for g in data["A_FEAT_GROUPS"])
    print(f"canonical features: {nfeat} in {len(data['A_FEAT_GROUPS'])} groups")
    # sanity: Zapier audit-log + analytics tiers, plan->tier
    req = data["A_FEAT_REQ"]
    tn = data["A_TIER_NAME"]
    for f in ["Audit log", "Analytics dashboard", "Single sign-on (SSO / SAML)"]:
        r = req.get(f, {})
        pretty = {s: tn[s][o] for s, o in r.items()}
        print(f"  {f}: {pretty}")
    print("  zapier plan->tier:", data["A_PLAN_TIER"]["zapier"])
