"""Telegram bot.

Admin-only. The allowlist is numeric chat IDs, never @usernames -- a username
can be released and re-registered by somebody else, which would silently hand
the gate to a stranger.

An update from a non-allowlisted chat is dropped with NO reply. Answering "you
are not authorised" confirms the bot exists and that its owner is worth
pursuing.

Implemented directly against the Bot API rather than through a bot framework:
this needs getUpdates and sendMessage and nothing else, and owning the poll
loop is what makes the watchdog and the single-instance guard straightforward.
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Any, Callable, Optional, Sequence

import httpx

from . import grants as g
from .clock import now
from .duration import DurationError, parse as parse_duration, humanise
from .store import Store

log = logging.getLogger("gate_pin.bot")

HELP = """<b>Gate PIN</b>

<code>/menu</code> — <b>buttons for your presets</b>, one tap to mint

<code>/new 2h cover.driveway</code> — mint a grant
<code>/new plumber</code> — mint from a preset
<code>/new 2h cover.driveway --token-only</code> — link only
<code>/list</code> — live grants
<code>/revoke &lt;id&gt;</code> — kill a grant now
<code>/extend &lt;id&gt; 1h</code> — push out a live grant
<code>/presets</code> — saved presets
"""


class TelegramBot:
    def __init__(
        self,
        *,
        token: str,
        chat_ids: Sequence[int],
        store: Store,
        base_url: str,
        pin_length: int = 6,
        max_live_pin_grants: int = 20,
        status: Optional[dict] = None,
        on_error: Optional[Callable[[str], Any]] = None,
    ):
        self._token = token
        self._chats = {int(c) for c in chat_ids}
        self._store = store
        self._base_url = base_url
        self._pin_length = pin_length
        self._cap = max_live_pin_grants
        self._offset = 0
        self._status = status if status is not None else {}
        self._on_error = on_error
        self._client: Optional[httpx.AsyncClient] = None
        self._status.update(
            {"configured": bool(token and self._chats), "running": False,
             "last_ok": None, "last_error": None}
        )

    @property
    def configured(self) -> bool:
        return bool(self._token and self._chats)

    def _api(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._token}/{method}"

    async def send(self, chat_id: int, text: str, buttons: Optional[list] = None) -> None:
        """Send a message, optionally with an inline keyboard.

        `buttons` is a list of rows, each a list of (label, callback_data).
        Callback data is capped at 64 bytes by Telegram, so ids stay short.
        """
        if not self._client:
            return
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if buttons:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": label, "callback_data": data} for label, data in row]
                    for row in buttons
                ]
            }
        try:
            await self._client.post(self._api("sendMessage"), json=payload)
        except Exception as exc:
            log.warning("sendMessage failed: %s", exc)

    async def _answer_callback(self, callback_id: str, text: str = "") -> None:
        """Dismiss the spinner on a tapped button. Without this it spins for
        ~15 seconds and the tap looks like it did nothing."""
        if not self._client:
            return
        try:
            await self._client.post(
                self._api("answerCallbackQuery"),
                json={"callback_query_id": callback_id, "text": text[:200]},
            )
        except Exception as exc:
            log.warning("answerCallbackQuery failed: %s", exc)

    async def _publish_commands(self) -> None:
        """Populate Telegram's own / menu, so the commands are discoverable
        without reading documentation."""
        if not self._client:
            return
        try:
            await self._client.post(self._api("setMyCommands"), json={"commands": [
                {"command": "menu", "description": "Mint a code"},
                {"command": "list", "description": "Live grants"},
                {"command": "presets", "description": "Saved presets"},
                {"command": "help", "description": "How to use this"},
            ]})
        except Exception as exc:
            log.warning("setMyCommands failed: %s", exc)

    async def broadcast(self, text: str) -> None:
        for c in self._chats:
            await self.send(c, text)

    # ---- lifecycle ------------------------------------------------------

    async def run(self) -> None:
        """Long-poll forever, restarting on error.

        A wedged or crashed poller means you cannot mint a code, and you find
        out when somebody is standing at the gate. Every failure is recorded in
        the status dict the admin panel reads.
        """
        if not self.configured:
            self._status["running"] = False
            self._status["last_error"] = "no bot token or chat id configured"
            return
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(70.0, connect=10.0))
        await self._publish_commands()
        backoff = 1
        try:
            while True:
                try:
                    await self._poll_once()
                    self._status.update(
                        {"running": True, "last_ok": now(), "last_error": None}
                    )
                    backoff = 1
                except asyncio.CancelledError:
                    raise
                except httpx.HTTPStatusError as exc:
                    if exc.response is not None and exc.response.status_code == 409:
                        # Two pollers on one token: Telegram refuses both.
                        # Usually a previous instance that has not exited yet.
                        msg = "another poller holds this bot token (409)"
                    else:
                        msg = f"telegram http error: {exc}"
                    await self._fail(msg, backoff)
                    backoff = min(60, backoff * 2)
                except Exception as exc:
                    await self._fail(f"{type(exc).__name__}: {exc}", backoff)
                    backoff = min(60, backoff * 2)
        finally:
            self._status["running"] = False
            if self._client:
                await self._client.aclose()

    async def _fail(self, msg: str, backoff: int) -> None:
        log.warning("bot poll failed: %s (retry in %ss)", msg, backoff)
        self._status.update({"running": False, "last_error": msg})
        if self._on_error:
            try:
                res = self._on_error(msg)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass
        await asyncio.sleep(backoff)

    async def _poll_once(self) -> None:
        assert self._client
        r = await self._client.get(
            self._api("getUpdates"),
            params={"timeout": 50, "offset": self._offset, "allowed_updates": '["message","callback_query"]'},
        )
        r.raise_for_status()
        for update in r.json().get("result", []):
            self._offset = max(self._offset, int(update["update_id"]) + 1)
            await self._handle(update)

    async def _handle(self, update: dict) -> None:
        callback = update.get("callback_query")
        if callback:
            chat_id = ((callback.get("message") or {}).get("chat") or {}).get("id")
            # A tapped button is authorised exactly like a typed command. Both
            # carry the chat, and neither is trusted without the allowlist.
            if chat_id is None or int(chat_id) not in self._chats:
                log.info("ignored callback from unlisted chat %s", chat_id)
                return
            try:
                await self._on_callback(int(chat_id), callback)
            except Exception as exc:
                log.exception("callback failed")
                await self._answer_callback(callback.get("id", ""), "Something went wrong")
                await self.send(chat_id, f"Something went wrong: {html.escape(str(exc))}")
            return

        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        text = (message.get("text") or "").strip()
        if chat_id is None or not text:
            return
        if int(chat_id) not in self._chats:
            # No reply. Silence does not confirm the bot exists.
            log.info("ignored message from unlisted chat %s", chat_id)
            return
        try:
            await self._command(int(chat_id), text)
        except Exception as exc:
            log.exception("command failed")
            await self.send(chat_id, f"Something went wrong: {html.escape(str(exc))}")

    # ---- commands -------------------------------------------------------

    async def _command(self, chat_id: int, text: str) -> None:
        parts = text.split()
        cmd = parts[0].lower().split("@")[0]
        args = parts[1:]
        if cmd in ("/start", "/menu"):
            await self._menu(chat_id)
        elif cmd == "/help":
            await self.send(chat_id, HELP)
        elif cmd == "/new":
            await self._new(chat_id, args)
        elif cmd == "/list":
            await self._list(chat_id)
        elif cmd == "/revoke":
            await self._revoke(chat_id, args)
        elif cmd == "/extend":
            await self._extend(chat_id, args)
        elif cmd == "/presets":
            await self._presets(chat_id)
        else:
            await self.send(chat_id, "Unknown command. /help for the list.")


    # ---- buttons --------------------------------------------------------

    async def _menu(self, chat_id: int) -> None:
        """The main screen: one button per preset, because a preset is exactly
        'the thing I mint often'. Typing entity ids one-handed at a gate is the
        interface this replaces."""
        presets = await asyncio.to_thread(self._store.list_presets)
        if not presets:
            await self.send(
                chat_id,
                "<b>No presets yet.</b>\n\nCreate one in the Gate PIN panel "
                "(Presets tab) and it appears here as a button.\n\n"
                "Until then: <code>/new 2h cover.driveway</code>",
                buttons=[[("Live grants", "list")]],
            )
            return

        rows, row = [], []
        for pre in presets[:12]:
            row.append(
                (
                    f"{pre['name']} · {humanise(pre['duration_s'])} · {_kinds(pre['kinds'])}",
                    f"m:{pre['id']}",
                )
            )
            if len(row) == 2:
                rows.append(row); row = []
        if row:
            rows.append(row)
        rows.append([("Live grants", "list")])

        live = await asyncio.to_thread(self._store.live_pin_grant_count)
        await self.send(
            chat_id,
            f"<b>Mint a code</b>\nLive PIN grants: {live}/{self._cap}",
            buttons=rows,
        )

    async def _on_callback(self, chat_id: int, callback: dict) -> None:
        cid = callback.get("id", "")
        data = callback.get("data") or ""
        action, _, arg = data.partition(":")

        if action == "m":
            preset = next(
                (p for p in await asyncio.to_thread(self._store.list_presets) if p["id"] == arg),
                None,
            )
            if not preset:
                await self._answer_callback(cid, "That preset is gone")
                return
            await self._answer_callback(cid, "Minting...")
            await self._mint_and_reply(
                chat_id,
                label=preset["name"],
                entities=preset["entities"],
                duration=preset["duration_s"],
                theme=preset["theme"],
                kinds=preset["kinds"],
            )

        elif action == "list":
            await self._answer_callback(cid)
            await self._list(chat_id)

        elif action == "r":
            ok = await asyncio.to_thread(self._store.revoke_grant, arg)
            if ok:
                await asyncio.to_thread(
                    self._store.log, "revoke", grant_id=arg, detail="via telegram button"
                )
                await self._answer_callback(cid, "Revoked")
                await self.send(chat_id, f"Revoked <code>{html.escape(arg)}</code>. Both credentials are dead.")
            else:
                await self._answer_callback(cid, "Already gone")

        elif action == "i":
            grant_id, _, kind = arg.partition(":")
            try:
                result = await asyncio.to_thread(
                    g.reissue, self._store, grant_id,
                    kinds=[kind or "token"],
                    pin_length=self._pin_length,
                    max_live_pin_grants=self._cap,
                )
            except g.MintError as exc:
                await self._answer_callback(cid, str(exc)[:180])
                return
            await self._answer_callback(cid, "New credential issued")
            # The previous key of this kind has just stopped working, and that
            # is easy to miss when it happened via a button.
            await self.send(
                chat_id,
                f"<b>{html.escape(result.grant.label or 'Grant')}</b> · "
                f"<code>{result.grant.id}</code>\n"
                f"New {'PIN' if kind == 'pin' else 'link'} issued. The previous one "
                f"no longer works.\nValid until {_clock(result.grant.valid_until)}",
                buttons=[[("Revoke", f"r:{result.grant.id}")]],
            )
            if result.pin:
                await self.send(chat_id, f"PIN <code>{result.pin}</code>")
            link = result.link(self._base_url)
            if link:
                await self.send(chat_id, link)

        elif action == "x":
            grant_id, _, secs = arg.partition(":")
            grant = await asyncio.to_thread(self._store.get_grant, grant_id)
            if grant is None or grant.status() != "active":
                await self._answer_callback(cid, "Only a live grant can be extended")
                return
            extra = int(secs or 3600)
            if await asyncio.to_thread(self._store.extend_grant, grant.id, grant.valid_until + extra):
                await asyncio.to_thread(
                    self._store.log, "extend", grant_id=grant.id, detail=f"+{extra}s via telegram button"
                )
                await self._answer_callback(cid, f"Extended by {humanise(extra)}")
                await self.send(chat_id, f"<code>{html.escape(grant.id)}</code> now valid until {_clock(grant.valid_until + extra)}.")
            else:
                await self._answer_callback(cid, "Could not extend")

        else:
            await self._answer_callback(cid)

    async def _mint_and_reply(self, chat_id, *, label, entities, duration, theme, kinds):
        start = now()
        try:
            result = await asyncio.to_thread(
                g.mint, self._store,
                label=label, entities=entities,
                valid_from=start, valid_until=start + duration,
                theme=theme, kinds=kinds,
                pin_length=self._pin_length, max_live_pin_grants=self._cap,
            )
        except g.MintError as exc:
            await self.send(chat_id, f"Refused: {html.escape(str(exc))}")
            return

        await self.send(
            chat_id,
            f"<b>{html.escape(result.grant.label or 'Grant')}</b> · <code>{result.grant.id}</code>\n"
            f"{html.escape(', '.join(result.grant.entities))}\n"
            f"Valid {humanise(duration)}, until {_clock(result.grant.valid_until)}",
            buttons=[[
                ("+1 hour", f"x:{result.grant.id}:3600"),
                ("Revoke", f"r:{result.grant.id}"),
            ]],
        )
        # PIN and link in SEPARATE messages, so forwarding the link to a visitor
        # does not also forward the PIN.
        if result.pin:
            await self.send(chat_id, f"PIN <code>{result.pin}</code>")
        link = result.link(self._base_url)
        if link:
            await self.send(chat_id, link)

    async def _new(self, chat_id: int, args: list[str]) -> None:
        if not args:
            await self.send(chat_id, "Usage: <code>/new 2h cover.driveway</code> or <code>/new plumber</code>")
            return

        kinds = ["pin", "token"]
        flags = {a.lower() for a in args if a.startswith("--")}
        args = [a for a in args if not a.startswith("--")]
        if "--pin-only" in flags:
            kinds = ["pin"]
        elif "--token-only" in flags:
            kinds = ["token"]

        preset = await asyncio.to_thread(self._store.get_preset_by_name, args[0])
        if preset:
            label = " ".join(args[1:]) or preset["name"]
            entities, duration, theme = preset["entities"], preset["duration_s"], preset["theme"]
            if not flags:
                kinds = preset["kinds"]
        else:
            try:
                duration = parse_duration(args[0])
            except DurationError as exc:
                await self.send(chat_id, f"{html.escape(str(exc))} Or name a preset — /presets.")
                return
            entities = [a for a in args[1:] if "." in a]
            label = " ".join(a for a in args[1:] if "." not in a)
            theme = await asyncio.to_thread(self._store.get_setting, "default_theme", "dark")
            if not entities:
                await self.send(chat_id, "Name at least one entity, e.g. <code>cover.driveway</code>")
                return

        await self._mint_and_reply(
            chat_id, label=label, entities=entities,
            duration=duration, theme=theme, kinds=kinds,
        )

    async def _list(self, chat_id: int) -> None:
        grants = await asyncio.to_thread(self._store.list_grants, False)
        if not grants:
            await self.send(chat_id, "No live grants.")
            return
        lines = []
        t = now()
        for x in grants:
            state = "starts " + humanise(x.valid_from - t) if x.status() == "scheduled" else humanise(x.valid_until - t) + " left"
            lines.append(
                f"<code>{x.id}</code> · {html.escape(x.label or 'unlabelled')} · "
                f"{state} · {'+'.join(x.kinds)}"
            )
        cap = await asyncio.to_thread(self._store.live_pin_grant_count)
        lines.append(f"\nLive PIN grants: {cap}/{self._cap}")
        buttons = []
        for x in grants[:6]:
            row = []
            if "token" in x.kinds:
                row.append((f"New link · {x.label or x.id}"[:26], f"i:{x.id}:token"))
            if "pin" in x.kinds:
                row.append((f"New PIN · {x.label or x.id}"[:26], f"i:{x.id}:pin"))
            if row:
                buttons.append(row)
            buttons.append([(f"Revoke {x.label or x.id}"[:28], f"r:{x.id}")])
        await self.send(chat_id, "\n".join(lines), buttons=buttons or None)

    async def _revoke(self, chat_id: int, args: list[str]) -> None:
        if not args:
            await self.send(chat_id, "Usage: <code>/revoke &lt;id&gt;</code>")
            return
        ok = await asyncio.to_thread(self._store.revoke_grant, args[0])
        if ok:
            await asyncio.to_thread(self._store.log, "revoke", grant_id=args[0], detail="via telegram")
            await self.send(chat_id, f"Revoked <code>{html.escape(args[0])}</code>. Both credentials are dead.")
        else:
            await self.send(chat_id, "No such live grant.")

    async def _extend(self, chat_id: int, args: list[str]) -> None:
        if len(args) < 2:
            await self.send(chat_id, "Usage: <code>/extend &lt;id&gt; 1h</code>")
            return
        grant = await asyncio.to_thread(self._store.get_grant, args[0])
        if grant is None:
            await self.send(chat_id, "No such grant.")
            return
        if grant.status() != "active":
            await self.send(
                chat_id,
                f"That grant is {grant.status()}. Only a live grant can be extended — mint a new one.",
            )
            return
        try:
            extra = parse_duration(args[1])
        except DurationError as exc:
            await self.send(chat_id, html.escape(str(exc)))
            return
        new_until = grant.valid_until + extra
        if await asyncio.to_thread(self._store.extend_grant, grant.id, new_until):
            await asyncio.to_thread(self._store.log, "extend", grant_id=grant.id, detail=f"+{extra}s via telegram")
            await self.send(chat_id, f"Extended to {_clock(new_until)}.")
        else:
            await self.send(chat_id, "Could not extend that grant.")

    async def _presets(self, chat_id: int) -> None:
        presets = await asyncio.to_thread(self._store.list_presets)
        if not presets:
            await self.send(chat_id, "No presets yet. Create them in the admin panel.")
            return
        await self.send(
            chat_id,
            "\n".join(
                f"<code>{html.escape(p['name'])}</code> · {humanise(p['duration_s'])} · "
                f"{_kinds(p['kinds'])} · {html.escape(', '.join(p['entities']))}"
                for p in presets
            ),
        )


def _kinds(kinds: Sequence[str]) -> str:
    """What a preset will hand you, in the words the messages already use --
    a menu button that mints a link only should say so before it is tapped."""
    return " + ".join("PIN" if k == "pin" else "link" for k in kinds) or "nothing"


def _clock(epoch: int) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(epoch).strftime("%a %H:%M")
