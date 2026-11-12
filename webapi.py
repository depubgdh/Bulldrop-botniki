import functools
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl

from aiohttp import web

import db
import tg_http
from config import ADMIN_IDS, BOT_TOKEN, BOT_USERNAME

INIT_DATA_MAX_AGE = 24 * 60 * 60  # 24 soat
NO_STORE = {"Cache-Control": "no-store"}
FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,256}$")
MEDIA_KINDS = ("img", "vid", "tgs")
GATE_MESSAGES = {
    "register": "Avval botda /start bosib ro‘yxatdan o‘ting.",
    "subscribe": "Davom etish uchun kanalga a‘zo bo‘ling.",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def api(handler):
    """ApiError ni JSON javobga aylantiradi: {"error": kod, "message": matn}."""
    @functools.wraps(handler)
    async def wrapper(request):
        try:
            return await handler(request)
        except ApiError as exc:
            return web.json_response({"error": exc.code, "message": exc.message}, status=exc.status, headers=NO_STORE)
    return wrapper


# ------------------------------------------------------------------ Telegram initData

def validate_init_data(init_data: str, bot_token: str, max_age: int = INIT_DATA_MAX_AGE):
    """Telegram Mini App initData imzosini tekshiradi. To'g'ri bo'lsa user dict, aks holda None."""
    if not init_data or not bot_token:
        return None
    parsed = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated, received_hash):
        return None
    try:
        if time.time() - int(parsed.get("auth_date", "0")) > max_age:
            return None
        user = json.loads(parsed.get("user", ""))
    except (ValueError, TypeError):
        return None
    if not isinstance(user, dict) or "id" not in user:
        return None
    return user


# ------------------------------------------------------------------ JSON yasovchilar (sof funksiyalar)

def media_url(raw) -> str:
    """Bazadagi rasm havolasini brauzer ochadigan manzilga aylantiradi.
    'tg:<tur>:<file_id>' -> /media/<tur>/<file_id>; oddiy https:// havola o'zgarishsiz."""
    raw = (raw or "").strip()
    if raw.startswith("tg:"):
        parts = raw.split(":", 2)
        if len(parts) == 3 and parts[1] in MEDIA_KINDS and FILE_ID_RE.match(parts[2]):
            return f"/media/{parts[1]}/{parts[2]}"
        return ""
    if raw.lower().startswith(("https://", "http://")):
        return raw
    return ""


def item_json(item) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "price": item["price"],
        "image_url": media_url(item["image_url"]),
        "probability": item["probability"],
        "rarity": item["rarity"],
    }


def inv_json(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "price": row["price"],
        "image_url": media_url(row["image_url"]),
        "rarity": row["rarity"],
    }


def wallet_json(wallet: dict) -> dict:
    return {"coins": wallet["coins"], "free_left": wallet["free_left"], "opens": wallet["opens"]}


def banner_payload():
    image = media_url(db.get_setting("banner_image"))
    if not image:
        return None
    return {"image": image, "link": db.get_setting("banner_link") or ""}


def cases_payload() -> dict:
    cases = []
    for case in db.get_cases():
        items = db.get_case_items(case["id"])
        total = sum(float(i["probability"]) for i in items) or 1.0
        cases.append({
            "id": case["id"],
            "name": case["name"],
            "price": case["price"],
            "description": case["description"] or "",
            "image_url": media_url(case["image_url"]),
            "items": [
                {**item_json(i), "percent": round(float(i["probability"]) / total * 100, 2)}
                for i in items
            ],
        })
    return {"cases": cases, "banner": banner_payload(), "free_limit": db.free_limit()}


def channel_link(channel) -> str:
    return f"https://t.me/{channel[1:]}" if channel and channel.startswith("@") else ""


def parse_range(header, size):
    """'Range: bytes=...' sarlavhasini (start, end) ga aylantiradi. Yo'q bo'lsa None, noto'g'ri bo'lsa 'bad'."""
    if not header or not header.startswith("bytes=") or size <= 0:
        return None
    try:
        start_s, _, end_s = header[6:].split(",")[0].strip().partition("-")
        if start_s == "":
            length = int(end_s)
            if length <= 0:
                return "bad"
            start, end = max(0, size - length), size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else size - 1
        end = min(end, size - 1)
        if start < 0 or start > end:
            return "bad"
    except ValueError:
        return "bad"
    return start, end


# ------------------------------------------------------------------ autentifikatsiya

async def _gate(user_id: int) -> str:
    """'ok' | 'register' | 'subscribe'."""
    row = db.get_user(user_id)
    if not row or not row["accepted_terms"] or not row["phone"]:
        return "register"
    if user_id not in ADMIN_IDS:
        channel = db.get_setting("required_channel")
        if channel and not await tg_http.is_subscribed(channel, user_id):
            return "subscribe"
    return "ok"


