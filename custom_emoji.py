"""Maxsus (custom) emoji: botdagi oddiy emojilarni Telegram'ning maxsus emojilari bilan almashtiradi.

Qanday ishlaydi
- Admin panel → «✨ Maxsus belgilar» da admin maxsus emojilarni (Telegram Premium emoji paketidan) botga yuboradi.
  Bot ularning ID sini o'qiydi va «oddiy emoji → maxsus emoji ID» jadvalini bazaga saqlaydi.
- Bot yuboradigan har bir xabarda: (1) tugma matni shu oddiy emoji bilan boshlansa, u o'chirilib, tugmaga
  `icon_custom_emoji_id` qo'yiladi; (2) xabar matnidagi shu emojilar `custom_emoji` entity'ga aylanadi.
- Jadval bo'sh bo'lsa yoki biror narsa xato ketsa, xabar o'zgarishsiz (oddiy emoji bilan) yuboriladi.

Telegram talabi: maxsus emoji tugma va xabarlarda faqat bot egasida Telegram Premium bo'lsa (yoki bot Fragment'da
qo'shimcha username sotib olgan bo'lsa) ko'rinadi; aks holda foydalanuvchi oddiy emojini ko'radi.
"""
import json
import logging
import time

import db

log = logging.getLogger("custom_emoji")
KEY = "custom_emoji"
VS16 = "️"
_cache = (0.0, {})


def norm(ch: str) -> str:
    return ch.replace(VS16, "")


def mapping() -> dict:
    """{oddiy emoji: maxsus emoji ID}. 5 soniya keshlanadi."""
    global _cache
    if time.time() - _cache[0] < 5:
        return _cache[1]
    try:
        data = json.loads(db.get_setting(KEY) or "{}")
    except ValueError:
        data = {}
    data = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(data, dict) else {}
    _cache = (time.time(), data)
    return data


def save_mapping(data: dict) -> None:
    global _cache
    db.set_setting(KEY, json.dumps(data, ensure_ascii=False) if data else None)
    _cache = (0.0, {})


def extract_from_message(message) -> dict:
    """Xabardagi maxsus emojilardan {oddiy emoji: ID} chiqaradi (offset/length UTF-16 birligida)."""
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    raw = text.encode("utf-16-le")
    out = {}
    for e in entities:
        if getattr(e, "type", None) == "custom_emoji" and getattr(e, "custom_emoji_id", None):
            ch = raw[e.offset * 2:(e.offset + e.length) * 2].decode("utf-16-le", "ignore")
            if ch:
                out[norm(ch)] = str(e.custom_emoji_id)
    return out


def _split_leading(text: str, m: dict):
    """Matn mapping'dagi emoji bilan boshlansa — (emoji, qolgan matn), aks holda (None, text)."""
    t = text.lstrip()
    for key in sorted(m, key=len, reverse=True):
        for variant in (key + VS16, key):
            if t.startswith(variant):
                return key, t[len(variant):].lstrip()
    return None, text


def convert_button(btn, m: dict):
    if not hasattr(btn, "text") or "icon_custom_emoji_id" not in getattr(type(btn), "model_fields", {}):
        return btn
    if getattr(btn, "icon_custom_emoji_id", None):
        return btn
    key, rest = _split_leading(btn.text or "", m)
    if key and rest:
        return btn.model_copy(update={"text": rest, "icon_custom_emoji_id": m[key]})
    return btn


def convert_markup(markup, m: dict):
    rows = getattr(markup, "inline_keyboard", None)
    if not rows:
        return markup
    new_rows = [[convert_button(b, m) for b in row] for row in rows]
    return markup.model_copy(update={"inline_keyboard": new_rows})


def text_entities(text: str, m: dict, make_entity) -> list:
    """Matndagi mapping'dagi emojilar uchun custom_emoji entity'lar ro'yxati."""
    if not text:
        return []
    keys = set(m)
    longest = max((len(k) for k in keys), default=0) + 1
    out, i, u16 = [], 0, 0
    while i < len(text) and len(out) < 100:
        hit = None
        for ln in range(min(longest, len(text) - i), 0, -1):
            seg = text[i:i + ln]
            if norm(seg) in keys and norm(seg) == seg.replace(VS16, ""):
                hit = seg
                break
        if hit:
            n16 = len(hit.encode("utf-16-le")) // 2
            out.append(make_entity(u16, n16, m[norm(hit)]))
            i += len(hit)
            u16 += n16
        else:
            u16 += len(text[i].encode("utf-16-le")) // 2
            i += 1
    return out


def transform_method(method):
    """Bot API so'rovini (SendMessage, EditMessageText, SendPhoto ...) maxsus emoji bilan boyitadi."""
    m = mapping()
    if not m:
        return method
    updates = {}
    rm = getattr(method, "reply_markup", None)
    if rm is not None and getattr(rm, "inline_keyboard", None):
        updates["reply_markup"] = convert_markup(rm, m)
    if not isinstance(getattr(method, "parse_mode", None), str):  # parse_mode bor bo'lsa, entity qo'shmaymiz
        from aiogram.types import MessageEntity

        def make(offset, length, emoji_id):
            return MessageEntity(type="custom_emoji", offset=offset, length=length, custom_emoji_id=emoji_id)

        for text_field, ent_field in (("text", "entities"), ("caption", "caption_entities")):
            text = getattr(method, text_field, None)
            if isinstance(text, str) and text and not getattr(method, ent_field, None) and hasattr(method, ent_field):
                ents = text_entities(text, m, make)
                if ents:
                    updates[ent_field] = ents
    return method.model_copy(update=updates) if updates else method


def make_middleware():
    from aiogram.client.session.middlewares.base import BaseRequestMiddleware

    class CustomEmojiMiddleware(BaseRequestMiddleware):
        async def __call__(self, make_request, bot, method):
            try:
                method = transform_method(method)
            except Exception:
                log.exception("Maxsus emoji almashtirishda xato — xabar o'zgarishsiz yuboriladi")
            return await make_request(bot, method)

    return CustomEmojiMiddleware()
