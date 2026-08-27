"""Telegram bot behaviour.

Exercised against a fake Telegram API rather than the real one, so the
authorisation rules and the button flow are covered without a network or a
token.
"""

import asyncio

import pytest

from gate_pin.bot import TelegramBot
from gate_pin.clock import now
from gate_pin.store import Store, load_or_create_secret

ALLOWED = 111
STRANGER = 999


class FakeTelegram:
    """Stands in for httpx.AsyncClient against api.telegram.org."""

    def __init__(self):
        self.sent = []
        self.answered = []
        self.commands = []

    async def post(self, url, json=None, **kw):
        if url.endswith("sendMessage"):
            self.sent.append(json)
        elif url.endswith("answerCallbackQuery"):
            self.answered.append(json)
        elif url.endswith("setMyCommands"):
            self.commands.append(json)
        return None

    async def aclose(self):
        return None


@pytest.fixture()
def bot(tmp_path):
    secret = load_or_create_secret(tmp_path / "s.key")
    store = Store(tmp_path / "b.db", secret)
    store.upsert_preset(
        preset_id="p1", name="plumber", entities=["cover.driveway"],
        duration_s=7200, theme="dark", kinds=["pin", "token"],
    )
    b = TelegramBot(
        token="fake", chat_ids=[ALLOWED], store=store,
        base_url="https://gate.example.com", pin_length=6, max_live_pin_grants=20,
    )
    b._client = FakeTelegram()
    yield b, store, b._client
    store.close()


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def msg(chat_id, text):
    return {"message": {"chat": {"id": chat_id}, "text": text}}


def tap(chat_id, data):
    return {"callback_query": {"id": "cb1", "data": data,
                               "message": {"chat": {"id": chat_id}}}}


def test_a_stranger_gets_no_reply_at_all(bot):
    """Answering an unknown chat confirms the bot exists and that its owner is
    worth pursuing. Silence is the design."""
    b, _, tg = bot
    run(b._handle(msg(STRANGER, "/menu")))
    run(b._handle(msg(STRANGER, "/new 2h cover.driveway")))
    assert tg.sent == []


def test_a_tapped_button_from_a_stranger_is_ignored_too(bot):
    """A callback carries a chat like a message does, and is authorised the
    same way. Missing this would leave a hole behind the buttons."""
    b, store, tg = bot
    run(b._handle(tap(STRANGER, "m:p1")))
    assert tg.sent == [] and tg.answered == []
    assert store.list_grants() == []


def test_menu_shows_a_button_per_preset(bot):
    b, _, tg = bot
    run(b._handle(msg(ALLOWED, "/menu")))
    keyboard = tg.sent[0]["reply_markup"]["inline_keyboard"]
    labels = [btn["text"] for row in keyboard for btn in row]
    assert any("plumber" in l for l in labels)
    assert any("Live grants" == l for l in labels)


def test_menu_without_presets_says_so_rather_than_showing_nothing(bot):
    b, store, tg = bot
    store.delete_preset("p1")
    run(b._handle(msg(ALLOWED, "/menu")))
    assert "No presets yet" in tg.sent[0]["text"]


def test_tapping_a_preset_mints_and_sends_pin_and_link_separately(bot):
    """Separate messages so forwarding the link does not also forward the PIN."""
    b, store, tg = bot
    run(b._handle(tap(ALLOWED, "m:p1")))
    assert tg.answered, "the spinner must be dismissed or the tap looks dead"
    texts = [m["text"] for m in tg.sent]
    assert any("PIN <code>" in t for t in texts)
    assert any(t.startswith("https://gate.example.com/g/") for t in texts)
    pin_msg = next(t for t in texts if "PIN <code>" in t)
    link_msg = next(t for t in texts if t.startswith("https://"))
    assert pin_msg is not link_msg
    assert len(store.list_grants()) == 1


