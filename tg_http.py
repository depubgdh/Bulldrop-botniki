"""Telegram Bot API'ga to'g'ridan-to'g'ri HTTP so'rovlar: media proksi va kanal a'zoligini tekshirish."""
import gzip
import time

import aiohttp

from config import BOT_TOKEN

API = "https://api.telegram.org"
_CACHE_MAX = 128
_files = {}      # file_id -> (vaqt, bytes, content_type)
_members = {}    # (chat, user_id) -> (vaqt, bool)

_TYPES = {
    ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".mp4": "video/mp4", ".webm": "video/webm", ".tgs": "application/json",
}


def _content_type(path: str) -> str:
    for ext, ctype in _TYPES.items():
        if path.lower().endswith(ext):
            return ctype
    return "application/octet-stream"


async def fetch_file(file_id: str):
    """Telegram fayli (rasm, GIF, stiker) baytlarini va content-type ni qaytaradi. .tgs JSON'ga aylantiriladi."""
    hit = _files.get(file_id)
    if hit and time.time() - hit[0] < 3600:
        return hit[1], hit[2]
    if not BOT_TOKEN:
        return None
    timeout = aiohttp.ClientTimeout(total=25)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{API}/bot{BOT_TOKEN}/getFile", params={"file_id": file_id}) as resp:
                info = await resp.json()
            if not info.get("ok"):
                return None
            path = (info.get("result") or {}).get("file_path")
            if not path:
                return None
            async with session.get(f"{API}/file/bot{BOT_TOKEN}/{path}") as resp:
                if resp.status != 200:
                    return None
                body = await resp.read()
    except (aiohttp.ClientError, ValueError, TimeoutError):
        return None

    ctype = _content_type(path)
    if path.lower().endswith(".tgs"):  # animatsion stiker: gzip'langan Lottie JSON
        try:
            body = gzip.decompress(body)
        except OSError:
            return None
    if len(_files) >= _CACHE_MAX:
        _files.pop(min(_files, key=lambda k: _files[k][0]), None)
    _files[file_id] = (time.time(), body, ctype)
    return body, ctype


async def is_subscribed(chat, user_id: int) -> bool:
    """Foydalanuvchi kanalga a'zomi. Tekshirib bo'lmasa (bot admin emas va hokazo), True qaytaradi —
    noto'g'ri sozlama hammani bloklab qo'ymasligi uchun."""
    key = (str(chat), int(user_id))
    hit = _members.get(key)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    if not BOT_TOKEN:
        return True
    chat_id = int(chat) if str(chat).lstrip("-").isdigit() else str(chat)
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                f"{API}/bot{BOT_TOKEN}/getChatMember",
                params={"chat_id": chat_id, "user_id": int(user_id)},
            ) as resp:
                data = await resp.json()
    except (aiohttp.ClientError, ValueError, TimeoutError):
        return True
    if not data.get("ok"):
        return True
    ok = (data.get("result") or {}).get("status") in ("creator", "administrator", "member", "restricted")
    if len(_members) > 5000:
        _members.clear()
    _members[key] = (time.time(), ok)
    return ok
