import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
import db
import backup
from admin import router as admin_router
from features import router

async def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN .env faylida kiritilmagan.")
    logging.basicConfig(level=logging.INFO)
    await backup.restore_if_needed()
    db.init_db()
    bot = Bot(token=BOT_TOKEN)
    backup_task = asyncio.create_task(backup.backup_loop(bot))
    dp = Dispatcher(storage=MemoryStorage())
    # Admin router birinchi bo'lishi kerak: uning holat (state) handlerlari fallback'dan oldin ishlaydi
    dp.include_router(admin_router)
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    finally:
        backup_task.cancel()
        try:
            await backup.save_now(bot)  # o'chirishdan oldin oxirgi zaxira
        except Exception:
            logging.exception("Yakuniy zaxira yuborilmadi")

if __name__ == "__main__":
    asyncio.run(main())
