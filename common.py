"""Bot qismlari (features.py va admin.py) uchun umumiy yordamchilar."""
import json

from aiogram.exceptions import TelegramBadRequest

import db
from config import ADMIN_IDS

COIN = "🪙"

# Bot bosh menyusidagi sozlanadigan tugmalar (callback_data = "menu_<id>")
MENU_ITEMS = {
    "boxes": "🎁 Super Qutilar",
    "signal": "📡 Bulldrop Signal",
    "inventory": "🎒 Inventory",
    "account": "👤 Hisobim",
    "games": "🎮 Botdagi o‘yinlar",
    "rewards": "🏆 Yutuqlarim",
    "stats": "📊 Statistika",
    "support": "💬 Bot support",
}
MENU_STYLES = [None, "primary", "success", "danger"]
STYLE_EMOJI = {None: "⚪", "primary": "🔵", "success": "🟢", "danger": "🔴"}


def menu_layout() -> dict:
    """Menyu tugmalari tartibi, yashirilganlari va ranglari: {"order": [...], "hidden": [...], "style": {id: rang}}."""
    try:
        saved = json.loads(db.get_setting("menu_layout") or "{}")
    except ValueError:
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    order = [i for i in saved.get("order", []) if i in MENU_ITEMS]
    order += [i for i in MENU_ITEMS if i not in order]
    hidden = [i for i in saved.get("hidden", []) if i in MENU_ITEMS]
    style = {k: v for k, v in (saved.get("style") or {}).items() if k in MENU_ITEMS and v in MENU_STYLES}
    return {"order": order, "hidden": hidden, "style": style}


def save_menu_layout(layout: dict) -> None:
    db.set_setting("menu_layout", json.dumps(layout, ensure_ascii=False))


def fmt_num(value) -> str:
    return f"{int(value):,}".replace(",", " ")


def channel_url(channel: str) -> str:
    """@kanal ko'rinishidagi kanal uchun havola; maxfiy (raqamli ID) kanal uchun bo'sh qator."""
    return f"https://t.me/{channel[1:]}" if channel and channel.startswith("@") else ""


async def edit_or_send(message, text: str, reply_markup=None) -> None:
    """Xabarni tahrirlaydi. Tahrirlab bo'lmasa (masalan, xabar rasmli bo'lsa), o'chirib qaytadan yuboradi."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, reply_markup=reply_markup)


def extract_media(message):
    """Admin yuborgan xabardan rasm/GIF/stiker/havolani oladi.

    Qaytaradi: 'tg:<tur>:<file_id>' yoki https:// havola; "-" bo'lsa ""; tushunarsiz bo'lsa None.
    Tur: img (rasm, oddiy stiker), vid (GIF, video, video-stiker), tgs (animatsion stiker)."""
    if message.photo:
        return "tg:img:" + message.photo[-1].file_id
    if message.animation:
        return "tg:vid:" + message.animation.file_id
    if message.video:
        return "tg:vid:" + message.video.file_id
    if message.sticker:
        sticker = message.sticker
        if sticker.is_animated:
            return "tg:tgs:" + sticker.file_id
        if sticker.is_video:
            return "tg:vid:" + sticker.file_id
        return "tg:img:" + sticker.file_id
    if message.document:
        mime = message.document.mime_type or ""
        if mime.startswith("image/"):
            return "tg:img:" + message.document.file_id
        if mime in ("video/mp4", "video/webm"):
            return "tg:vid:" + message.document.file_id
    text = (message.text or "").strip()
    if not text:
        return None
    if text == "-":
        return ""
    if text.lower().startswith(("http://", "https://")):
        return text
    return None


async def check_subscription(bot, user_id: int):
    """(a'zomi, kanal) juftligi. Kanal sozlanmagan yoki foydalanuvchi admin bo'lsa — a'zo hisoblanadi.
    Tekshirib bo'lmasa (bot kanalda admin emas), foydalanuvchini bloklamaymiz."""
    channel = db.get_setting("required_channel")
    if not channel or user_id in ADMIN_IDS:
        return True, channel
    chat = int(channel) if channel.lstrip("-").isdigit() else channel
    try:
        member = await bot.get_chat_member(chat, user_id)
    except Exception:
        return True, channel
    return member.status in ("creator", "administrator", "member", "restricted"), channel
