"""Application entrypoint: FastAPI app, Telegram poller, watchdog."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from gate_pin.bot import TelegramBot
from gate_pin.ha import HomeAssistant
from gate_pin.ratelimit import RateLimiter
from gate_pin.store import Store, load_or_create_secret

from . import options as options_mod
from . import routes_admin, routes_guest
from .deps import Deps
from .token import supervisor_token

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("gate_pin")

AUDIT_PRUNE_INTERVAL_S = 6 * 3600
BOT_HEARTBEAT_CHECK_S = 60
BOT_STALE_AFTER_S = 300


@asynccontextmanager
async def lifespan(app: FastAPI):
    opts = options_mod.load()
    secret = load_or_create_secret(opts.secret_path)
    store = Store(opts.db_path, secret)
    ha = HomeAssistant(supervisor_token)
    limiter = RateLimiter(global_budget=20, cooldown_s=900)
    bot_status: dict = {}

    app.state.deps = Deps(
        store=store,
        secret=secret,
        ha=ha,
        limiter=limiter,
        options=opts,
        bot_status=bot_status,
    )
    Path(opts.branding_dir).mkdir(parents=True, exist_ok=True)

    async def alert(message: str) -> None:
        if opts.notify_service:
            await ha.notify(opts.notify_service, "Gate PIN", message)
        else:
            await ha.persistent_notification("Gate PIN", message)

    bot = TelegramBot(
        token=opts.telegram_bot_token,
        chat_ids=opts.telegram_chat_ids,
        store=store,
        base_url=opts.external_base_url,
        pin_length=opts.pin_length,
        max_live_pin_grants=opts.max_live_pin_grants,
        status=bot_status,
        on_error=None,
    )
    app.state.bot = bot

    tasks = [
        asyncio.create_task(_supervise_bot(bot, alert), name="bot"),
        asyncio.create_task(_watch_bot_heartbeat(bot, bot_status, alert), name="bot-watchdog"),
        asyncio.create_task(_prune(store, opts.audit_retention_days), name="prune"),
    ]

    log.info(
        "gate-pin ready · base_url=%s · pin_len=%d · pin_cap=%d · telegram=%s",
        opts.external_base_url,
        opts.pin_length,
        opts.max_live_pin_grants,
        "configured" if bot.configured else "not configured",
    )
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await ha.aclose()
        store.close()


async def _supervise_bot(bot: TelegramBot, alert) -> None:
    """Restart the poller if it ever returns."""
    if not bot.configured:
        log.info("telegram not configured; poller not started")
        return
    while True:
        try:
            await bot.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("bot poller crashed: %s", exc)
        await asyncio.sleep(10)


async def _watch_bot_heartbeat(bot: TelegramBot, status: dict, alert) -> None:
    """Alert when the bot stops answering.

    Watches the heartbeat rather than waiting for the poller coroutine to
    return, because it never does -- bot.run() handles its own errors and
    retries forever. Without this a wedged bot is silent until the evening
    somebody is standing at the gate and you cannot mint a code.

    Announced once per outage, not once per retry, so an outage does not become
    its own notification flood.
    """
    if not bot.configured:
        return
    announced = False
    while True:
        await asyncio.sleep(BOT_HEARTBEAT_CHECK_S)
        last_ok = status.get("last_ok")
        stale = last_ok is None or (int(time.time()) - int(last_ok)) > BOT_STALE_AFTER_S
        down = stale or not status.get("running")
        if down and not announced:
            announced = True
            detail = status.get("last_error") or "no successful poll recently"
            log.warning("telegram bot appears down: %s", detail)
            try:
                await alert(f"The Telegram bot has stopped responding ({detail}). You cannot mint codes from Telegram until it recovers.")
            except Exception:
                pass
        elif not down and announced:
            announced = False
            log.info("telegram bot recovered")
            try:
                await alert("The Telegram bot is responding again.")
            except Exception:
                pass


async def _prune(store: Store, retention_days: int) -> None:
    while True:
        try:
            removed = await asyncio.to_thread(store.prune_audit, retention_days)
            if removed:
                log.info("pruned %d audit rows older than %dd", removed, retention_days)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("audit prune failed: %s", exc)
        await asyncio.sleep(AUDIT_PRUNE_INTERVAL_S)


app = FastAPI(
    title="Gate PIN",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.include_router(routes_guest.router)
app.include_router(routes_admin.router)


@app.get("/api/guest/logo")
async def guest_logo(request: Request):
    """Serve the branding logo from the add-on itself.

    Never hotlinked from elsewhere: a third-party asset request from the guest
    page would carry the link token out in the Referer header.
    """
    d = request.app.state.deps
    name = await asyncio.to_thread(d.store.get_setting, "logo", "")
    if not name:
        return JSONResponse({"detail": "no logo"}, status_code=404)
    path = Path(d.options.branding_dir) / name
    if not path.exists():
        return JSONResponse({"detail": "no logo"}, status_code=404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=300"})


def run() -> None:
    uvicorn.run(
        app,
        host="127.0.0.1",  # never bound publicly; nginx is the only front door
        port=int(os.environ.get("GATE_PIN_PORT", "8080")),
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    run()
