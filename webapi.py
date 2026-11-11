import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from aiohttp import web

import db
from config import BOT_TOKEN, BOT_USERNAME

INIT_DATA_MAX_AGE = 24 * 60 * 60  # 24 soat


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


def _item_json(item) -> dict:
    return {
        "id": item["id"],
        "name": item["name"],
        "price": item["price"],
        "image_url": item["image_url"] or "",
        "probability": item["probability"],
        "rarity": item["rarity"],
    }


async def _auth_user(request: web.Request):
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="JSON kerak")
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text="JSON kerak")
    user = validate_init_data(str(body.get("init_data", "")), BOT_TOKEN)
    if not user:
        raise web.HTTPUnauthorized(text="Telegram ichida oching")
    return user, body


async def api_cases(request: web.Request) -> web.Response:
    cases = []
    for case in db.get_cases():
        items = db.get_case_items(case["id"])
        total = sum(float(i["probability"]) for i in items) or 1.0
        cases.append({
            "id": case["id"],
            "name": case["name"],
            "price": case["price"],
            "description": case["description"] or "",
            "image_url": case["image_url"] or "",
            "items": [
                {**_item_json(i), "percent": round(float(i["probability"]) / total * 100, 2)}
                for i in items
            ],
        })
    return web.json_response({"cases": cases}, headers={"Cache-Control": "no-store"})


async def api_me(request: web.Request) -> web.Response:
    user, _ = await _auth_user(request)
    return web.json_response({
        "id": user["id"],
        "first_name": user.get("first_name", ""),
        "username": user.get("username", ""),
        "bot_username": BOT_USERNAME,
        "referrals": db.count_referrals(int(user["id"])),
    }, headers={"Cache-Control": "no-store"})


async def api_open(request: web.Request) -> web.Response:
    """Demo rejim: quti ochilganda tasodifiy sovg'a qaytaradi. Pul yechilmaydi."""
    _, body = await _auth_user(request)
    try:
        case_id = int(body.get("case_id"))
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="case_id noto'g'ri")
    case = db.get_case(case_id)
    if not case:
        raise web.HTTPNotFound(text="Quti topilmadi")
    winner = db.pick_case_item(case_id)
    if not winner:
        raise web.HTTPConflict(text="Bu qutida sovg'a yo'q")
    return web.json_response({"item": _item_json(winner)}, headers={"Cache-Control": "no-store"})


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/api/cases", api_cases)
    app.router.add_post("/api/me", api_me)
    app.router.add_post("/api/open", api_open)
