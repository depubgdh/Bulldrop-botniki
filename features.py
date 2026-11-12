import asyncio
import random

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

import db
from common import (
    COIN,
    MENU_ITEMS,
    channel_url,
    check_subscription,
    edit_or_send,
    fmt_num,
    menu_layout,
)
from config import ADMIN_IDS, SUPPORT_USERNAME, TERMS_TEXT, WEBAPP_URL

router = Router()

RARITY_LABELS = {
    "common": "⚪ Oddiy",
    "rare": "🔵 Noyob",
    "epic": "🟣 Epik",
    "legendary": "🟡 Afsonaviy",
    "mythic": "🔴 Mifik",
}
INVENTORY_PAGE = 20


class Registration(StatesGroup):
    waiting_phone = State()


class SaperFlow(StatesGroup):
    waiting_game_id = State()


# ------------------------------------------------------------------ tugmalar

def _button(text: str, data: str, style=None) -> InlineKeyboardButton:
    if style:
        try:
            return InlineKeyboardButton(text=text, callback_data=data, style=style)
        except Exception:
            pass  # aiogram/Telegram bu versiyada rangni bilmasa, oddiy tugma
    return InlineKeyboardButton(text=text, callback_data=data)


def main_menu(user_id=None) -> InlineKeyboardMarkup:
    rows = []
    if WEBAPP_URL.startswith("https://"):
        rows.append([InlineKeyboardButton(text="🚀 Mini App ochish", web_app=WebAppInfo(url=WEBAPP_URL))])

    layout = menu_layout()
    hidden = set(layout["hidden"])
    buttons = [
        _button(MENU_ITEMS[item], f"menu_{item}", layout["style"].get(item))
        for item in layout["order"]
        if item not in hidden
    ]
    for start in range(0, len(buttons), 2):
        rows.append(buttons[start:start + 2])

    if user_id in ADMIN_IDS:
        rows.append([InlineKeyboardButton(text="🛠 Admin panel", callback_data="menu_admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def terms_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Davom etish", callback_data="accept_terms")]])


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def signal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Crash — demo", callback_data="signal_crash")],
        [InlineKeyboardButton(text="Saper — demo", callback_data="signal_saper")],
        [InlineKeyboardButton(text="Narvon", callback_data="signal_ladder")],
        [InlineKeyboardButton(text="Minora", callback_data="signal_tower")],
        [InlineKeyboardButton(text="↩️ Bosh menyu", callback_data="go_home")],
    ])


