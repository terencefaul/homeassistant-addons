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

    async def send(self, chat_id: int, text: str) -> None:
        if not self._client:
            return
        try:
            await self._client.post(
                self._api("sendMessage"),
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        except Exception as exc:
            log.warning("sendMessage failed: %s", exc)

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
            params={"timeout": 50, "offset": self._offset, "allowed_updates": '["message"]'},
        )
        r.raise_for_status()
        for update in r.json().get("result", []):
            self._offset = max(self._offset, int(update["update_id"]) + 1)
            await self._handle(update)

    async def _handle(self, update: dict) -> None:
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
        if cmd in ("/start", "/help"):
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

        start = now()
        try:
            result = await asyncio.to_thread(
                g.mint,
                self._store,
                label=label,
                entities=entities,
                valid_from=start,
                valid_until=start + duration,
                theme=theme,
                kinds=kinds,
                pin_length=self._pin_length,
                max_live_pin_grants=self._cap,
            )
        except g.MintError as exc:
            await self.send(chat_id, f"Refused: {html.escape(str(exc))}")
            return

        await self.send(
            chat_id,
            f"<b>{html.escape(result.grant.label or 'Grant')}</b> · <code>{result.grant.id}</code>\n"
            f"{html.escape(', '.join(result.grant.entities))}\n"
            f"Valid {humanise(duration)}, until {_clock(result.grant.valid_until)}",
        )
        # PIN and link go in SEPARATE messages, so forwarding the link to a
        # visitor does not also forward the PIN.
        if result.pin:
            await self.send(chat_id, f"PIN <code>{result.pin}</code>")
        link = result.link(self._base_url)
        if link:
            await self.send(chat_id, link)

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
        await self.send(chat_id, "\n".join(lines))

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
                f"{html.escape(', '.join(p['entities']))}"
                for p in presets
            ),
        )


def _clock(epoch: int) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(epoch).strftime("%a %H:%M")
