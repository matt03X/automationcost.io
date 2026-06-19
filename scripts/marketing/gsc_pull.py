"""GSC konektor — stáhne Search Console data (reálná SEO pravda).

Auth: service account (read-only). Token/klíč:
  - GSC_SA_JSON       = celý obsah JSON klíče (vhodné pro GH secret), NEBO
  - GSC_SA_JSON_PATH  = cesta k .json klíči (lokálně)
  - GSC_SITE_URL      = property (default 'sc-domain:wizardcost.com';
                        pro URL-prefix property dej 'https://wizardcost.com/')

Vrací dict s totals + top dotazy / stránky / země / vývoj po dnech za 28 dní.
GSC má ~2denní zpoždění dat → okno končí (dnes − 2 dny).

Spuštění samostatně:  python scripts/marketing/gsc_pull.py   (vypíše JSON)
Závislosti:           pip install google-auth requests
"""
from __future__ import annotations
import datetime
import json
import sys
from urllib.parse import quote

from _common import env_value, require

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def _session():
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
    except ImportError:
        raise SystemExit("CHYBA: chybí závislost. Spusť: pip install google-auth requests")

    raw = env_value("GSC_SA_JSON")
    path = env_value("GSC_SA_JSON_PATH")
    if raw:
        creds = service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    elif path:
        creds = service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    else:
        raise SystemExit("CHYBA: nastav GSC_SA_JSON nebo GSC_SA_JSON_PATH (viz README).")
    return AuthorizedSession(creds)


def pull() -> dict:
    site = env_value("GSC_SITE_URL") or "sc-domain:wizardcost.com"
    session = _session()
    url = (
        "https://searchconsole.googleapis.com/webmasters/v3/sites/"
        f"{quote(site, safe='')}/searchAnalytics/query"
    )
    end = datetime.date.today() - datetime.timedelta(days=2)
    start = end - datetime.timedelta(days=27)
    base = {"startDate": start.isoformat(), "endDate": end.isoformat()}

    def q(dims: list[str], limit: int = 25) -> list[dict]:
        body = dict(base, rowLimit=limit)
        if dims:
            body["dimensions"] = dims
        r = session.post(url, json=body)
        if r.status_code >= 400:
            raise SystemExit(f"GSC API {r.status_code} pro dims={dims}: {r.text[:400]}")
        return r.json().get("rows", [])

    totals = q([], 1)
    return {
        "source": "gsc",
        "site": site,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "totals": totals[0] if totals else {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0},
        "by_query": q(["query"], 25),
        "by_page": q(["page"], 25),
        "by_country": q(["country"], 10),
        "by_date": q(["date"], 28),
    }


if __name__ == "__main__":
    print(json.dumps(pull(), indent=2, ensure_ascii=False))
