import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
import db
from admin import router as admin_router
from features import router

async def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN .env faylida kiritilmagan.")
    logging.basicConfig(level=logging.INFO)
    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    # Admin router birinchi bo'lishi kerak: uning holat (state) handlerlari fallback'dan oldin ishlaydi
    dp.include_router(admin_router)
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
