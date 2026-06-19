"""Sdílené utility pro marketing konektory (GSC + Cloudflare).

Token zdroj: os.environ → fallback engine/.env (mimo tohle repo, gitignored).
NIKDY token necommitovat. Stejný vzor jako scripts/send_price_alerts.py.
"""
from __future__ import annotations
import os
from pathlib import Path

# TLS fix: na Windows s antivirovou TLS-inspekcí Python nezná injektovaný root cert
# (prohlížeč ano, bere ho z OS úložiště). truststore přiměje Python použít OS cert store.
# No-op tam, kde není potřeba (čistá CI s certifi). Bezpečné — ověřování zůstává zapnuté.
try:
    import truststore as _truststore
    _truststore.inject_into_ssl()
except Exception:
    pass

# scripts/marketing/_common.py → parents[2] = repo root (wizardcost)
REPO = Path(__file__).resolve().parents[2]
# workspace layout: <root>/{cost.io/wizardcost, engine} → engine/.env je o dvě úrovně výš
ENGINE_ENV = REPO.parents[1] / "engine" / ".env"


def env_value(key: str) -> str:
    """Vrátí hodnotu z os.environ, jinak z engine/.env, jinak ''."""
    v = os.environ.get(key, "").strip()
    if v:
        return v
    if ENGINE_ENV.exists():
        for line in ENGINE_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{key}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def require(key: str) -> str:
    v = env_value(key)
    if not v:
        raise SystemExit(
            f"CHYBA: {key} nenalezen (os.environ ani engine/.env). "
            f"Viz scripts/marketing/README.md → setup."
        )
    return v
