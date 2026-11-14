import asyncio
import random
from urllib.parse import quote

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
from config import ADMIN_IDS, BOT_USERNAME, SUPPORT_USERNAME, TERMS_TEXT, WEBAPP_URL

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
    paid = db.pay_referral(message.from_user.id)  # do'st taklifi bonusi (bir marta)
    if paid and paid["amount"] > 0:
        try:
            await message.bot.send_message(
                paid["referrer_id"],
                f"🎉 Do‘stingiz ro‘yxatdan o‘tdi! Sizga +{fmt_num(paid['amount'])} {COIN} demo bonus berildi.",
            )
        except Exception:
            pass
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


@router.callback_query(F.data == "game_soon")
async def game_soon(call: CallbackQuery) -> None:
    await call.answer("Crash tez orada qo‘shiladi.", show_alert=True)


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



# ------------------------------------------------------------------ bonus: do'st chaqirish va shartlar

TASK_ICONS = {"approved": "✅", "pending": "⏳", "rejected": "❌"}


def referral_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}" if BOT_USERNAME else ""


def bonus_view(user_id: int):
    reward = db.ref_reward()
    link = referral_link(user_id)
    tasks = db.get_tasks()
    status = db.claim_statuses(user_id)
    text = (
        "💎 Bonus\n\n"
        f"👥 Do‘st chaqirish\n"
        f"Taklif qilgan har bir do‘stingiz ro‘yxatdan o‘tsa (telefon yuborsa) — sizga +{fmt_num(reward)} {COIN}.\n"
        + (f"Sizning havolangiz:\n{link}\n" if link else "Havola hozircha mavjud emas (BOT_USERNAME sozlanmagan).\n")
        + f"Ro‘yxatdan o‘tgan do‘stlar: {db.count_referrals(user_id)}\n\n"
        "🎯 Shartlar\n"
        + ("Quyidagi shartlarni bajaring va bonus oling:" if tasks else "Hozircha shartlar yo‘q.")
        + "\n\nBonus faqat o‘yin ichidagi demo coin; pulga almashtirilmaydi."
    )
    rows = []
    for task in tasks:
        icon = TASK_ICONS.get(status.get(task["id"]), "🎯")
        rows.append([InlineKeyboardButton(
            text=f"{icon} {task['title']} +{fmt_num(task['reward'])} {COIN}"[:60],
            callback_data=f"bonus_t_{task['id']}",
        )])
    if link:
        share = f"https://t.me/share/url?url={quote(link)}&text={quote('BULLDROP — demo o‘yinlar va sovg‘a qutilari!')}"
        rows.append([InlineKeyboardButton(text="📤 Do‘stga yuborish", url=share)])
    rows.append([InlineKeyboardButton(text="↩️ Bosh menyu", callback_data="go_home")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "menu_bonus")
async def menu_bonus(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        text, markup = bonus_view(call.from_user.id)
        await edit_or_send(call.message, text, markup)


@router.callback_query(F.data.startswith("bonus_t_"))
async def bonus_task_view(call: CallbackQuery) -> None:
    await call.answer()
    task = db.get_task(call.data.replace("bonus_t_", "")) if call.data.replace("bonus_t_", "").isdigit() else None
    if not task or not task["is_active"]:
        if call.message:
            await edit_or_send(call.message, "Bu shart topilmadi.", InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="🔙 Bonus", callback_data="menu_bonus")]]))
        return
    status = db.claim_statuses(call.from_user.id).get(task["id"])
    text = f"🎯 {task['title']}\n\n{task['description'] or ''}\n\nMukofot: +{fmt_num(task['reward'])} {COIN}"
    rows = []
    if task["url"].lower().startswith(("https://", "http://")):
        rows.append([InlineKeyboardButton(text="🔗 Bajarish uchun havola", url=task["url"])])
    if status == "approved":
        text += "\n\n✅ Bu shart bajarilgan, bonus olingan."
    elif status == "pending":
        text += "\n\n⏳ So‘rovingiz admin tasdig‘ini kutmoqda."
    else:
        if status == "rejected":
            text += "\n\n❌ Oldingi so‘rovingiz rad etilgan. Shartni bajarib, qayta yuboring."
        rows.append([InlineKeyboardButton(text="✅ Bajardim", callback_data=f"bonus_d_{task['id']}")])
    rows.append([InlineKeyboardButton(text="🔙 Bonus", callback_data="menu_bonus")])
    if call.message:
        await edit_or_send(call.message, text, InlineKeyboardMarkup(inline_keyboard=rows))


async def _is_channel_member(bot, channel: str, user_id: int):
    """True/False — a'zo yoki yo'q; None — tekshirib bo'lmadi (bot kanalda admin emas va hokazo)."""
    chat = int(channel) if channel.lstrip("-").isdigit() else channel
    try:
        member = await bot.get_chat_member(chat, user_id)
    except Exception:
        return None
    return member.status in ("creator", "administrator", "member", "restricted")