def saper_keyboard(green_cells: list[int]) -> InlineKeyboardMarkup:
    rows = []
    for row in range(5):
        rows.append([
            InlineKeyboardButton(
                text="🟩" if row * 5 + col + 1 in green_cells else "☑️",
                callback_data="saper_cell",
            )
            for col in range(5)
        ])
    rows.append([InlineKeyboardButton(text="↩️ Bosh menyu", callback_data="go_home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cases_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for case in db.get_cases():
        rows.append([
            InlineKeyboardButton(
                text=f"{case['name']} — {fmt_num(case['price'])} {COIN}",
                callback_data=f"case_open_{case['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="↩️ Bosh menyu", callback_data="go_home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wallet_line(user_id: int) -> str:
    w = db.wallet(user_id)
    return f"{COIN} Coin: {fmt_num(w['coins'])}  ·  🎟 Tekin ochish: {w['free_left']}"


# ------------------------------------------------------------------ bosh menyu

async def show_home(message: Message, user_id: int, from_callback: bool = False) -> None:
    """Bosh menyuni ko'rsatadi (admin o'rnatgan matn va rasm bilan)."""
    text = db.get_setting("home_text") or "BULLDROP bosh menyusi:"
    photo = db.get_setting("home_image")
    markup = main_menu(user_id)
    if photo:
        if from_callback:
            try:
                await message.delete()
            except Exception:
                pass
        try:
            await message.answer_photo(photo, caption=text[:1024], reply_markup=markup)
            return
        except Exception:
            pass  # rasm yaroqsiz bo'lsa, oddiy matn ko'rsatamiz
    if from_callback:
        await edit_or_send(message, text, markup)
    else:
        await message.answer(text, reply_markup=markup)


def is_registered(user_id: int) -> bool:
    user = db.get_user(user_id)
    return bool(user and user["accepted_terms"] and user["phone"])


# ------------------------------------------------------------------ majburiy kanal

def subscribe_keyboard(channel: str) -> InlineKeyboardMarkup:
    rows = []
    url = channel_url(channel)
    if url:
        rows.append([InlineKeyboardButton(text="📢 Kanalga o‘tish", url=url)])
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class SubscriptionGate(BaseMiddleware):
    """Admin majburiy kanal yoqqan bo'lsa, a'zo bo'lmagan (ro'yxatdan o'tgan) foydalanuvchini to'xtatadi."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if user and not user.is_bot and getattr(event, "data", None) not in ("check_sub", "accept_terms"):
            if is_registered(user.id):
                ok, channel = await check_subscription(data["bot"], user.id)
                if not ok:
                    text = "📢 Botdan foydalanish uchun kanalimizga a‘zo bo‘ling, so‘ng «✅ Tekshirish» tugmasini bosing."
                    markup = subscribe_keyboard(channel)
                    if isinstance(event, CallbackQuery):
                        await event.answer()
                        if event.message:
                            await event.message.answer(text, reply_markup=markup)
                    else:
                        await event.answer(text, reply_markup=markup)
                    return None
        return await handler(event, data)


router.message.outer_middleware(SubscriptionGate())
router.callback_query.outer_middleware(SubscriptionGate())


@router.callback_query(F.data == "check_sub")
async def check_sub(call: CallbackQuery) -> None:
    ok, _ = await check_subscription(call.bot, call.from_user.id)
    if not ok:
        await call.answer("Siz hali kanalga a‘zo emassiz.", show_alert=True)
        return
    await call.answer("✅ Rahmat!")
    if call.message:
        await show_home(call.message, call.from_user.id, from_callback=True)


# ------------------------------------------------------------------ ro'yxatdan o'tish

@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    # Do'st taklifi: /start ref_<taklif qilgan odam ID si>
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("ref_") and parts[1][4:].isdigit():
        db.register_referral(message.from_user.id, int(parts[1][4:]))
    user = db.get_user(message.from_user.id)
    if not user or not user["accepted_terms"]:
        await message.answer(TERMS_TEXT, reply_markup=terms_keyboard())
        return
    if not user["phone"]:
        await state.set_state(Registration.waiting_phone)
        await message.answer("Telefon raqamingizni Telegram tugmasi orqali yuboring:", reply_markup=phone_keyboard())
        return
    await show_home(message, message.from_user.id)


@router.callback_query(F.data == "accept_terms")
async def accept_terms(call: CallbackQuery, state: FSMContext) -> None:
    db.save_user(call.from_user.id, call.from_user.username, accepted_terms=1)
    await call.answer("Rozilik saqlandi.")
    if call.message:
        await state.set_state(Registration.waiting_phone)
        await call.message.answer("Telefon raqamingizni Telegram tugmasi orqali yuboring:", reply_markup=phone_keyboard())


@router.message(Registration.waiting_phone, F.contact)
async def receive_phone(message: Message, state: FSMContext) -> None:
    contact = message.contact
    if message.chat.type != "private" or not contact or contact.user_id != message.from_user.id:
        await message.answer("Shaxsiy chatda o‘zingizning telefon raqamingizni yuboring.")
        return
    db.save_user(message.from_user.id, message.from_user.username, phone=contact.phone_number)
    await state.clear()
    await message.answer("✅ Ro‘yxatdan o‘tdingiz!", reply_markup=ReplyKeyboardRemove())
    await show_home(message, message.from_user.id)


@router.message(Registration.waiting_phone)
async def require_contact(message: Message) -> None:
    await message.answer("Telefon raqamni pastdagi Telegram kontakt tugmasi orqali yuboring.", reply_markup=phone_keyboard())


# ------------------------------------------------------------------ signal (demo)

@router.callback_query(F.data == "menu_signal")
async def open_signals(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await edit_or_send(
            call.message,
            "📡 Bulldrop Signal\n\nSinov rejimi: demo qiymatlar haqiqiy o‘yin natijalarini bashorat qilmaydi.",
            signal_keyboard(),
        )


@router.message(F.text == "📡 Bulldrop Signal")
async def open_signals_legacy(message: Message) -> None:
    await message.answer("📡 Signal demo rejimida. Haqiqiy o‘yin natijalari bashorat qilinmaydi.", reply_markup=signal_keyboard())


@router.callback_query(F.data == "signal_crash")
async def crash_demo(call: CallbackQuery) -> None:
    await call.answer()
    value = random.randint(101, 420) / 100
    if call.message:
        await call.message.answer(f"Crash demo qiymati: {value:.2f}x\nBu tasodifiy demo; haqiqiy signal yoki bashorat emas.")


@router.callback_query(F.data == "signal_saper")
async def saper_start(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(SaperFlow.waiting_game_id)
    if call.message:
        await call.message.answer("Saper demo uchun o‘yin ID raqamini yuboring:")


@router.message(SaperFlow.waiting_game_id)
async def saper_game_id(message: Message, state: FSMContext) -> None:
    game_id = (message.text or "").strip()
    if not game_id or len(game_id) > 80:
        await message.answer("ID 1–80 belgi bo‘lishi kerak. Qayta yuboring.")
        return
    await state.clear()
    loading = await message.answer("⏳ Demo ko‘rinish tayyorlanmoqda...")
    await asyncio.sleep(2)
    green = sorted(random.sample(range(1, 26), 3))
    db.add_saper_result(message.from_user.id, game_id, green)
    board = [" ".join("🟩" if row * 5 + col + 1 in green else "☑️" for col in range(5)) for row in range(5)]
    await loading.edit_text(
        f"Demo ID: {game_id}\n\n" + "\n".join(board) + "\n\nTasodifiy kataklar; haqiqiy o‘yin uchun signal emas.",
        reply_markup=saper_keyboard(green),
    )


@router.callback_query(F.data == "saper_cell")
async def saper_cell(call: CallbackQuery) -> None:
    await call.answer("Bu faqat demo ko‘rinish.")


@router.callback_query(F.data.in_({"signal_ladder", "signal_tower"}))
async def unavailable_signal(call: CallbackQuery) -> None:
    await call.answer("Bu bo‘lim hali ishlab chiqilmoqda.", show_alert=True)


# ------------------------------------------------------------------ bosh menyu, hisob, support

@router.callback_query(F.data == "go_home")
async def go_home(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    if call.message:
        await show_home(call.message, call.from_user.id, from_callback=True)


@router.callback_query(F.data == "menu_account")
async def account_callback(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        w = db.wallet(call.from_user.id)
        inv = db.inventory_list(call.from_user.id)
        await call.message.answer(
            f"👤 Hisobim\n"
            f"Telegram ID: {call.from_user.id}\n"
            f"{COIN} Coin: {fmt_num(w['coins'])}\n"
            f"🎟 Tekin ochishlar: {w['free_left']}\n"
            f"🎒 Inventory: {len(inv)} ta sovg‘a\n\n"
            "Coin faqat o‘yin ichida ishlatiladi; to‘lov va pul yechish bu versiyada yo‘q.",
            reply_markup=main_menu(call.from_user.id),
        )


@router.callback_query(F.data == "menu_support")
async def support_callback(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await call.message.answer(f"💬 Support: https://t.me/{SUPPORT_USERNAME}", reply_markup=main_menu(call.from_user.id))


@router.message(Command("support"))
@router.message(F.text == "💬 Bot support")
async def support_message(message: Message) -> None:
    await message.answer(f"💬 Support: https://t.me/{SUPPORT_USERNAME}", reply_markup=main_menu(message.from_user.id))


# ------------------------------------------------------------------ qutilar

@router.callback_query(F.data == "menu_boxes")
async def menu_boxes(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await edit_or_send(
            call.message,
            f"🎁 Super Qutilar\n\n{wallet_line(call.from_user.id)}",
            cases_keyboard(),
        )


@router.callback_query(F.data.startswith("case_open_"))
async def open_case(call: CallbackQuery) -> None:
    case_id = int(call.data.replace("case_open_", ""))
    res = db.open_case(call.from_user.id, case_id)
    if not res["ok"]:
        messages = {
            "no_case": "Quti topilmadi.",
            "no_items": "Bu qutida sovg‘a yo‘q.",
            "no_funds": f"Coin yetarli emas. Quti narxi: {fmt_num(res.get('price', 0))} {COIN}, sizda: {fmt_num(res.get('coins', 0))} {COIN}.",
        }
        await call.answer(messages.get(res["error"], "Xatolik."), show_alert=True)
        return

    case = db.get_case(case_id)
    item, w = res["item"], res["wallet"]
    await call.answer("🎁 Ochildi!")
    if call.message:
        paid = "tekin" if res["free"] else f"{fmt_num(case['price'])} {COIN}"
        await call.message.answer(
            f"🎁 {case['name']} ochildi ({paid})\n\n"
            f"Tushgan sovg‘a: {item['name']}\n"
            f"Daraja: {RARITY_LABELS.get(item['rarity'], item['rarity'])}\n"
            f"Qiymati: {fmt_num(item['price'])} {COIN}\n\n"
            f"{COIN} Coin: {fmt_num(w['coins'])}  ·  🎟 Tekin ochish: {w['free_left']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"💰 Sotish +{fmt_num(item['price'])} {COIN}", callback_data=f"sell_{item['id']}")],
                [InlineKeyboardButton(text="🎁 Yana ochish", callback_data=f"case_open_{case_id}")],
                [InlineKeyboardButton(text="🎒 Inventory", callback_data="menu_inventory")],
            ]),
        )


# ------------------------------------------------------------------ inventory

def inventory_view(user_id: int):
    items = db.inventory_list(user_id)
    head = f"🎒 Inventory\n{wallet_line(user_id)}"
    rows = []
    if not items:
        text = head + "\n\nHozircha bo‘sh. Qutilarni oching va sovg‘alarni to‘plang!"
    else:
        total = sum(int(i["price"]) for i in items)
        text = head + f"\n\n{len(items)} ta sovg‘a, jami {fmt_num(total)} {COIN}"
        for item in items[:INVENTORY_PAGE]:
            rows.append([InlineKeyboardButton(
                text=f"💰 {item['name']} +{fmt_num(item['price'])} {COIN}",
                callback_data=f"sell_{item['id']}",
            )])
        if len(items) > INVENTORY_PAGE:
            text += f"\n(Birinchi {INVENTORY_PAGE} tasi ko‘rsatilmoqda; hammasi Mini App’da.)"
        rows.append([InlineKeyboardButton(text=f"💰 Hammasini sotish +{fmt_num(total)} {COIN}", callback_data="sell_all")])
    rows.append([InlineKeyboardButton(text="🎁 Qutilar", callback_data="menu_boxes")])
    rows.append([InlineKeyboardButton(text="↩️ Bosh menyu", callback_data="go_home")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "menu_inventory")
async def menu_inventory(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        text, markup = inventory_view(call.from_user.id)
        await edit_or_send(call.message, text, markup)


@router.callback_query(F.data == "sell_all")
async def sell_all(call: CallbackQuery) -> None:
    res = db.sell_all(call.from_user.id)
    if not res["ok"]:
        await call.answer("Sotadigan sovg‘a yo‘q.", show_alert=True)
        return
    await call.answer(f"Sotildi: +{fmt_num(res['gained'])} {COIN}")
    if call.message:
        text, markup = inventory_view(call.from_user.id)
        await edit_or_send(call.message, text, markup)


@router.callback_query(F.data.startswith("sell_"))
async def sell_one(call: CallbackQuery) -> None:
    try:
        inv_id = int(call.data.replace("sell_", ""))
    except ValueError:
        await call.answer()
        return
    res = db.sell_item(call.from_user.id, inv_id)
    if not res["ok"]:
        await call.answer("Bu sovg‘a allaqachon sotilgan.", show_alert=True)
        return
    await call.answer(f"Sotildi: +{fmt_num(res['gained'])} {COIN}")
    if call.message:
        text, markup = inventory_view(call.from_user.id)
        await edit_or_send(call.message, text, markup)


# ------------------------------------------------------------------ boshqa

@router.callback_query(F.data.in_({"menu_games", "menu_rewards", "menu_stats"}))
async def planned_sections(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await edit_or_send(call.message, "Bu bo‘lim hozircha ishlab chiqilmoqda.", main_menu(call.from_user.id))


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("Menyudan tanlang yoki /start yuboring.", reply_markup=main_menu(message.from_user.id))
