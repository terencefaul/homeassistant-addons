"""SQLite persistence.

Chosen over Postgres deliberately: one writing process, a few dozen live
grants, a few thousand audit rows a year. Bundling Postgres would mean a second
process and Home Assistant backing up a live data directory; an external
Postgres would be an install dependency an add-on cannot declare.

Chosen over the reference add-on's flat JSON files because those did
read-modify-write on a whole file with no locking.

All methods are synchronous. The HTTP layer wraps them in asyncio.to_thread.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .clock import now

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS grants (
  id            TEXT PRIMARY KEY,
  label         TEXT NOT NULL DEFAULT '',
  created_at    INTEGER NOT NULL,
  valid_from    INTEGER NOT NULL,
  -- NOT NULL by design: a permanent credential cannot be represented.
  valid_until   INTEGER NOT NULL,
  theme         TEXT NOT NULL DEFAULT 'dark',
  revoked_at    INTEGER
);

CREATE TABLE IF NOT EXISTS credentials (
  hmac          BLOB PRIMARY KEY,
  grant_id      TEXT NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL CHECK (kind IN ('pin', 'token'))
);
CREATE INDEX IF NOT EXISTS credentials_grant ON credentials(grant_id);

CREATE TABLE IF NOT EXISTS grant_entities (
  grant_id      TEXT NOT NULL REFERENCES grants(id) ON DELETE CASCADE,
  entity_id     TEXT NOT NULL,
  PRIMARY KEY (grant_id, entity_id)
);

CREATE TABLE IF NOT EXISTS presets (
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  entities      TEXT NOT NULL,
  duration_s    INTEGER NOT NULL,
  theme         TEXT NOT NULL DEFAULT 'dark',
  kinds         TEXT NOT NULL DEFAULT 'pin,token',
  created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            INTEGER NOT NULL,
  grant_id      TEXT,
  kind          TEXT,
  event         TEXT NOT NULL,
  entity_id     TEXT,
  service       TEXT,
  client_ip     TEXT,
  detail        TEXT
);
CREATE INDEX IF NOT EXISTS audit_ts ON audit(ts DESC);
CREATE INDEX IF NOT EXISTS audit_grant ON audit(grant_id);

CREATE TABLE IF NOT EXISTS settings (
  key           TEXT PRIMARY KEY,
  value         TEXT NOT NULL
);
"""

EVENTS = (
    "redeem_ok",
    "redeem_fail",
    "act",
    "act_failed",
    "denied",
    "mint",
    "revoke",
    "extend",
    "reissue",
    "owner_act",
    "owner_act_failed",
    "lockout",
)


@dataclass(frozen=True)
class Grant:
    id: str
    label: str
    created_at: int
    valid_from: int
    valid_until: int
    theme: str
    revoked_at: Optional[int]
    entities: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()

    def status(self, at: Optional[int] = None) -> str:
        t = now() if at is None else at
        if self.revoked_at is not None:
            return "revoked"
        if t < self.valid_from:
            return "scheduled"
        if t >= self.valid_until:
            return "expired"
        return "active"

    @property
    def is_live(self) -> bool:
        return self.status() == "active"


