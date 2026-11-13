import asyncio
import logging
import os
from pathlib import Path

from aiohttp import web
import signal
import backup
from bot import main as run_bot
from webapi import setup_routes
import wheel


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "bulldrop", "wheel": hasattr(wheel, "play")})


async def miniapp(request: web.Request) -> web.FileResponse:
    response = web.FileResponse(Path(__file__).with_name("index.html"))
    # Telegram eski sahifani keshlab qo'ymasligi uchun
    response.headers["Cache-Control"] = "no-store"
    return response


async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", miniapp)
    app.router.add_get("/miniapp", miniapp)
    app.router.add_get("/healthz", health)
    setup_routes(app)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "10000"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.info("BULLDROP web server listening on 0.0.0.0:%s", port)
    return runner


async def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Baza yo'q bo'lsa (Render qayta ishga tushgan) — veb-server ochilishidan oldin Telegramdagi zaxiradan tiklaymiz
    await backup.restore_if_needed()
    task = asyncio.current_task()
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    except (NotImplementedError, RuntimeError):
        pass
    runner = await start_web_server()
    try:
        await run_bot()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
