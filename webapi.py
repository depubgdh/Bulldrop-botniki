import functools
import hashlib
import logging
import hmac
import json
import re
import time
from urllib.parse import parse_qsl

from aiohttp import web

import bulk
import db
import tg_http
import crane
import ladder
import mines
import signals
import apple
import pioarena
import vgames
import tower
import wheel
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
        except web.HTTPException:
            raise
        except Exception as exc:  # kutilmagan xato: logga yoziladi, Mini App'da aniq sabab ko'rinadi
            logging.exception("API xatosi: %s", request.path)
            return web.json_response(
                {"error": "server", "message": f"Server xatosi: {type(exc).__name__}: {exc}"},
                status=500, headers=NO_STORE,
            )
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
            "bg_color": case["bg_color"] if "bg_color" in case.keys() else "",
            "items": [
                {**item_json(i), "percent": round(float(i["probability"]) / total * 100, 2)}
                for i in items
            ],
        })
    free_limit = db.free_limit()
    return {"cases": cases, "banner": banner_payload(), "free_limit": free_limit, "hero": hero_payload(free_limit),
            "free_case": db.free_case_id()}


HERO_DEFAULTS = {
    "title": "BULLDROP",
    "text": "Har kim {free} ta bepul ochadi. Keyin tushgan sovg‘ani sotib, coin bilan yana oching.",
    "btn_text": "🎁 Qutilarga o‘tish",
    "btn_target": "tab:case",
}
HERO_KEYS = {
    "title": "app_hero_title",
    "text": "app_hero_text",
    "image": "app_hero_image",
    "btn_text": "app_hero_btn_text",
    "btn_target": "app_hero_btn_target",
}


def hero_payload(free_limit: int) -> dict:
    """Mini App bosh sahifasi (pushti blok): admin panelda o'zgartiriladi."""
    text = db.get_setting(HERO_KEYS["text"]) or HERO_DEFAULTS["text"]
    return {
        "title": db.get_setting(HERO_KEYS["title"]) or HERO_DEFAULTS["title"],
        "text": text.replace("{free}", str(free_limit)),
        "image": media_url(db.get_setting(HERO_KEYS["image"])),
        "btn_text": db.get_setting(HERO_KEYS["btn_text"]) or HERO_DEFAULTS["btn_text"],
        "btn_target": db.get_setting(HERO_KEYS["btn_target"]) or HERO_DEFAULTS["btn_target"],
    }


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
    try:
        wheel.settle(user_id)  # tugagan g‘ildirak raundlari yutug‘i
    except Exception:
        logging.exception("wheel.settle")
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
        "is_admin": user_id in ADMIN_IDS,
        **wallet_json(wallet),
    }, headers=NO_STORE)


