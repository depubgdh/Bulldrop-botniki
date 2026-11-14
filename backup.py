"""Bazani Telegram orqali zaxiralash va tiklash.

Render'ning bepul tarifida disk doimiy emas: har deploy/qayta ishga tushishda bulldrop.sqlite3 o'chadi
(telefon raqamlar, coin, sovg'alar yo'qoladi). Bu modul bazaning nusxasini birinchi adminning shaxsiy
chatiga fayl qilib yuboradi va qadab (pin) qo'yadi. Bot qayta ishga tushganda baza yo'q bo'lsa,
qadalgan fayldan avtomatik tiklaydi.
"""
import asyncio
import hashlib
import logging
import os
import sqlite3
import tempfile
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile

import db
from config import ADMIN_IDS, BOT_TOKEN

log = logging.getLogger("backup")
FILE_PREFIX = "bulldrop-backup"
INTERVAL = int(os.getenv("BACKUP_INTERVAL", "180"))  # soniya
_last_hash = None
_last_msg_id = None


def _target():
    return min(ADMIN_IDS) if ADMIN_IDS else None


def _snapshot(dest: Path) -> None:
    """Ishlayotgan bazadan izchil nusxa (SQLite backup API)."""
    src = sqlite3.connect(db.DB_PATH)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            try:  # g‘ildirak raundlari tez-tez o‘zgaradi va tiklash uchun kerak emas
                dst.execute("DELETE FROM wheel_rounds")
                dst.commit()
            except sqlite3.Error:
                pass
        finally:
            dst.close()
    finally:
        src.close()


def _logical_hash(path: Path) -> str:
    con = sqlite3.connect(path)
    try:
        h = hashlib.sha256()
        for line in con.iterdump():
            h.update(line.encode("utf-8", "replace"))
        return h.hexdigest()
    finally:
        con.close()


def _has_data(path: Path) -> bool:
    try:
        con = sqlite3.connect(path)
        try:
            return con.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
        finally:
            con.close()
    except Exception:
        return False


async def restore_if_needed() -> None:
    """Baza fayli yo'q bo'lsa, qadalgan zaxiradan tiklaydi. Hech qachon mavjud bazani ustiga yozmaydi."""
    target = _target()
    if not BOT_TOKEN or not target:
        return
    if db.DB_PATH.exists() and _has_data(db.DB_PATH):
        return
    bot = Bot(token=BOT_TOKEN)
    try:
        chat = await bot.get_chat(target)
        pinned = chat.pinned_message
        doc = pinned.document if pinned else None
        if not doc or not (doc.file_name or "").startswith(FILE_PREFIX):
            log.warning("Zaxira topilmadi (adminning chatida qadalgan fayl yo'q). Baza bo'sh boshlanadi.")
            return
        db.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = db.DB_PATH.with_suffix(".restore")
        await bot.download(doc.file_id, destination=tmp)
        if not _has_data(tmp):
            tmp.unlink(missing_ok=True)
            log.warning("Zaxira fayli bo'sh yoki buzuq — tiklanmadi.")
            return
        os.replace(tmp, db.DB_PATH)
        global _last_hash, _last_msg_id
        _last_msg_id = pinned.message_id
        log.warning("Baza zaxiradan tiklandi (%s).", doc.file_name)
    except Exception:
        log.exception("Zaxiradan tiklashda xato")
    finally:
        await bot.session.close()


async def save_now(bot: Bot) -> bool:
    """Baza o'zgargan bo'lsa, zaxirani yuboradi. True — yuborildi."""
    global _last_hash, _last_msg_id
    target = _target()
    if not target or not db.DB_PATH.exists():
        return False
    with tempfile.TemporaryDirectory() as tmpdir:
        snap = Path(tmpdir) / (FILE_PREFIX + ".sqlite3")
        await asyncio.to_thread(_snapshot, snap)
        digest = await asyncio.to_thread(_logical_hash, snap)
        if digest == _last_hash:
            return False
        msg = await bot.send_document(
            target, FSInputFile(snap, filename=FILE_PREFIX + ".sqlite3"),
            caption="🗄 BULLDROP bazasi (avto-zaxira). Bu xabarni o'chirmang.", disable_notification=True,
        )
        try:
            await bot.pin_chat_message(target, msg.message_id, disable_notification=True)
        except Exception:
            log.exception("Zaxirani qadab bo'lmadi")
        if _last_msg_id and _last_msg_id != msg.message_id:
            try:
                await bot.delete_message(target, _last_msg_id)
            except Exception:
                pass
        _last_msg_id, _last_hash = msg.message_id, digest
        return True


async def backup_loop(bot: Bot) -> None:
    await asyncio.sleep(20)
    while True:
        try:
            if await save_now(bot):
                log.info("Baza zaxirasi yuborildi")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Zaxira yuborishda xato (bot adminga yozishi uchun admin botga /start bosgan bo'lishi kerak)")
        await asyncio.sleep(INTERVAL)