def test_the_mint_confirmation_offers_revoke_and_extend(bot):
    b, _, tg = bot
    run(b._handle(tap(ALLOWED, "m:p1")))
    keyboard = tg.sent[0]["reply_markup"]["inline_keyboard"]
    data = [btn["callback_data"] for row in keyboard for btn in row]
    assert any(d.startswith("r:") for d in data)
    assert any(d.startswith("x:") for d in data)


def test_revoke_button_kills_the_grant(bot):
    b, store, tg = bot
    run(b._handle(tap(ALLOWED, "m:p1")))
    grant = store.list_grants()[0]
    run(b._handle(tap(ALLOWED, f"r:{grant.id}")))
    assert store.get_grant(grant.id).status() == "revoked"


def test_extend_button_refuses_a_grant_that_is_not_live(bot):
    b, store, tg = bot
    run(b._handle(tap(ALLOWED, "m:p1")))
    grant = store.list_grants()[0]
    store._x("UPDATE grants SET valid_until=? WHERE id=?", (now() - 1, grant.id))
    tg.answered.clear()
    run(b._handle(tap(ALLOWED, f"x:{grant.id}:3600")))
    assert "live" in tg.answered[0]["text"].lower()
    assert store.get_grant(grant.id).status() == "expired"


def test_callback_data_fits_telegram_limit(bot):
    """Telegram caps callback_data at 64 bytes and silently breaks past it."""
    b, store, tg = bot
    run(b._handle(msg(ALLOWED, "/menu")))
    run(b._handle(tap(ALLOWED, "m:p1")))
    for m in tg.sent:
        for row in (m.get("reply_markup") or {}).get("inline_keyboard", []):
            for btn in row:
                assert len(btn["callback_data"].encode()) <= 64, btn


def test_list_offers_reissue_and_revoke_per_grant(bot):
    b, store, tg = bot
    run(b._handle(tap(ALLOWED, "m:p1")))
    tg.sent.clear()
    run(b._handle(msg(ALLOWED, "/list")))
    data = [btn["callback_data"]
            for row in tg.sent[0]["reply_markup"]["inline_keyboard"] for btn in row]
    assert any(d.startswith("i:") and d.endswith(":token") for d in data)
    assert any(d.startswith("i:") and d.endswith(":pin") for d in data)
    assert any(d.startswith("r:") for d in data)


def test_reissue_button_replaces_that_credential_only(bot):
    """Re-issuing the link must leave the PIN working, so you can replace just
    the one that went missing."""
    b, store, tg = bot
    run(b._handle(tap(ALLOWED, "m:p1")))
    old_link = next(t for t in (m["text"] for m in tg.sent) if t.startswith("https://"))
    old_pin = next(t for t in (m["text"] for m in tg.sent) if "PIN <code>" in t)
    grant = store.list_grants()[0]

    tg.sent.clear()
    run(b._handle(tap(ALLOWED, f"i:{grant.id}:token")))
    new_link = next(t for t in (m["text"] for m in tg.sent) if t.startswith("https://"))

    assert new_link != old_link
    old_token = old_link.rsplit("/", 1)[-1]
    new_token = new_link.rsplit("/", 1)[-1]
    from gate_pin import grants as g
    assert g.redeem(store, old_token).outcome == g.OUTCOME_UNKNOWN
    assert g.redeem(store, new_token).ok
    # The PIN was not re-issued, so it must still work.
    pin = old_pin.split("<code>")[1].split("</code>")[0]
    assert g.redeem(store, pin).ok


def test_reissue_button_says_the_old_one_stopped_working(bot):
    """Easy to miss when it happened via a button rather than a decision."""
    b, store, tg = bot
    run(b._handle(tap(ALLOWED, "m:p1")))
    grant = store.list_grants()[0]
    tg.sent.clear()
    run(b._handle(tap(ALLOWED, f"i:{grant.id}:token")))
    assert any("no longer works" in m["text"] for m in tg.sent)
