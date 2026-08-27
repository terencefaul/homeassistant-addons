"""Add-on options, read from /data/options.json (written by Supervisor)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

OPTIONS_PATH = os.environ.get("GATE_PIN_OPTIONS", "/data/options.json")
DATA_DIR = os.environ.get("GATE_PIN_DATA", "/data")


@dataclass
class Options:
    external_base_url: str = "https://gate.terica.co.za"
    telegram_bot_token: str = ""
    telegram_chat_ids: list[int] = field(default_factory=list)
    notify_service: str = ""
    pin_length: int = 6
    max_live_pin_grants: int = 20
    trusted_proxy_cidr: str = "172.30.32.0/23"
    audit_retention_days: int = 90
    require_cf_header: bool = True

    @property
    def db_path(self) -> str:
        return str(Path(DATA_DIR) / "gate-pin.db")

    @property
    def secret_path(self) -> str:
        return str(Path(DATA_DIR) / "secret.key")

    @property
    def branding_dir(self) -> str:
        return str(Path(DATA_DIR) / "branding")


def load() -> Options:
    raw: dict = {}
    p = Path(OPTIONS_PATH)
    if p.exists():
        try:
            raw = json.loads(p.read_text() or "{}")
        except Exception:
            raw = {}
    known = {f for f in Options.__dataclass_fields__}
    return Options(**{k: v for k, v in raw.items() if k in known and v is not None})
