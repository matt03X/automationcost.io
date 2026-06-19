"""Cloudflare konektor — stáhne Web Analytics (cookieless RUM) přes GraphQL.

Auth: Bearer API token. Env:
  - CLOUDFLARE_API_TOKEN  = token s právem Account Analytics:Read
  - CLOUDFLARE_ACCOUNT_ID = account tag (32 hex)
  - CLOUDFLARE_SITE_TAG   = Web Analytics site token (default = ten z beacon.min.js)

Vrací dict: pageviews celkem + top země / referrery / cesty / vývoj po dnech za 28 dní.
Pozn.: 'count' v RUM datasetu = page views. 'Visits' Cloudflare počítá zvlášť;
v1 reportujeme pageviews (to, co web reálně vidí). Core Web Vitals zvlášť níže.

POZNÁMKA k prvnímu běhu: GraphQL schéma RUM je citlivé na názvy polí. Když dostaneš
'errors', je to skoro jistě jiný název dimenze (countryName/refererHost/requestPath) —
doladíme spolu podle chybové hlášky.

Spuštění:      python scripts/marketing/cf_pull.py
Závislosti:    pip install requests
"""
from __future__ import annotations
import datetime
import json
import sys

import requests

from _common import env_value, require

GQL = "https://api.cloudflare.com/client/v4/graphql"

_QUERY = """
query ($acct: String!, $tag: String!, $start: Time!, $end: Time!) {
  viewer {
    accounts(filter: { accountTag: $acct }) {
      total: rumPageloadEventsAdaptiveGroups(
        limit: 1
        filter: { siteTag: $tag, datetime_geq: $start, datetime_leq: $end }
      ) { count }
      byCountry: rumPageloadEventsAdaptiveGroups(
        limit: 15, orderBy: [count_DESC]
        filter: { siteTag: $tag, datetime_geq: $start, datetime_leq: $end }
      ) { count dimensions { metric: countryName } }
      byReferer: rumPageloadEventsAdaptiveGroups(
        limit: 15, orderBy: [count_DESC]
        filter: { siteTag: $tag, datetime_geq: $start, datetime_leq: $end }
      ) { count dimensions { metric: refererHost } }
      byPath: rumPageloadEventsAdaptiveGroups(
        limit: 25, orderBy: [count_DESC]
        filter: { siteTag: $tag, datetime_geq: $start, datetime_leq: $end }
      ) { count dimensions { metric: requestPath } }
      byDate: rumPageloadEventsAdaptiveGroups(
        limit: 35, orderBy: [date_ASC]
        filter: { siteTag: $tag, datetime_geq: $start, datetime_leq: $end }
      ) { count dimensions { metric: date } }
    }
  }
}
"""


def _gql(token: str, variables: dict) -> dict:
    r = requests.post(
        GQL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": _QUERY, "variables": variables},
        timeout=30,
    )
    if r.status_code >= 400:
        raise SystemExit(f"Cloudflare API {r.status_code}: {r.text[:400]}")
    data = r.json()
    if data.get("errors"):
        raise SystemExit("Cloudflare GraphQL errors: " + json.dumps(data["errors"], ensure_ascii=False))
    return data["data"]


def _rows(groups: list[dict]) -> list[dict]:
    return [{"value": g.get("dimensions", {}).get("metric"), "pageviews": g.get("count", 0)} for g in groups]


def pull() -> dict:
    token = require("CLOUDFLARE_API_TOKEN")
    acct = require("CLOUDFLARE_ACCOUNT_ID")
    # POZOR: Web Analytics siteTag v GraphQL ≠ beacon "token" v HTML (d92ac79…).
    # Skutečný siteTag pro wizardcost.com zjištěn z RUM datasetu (eef27819…).
    tag = env_value("CLOUDFLARE_SITE_TAG") or "eef278191e054ca08fdf56b6a6a6aed4"
    end = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    start = end - datetime.timedelta(days=28)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    data = _gql(token, {
        "acct": acct, "tag": tag,
        "start": start.strftime(fmt), "end": end.strftime(fmt),
    })
    accts = data.get("viewer", {}).get("accounts", [])
    a = accts[0] if accts else {}
    total = a.get("total", [{}])
    return {
        "source": "cloudflare",
        "site_tag": tag,
        "range": {"start": start.strftime(fmt), "end": end.strftime(fmt)},
        "pageviews_total": (total[0].get("count", 0) if total else 0),
        "by_country": _rows(a.get("byCountry", [])),
        "by_referer": _rows(a.get("byReferer", [])),
        "by_path": _rows(a.get("byPath", [])),
        "by_date": _rows(a.get("byDate", [])),
    }


if __name__ == "__main__":
    print(json.dumps(pull(), indent=2, ensure_ascii=False))
