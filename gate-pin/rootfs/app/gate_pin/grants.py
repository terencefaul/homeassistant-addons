"""Minting, redeeming and revoking grants."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from . import policy
from .clock import now
from .credentials import generate_id, generate_pin, generate_token
from .store import Grant, Store

THEMES = ("dark", "light", "contrast", "warm")
KINDS = ("pin", "token")


class MintError(Exception):
    """Minting was refused. The message is safe to show an administrator."""


@dataclass(frozen=True)
class MintResult:
    """Returned exactly once, at mint time.

    The plaintext credentials in here are never persisted and cannot be
    recovered afterwards. There is deliberately no 'show me the code again'
    feature -- re-mint instead.
    """

    grant: Grant
    pin: Optional[str]
    token: Optional[str]

    def link(self, base_url: str) -> Optional[str]:
        if not self.token:
            return None
        return f"{base_url.rstrip('/')}/g/{self.token}"


def mint(
    store: Store,
    *,
    label: str,
    entities: Sequence[str],
    valid_from: int,
    valid_until: int,
    theme: str = "dark",
    kinds: Iterable[str] = ("pin", "token"),
    pin_length: int = 6,
    max_live_pin_grants: int = 20,
) -> MintResult:
    kinds = tuple(dict.fromkeys(kinds))
    if not kinds:
        raise MintError("choose at least one of PIN or link")
    for k in kinds:
        if k not in KINDS:
            raise MintError(f"unknown credential kind: {k}")
    if theme not in THEMES:
        raise MintError(f"unknown theme: {theme}")

    entities = tuple(dict.fromkeys(e.strip() for e in entities if e.strip()))
    if not entities:
        raise MintError("choose at least one entity")
    for e in entities:
        if not policy.is_selectable(e):
            raise MintError(f"{e} is not an entity this add-on can expose")

    if valid_until <= valid_from:
        raise MintError("the window must end after it starts")
    if valid_until <= now():
        raise MintError("the window has already ended")

    if "pin" in kinds:
        live = store.live_pin_grant_count()
        if live >= max_live_pin_grants:
            raise MintError(
                f"already {live} live PIN grants (cap {max_live_pin_grants}). "
                "Mint a link-only grant, or revoke one first."
            )

    pin = token = None
    creds: list[tuple[str, str]] = []
    if "pin" in kinds:
        pin = _unique(store, lambda: generate_pin(pin_length))
        creds.append(("pin", pin))
    if "token" in kinds:
        token = _unique(store, generate_token)
        creds.append(("token", token))

    grant_id = _unique_id(store)
    grant = store.create_grant(
        grant_id=grant_id,
        label=label.strip(),
        valid_from=valid_from,
        valid_until=valid_until,
        theme=theme,
        entities=entities,
        credentials=creds,
    )
    store.log(
        "mint",
        grant_id=grant.id,
        detail=f"{label.strip() or 'unlabelled'} | {','.join(kinds)} | {len(entities)} entities",
    )
    return MintResult(grant=grant, pin=pin, token=token)


def _unique(store: Store, gen, attempts: int = 40) -> str:
    for _ in range(attempts):
        candidate = gen()
        if not store.credential_exists(candidate):
            return candidate
    raise MintError("could not generate an unused credential; revoke some grants")


def _unique_id(store: Store, attempts: int = 40) -> str:
    for _ in range(attempts):
        candidate = generate_id()
        if store.get_grant(candidate) is None:
            return candidate
    raise MintError("could not generate an unused grant id")


# ---- redemption outcomes -------------------------------------------------

# Every one of these is reported to the visitor as a DISTINCT message. Without
# that, an expired code, a not-yet-active code, a revoked code and a genuinely
# wrong code all present as "wrong code" -- which is what makes every failure
# mode in this system expensive to diagnose.
OUTCOME_OK = "ok"
OUTCOME_UNKNOWN = "unknown"
OUTCOME_SCHEDULED = "scheduled"
OUTCOME_EXPIRED = "expired"
OUTCOME_REVOKED = "revoked"


@dataclass(frozen=True)
class Redemption:
    outcome: str
    grant: Optional[Grant] = None
    kind: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.outcome == OUTCOME_OK


def redeem(store: Store, presented: str) -> Redemption:
    """Resolve a presented credential to a usable grant, or say precisely why not."""
    found = store.resolve_credential(presented)
    if found is None:
        return Redemption(OUTCOME_UNKNOWN)
    grant, kind = found
    status = grant.status()
    if status == "revoked":
        return Redemption(OUTCOME_REVOKED, grant, kind)
    if status == "scheduled":
        return Redemption(OUTCOME_SCHEDULED, grant, kind)
    if status == "expired":
        return Redemption(OUTCOME_EXPIRED, grant, kind)
    return Redemption(OUTCOME_OK, grant, kind)


def reissue(
    store: Store,
    grant_id: str,
    *,
    kinds: Iterable[str],
    pin_length: int = 6,
    max_live_pin_grants: int = 20,
) -> MintResult:
    """Issue a fresh credential for a grant that already exists.

    Needed because a credential is unrecoverable by design: only its keyed hash
    is kept, so there is no "show it again". Re-issuing keeps the grant -- same
    window, same entities, same single revocation -- and changes only the key.
    """
    kinds = tuple(dict.fromkeys(kinds))
    if not kinds:
        raise MintError("choose at least one of PIN or link")
    for k in kinds:
        if k not in KINDS:
            raise MintError(f"unknown credential kind: {k}")

    grant = store.get_grant(grant_id)
    if grant is None:
        raise MintError("no such grant")
    if grant.status() == "revoked":
        raise MintError("that grant was revoked; mint a new one")
    if grant.status() == "expired":
        raise MintError("that grant has expired; mint a new one")

    # Adding a PIN to a grant that had none makes it count against the cap.
    if "pin" in kinds and "pin" not in grant.kinds:
        live = store.live_pin_grant_count()
        if live >= max_live_pin_grants:
            raise MintError(
                f"already {live} live PIN grants (cap {max_live_pin_grants}). "
                "Re-issue the link instead, or revoke one first."
            )

    pin = token = None
    creds: list[tuple[str, str]] = []
    if "pin" in kinds:
        pin = _unique(store, lambda: generate_pin(pin_length))
        creds.append(("pin", pin))
    if "token" in kinds:
        token = _unique(store, generate_token)
        creds.append(("token", token))

    store.replace_credentials(grant_id, creds)
    store.log("reissue", grant_id=grant_id, detail=",".join(kinds))
    refreshed = store.get_grant(grant_id)
    assert refreshed is not None
    return MintResult(grant=refreshed, pin=pin, token=token)
