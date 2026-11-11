import asyncio
import random

from aiogram import F, Router
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
from config import ADMIN_IDS, SUPPORT_USERNAME, TERMS_TEXT, WEBAPP_URL

router = Router()


class Registration(StatesGroup):
    waiting_phone = State()


class SaperFlow(StatesGroup):
    waiting_game_id = State()


class AdminStates(StatesGroup):
    waiting_case_name = State()
    waiting_case_price = State()
    waiting_case_desc = State()
    waiting_case_image = State()

    waiting_item_name = State()
    waiting_item_price = State()
    waiting_item_image = State()
    waiting_item_prob = State()
    waiting_item_rarity = State()


def admin_menu() -> InlineKeyboardMarkup:
    # Admin panelda endi bitta bo'lim: Qutilar (yaratish, sovg'a qo'shish va ro'yxat shu yerda)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Qutilar", callback_data="admin_boxes")],
        [InlineKeyboardButton(text="🔙 Bosh menyu", callback_data="go_home")],
    ])


def admin_boxes_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="➕ Quti yaratish", callback_data="admin_add_case")]]
    for case in db.get_cases():
        rows.append([
            InlineKeyboardButton(
                text=f"📦 {case['name']} — {case['price']} so'm",
                callback_data=f"admin_case_{case['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 Admin panel", callback_data="menu_admin")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_case_keyboard(case_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🎁 Sovg‘a qo‘shish", callback_data=f"admin_item_{case_id}")]]
    for item in db.get_case_items(case_id):
        rows.append([
            InlineKeyboardButton(text=f"🗑 {item['name']}", callback_data=f"admin_di_{item['id']}")
        ])
    rows.append([InlineKeyboardButton(text="🗑 Qutini o‘chirish", callback_data=f"admin_dc_{case_id}")])
    rows.append([InlineKeyboardButton(text="🔙 Qutilar", callback_data="admin_boxes")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_case_text(case_id: int) -> str:
    case = db.get_case(case_id)
    if not case:
        return "Quti topilmadi."
    items = db.get_case_items(case_id)
    lines = [f"📦 {case['name']} (ID: {case['id']})", f"💰 Narx: {case['price']} so'm"]
    if case["description"]:
        lines.append(case["description"])
    lines.append("")
    if items:
        total = sum(float(i["probability"]) for i in items)
        lines.append(f"🎁 Sovg‘alar ({len(items)}):")
        for n, item in enumerate(items, 1):
            lines.append(f"{n}. {item['name']} — {item['price']} so'm — {item['rarity']} — {item['probability']}%")
        lines.append(f"\nFoizlar yig‘indisi: {round(total, 2)}")
    else:
        lines.append("Hozircha sovg‘a yo‘q. «🎁 Sovg‘a qo‘shish» tugmasini bosing.")
    return "\n".join(lines)


def main_menu() -> InlineKeyboardMarkup:
    rows = []
    if WEBAPP_URL.startswith("https://"):
        rows.append([InlineKeyboardButton(text="🚀 Mini App ochish", web_app=WebAppInfo(url=WEBAPP_URL))])

    rows.extend([
        [InlineKeyboardButton(text="🎁 Super Qutilar", callback_data="menu_boxes"), InlineKeyboardButton(text="📡 Bulldrop Signal", callback_data="menu_signal")],
        [InlineKeyboardButton(text="🎮 Botdagi o‘yinlar", callback_data="menu_games"), InlineKeyboardButton(text="👤 Hisobim", callback_data="menu_account")],
        [InlineKeyboardButton(text="🏆 Yutuqlarim", callback_data="menu_rewards"), InlineKeyboardButton(text="📊 Statistika", callback_data="menu_stats")],
        [InlineKeyboardButton(text="💬 Bot support", callback_data="menu_support")],
    ])

    if ADMIN_IDS:
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
                text=f"{case['name']} — {case['price']} so'm",
                callback_data=f"case_open_{case['id']}"
            )
        ])
    rows.append([InlineKeyboardButton(text="↩️ Bosh menyu", callback_data="go_home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_home(message: Message) -> None:
    await message.answer("BULLDROP bosh menyusi:", reply_markup=main_menu())


@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
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
    # Telegram bo'sh matnli xabarni qabul qilmaydi, shuning uchun belgi yuboramiz
    await message.answer("👋", reply_markup=ReplyKeyboardRemove())
    await send_home(message)


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
    await send_home(message)


@router.message(Registration.waiting_phone)
async def require_contact(message: Message) -> None:
    await message.answer("Telefon raqamni pastdagi Telegram kontakt tugmasi orqali yuboring.", reply_markup=phone_keyboard())


@router.callback_query(F.data == "menu_signal")
async def open_signals(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await call.message.edit_text(
            "📡 Bulldrop Signal\n\nSinov rejimi: demo qiymatlar haqiqiy o‘yin natijalarini bashorat qilmaydi.",
            reply_markup=signal_keyboard(),
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


@router.callback_query(F.data == "go_home")
async def go_home(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await call.message.edit_text("BULLDROP bosh menyusi:", reply_markup=main_menu())


@router.callback_query(F.data == "menu_account")
async def account_callback(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await call.message.answer(
            f"👤 Hisobim\nTelegram ID: {call.from_user.id}\n"
            "🧧 Demo balans: 0\nTo‘lov va pul yechish bu prototipda o‘chiq.",
            reply_markup=main_menu(),
        )


@router.callback_query(F.data == "menu_support")
async def support_callback(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await call.message.answer(f"💬 Support: https://t.me/{SUPPORT_USERNAME}", reply_markup=main_menu())


@router.message(Command("support"))
@router.message(F.text == "💬 Bot support")
async def support_message(message: Message) -> None:
    await message.answer(f"💬 Support: https://t.me/{SUPPORT_USERNAME}", reply_markup=main_menu())


@router.callback_query(F.data == "menu_boxes")
async def menu_boxes(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await call.message.edit_text("🎁 Super Qutilar", reply_markup=cases_keyboard())


@router.callback_query(F.data == "menu_admin")
async def menu_admin(call: CallbackQuery) -> None:
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Bu bo‘lim faqat admin uchun.", show_alert=True)
        return
    await call.answer()
    if call.message:
        await call.message.edit_text("🛠 Admin panel", reply_markup=admin_menu())


@router.callback_query(F.data == "admin_add_case")
async def admin_add_case(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    await call.answer()
    await state.set_state(AdminStates.waiting_case_name)
    if call.message:
        await call.message.edit_text("Quti nomini kiriting:")


@router.callback_query(F.data == "admin_boxes")
async def admin_boxes(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    await call.answer()
    await state.clear()
    if call.message:
        text = "📦 Qutilar\n\nQuti tanlang yoki yangisini yarating:" if db.get_cases() else "📦 Qutilar\n\nHozircha quti yo‘q. Birinchisini yarating:"
        await call.message.edit_text(text, reply_markup=admin_boxes_keyboard())


@router.callback_query(F.data.startswith("admin_case_"))
async def admin_case_view(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    case_id = int(call.data.replace("admin_case_", ""))
    if not db.get_case(case_id):
        await call.answer("Quti topilmadi.", show_alert=True)
        return
    await call.answer()
    await state.clear()
    if call.message:
        await call.message.edit_text(admin_case_text(case_id), reply_markup=admin_case_keyboard(case_id))


@router.callback_query(F.data.startswith("admin_item_"))
async def admin_add_item(call: CallbackQuery, state: FSMContext) -> None:
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    case_id = int(call.data.replace("admin_item_", ""))
    if not db.get_case(case_id):
        await call.answer("Quti topilmadi.", show_alert=True)
        return
    await call.answer()
    await state.update_data(item_case_id=case_id)
    await state.set_state(AdminStates.waiting_item_name)
    if call.message:
        await call.message.answer("Sovg‘a nomini kiriting:")


@router.callback_query(F.data.startswith("admin_di_"))
async def admin_delete_item(call: CallbackQuery) -> None:
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    case_id = db.deactivate_item(int(call.data.replace("admin_di_", "")))
    if case_id is None:
        await call.answer("Sovg‘a topilmadi.", show_alert=True)
        return
    await call.answer("Sovg‘a o‘chirildi.")
    if call.message:
        await call.message.edit_text(admin_case_text(case_id), reply_markup=admin_case_keyboard(case_id))


@router.callback_query(F.data.startswith("admin_dc_"))
async def admin_delete_case(call: CallbackQuery) -> None:
    if call.from_user.id not in ADMIN_IDS:
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    db.deactivate_case(int(call.data.replace("admin_dc_", "")))
    await call.answer("Quti o‘chirildi.")
    if call.message:
        await call.message.edit_text("📦 Qutilar", reply_markup=admin_boxes_keyboard())


@router.message(AdminStates.waiting_case_name)
async def admin_case_name(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.update_data(case_name=message.text)
    await state.set_state(AdminStates.waiting_case_price)
    await message.answer("Quti ochish narxini son bilan kiriting:")


@router.message(AdminStates.waiting_case_price)
async def admin_case_price(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        price = int(message.text)
    except ValueError:
        await message.answer("Narx son bo‘lishi kerak. Qayta kiriting:")
        return
    await state.update_data(case_price=price)
    await state.set_state(AdminStates.waiting_case_desc)
    await message.answer("Quti haqida qisqa ma’lumot yozing:")


@router.message(AdminStates.waiting_case_desc)
async def admin_case_desc(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.update_data(case_desc=message.text)
    await state.set_state(AdminStates.waiting_case_image)
    await message.answer("Quti rasmi URL yoki GIF URL yuboring. Bo‘sh qoldirish mumkin:")


@router.message(AdminStates.waiting_case_image)
async def admin_case_image(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()

    case_id = db.add_case(
        name=data["case_name"],
        price=data["case_price"],
        description=data.get("case_desc", ""),
        image_url=(message.text or "").strip(),
    )
    await state.clear()
    await message.answer(
        "✅ Quti yaratildi!\n\n" + admin_case_text(case_id),
        reply_markup=admin_case_keyboard(case_id),
    )


@router.message(AdminStates.waiting_item_name)
async def admin_item_name(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.update_data(item_name=message.text)
    await state.set_state(AdminStates.waiting_item_price)
    await message.answer("Sovg‘a narxini son bilan kiriting:")


@router.message(AdminStates.waiting_item_price)
async def admin_item_price(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        price = int(message.text)
    except ValueError:
        await message.answer("Narx son bo‘lishi kerak. Qayta kiriting:")
        return
    await state.update_data(item_price=price)
    await state.set_state(AdminStates.waiting_item_image)
    await message.answer("Sovg‘a rasmi URL yoki GIF URL yuboring. Bo‘sh qoldirish mumkin:")


@router.message(AdminStates.waiting_item_image)
async def admin_item_image(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.update_data(item_image=(message.text or "").strip())
    await state.set_state(AdminStates.waiting_item_prob)
    await message.answer("Foiz qiymatini kiriting (masalan: 10.5):")


@router.message(AdminStates.waiting_item_prob)
async def admin_item_prob(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        probability = float(message.text)
    except ValueError:
        await message.answer("Foiz son bo‘lishi kerak. Qayta kiriting:")
        return
    await state.update_data(item_prob=probability)
    await state.set_state(AdminStates.waiting_item_rarity)
    await message.answer("Rarity kiriting: common / rare / epic / legendary / mythic")


@router.message(AdminStates.waiting_item_rarity)
async def admin_item_rarity(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    rarity = (message.text or "common").strip().lower()
    if rarity not in {"common", "rare", "epic", "legendary", "mythic"}:
        await message.answer("Noto‘g‘ri rarity. common / rare / epic / legendary / mythic dan birini kiriting:")
        return

    data = await state.get_data()
    db.add_case_item(
        case_id=data["item_case_id"],
        name=data["item_name"],
        price=data["item_price"],
        image_url=data.get("item_image", ""),
        probability=data["item_prob"],
        rarity=rarity,
    )
    await state.clear()
    case_id = data["item_case_id"]
    await message.answer(
        "✅ Sovg‘a qo‘shildi!\n\n" + admin_case_text(case_id),
        reply_markup=admin_case_keyboard(case_id),
    )


@router.callback_query(F.data.startswith("case_open_"))
async def open_case(call: CallbackQuery) -> None:
    case_id = int(call.data.replace("case_open_", ""))
    case = db.get_case(case_id)
    if not case:
        await call.answer("Quti topilmadi.", show_alert=True)
        return

    items = db.get_case_items(case_id)
    if not items:
        await call.answer("Bu qutida sovg‘a yo‘q.", show_alert=True)
        return

    winner = db.pick_case_item(case_id)
    await call.answer(f"{case['name']} ochilmoqda...")

    if call.message:
        await call.message.answer(
            f"🎁 {case['name']} ochildi\n\n"
            f"Yutgan sovg‘a: {winner['name']}\n"
            f"Narx: {winner['price']} so'm\n"
            f"Rarity: {winner['rarity']}"
        )


@router.callback_query(F.data.in_({"menu_games", "menu_rewards", "menu_stats"}))
async def planned_sections(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await call.message.edit_text("Bu bo‘lim hozircha ishlab chiqilmoqda.", reply_markup=main_menu())


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Bu buyruq faqat admin uchun.")
        return
    await message.answer("🛠 Admin panel", reply_markup=admin_menu())


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("Menyudan tanlang yoki /start yuboring.", reply_markup=main_menu())