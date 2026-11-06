import asyncio
import logging
import os
from aiohttp import web

from bot import main as run_bot


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "bulldrop"})


async def start_web_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/healthz", health)

    runner = web.AppRunner(app)
    await runner.setup()

    # Render injects PORT automatically. Do not hardcode 8000 or 8080.
    port = int(os.environ.get("PORT", "10000"))
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logging.info("BULLDROP health server listening on 0.0.0.0:%s", port)
    return runner


async def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    runner = await start_web_server()
    try:
        # Run Telegram long polling alongside the HTTP server.
        await run_bot()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