@router.callback_query(F.data.startswith("bonus_d_"))
async def bonus_done(call: CallbackQuery) -> None:
    raw = call.data.replace("bonus_d_", "")
    task = db.get_task(raw) if raw.isdigit() else None
    if not task or not task["is_active"]:
        await call.answer("Bu shart topilmadi.", show_alert=True)
        return
    user = call.from_user
    if not is_registered(user.id):
        await call.answer("Avval /start bosib ro‘yxatdan o‘ting.", show_alert=True)
        return

    # Kanal sharti: bot kanalda admin bo'lsa, a'zolik avtomatik tekshiriladi
    if task["channel"]:
        member = await _is_channel_member(call.bot, task["channel"], user.id)
        if member is False:
            await call.answer("Siz hali kanalga a‘zo emassiz. A‘zo bo‘lib, qayta bosing.", show_alert=True)
            return
        if member:
            res = db.auto_approve(task["id"], user.id)
            if not res["ok"]:
                await call.answer("Bu bonus allaqachon olingan.", show_alert=True)
            else:
                await call.answer(f"🎉 +{fmt_num(res['reward'])} {COIN} bonus berildi!", show_alert=True)
            if call.message:
                text, markup = bonus_view(user.id)
                await edit_or_send(call.message, text, markup)
            return
        # member is None: bot tekshira olmadi — qo'lda tasdiqlashga o'tamiz

    res = db.submit_claim(task["id"], user.id)
    if not res["ok"]:
        msg = "Bonus allaqachon olingan." if res["status"] == "approved" else "So‘rovingiz allaqachon admin tasdig‘ida."
        await call.answer(msg, show_alert=True)
        return
    await call.answer("✅ So‘rov adminga yuborildi. Tasdiqlansa, bonus beriladi.", show_alert=True)
    name = user.full_name + (f" (@{user.username})" if user.username else "")
    note = (
        f"🧾 Bonus so‘rovi #{res['claim_id']}\n\n"
        f"Foydalanuvchi: {name}\nID: {user.id}\n"
        f"Shart: {task['title']}\nMukofot: {fmt_num(task['reward'])} {COIN}\n\n"
        "Shartni bajarganini tekshirib, qaror qiling:"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"bonus_ok_{res['claim_id']}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"bonus_no_{res['claim_id']}"),
    ]])
    for admin_id in ADMIN_IDS:
        try:
            await call.bot.send_message(admin_id, note, reply_markup=markup)
        except Exception:
            pass
    if call.message:
        text, markup2 = bonus_view(user.id)
        await edit_or_send(call.message, text, markup2)

# ------------------------------------------------------------------ boshqa

def _game_button(text: str, game: str, fallback: str) -> InlineKeyboardButton:
    """Mini App'ni to‘g‘ridan-to‘g‘ri shu o‘yin ochiq holda ishga tushiradi."""
    if WEBAPP_URL.startswith("https://"):
        sep = "&" if "?" in WEBAPP_URL else "?"
        return InlineKeyboardButton(text=text, web_app=WebAppInfo(url=f"{WEBAPP_URL}{sep}game={game}"))
    return InlineKeyboardButton(text=text, callback_data=fallback)


def games_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_game_button("🎡 G‘ildirak", "wheel", "menu_games")],
        [_game_button("💣 Saper", "mines", "signal_saper")],
        [_game_button("🗼 Minora", "tower", "signal_tower")],
        [_game_button("🪜 Narvon", "ladder", "signal_ladder")],
        [_game_button("🏗 Qurilish", "build", "menu_games")],
        [InlineKeyboardButton(text="💥 Crash — tez orada", callback_data="game_soon")],
        [InlineKeyboardButton(text="🔙 Bosh menyu", callback_data="go_home")],
    ])


@router.callback_query(F.data == "menu_games")
async def games_menu(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await call.message.edit_text(
            "🎮 Botdagi o‘yinlar\n\nBarcha o‘yinlar demo: faqat virtual coin bilan o‘ynaladi, haqiqiy pul yo‘q. Eng kam tikish — 500 coin.",
            reply_markup=games_keyboard(),
        )


@router.callback_query(F.data.in_({"menu_rewards", "menu_stats"}))
async def planned_sections(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await edit_or_send(call.message, "Bu bo‘lim hozircha ishlab chiqilmoqda.", main_menu(call.from_user.id))


@router.message()
async def fallback(message: Message) -> None:
    # Xizmat xabarlari (masalan, "fayl qadaldi") va botning o'z xabarlariga javob bermaymiz
    if message.pinned_message or not message.from_user or message.from_user.is_bot:
        return
    await message.answer("Menyudan tanlang yoki /start yuboring.", reply_markup=main_menu(message.from_user.id))
