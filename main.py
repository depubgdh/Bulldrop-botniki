import asyncio
import logging
import hashlib
import os
from pathlib import Path

from aiohttp import web
import signal
import backup
from bot import main as run_bot, build as build_bot
from webapi import setup_routes
import crane
import ladder
import mines
import tower
import wheel


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "bulldrop", "wheel": hasattr(wheel, "place_bet"), "mines": hasattr(mines, "start"), "tower": hasattr(tower, "start"), "ladder": hasattr(ladder, "start"), "crane": hasattr(crane, "start")})


async def miniapp(request: web.Request) -> web.FileResponse:
    response = web.FileResponse(Path(__file__).with_name("index.html"))
    # Telegram eski sahifani keshlab qo'ymasligi uchun
    response.headers["Cache-Control"] = "no-store"
    return response


BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
# Webhook rejimi: WEBHOOK_URL (yoki WEBAPP_URL) berilsa va WEBHOOK=1 bo'lsa (Cloud Run). Aks holda polling.
WEBHOOK_BASE = (os.getenv("WEBHOOK_URL") or os.getenv("WEBAPP_URL") or "").strip().rstrip("/")
USE_WEBHOOK = os.getenv("WEBHOOK", "").strip().lower() in ("1", "true", "yes") and bool(WEBHOOK_BASE)
_SECRET = hashlib.sha256(("bulldrop:" + BOT_TOKEN).encode()).hexdigest()[:32]
WEBHOOK_PATH = "/tg/" + _SECRET


async def start_web_server(bot=None, dp=None) -> web.AppRunner:
    app = web.Application(client_max_size=12 * 1024 * 1024)
    app.router.add_get("/", miniapp)
    app.router.add_get("/miniapp", miniapp)
    app.router.add_get("/healthz", health)
    setup_routes(app)
    if bot is not None:
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler
        # handle_in_background=False: javob yangilanish ishlanib bo'lgach qaytadi (Cloud Run javobdan keyin CPU'ni cheklaydi)
        SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=_SECRET, handle_in_background=False).register(app, path=WEBHOOK_PATH)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "10000"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.info("BULLDROP web server listening on 0.0.0.0:%s", port)
    return runner


async def main_webhook() -> None:
    bot, dp = await build_bot()
    runner = await start_web_server(bot, dp)
    wheel_task = asyncio.create_task(wheel.tick_loop())
    backup_task = asyncio.create_task(backup.backup_loop(bot))
    try:
        try:
            await bot.set_webhook(WEBHOOK_BASE + WEBHOOK_PATH, secret_token=_SECRET,
                                  allowed_updates=dp.resolve_used_update_types())
            logging.info("Webhook o'rnatildi: %s/tg/***", WEBHOOK_BASE)
        except Exception:
            logging.exception("Webhook o'rnatilmadi (WEBHOOK_URL ni tekshiring)")
        await asyncio.Event().wait()
    finally:
        wheel_task.cancel()
        backup_task.cancel()
        try:
            await backup.save_now(bot)  # o'chirishdan oldin oxirgi zaxira
        except Exception:
            logging.exception("Yakuniy zaxira yuborilmadi")
        await bot.session.close()
        await runner.cleanup()


async def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Baza yo'q bo'lsa (server qayta ishga tushgan) — veb-server ochilishidan oldin Telegramdagi zaxiradan tiklaymiz
    await backup.restore_if_needed()
    task = asyncio.current_task()
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    except (NotImplementedError, RuntimeError):
        pass
    if USE_WEBHOOK:
        await main_webhook()
        return
    runner = await start_web_server()
    wheel_task = asyncio.create_task(wheel.tick_loop())
    try:
        await run_bot()
    finally:
        wheel_task.cancel()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