@api
async def api_open(request):
    user_id, _, body, _ = await _auth(request)
    try:
        case_id = int(body.get("case_id"))
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", "case_id noto‘g‘ri")
    res = db.open_case(user_id, case_id, body.get("count", 1))
    if not res["ok"]:
        errors = {
            "bad_count": (400, "Bir vaqtda 1, 2, 3, 5 yoki 10 ta quti ochish mumkin."),
            "no_case": (404, "Quti topilmadi."),
            "no_items": (409, "Bu qutida sovg‘a yo‘q."),
            "no_funds": (402, "Coin yetarli emas."),
        }
        status, message = errors.get(res["error"], (400, "Xatolik"))
        raise ApiError(status, res["error"], message)
    return web.json_response(
        {"item": inv_json(res["item"]), "items": [inv_json(i) for i in res["items"]], "free": res["free"],
         "free_used": res["free_used"], "cost": res["cost"], "wallet": wallet_json(res["wallet"])},
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
    elif isinstance(body.get("ids"), list):
        try:
            res = db.sell_items(user_id, body["ids"])
        except (TypeError, ValueError):
            raise ApiError(400, "bad_request", "ids noto‘g‘ri")
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


@api
async def api_admin_overview(request):
    """Faqat adminlar uchun: bosh sahifa sozlamalari va statistika (Mini App admin menyusi)."""
    user_id, _, _, _ = await _auth(request)
    if user_id not in ADMIN_IDS:
        raise ApiError(403, "forbidden", "Bu bo‘lim faqat admin uchun.")
    free_limit = db.free_limit()
    return web.json_response({
        "hero": hero_payload(free_limit),
        "free_limit": free_limit,
        "stats": db.stats(),
        "cases": len(db.get_cases()),
        "wheel": {"daily": wheel.daily_amount(), "locked": sorted(wheel.locked_types())},
    }, headers=NO_STORE)


WHEEL_ERRORS = {
    "bad_request": (400, "Noto‘g‘ri so‘rov."),
    "bad_bet": (400, "Tikish kamida 500 coin bo‘lishi kerak."),
    "no_funds": (402, "Coin yetarli emas."),
    "closed": (409, "Tikish yopildi. Keyingi raundni kuting."),
    "locked": (409, "Bu sektor vaqtincha qulflangan."),
    "no_daily": (404, "Kunlik coin yo‘q."),
    "claimed": (409, "Bugungi kunlik coin allaqachon olingan."),
}


def _wheel_error(exc: "wheel.WheelError") -> ApiError:
    status, message = WHEEL_ERRORS.get(exc.code, (400, "Xatolik"))
    return ApiError(status, exc.code, message)


@api
async def api_wheel_state(request):
    user_id, _, _, _ = await _auth(request)
    return web.json_response(wheel.state_for(user_id), headers=NO_STORE)


@api
async def api_wheel_bet(request):
    user_id, _, body, _ = await _auth(request)
    try:
        res = wheel.place_bet(user_id, body.get("kind"), body.get("amount"), body.get("request_id"), body.get("round"))
    except wheel.WheelError as exc:
        raise _wheel_error(exc)
    return web.json_response(res, headers=NO_STORE)


MINES_ERRORS = {
    "bad_request": (400, "Noto‘g‘ri so‘rov."),
    "bad_bet": (400, "Tikish kamida 500 coin bo‘lishi kerak."),
    "no_funds": (402, "Coin yetarli emas."),
    "active": (409, "Tugallanmagan o‘yin bor — davom eting."),
    "no_game": (404, "Faol o‘yin yo‘q."),
    "nothing_opened": (409, "Avval kamida bitta katakni oching."),
}


def _mines_error(exc: "mines.MinesError") -> ApiError:
    status, message = MINES_ERRORS.get(exc.code, (400, "Xatolik"))
    return ApiError(status, exc.code, message)


@api
async def api_mines_state(request):
    user_id, _, _, _ = await _auth(request)
    return web.json_response(mines.state_for(user_id), headers=NO_STORE)


@api
async def api_mines_start(request):
    user_id, _, body, _ = await _auth(request)
    try:
        res = mines.start(user_id, body.get("bet"), body.get("mines"), body.get("request_id"))
    except mines.MinesError as exc:
        raise _mines_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_mines_open(request):
    user_id, _, body, _ = await _auth(request)
    try:
        res = mines.open_cell(user_id, body.get("cell"))
    except mines.MinesError as exc:
        raise _mines_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_mines_cashout(request):
    user_id, _, _, _ = await _auth(request)
    try:
        res = mines.cashout(user_id)
    except mines.MinesError as exc:
        raise _mines_error(exc)
    return web.json_response(res, headers=NO_STORE)


TOWER_ERRORS = dict(MINES_ERRORS, nothing_opened=(409, "Avval kamida bitta qavatdan o‘ting."))


def _game_api(module, error_cls, errors):
    def raiser(exc):
        status, message = errors.get(exc.code, (400, "Xatolik"))
        return ApiError(status, exc.code, message)
    return raiser


CRANE_ERRORS = dict(MINES_ERRORS, nothing_opened=(409, "Avval kamida bitta qavat quring."))
_crane_error = _game_api(crane, crane.CraneError, CRANE_ERRORS)
_tower_error = _game_api(tower, tower.TowerError, TOWER_ERRORS)
_ladder_error = _game_api(ladder, ladder.LadderError, TOWER_ERRORS)


@api
async def api_tower_state(request):
    user_id, _, _, _ = await _auth(request)
    return web.json_response(tower.state_for(user_id), headers=NO_STORE)


@api
async def api_tower_start(request):
    user_id, _, body, _ = await _auth(request)
    try:
        res = tower.start(user_id, body.get("bet"), body.get("request_id"))
    except tower.TowerError as exc:
        raise _tower_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_tower_pick(request):
    user_id, _, body, _ = await _auth(request)
    try:
        res = tower.pick(user_id, body.get("col"))
    except tower.TowerError as exc:
        raise _tower_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_tower_cashout(request):
    user_id, _, _, _ = await _auth(request)
    try:
        res = tower.cashout(user_id)
    except tower.TowerError as exc:
        raise _tower_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_ladder_state(request):
    user_id, _, _, _ = await _auth(request)
    return web.json_response(ladder.state_for(user_id), headers=NO_STORE)


@api
async def api_ladder_start(request):
    user_id, _, body, _ = await _auth(request)
    try:
        res = ladder.start(user_id, body.get("bet"), body.get("stones"), body.get("request_id"))
    except ladder.LadderError as exc:
        raise _ladder_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_ladder_step(request):
    user_id, _, body, _ = await _auth(request)
    try:
        res = ladder.step(user_id, body.get("col"))
    except ladder.LadderError as exc:
        raise _ladder_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_ladder_cashout(request):
    user_id, _, _, _ = await _auth(request)
    try:
        res = ladder.cashout(user_id)
    except ladder.LadderError as exc:
        raise _ladder_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_build_state(request):
    user_id, _, _, _ = await _auth(request)
    return web.json_response(crane.state_for(user_id), headers=NO_STORE)


@api
async def api_build_start(request):
    user_id, _, body, _ = await _auth(request)
    try:
        res = crane.start(user_id, body.get("bet"), body.get("request_id"))
    except crane.CraneError as exc:
        raise _crane_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_build_drop(request):
    user_id, _, _, _ = await _auth(request)
    try:
        res = crane.drop(user_id)
    except crane.CraneError as exc:
        raise _crane_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_build_cashout(request):
    user_id, _, _, _ = await _auth(request)
    try:
        res = crane.cashout(user_id)
    except crane.CraneError as exc:
        raise _crane_error(exc)
    return web.json_response(res, headers=NO_STORE)


# ------------------------------------------------------------------ bonus (Mini App)

def _task_json(task, status) -> dict:
    return {"id": task["id"], "title": task["title"], "description": task["description"] or "",
            "url": task["url"] or "", "auto": bool(task["channel"]), "reward": task["reward"], "status": status or ""}


@api
async def api_bonus_state(request):
    user_id, _, _, _ = await _auth(request)
    status = db.claim_statuses(user_id)
    return web.json_response({
        "ref_reward": db.ref_reward(),
        "referrals": db.count_referrals(user_id),
        "tasks": [_task_json(t, status.get(t["id"])) for t in db.get_tasks()],
    }, headers=NO_STORE)


@api
async def api_bonus_claim(request):
    """«Bajardim»: kanal sharti bo'lsa a'zolik avtomatik tekshiriladi, aks holda adminga tasdiqlash so'rovi ketadi."""
    user_id, user, body, _ = await _auth(request)
    try:
        task = db.get_task(int(body.get("task_id")))
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", "task_id noto‘g‘ri")
    if not task or not task["is_active"]:
        raise ApiError(404, "no_task", "Bu shart topilmadi.")

    if task["channel"]:
        member = await tg_http.member_status(task["channel"], user_id)
        if member is False:
            raise ApiError(409, "not_member", "Siz hali kanalga a‘zo emassiz. A‘zo bo‘lib, qayta bosing.")
        if member:
            res = db.auto_approve(task["id"], user_id)
            if not res["ok"]:
                raise ApiError(409, "claimed", "Bu bonus allaqachon olingan.")
            return web.json_response({"status": "approved", "reward": res["reward"],
                                      "wallet": wallet_json(db.wallet(user_id))}, headers=NO_STORE)
        # member is None: bot tekshira olmadi — qo'lda tasdiqlashga o'tamiz

    res = db.submit_claim(task["id"], user_id)
    if not res["ok"]:
        if res["status"] == "approved":
            raise ApiError(409, "claimed", "Bu bonus allaqachon olingan.")
        raise ApiError(409, "pending", "So‘rovingiz allaqachon admin tasdig‘ida.")
    name = (user.get("first_name") or "") + (f" (@{user['username']})" if user.get("username") else "")
    note = (f"🧾 Bonus so‘rovi #{res['claim_id']}\n\nFoydalanuvchi: {name.strip() or user_id}\nID: {user_id}\n"
            f"Shart: {task['title']}\nMukofot: {task['reward']} coin\n\nShartni bajarganini tekshirib, qaror qiling:")
    markup = {"inline_keyboard": [[{"text": "✅ Tasdiqlash", "callback_data": f"bonus_ok_{res['claim_id']}"},
                                    {"text": "❌ Rad etish", "callback_data": f"bonus_no_{res['claim_id']}"}]]}
    for admin_id in ADMIN_IDS:
        await tg_http.send_message(admin_id, note, markup)
    return web.json_response({"status": "pending"}, headers=NO_STORE)


@api
async def api_wheel_daily(request):
    user_id, _, _, _ = await _auth(request)
    try:
        res = wheel.claim_daily(user_id)
    except wheel.WheelError as exc:
        raise _wheel_error(exc)
    return web.json_response(res, headers=NO_STORE)


# ------------------------------------------------------------------ Signal (coin evaziga, tasodifiy tavsiya)

SIGNAL_ERRORS = {
    "bad_game": (400, "Noto‘g‘ri o‘yin."),
    "bad_ref": (400, "O‘yin ID raqamini kiriting (harf, raqam, - _ # . belgilari, 32 tagacha)."),
    "off": (409, "Bu signal vaqtincha o‘chirilgan."),
    "no_funds": (402, "Coin yetarli emas."),
    "bad_result": (400, "Noto‘g‘ri natija."),
    "not_found": (404, "Signal topilmadi."),
    "bad_price": (400, "Narx noto‘g‘ri."),
}


def _signal_error(exc) -> ApiError:
    status, message = SIGNAL_ERRORS.get(exc.code, (400, "Xatolik"))
    return ApiError(status, exc.code, message)


@api
async def api_signal_state(request):
    user_id, _, _, _ = await _auth(request)
    return web.json_response({**signals.state_for(user_id), "coins": db.wallet(user_id)["coins"]}, headers=NO_STORE)


@api
async def api_signal_buy(request):
    user_id, _, body, _ = await _auth(request)
    try:
        res = signals.buy(user_id, str(body.get("game", "")), str(body.get("ref", "")))
    except signals.SignalError as exc:
        raise _signal_error(exc)
    return web.json_response(res, headers=NO_STORE)


@api
async def api_signal_mark(request):
    user_id, _, body, _ = await _auth(request)
    try:
        signals.mark(user_id, int(body.get("id", 0)), str(body.get("result", "")))
    except (signals.SignalError, ValueError) as exc:
        raise _signal_error(exc) if isinstance(exc, signals.SignalError) else ApiError(400, "bad_request", "Noto‘g‘ri so‘rov.")
    return web.json_response({"ok": True}, headers=NO_STORE)


# ------------------------------------------------------------------ Admin (Mini App ichida)

async def _admin(request):
    user_id, _, body, _ = await _auth(request)
    if user_id not in ADMIN_IDS:
        raise ApiError(403, "forbidden", "Bu bo‘lim faqat admin uchun.")
    return user_id, body


def _admin_cases() -> list:
    out = []
    for case in db.get_cases():
        items = db.get_case_items(case["id"])
        total = sum(float(i["probability"]) for i in items) or 1.0
        out.append({
            "id": case["id"], "name": case["name"], "price": case["price"],
            "description": case["description"] or "", "image": media_url(case["image_url"]),
            "bg_color": case["bg_color"] if "bg_color" in case.keys() else "",
            "ev": round(db.case_ev(case["id"])) if items else 0,
            "items": [{**item_json(i), "probability": float(i["probability"]),
                       "percent": round(float(i["probability"]) / total * 100, 2)} for i in items],
        })
    return out


def _int(value, default=None, minimum=None, maximum=None):
    try:
        n = int(str(value).replace(" ", ""))
    except (TypeError, ValueError):
        if default is not None:
            return default
        raise ApiError(400, "bad_request", "Son kerak.")
    if (minimum is not None and n < minimum) or (maximum is not None and n > maximum):
        raise ApiError(400, "bad_request", "Qiymat ruxsat etilgan oraliqdan tashqarida.")
    return n


@api
async def api_admin_cases(request):
    await _admin(request)
    return web.json_response({"cases": _admin_cases(), "rarities": bulk.RARITIES}, headers=NO_STORE)


@api
async def api_admin_case_save(request):
    _, body = await _admin(request)
    name = str(body.get("name", "")).strip()[:80]
    if not name:
        raise ApiError(400, "bad_request", "Quti nomini kiriting.")
    price = _int(body.get("price"), minimum=0, maximum=100_000_000)
    desc = str(body.get("description", "")).strip()[:300]
    bg = str(body.get("bg_color", "")).strip().lower()
    if bg and not re.fullmatch(r"#[0-9a-f]{6}", bg):
        raise ApiError(400, "bad_request", "Rang #rrggbb ko‘rinishida bo‘lsin.")
    case_id = body.get("id")
    if case_id:
        case_id = _int(case_id)
        if not db.get_case(case_id):
            raise ApiError(404, "not_found", "Quti topilmadi.")
        db.update_case(case_id, name=name, price=price, description=desc)
    else:
        db.add_case(name, price, desc, "")
        case_id = max(c["id"] for c in db.get_cases())
    db.set_case_bg(case_id, bg)
    if body.get("image_url") is not None and str(body["image_url"]).strip().lower().startswith("https://"):
        db.set_case_image(case_id, str(body["image_url"]).strip())
    elif body.get("image_url") == "":
        db.set_case_image(case_id, "")
    return web.json_response({"ok": True, "id": case_id, "cases": _admin_cases()}, headers=NO_STORE)


@api
async def api_admin_case_delete(request):
    _, body = await _admin(request)
    db.deactivate_case(_int(body.get("id")))
    return web.json_response({"ok": True, "cases": _admin_cases()}, headers=NO_STORE)


@api
async def api_admin_items_bulk(request):
    """Ro'yxat bilan tez qo'shish: har qator «Nomi | qiymat | foiz | daraja | havola»."""
    _, body = await _admin(request)
    case_id = _int(body.get("case_id"))
    if not db.get_case(case_id):
        raise ApiError(404, "not_found", "Quti topilmadi.")
    added, bad = 0, []
    for line in str(body.get("text", "")).splitlines():
        if not line.strip():
            continue
        item = bulk.parse_item_line(line)
        if not item:
            bad.append(line.strip()[:80])
            continue
        db.add_case_item(case_id, item["name"], item["price"], item["image"], item["prob"], item["rarity"])
        added += 1
    return web.json_response({"ok": True, "added": added, "bad": bad[:10], "cases": _admin_cases()}, headers=NO_STORE)


@api
async def api_admin_item_save(request):
    _, body = await _admin(request)
    item_id = _int(body.get("id"))
    if not db.get_case_item(item_id):
        raise ApiError(404, "not_found", "Sovg‘a topilmadi.")
    rarity = str(body.get("rarity", "")) or None
    if rarity and rarity not in bulk.RARITIES:
        raise ApiError(400, "bad_request", "Noto‘g‘ri daraja.")
    try:
        prob = float(str(body.get("probability")).replace(",", ".")) if body.get("probability") not in (None, "") else None
    except ValueError:
        raise ApiError(400, "bad_request", "Foiz son bo‘lishi kerak.")
    if prob is not None and prob <= 0:
        raise ApiError(400, "bad_request", "Foiz 0 dan katta bo‘lsin.")
    price = _int(body.get("price"), minimum=0) if body.get("price") not in (None, "") else None
    name = str(body.get("name", "")).strip()[:80] or None
    db.update_item(item_id, name=name, price=price, rarity=rarity, probability=prob)
    return web.json_response({"ok": True, "cases": _admin_cases()}, headers=NO_STORE)


@api
async def api_admin_item_delete(request):
    _, body = await _admin(request)
    db.deactivate_item(_int(body.get("id")))
    return web.json_response({"ok": True, "cases": _admin_cases()}, headers=NO_STORE)


@api
async def api_admin_ads(request):
    await _admin(request)
    free_limit = db.free_limit()
    hero = hero_payload(free_limit)
    return web.json_response({
        "hero": {**hero, "text_raw": db.get_setting(HERO_KEYS["text"]) or HERO_DEFAULTS["text"]},
        "banner": banner_payload() or {"image": "", "link": ""},
        "free_limit": free_limit,
    }, headers=NO_STORE)


@api
async def api_admin_ads_save(request):
    _, body = await _admin(request)
    for field in ("title", "text", "btn_text", "btn_target"):
        if field in body:
            value = str(body[field]).strip()[:400]
            db.set_setting(HERO_KEYS[field], value or None)
    if "hero_image" in body:
        img = str(body["hero_image"]).strip()
        if img == "" or img.lower().startswith("https://"):
            db.set_setting(HERO_KEYS["image"], img or None)
    if "banner_link" in body:
        db.set_setting("banner_link", str(body["banner_link"]).strip()[:300] or None)
    if "banner_image" in body:
        img = str(body["banner_image"]).strip()
        if img == "" or img.lower().startswith("https://"):
            db.set_setting("banner_image", img or None)
    return web.json_response({"ok": True}, headers=NO_STORE)


@api
async def api_admin_upload(request):
    """multipart: init_data, target (case|hero|banner), id (quti uchun), file. Rasm Telegram'ga yuklanib, file_id saqlanadi."""
    reader = await request.multipart()
    fields, blob, fname, ctype = {}, b"", "file", ""
    async for part in reader:
        if part.name == "file":
            fname, ctype = part.filename or "file", part.headers.get("Content-Type", "")
            blob = await part.read(decode=False)
        else:
            fields[part.name] = (await part.text())[:4096]
    user = validate_init_data(fields.get("init_data", ""), BOT_TOKEN)
    if not user or int(user["id"]) not in ADMIN_IDS:
        raise ApiError(403, "forbidden", "Bu bo‘lim faqat admin uchun.")
    if not blob or len(blob) > 10 * 1024 * 1024:
        raise ApiError(400, "bad_request", "Fayl bo‘sh yoki 10 MB dan katta.")
    ref = await tg_http.upload_media(int(user["id"]), blob, fname, ctype)
    if not ref:
        raise ApiError(502, "upload", "Yuklab bo‘lmadi. Rasm/GIF/MP4 yuboring (botda /start bosgan bo‘lishingiz kerak).")
    target = fields.get("target")
    if target == "case":
        case_id = _int(fields.get("id"))
        if not db.get_case(case_id):
            raise ApiError(404, "not_found", "Quti topilmadi.")
        db.set_case_image(case_id, ref)
    elif target == "hero":
        db.set_setting(HERO_KEYS["image"], ref)
    elif target == "banner":
        db.set_setting("banner_image", ref)
    elif target == "pioad":
        if not pioarena.ad_set_video(_int(fields.get("id")), ref):
            raise ApiError(404, "not_found", "Reklama topilmadi.")
    elif target == "item":
        item_id = _int(fields.get("id"))
        if not db.get_case_item(item_id):
            raise ApiError(404, "not_found", "Sovg‘a topilmadi.")
        db.set_item_image(item_id, ref)
    else:
        raise ApiError(400, "bad_request", "Noto‘g‘ri nishon.")
    return web.json_response({"ok": True, "url": media_url(ref)}, headers=NO_STORE)


@api
async def api_admin_signals(request):
    await _admin(request)
    return web.json_response({"config": signals.config(), "stats": signals.admin_stats()}, headers=NO_STORE)


@api
async def api_admin_signals_save(request):
    _, body = await _admin(request)
    try:
        signals.set_config(str(body.get("game", "")),
                           price=body.get("price") if body.get("price") not in (None, "") else None,
                           on=body.get("on") if "on" in body else None)
    except signals.SignalError as exc:
        raise _signal_error(exc)
    except (TypeError, ValueError):
        raise ApiError(400, "bad_request", "Narx son bo‘lishi kerak.")
    return web.json_response({"ok": True, "config": signals.config()}, headers=NO_STORE)


def _user_json(card) -> dict:
    user = card["user"]
    return {
        "id": user["user_id"], "username": user["username"] or "", "phone": user["phone"] or "",
        "coins": card["wallet"]["coins"], "opens": card["wallet"]["opens"],
        "inventory": card["inventory"], "referrals": card["referrals"],
    }


@api
async def api_admin_user(request):
    _, body = await _admin(request)
    row = db.find_user(str(body.get("query", "")))
    if not row:
        raise ApiError(404, "not_found", "Foydalanuvchi topilmadi.")
    return web.json_response({"user": _user_json(db.user_card(row["user_id"]))}, headers=NO_STORE)


@api
async def api_admin_coins(request):
    """Foydalanuvchi coinini qo'shish/ayirish (musbat yoki manfiy son)."""
    admin_id, body = await _admin(request)
    target = _int(body.get("user_id"))
    delta = _int(body.get("delta"), minimum=-1_000_000_000, maximum=1_000_000_000)
    if not db.get_user(target):
        raise ApiError(404, "not_found", "Foydalanuvchi topilmadi.")
    db.add_coins(target, delta)
    logging.info("admin %s coin %+d -> user %s", admin_id, delta, target)
    return web.json_response({"user": _user_json(db.user_card(target))}, headers=NO_STORE)


_apple_error = _game_api(apple, apple.AppleError, dict(TOWER_ERRORS, nothing_opened=(409, "Avval kamida bitta olmani oching.")))


@api
async def api_apple_state(request):
    user_id, _, _, _ = await _auth(request)
    return web.json_response(apple.state_for(user_id), headers=NO_STORE)


@api
async def api_apple_start(request):
    user_id, _, body, _ = await _auth(request)
    try:
        return web.json_response(apple.start(user_id, body.get("bet"), body.get("request_id")), headers=NO_STORE)
    except apple.AppleError as exc:
        raise _apple_error(exc)


@api
async def api_apple_step(request):
    user_id, _, body, _ = await _auth(request)
    try:
        return web.json_response(apple.step(user_id, body.get("col")), headers=NO_STORE)
    except apple.AppleError as exc:
        raise _apple_error(exc)


@api
async def api_apple_cashout(request):
    user_id, _, _, _ = await _auth(request)
    try:
        return web.json_response(apple.cashout(user_id), headers=NO_STORE)
    except apple.AppleError as exc:
        raise _apple_error(exc)


PIO_ERRORS = {
    "bad_request": (400, "Noto‘g‘ri so‘rov."),
    "no_funds": (402, "Coin yetarli emas (1000 kerak). Tekin rejimda o‘ynang."),
    "no_game": (404, "Faol o‘yin yo‘q."),
}
_pio_error = _game_api(pioarena, pioarena.PioError, PIO_ERRORS)


@api
async def api_pio_lobby(request):
    user_id, _, _, _ = await _auth(request)
    return web.json_response(pioarena.lobby(user_id), headers=NO_STORE)


@api
async def api_pio_start(request):
    user_id, _, _, _ = await _auth(request)
    try:
        return web.json_response(pioarena.start(user_id), headers=NO_STORE)
    except pioarena.PioError as exc:
        raise _pio_error(exc)


@api
async def api_pio_finish(request):
    user_id, _, body, _ = await _auth(request)
    try:
        return web.json_response(pioarena.finish(user_id, body.get("game_id"), body.get("areas"), bool(body.get("quit"))), headers=NO_STORE)
    except pioarena.PioError as exc:
        raise _pio_error(exc)


def _pio_ad_json(r) -> dict:
    return {"id": r["id"], "video": media_url(r["video"]), "has_video": bool(r["video"]), "link": r["link"], "active": bool(r["active"]), "views": r["views"]}


@api
async def api_pio_ad(request):
    await _auth(request)
    ad = pioarena.ad_pick()
    return web.json_response({"ad": {"id": ad["id"], "video": media_url(ad["video"]), "link": ad["link"]} if ad and media_url(ad["video"]) else None}, headers=NO_STORE)


@api
async def api_admin_pio_ads(request):
    await _admin(request)
    return web.json_response({"ads": [_pio_ad_json(r) for r in pioarena.ads_all()]}, headers=NO_STORE)


@api
async def api_admin_pio_ad_save(request):
    _, body = await _admin(request)
    try:
        pioarena.ad_save(_int(body.get("id")), body.get("video"), body.get("link"), bool(body.get("active", True)))
    except pioarena.PioError:
        raise ApiError(400, "bad_request", "Havola https:// bilan boshlanishi kerak.")
    return web.json_response({"ads": [_pio_ad_json(r) for r in pioarena.ads_all()]}, headers=NO_STORE)


@api
async def api_admin_pio_ad_delete(request):
    _, body = await _admin(request)
    pioarena.ad_delete(_int(body.get("id")))
    return web.json_response({"ads": [_pio_ad_json(r) for r in pioarena.ads_all()]}, headers=NO_STORE)


# ------------------------------------------------------------------ Virtual o'yinlar (reyting)

@api
async def api_vgame_top(request):
    user_id, _, body, _ = await _auth(request)
    try:
        return web.json_response(vgames.top(str(body.get("game", "")), user_id), headers=NO_STORE)
    except ValueError:
        raise ApiError(400, "bad_game", "Noto‘g‘ri o‘yin.")


@api
async def api_vgame_score(request):
    user_id, tg_user, body, _ = await _auth(request)
    try:
        score = int(body.get("score", 0))
        name = (tg_user.get("first_name") if isinstance(tg_user, dict) else "") or "Bull"
        vgames.submit(user_id, name, str(body.get("game", "")), score)
        return web.json_response(vgames.top(str(body.get("game", "")), user_id), headers=NO_STORE)
    except (ValueError, TypeError):
        raise ApiError(400, "bad_request", "Noto‘g‘ri so‘rov.")


# ------------------------------------------------------------------ Admin: kirish sovg'asi, bonus, kanal, xabar

@api
async def api_admin_welcome(request):
    await _admin(request)
    return web.json_response({
        "case_id": db.free_case_id(),
        "chosen": int(db.get_setting("free_case_id") or 0),
        "free_limit": db.free_limit(),
        "cases": [{"id": c["id"], "name": c["name"], "price": c["price"]} for c in db.get_cases()],
    }, headers=NO_STORE)


@api
async def api_admin_welcome_save(request):
    _, body = await _admin(request)
    case_id = _int(body.get("case_id", 0), default=0, minimum=0)
    if case_id and not db.get_case(case_id):
        raise ApiError(404, "not_found", "Quti topilmadi.")
    db.set_free_case(case_id)
    if body.get("free_limit") not in (None, ""):
        db.set_setting("free_opens", _int(body.get("free_limit"), minimum=0, maximum=1000))
    return await api_admin_welcome(request)


def _task_json(t) -> dict:
    return {"id": t["id"], "title": t["title"], "description": t["description"] or "", "url": t["url"] or "",
            "channel": t["channel"] or "", "reward": t["reward"], "active": bool(t["is_active"])}


def _bonus_payload() -> dict:
    return {
        "ref_reward": db.ref_reward(),
        "tasks": [_task_json(t) for t in db.get_tasks(active_only=False)],
        "pending": [{"id": c["id"], "user_id": c["user_id"], "username": c["username"] or "", "title": c["title"] or "",
                     "reward": c["reward"] or 0, "at": c["created_at"]} for c in db.pending_claims(30)],
    }


@api
async def api_admin_bonus(request):
    await _admin(request)
    return web.json_response(_bonus_payload(), headers=NO_STORE)


@api
async def api_admin_bonus_save(request):
    _, body = await _admin(request)
    db.set_setting("ref_reward", _int(body.get("ref_reward"), minimum=0, maximum=100_000_000))
    return web.json_response(_bonus_payload(), headers=NO_STORE)


@api
async def api_admin_task_save(request):
    _, body = await _admin(request)
    title = str(body.get("title", "")).strip()[:100]
    if not title:
        raise ApiError(400, "bad_request", "Shart nomini kiriting.")
    desc = str(body.get("description", "")).strip()[:500]
    url = str(body.get("url", "")).strip()[:300]
    channel = str(body.get("channel", "")).strip()[:100]
    reward = _int(body.get("reward"), minimum=0, maximum=100_000_000)
    if body.get("id"):
        tid = _int(body.get("id"))
        if not db.get_task(tid):
            raise ApiError(404, "not_found", "Shart topilmadi.")
        db.update_task(tid, title=title, description=desc, url=url, channel=channel, reward=reward,
                       is_active=1 if body.get("active", True) else 0)
    else:
        db.add_task(title, desc, url, channel, reward)
    return web.json_response(_bonus_payload(), headers=NO_STORE)


@api
async def api_admin_task_delete(request):
    _, body = await _admin(request)
    db.delete_task(_int(body.get("id")))
    return web.json_response(_bonus_payload(), headers=NO_STORE)


@api
async def api_admin_claim(request):
    _, body = await _admin(request)
    approve = bool(body.get("approve"))
    res = db.resolve_claim(_int(body.get("id")), approve)
    if res:
        if approve:
            text = f"🎉 «{res['title']}» sharti tasdiqlandi! Sizga +{res['reward']} coin berildi."
        else:
            text = f"❌ «{res['title']}» bo‘yicha so‘rovingiz rad etildi. Shartni to‘liq bajarib, qayta yuboring."
        await tg_http.send_message(res["user_id"], text)
    return web.json_response(_bonus_payload(), headers=NO_STORE)


@api
async def api_admin_coins_all(request):
    """Ro'yxatdan o'tgan hammaga coin bonus."""
    admin_id, body = await _admin(request)
    amount = _int(body.get("amount"), minimum=1, maximum=100_000_000)
    n = db.add_coins_all(amount)
    logging.info("admin %s coins_all +%d -> %d users", admin_id, amount, n)
    return web.json_response({"ok": True, "users": n}, headers=NO_STORE)


@api
async def api_admin_channel(request):
    admin_id, body = await _admin(request)
    if "channel" in body:
        raw = str(body.get("channel", "")).strip()
        if not raw:
            db.set_setting("required_channel", None)
        else:
            ref = raw if raw.lstrip("-").isdigit() or raw.startswith("@") else "@" + raw.rsplit("/", 1)[-1]
            if ref.lstrip("-").isdigit():
                ref = int(ref)
            ok = await tg_http.member_status(ref, admin_id)
            if ok is None:
                raise ApiError(400, "channel", "Kanal topilmadi yoki bot u yerda admin emas. Botni kanalga admin qiling.")
            db.set_setting("required_channel", str(ref))
    return web.json_response({"channel": db.get_setting("required_channel") or ""}, headers=NO_STORE)


_BROADCAST = {"running": False}


async def _broadcast_task(text: str, ids: list) -> None:
    import asyncio
    try:
        for uid in ids:
            await tg_http.send_message(uid, text)
            await asyncio.sleep(0.05)
    finally:
        _BROADCAST["running"] = False


@api
async def api_admin_broadcast(request):
    """Matnli xabarni hammaga yuboradi (rasm/GIF/video uchun botdagi /admin dan foydalaning)."""
    import asyncio
    _, body = await _admin(request)
    text = str(body.get("text", "")).strip()[:3500]
    if not text:
        raise ApiError(400, "bad_request", "Xabar matnini kiriting.")
    if _BROADCAST["running"]:
        raise ApiError(409, "busy", "Oldingi yuborish hali tugamagan.")
    ids = db.all_user_ids()
    _BROADCAST["running"] = True
    asyncio.get_event_loop().create_task(_broadcast_task(text, ids))
    return web.json_response({"ok": True, "total": len(ids)}, headers=NO_STORE)


def setup_routes(app: web.Application) -> None:
    app.router.add_post("/api/wheel/state", api_wheel_state)
    app.router.add_post("/api/wheel/bet", api_wheel_bet)
    app.router.add_post("/api/mines/state", api_mines_state)
    app.router.add_post("/api/mines/start", api_mines_start)
    app.router.add_post("/api/mines/open", api_mines_open)
    app.router.add_post("/api/mines/cashout", api_mines_cashout)
    app.router.add_post("/api/tower/state", api_tower_state)
    app.router.add_post("/api/tower/start", api_tower_start)
    app.router.add_post("/api/tower/pick", api_tower_pick)
    app.router.add_post("/api/tower/cashout", api_tower_cashout)
    app.router.add_post("/api/ladder/state", api_ladder_state)
    app.router.add_post("/api/ladder/start", api_ladder_start)
    app.router.add_post("/api/ladder/step", api_ladder_step)
    app.router.add_post("/api/ladder/cashout", api_ladder_cashout)
    app.router.add_post("/api/wheel/daily", api_wheel_daily)
    app.router.add_post("/api/bonus/state", api_bonus_state)
    app.router.add_post("/api/bonus/claim", api_bonus_claim)
    app.router.add_post("/api/build/state", api_build_state)
    app.router.add_post("/api/build/start", api_build_start)
    app.router.add_post("/api/build/drop", api_build_drop)
    app.router.add_post("/api/build/cashout", api_build_cashout)


    app.router.add_post("/api/admin/overview", api_admin_overview)
    app.router.add_post("/api/apple/state", api_apple_state)
    app.router.add_post("/api/apple/start", api_apple_start)
    app.router.add_post("/api/apple/step", api_apple_step)
    app.router.add_post("/api/apple/cashout", api_apple_cashout)
    app.router.add_post("/api/pio/lobby", api_pio_lobby)
    app.router.add_post("/api/pio/ad", api_pio_ad)
    app.router.add_post("/api/admin/pio_ads", api_admin_pio_ads)
    app.router.add_post("/api/admin/pio_ads/save", api_admin_pio_ad_save)
    app.router.add_post("/api/admin/pio_ads/delete", api_admin_pio_ad_delete)
    app.router.add_post("/api/pio/start", api_pio_start)
    app.router.add_post("/api/pio/finish", api_pio_finish)
    app.router.add_post("/api/vgame/top", api_vgame_top)
    app.router.add_post("/api/vgame/score", api_vgame_score)
    app.router.add_post("/api/admin/welcome", api_admin_welcome)
    app.router.add_post("/api/admin/welcome/save", api_admin_welcome_save)
    app.router.add_post("/api/admin/bonus", api_admin_bonus)
    app.router.add_post("/api/admin/bonus/save", api_admin_bonus_save)
    app.router.add_post("/api/admin/task/save", api_admin_task_save)
    app.router.add_post("/api/admin/task/delete", api_admin_task_delete)
    app.router.add_post("/api/admin/claim", api_admin_claim)
    app.router.add_post("/api/admin/coins_all", api_admin_coins_all)
    app.router.add_post("/api/admin/channel", api_admin_channel)
    app.router.add_post("/api/admin/broadcast", api_admin_broadcast)
    app.router.add_post("/api/signal/state", api_signal_state)
    app.router.add_post("/api/signal/buy", api_signal_buy)
    app.router.add_post("/api/signal/mark", api_signal_mark)
    app.router.add_post("/api/admin/cases", api_admin_cases)
    app.router.add_post("/api/admin/case/save", api_admin_case_save)
    app.router.add_post("/api/admin/case/delete", api_admin_case_delete)
    app.router.add_post("/api/admin/items/bulk", api_admin_items_bulk)
    app.router.add_post("/api/admin/item/save", api_admin_item_save)
    app.router.add_post("/api/admin/item/delete", api_admin_item_delete)
    app.router.add_post("/api/admin/ads", api_admin_ads)
    app.router.add_post("/api/admin/ads/save", api_admin_ads_save)
    app.router.add_post("/api/admin/upload", api_admin_upload)
    app.router.add_post("/api/admin/signals", api_admin_signals)
    app.router.add_post("/api/admin/signals/save", api_admin_signals_save)
    app.router.add_post("/api/admin/user", api_admin_user)
    app.router.add_post("/api/admin/coins", api_admin_coins)
    app.router.add_get("/api/cases", api_cases)
    app.router.add_post("/api/me", api_me)
    app.router.add_post("/api/open", api_open)
    app.router.add_post("/api/inventory", api_inventory)
    app.router.add_post("/api/sell", api_sell)
    app.router.add_get("/media/{kind}/{file_id}", media)