class Store:
    """Owns the database and the HMAC secret."""

    def __init__(self, db_path: str | os.PathLike[str], secret: bytes):
        self._lock = threading.Lock()
        self._secret = secret
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.executescript(SCHEMA)
            self._db.commit()

    # ---- credential fingerprinting -------------------------------------

    def fingerprint(self, credential: str) -> bytes:
        """Keyed hash of a credential.

        Must be indexable for lookup, which rules out bcrypt. A bare hash of a
        6-digit PIN is reversed instantly from a leaked database; a keyed HMAC
        is not, without the secret.
        """
        return hmac.new(
            self._secret, credential.encode("utf-8"), hashlib.sha256
        ).digest()

    # ---- low level ------------------------------------------------------

    def _q(self, sql: str, args: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._db.execute(sql, args))

    def _x(self, sql: str, args: Sequence[Any] = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ---- grants ---------------------------------------------------------

    def _hydrate(self, row: sqlite3.Row) -> Grant:
        gid = row["id"]
        ents = tuple(
            r["entity_id"]
            for r in self._q(
                "SELECT entity_id FROM grant_entities WHERE grant_id=? ORDER BY entity_id",
                (gid,),
            )
        )
        kinds = tuple(
            r["kind"]
            for r in self._q(
                "SELECT kind FROM credentials WHERE grant_id=? ORDER BY kind", (gid,)
            )
        )
        return Grant(
            id=gid,
            label=row["label"],
            created_at=row["created_at"],
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            theme=row["theme"],
            revoked_at=row["revoked_at"],
            entities=ents,
            kinds=kinds,
        )

    def create_grant(
        self,
        *,
        grant_id: str,
        label: str,
        valid_from: int,
        valid_until: int,
        theme: str,
        entities: Iterable[str],
        credentials: Iterable[tuple[str, str]],
    ) -> Grant:
        """Insert a grant, its entities and its credentials in one transaction.

        `credentials` is an iterable of (kind, plaintext). The plaintext is
        fingerprinted here and immediately discarded -- it is never persisted,
        so no code path can read a credential back after minting.
        """
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute(
                    "INSERT INTO grants (id,label,created_at,valid_from,valid_until,theme)"
                    " VALUES (?,?,?,?,?,?)",
                    (grant_id, label, now(), valid_from, valid_until, theme),
                )
                for e in entities:
                    self._db.execute(
                        "INSERT OR IGNORE INTO grant_entities (grant_id,entity_id) VALUES (?,?)",
                        (grant_id, e),
                    )
                for kind, plaintext in credentials:
                    self._db.execute(
                        "INSERT INTO credentials (hmac,grant_id,kind) VALUES (?,?,?)",
                        (self.fingerprint(plaintext), grant_id, kind),
                    )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        got = self.get_grant(grant_id)
        assert got is not None
        return got

    def get_grant(self, grant_id: str) -> Optional[Grant]:
        rows = self._q("SELECT * FROM grants WHERE id=?", (grant_id,))
        return self._hydrate(rows[0]) if rows else None

    def resolve_credential(self, plaintext: str) -> Optional[tuple[Grant, str]]:
        """Look up a presented credential. Returns (grant, kind) or None.

        Returns the grant whatever its status -- the caller decides whether a
        scheduled, expired or revoked grant is usable, because those must be
        reported to the visitor as distinct outcomes rather than all collapsing
        into 'wrong code'.
        """
        rows = self._q(
            "SELECT grant_id, kind FROM credentials WHERE hmac=?",
            (self.fingerprint(plaintext),),
        )
        if not rows:
            return None
        g = self.get_grant(rows[0]["grant_id"])
        return (g, rows[0]["kind"]) if g else None

    def credential_exists(self, plaintext: str) -> bool:
        return bool(
            self._q("SELECT 1 FROM credentials WHERE hmac=?", (self.fingerprint(plaintext),))
        )

    def list_grants(self, include_finished: bool = True) -> list[Grant]:
        rows = self._q("SELECT * FROM grants ORDER BY created_at DESC")
        grants = [self._hydrate(r) for r in rows]
        if include_finished:
            return grants
        return [g for g in grants if g.status() in ("active", "scheduled")]

    def revoke_grant(self, grant_id: str) -> bool:
        return (
            self._x(
                "UPDATE grants SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
                (now(), grant_id),
            )
            == 1
        )

    def extend_grant(self, grant_id: str, new_valid_until: int) -> bool:
        """Push out a live grant's expiry.

        Only a live grant can be extended. Reviving an expired one would mean a
        code still sitting in someone's messages silently starts working again.
        """
        t = now()
        return (
            self._x(
                "UPDATE grants SET valid_until=? WHERE id=? AND revoked_at IS NULL"
                " AND valid_from <= ? AND valid_until > ? AND ? > valid_until",
                (new_valid_until, grant_id, t, t, new_valid_until),
            )
            == 1
        )

    def live_pin_grant_count(self) -> int:
        t = now()
        rows = self._q(
            "SELECT COUNT(*) AS n FROM grants g JOIN credentials c ON c.grant_id=g.id"
            " WHERE c.kind='pin' AND g.revoked_at IS NULL AND g.valid_until > ?",
            (t,),
        )
        return int(rows[0]["n"])

    def grant_allows(self, grant_id: str, entity_id: str) -> bool:
        """Is this entity attached to THIS grant?

        Scoped by grant_id, never merely 'some grant'. The reference add-on
        shipped a bug of exactly this shape (CHANGELOG 0.1.33) where a session
        authenticated to one link could reach another.
        """
        return bool(
            self._q(
                "SELECT 1 FROM grant_entities WHERE grant_id=? AND entity_id=?",
                (grant_id, entity_id),
            )
        )

    def replace_credentials(
        self, grant_id: str, credentials: Iterable[tuple[str, str]]
    ) -> None:
        """Issue fresh credentials for an existing grant, replacing those kinds.

        A credential cannot be recovered -- only its keyed hash is stored -- so
        "send it again" has to mean "issue another key to the same lock". The
        grant keeps its window, its entity list and its single revocation; only
        the key changes.

        Replacing rather than adding is the safer default: you re-issue because
        the first one did not arrive, and a credential that went astray should
        not stay live.
        """
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                for kind, plaintext in credentials:
                    self._db.execute(
                        "DELETE FROM credentials WHERE grant_id=? AND kind=?",
                        (grant_id, kind),
                    )
                    self._db.execute(
                        "INSERT INTO credentials (hmac,grant_id,kind) VALUES (?,?,?)",
                        (self.fingerprint(plaintext), grant_id, kind),
                    )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise

    # ---- presets --------------------------------------------------------

    def upsert_preset(
        self,
        *,
        preset_id: str,
        name: str,
        entities: Sequence[str],
        duration_s: int,
        theme: str,
        kinds: Sequence[str],
    ) -> None:
        self._x(
            "INSERT INTO presets (id,name,entities,duration_s,theme,kinds,created_at)"
            " VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(id) DO UPDATE SET name=excluded.name, entities=excluded.entities,"
            " duration_s=excluded.duration_s, theme=excluded.theme, kinds=excluded.kinds",
            (
                preset_id,
                name,
                ",".join(entities),
                duration_s,
                theme,
                ",".join(kinds),
                now(),
            ),
        )

    def list_presets(self) -> list[dict[str, Any]]:
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "entities": [e for e in r["entities"].split(",") if e],
                "duration_s": r["duration_s"],
                "theme": r["theme"],
                "kinds": [k for k in r["kinds"].split(",") if k],
            }
            for r in self._q("SELECT * FROM presets ORDER BY name")
        ]

    def get_preset_by_name(self, name: str) -> Optional[dict[str, Any]]:
        for p in self.list_presets():
            if p["name"].lower() == name.lower():
                return p
        return None

    def delete_preset(self, preset_id: str) -> bool:
        return self._x("DELETE FROM presets WHERE id=?", (preset_id,)) == 1

    # ---- settings (branding) -------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        rows = self._q("SELECT value FROM settings WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def set_setting(self, key: str, value: str) -> None:
        self._x(
            "INSERT INTO settings (key,value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    # ---- audit ----------------------------------------------------------

    def log(
        self,
        event: str,
        *,
        grant_id: Optional[str] = None,
        kind: Optional[str] = None,
        entity_id: Optional[str] = None,
        service: Optional[str] = None,
        client_ip: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        self._x(
            "INSERT INTO audit (ts,grant_id,kind,event,entity_id,service,client_ip,detail)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (now(), grant_id, kind, event, entity_id, service, client_ip, detail),
        )

    def audit(
        self,
        *,
        limit: int = 200,
        grant_id: Optional[str] = None,
        event: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT a.*, g.label AS grant_label FROM audit a LEFT JOIN grants g ON g.id=a.grant_id WHERE 1=1"
        args: list[Any] = []
        if grant_id:
            sql += " AND a.grant_id=?"
            args.append(grant_id)
        if event:
            sql += " AND a.event=?"
            args.append(event)
        sql += " ORDER BY a.ts DESC, a.id DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        return [dict(r) for r in self._q(sql, args)]

    def prune_audit(self, retention_days: int) -> int:
        cutoff = now() - retention_days * 86400
        return self._x("DELETE FROM audit WHERE ts < ?", (cutoff,))


def load_or_create_secret(path: str | os.PathLike[str]) -> bytes:
    """Read the HMAC secret, creating it on first run.

    Losing this file invalidates every credential ever issued, which is the
    correct failure mode -- it is stored alongside the database in /data and
    therefore travels with Home Assistant's own backups.
    """
    p = Path(path)
    if p.exists():
        data = p.read_bytes().strip()
        if len(data) >= 32:
            return data
    p.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(48)
    p.write_bytes(secret)
    os.chmod(p, 0o600)
    return secret