async def _auth(request, require_ok: bool = True):
    try:
        body = await request.json()
    except Exception:
        raise ApiError(400, "bad_request", "JSON kerak")
    if not isinstance(body, dict):
        raise ApiError(400, "bad_request", "JSON kerak")
    user = validate_init_data(str(body.get("init_data", "")), BOT_TOKEN)
    if not user:
        raise ApiError(401, "auth", "Telegram ichida oching")
    user_id = int(user["id"])
    db.ensure_user(user_id, user.get("username"))
    gate = await _gate(user_id)
    if require_ok and gate != "ok":
        raise ApiError(403, gate, GATE_MESSAGES[gate])
    return user_id, user, body, gate


# ------------------------------------------------------------------ handlerlar

@api
async def api_cases(request):
    return web.json_response(cases_payload(), headers=NO_STORE)


@api
async def api_me(request):
    user_id, user, _, gate = await _auth(request, require_ok=False)
    wallet = db.wallet(user_id)
    channel = db.get_setting("required_channel")
    return web.json_response({
        "id": user_id,
        "first_name": user.get("first_name", ""),
        "username": user.get("username", ""),
        "bot_username": BOT_USERNAME,
        "gate": gate,
        "channel_url": channel_link(channel) if gate == "subscribe" else "",
        "referrals": db.count_referrals(user_id),
        **wallet_json(wallet),
    }, headers=NO_STORE)


@api
async def api_open(request):
    user_id, _, body, _ = await _auth(request)
    try:
        case_id = int(body.get("case_id"))
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", "case_id noto‘g‘ri")
    res = db.open_case(user_id, case_id)
    if not res["ok"]:
        errors = {
            "no_case": (404, "Quti topilmadi."),
            "no_items": (409, "Bu qutida sovg‘a yo‘q."),
            "no_funds": (402, "Coin yetarli emas."),
        }
        status, message = errors.get(res["error"], (400, "Xatolik"))
        raise ApiError(status, res["error"], message)
    return web.json_response(
        {"item": inv_json(res["item"]), "free": res["free"], "wallet": wallet_json(res["wallet"])},
        headers=NO_STORE,
    )


@api
async def api_inventory(request):
    user_id, _, _, _ = await _auth(request)
    return web.json_response({
        "items": [inv_json(r) for r in db.inventory_list(user_id)],
        "wallet": wallet_json(db.wallet(user_id)),
    }, headers=NO_STORE)


@api
async def api_sell(request):
    user_id, _, body, _ = await _auth(request)
    if body.get("all"):
        res = db.sell_all(user_id)
    else:
        try:
            inv_id = int(body.get("id"))
        except (TypeError, ValueError):
            raise ApiError(400, "bad_request", "id noto‘g‘ri")
        res = db.sell_item(user_id, inv_id)
    if not res["ok"]:
        raise ApiError(404, "not_found", "Sovg‘a topilmadi (allaqachon sotilgan bo‘lishi mumkin).")
    return web.json_response(
        {"gained": res["gained"], "count": res["count"], "wallet": wallet_json(res["wallet"])},
        headers=NO_STORE,
    )


async def media(request):
    """Telegram'dagi rasm/GIF/stikerni Mini App'ga beradi (bot tokeni brauzerga chiqmaydi).
    Faqat bazada ishlatilgan file_id lar beriladi."""
    kind = request.match_info.get("kind", "")
    file_id = request.match_info.get("file_id", "")
    if kind not in MEDIA_KINDS or not FILE_ID_RE.match(file_id) or not db.media_known(f"tg:{kind}:{file_id}"):
        return web.Response(status=404)
    fetched = await tg_http.fetch_file(file_id)
    if not fetched:
        return web.Response(status=404)
    body, ctype = fetched
    headers = {"Cache-Control": "public, max-age=3600", "Accept-Ranges": "bytes"}
    # Safari/iOS <video> uchun Range (206) kerak
    rng = parse_range(request.headers.get("Range"), len(body))
    if rng == "bad":
        return web.Response(status=416, headers={"Content-Range": f"bytes */{len(body)}"})
    if rng:
        start, end = rng
        headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
        return web.Response(status=206, body=body[start:end + 1], content_type=ctype, headers=headers)
    return web.Response(body=body, content_type=ctype, headers=headers)


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/api/cases", api_cases)
    app.router.add_post("/api/me", api_me)
    app.router.add_post("/api/open", api_open)
    app.router.add_post("/api/inventory", api_inventory)
    app.router.add_post("/api/sell", api_sell)
    app.router.add_get("/media/{kind}/{file_id}", media)
