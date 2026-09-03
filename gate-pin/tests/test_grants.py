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


# ---- ordering and the migration that makes it possible --------------------

def _preset(store, name, **kw):
    store.upsert_preset(
        preset_id=name, name=name, entities=["cover.driveway"],
        duration_s=3600, theme="dark", kinds=["pin"], **kw,
    )


def test_new_presets_append_rather_than_sorting_by_name(store):
    """A list you can reorder has to put new items somewhere predictable, and
    'last' is the only place that does not disturb an order already set."""
    for name in ("courier", "builder", "plumber"):
        _preset(store, name)
    assert [p["name"] for p in store.list_presets()] == ["courier", "builder", "plumber"]


def test_a_migrated_database_still_reads_alphabetically(store):
    """What every existing install sees on upgrade: the migration leaves every
    position at 0, and name is the tiebreak, so nothing appears to have moved
    until the owner moves something."""
    for name in ("courier", "builder", "plumber"):
        _preset(store, name)
    store._x("UPDATE presets SET position=0")
    assert [p["name"] for p in store.list_presets()] == ["builder", "courier", "plumber"]


def test_reordering_presets_sticks(store):
    for name in ("courier", "builder", "plumber"):
        _preset(store, name)
    store.reorder_presets(["plumber", "courier", "builder"])
    assert [p["name"] for p in store.list_presets()] == ["plumber", "courier", "builder"]


def test_editing_a_preset_does_not_move_it(store):
    """Renaming or retiming a preset from the panel must not throw away the
    order the owner set -- the two are edited on the same screen."""
    for name in ("courier", "builder", "plumber"):
        _preset(store, name)
    store.reorder_presets(["plumber", "courier", "builder"])
    store.upsert_preset(
        preset_id="courier", name="courier", entities=["cover.driveway"],
        duration_s=7200, theme="warm", kinds=["token"],
    )
    assert [p["name"] for p in store.list_presets()] == ["plumber", "courier", "builder"]


def test_a_new_preset_lands_at_the_end(store):
    for name in ("courier", "builder"):
        _preset(store, name)
    store.reorder_presets(["courier", "builder"])
    _preset(store, "plumber")
    assert [p["name"] for p in store.list_presets()] == ["courier", "builder", "plumber"]


def test_reordering_keeps_rows_it_was_not_told_about(store):
    """The panel sends back the list it was showing. A preset created from
    Telegram in between must not be dropped from the ordering."""
    for name in ("courier", "builder"):
        _preset(store, name)
    _preset(store, "plumber")
    store.reorder_presets(["plumber", "courier"])
    names = [p["name"] for p in store.list_presets()]
    assert names[:2] == ["plumber", "courier"]
    assert "builder" in names


def test_grants_read_newest_first_until_they_are_reordered(store):
    first = mint(store, label="first")
    second = mint(store, label="second")
    assert [x.label for x in store.list_grants()] == ["second", "first"]
    store.reorder_grants([first.grant.id, second.grant.id])
    assert [x.label for x in store.list_grants()] == ["first", "second"]


def test_a_new_grant_goes_to_the_top_even_after_a_reorder(store):
    """The opposite of presets, deliberately: this list is read to find the
    grant you just made, or the one you need to revoke."""
    a = mint(store, label="a")
    b = mint(store, label="b")
    store.reorder_grants([a.grant.id, b.grant.id])
    mint(store, label="newest")
    assert [x.label for x in store.list_grants()][0] == "newest"


def test_a_database_without_the_position_columns_gains_them(tmp_path):
    """CREATE TABLE IF NOT EXISTS does nothing to a table that already exists,
    so a column added after release reaches new installs only. Without the
    migration this raises "no such column: position" on every existing one."""
    import sqlite3

    secret = load_or_create_secret(tmp_path / "secret.key")
    path = tmp_path / "old.db"

    # A presets table shaped the way it was before ordering existed.
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE presets (
          id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, entities TEXT NOT NULL,
          duration_s INTEGER NOT NULL, theme TEXT NOT NULL DEFAULT 'dark',
          created_at INTEGER NOT NULL
        );
        INSERT INTO presets VALUES ('p1','plumber','cover.driveway',3600,'dark',0);
        """
    )
    db.commit()
    db.close()

    s = Store(path, secret)
    try:
        # Both columns added after the fact, and the existing row survived.
        assert [p["name"] for p in s.list_presets()] == ["plumber"]
        assert s.list_presets()[0]["kinds"] == ["pin", "token"]
        _preset(s, "courier")
        s.reorder_presets(["courier", "p1"])
        assert [p["name"] for p in s.list_presets()] == ["courier", "plumber"]
    finally:
        s.close()
