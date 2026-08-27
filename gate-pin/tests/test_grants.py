import pytest

from gate_pin import grants as g
from gate_pin.clock import now
from gate_pin.store import Store, load_or_create_secret


@pytest.fixture()
def store(tmp_path):
    secret = load_or_create_secret(tmp_path / "secret.key")
    s = Store(tmp_path / "t.db", secret)
    yield s
    s.close()


def mint(store, **kw):
    base = dict(
        label="test",
        entities=["cover.driveway"],
        valid_from=now() - 1,
        valid_until=now() + 3600,
        kinds=("pin", "token"),
    )
    base.update(kw)
    return g.mint(store, **base)


def test_mint_issues_both_credentials_resolving_to_one_grant(store):
    r = mint(store)
    assert r.pin and r.token and r.pin != r.token
    by_pin = g.redeem(store, r.pin)
    by_token = g.redeem(store, r.token)
    assert by_pin.ok and by_token.ok
    assert by_pin.grant.id == by_token.grant.id == r.grant.id
    assert by_pin.kind == "pin" and by_token.kind == "token"


def test_plaintext_credentials_are_never_stored(store):
    r = mint(store)
    rows = store._q("SELECT hmac FROM credentials")
    stored = b"".join(row["hmac"] for row in rows)
    assert r.pin.encode() not in stored
    assert r.token.encode() not in stored


def test_revocation_kills_both_credentials(store):
    r = mint(store)
    assert store.revoke_grant(r.grant.id)
    assert g.redeem(store, r.pin).outcome == g.OUTCOME_REVOKED
    assert g.redeem(store, r.token).outcome == g.OUTCOME_REVOKED


def test_each_failure_mode_is_distinguishable(store):
    """The whole point: 'wrong', 'not yet', 'expired' and 'cancelled' must
    never collapse into one message."""
    assert g.redeem(store, "000000").outcome == g.OUTCOME_UNKNOWN

    later = mint(store, valid_from=now() + 600, valid_until=now() + 1200)
    assert g.redeem(store, later.pin).outcome == g.OUTCOME_SCHEDULED

    past = g.mint(
        store, label="x", entities=["cover.driveway"],
        valid_from=now() - 100, valid_until=now() + 1, kinds=("pin",),
    )
    store._x("UPDATE grants SET valid_until=? WHERE id=?", (now() - 1, past.grant.id))
    assert g.redeem(store, past.pin).outcome == g.OUTCOME_EXPIRED

    rev = mint(store)
    store.revoke_grant(rev.grant.id)
    assert g.redeem(store, rev.pin).outcome == g.OUTCOME_REVOKED


def test_a_grant_can_never_be_permanent(store):
    with pytest.raises(g.MintError):
        mint(store, valid_until=now() - 10)
    with pytest.raises(g.MintError):
        mint(store, valid_from=now() + 100, valid_until=now() + 50)


def test_live_pin_cap_blocks_pins_but_not_tokens(store):
    for _ in range(3):
        mint(store, kinds=("pin",))
    with pytest.raises(g.MintError) as exc:
        mint(store, kinds=("pin",), max_live_pin_grants=3)
    assert "cap 3" in str(exc.value)
    # Token-only grants have no keyspace-decay property, so they stay available.
    assert mint(store, kinds=("token",), max_live_pin_grants=3).token


def test_token_only_grant_has_no_pin(store):
    r = mint(store, kinds=("token",))
    assert r.pin is None and r.token
    assert store.get_grant(r.grant.id).kinds == ("token",)
    assert store.live_pin_grant_count() == 0


def test_unexposable_entity_is_refused(store):
    with pytest.raises(g.MintError):
        mint(store, entities=["climate.lounge"])


def test_extend_only_applies_to_a_live_grant(store):
    """Reviving an expired grant would mean a code still sitting in someone's
    messages silently starts working again."""
    r = mint(store)
    assert store.extend_grant(r.grant.id, r.grant.valid_until + 600)

    store._x("UPDATE grants SET valid_until=? WHERE id=?", (now() - 1, r.grant.id))
    assert not store.extend_grant(r.grant.id, now() + 3600)
    assert g.redeem(store, r.pin).outcome == g.OUTCOME_EXPIRED


def test_grant_scoping_is_per_grant_not_global(store):
    """The reference add-on shipped a bug of exactly this shape (0.1.33)."""
    a = mint(store, entities=["cover.driveway"])
    b = mint(store, entities=["light.porch"])
    assert store.grant_allows(a.grant.id, "cover.driveway")
    assert not store.grant_allows(a.grant.id, "light.porch")
    assert not store.grant_allows(b.grant.id, "cover.driveway")
