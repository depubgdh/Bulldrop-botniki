from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

import db
from admins import is_admin
from config import ADMIN_IDS, SUPPORT_USERNAME, TERMS_TEXT, WEBAPP_URL

router = Router()


class Registration(StatesGroup):
    waiting_phone = State()


class SaperFlow(StatesGroup):
    waiting_game_id = State()


def main_menu() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🎁 Super Qutilar", callback_data="menu_boxes"), InlineKeyboardButton(text="📡 Bulldrop Signal", callback_data="menu_signal")],
        [InlineKeyboardButton(text="🎮 Botdagi o‘yinlar", callback_data="menu_games"), InlineKeyboardButton(text="👤 Hisobim", callback_data="menu_account")],
        [InlineKeyboardButton(text="🏆 Yutuqlarim", callback_data="menu_rewards"), InlineKeyboardButton(text="📊 Statistika", callback_data="menu_stats")],
        [InlineKeyboardButton(text="💬 Bot support", callback_data="menu_support")],
    ]
    if WEBAPP_URL.startswith("https://"):
        rows.insert(0, [InlineKeyboardButton(text="🚀 Mini App ochish", web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def terms_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Davom etish", callback_data="accept_terms")]])


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)


def signal_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Crash — demo", callback_data="signal_crash")],
        [InlineKeyboardButton(text="Saper — demo", callback_data="signal_saper")],
        [InlineKeyboardButton(text="Narvon", callback_data="signal_ladder")],
        [InlineKeyboardButton(text="Minora", callback_data="signal_tower")],
        [InlineKeyboardButton(text="↩️ Bosh menyu", callback_data="go_home")],
    ])


def saper_keyboard(green_cells: list[int]) -> InlineKeyboardMarkup:
    buttons = []
    for row in range(5):
        buttons.append([
            InlineKeyboardButton(
                text="🟩" if row * 5 + col + 1 in green_cells else "☑️",
                callback_data="saper_cell",
            )
            for col in range(5)
        ])
    buttons.append([InlineKeyboardButton(text="↩️ Bosh menyu", callback_data="go_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def show_main_menu(message: Message) -> None:
    await message.answer("BULLDROP bosh menyusi:", reply_markup=main_menu())


async def ask_phone(message: Message, state: FSMContext) -> None:
    await state.set_state(Registration.waiting_phone)
    await message.answer("Davom etish uchun telefon raqamingizni Telegram tugmasi orqali yuboring:", reply_markup=phone_keyboard())


@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    user = db.get_user(message.from_user.id)
    if not user or not user["accepted_terms"]:
        await message.answer(TERMS_TEXT, reply_markup=terms_keyboard())
        return
    if not user["phone"]:
        await ask_phone(message, state)
        return
    await message.answer("BULLDROP bosh menyusi:", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(message)


@router.callback_query(F.data == "accept_terms")
async def accept_terms(call: CallbackQuery, state: FSMContext) -> None:
    db.save_user(call.from_user.id, call.from_user.username, accepted_terms=1)
    await call.answer("Rozilik saqlandi.")
    if call.message:
        await ask_phone(call.message, state)


@router.message(Registration.waiting_phone, F.contact)
async def receive_phone(message: Message, state: FSMContext) -> None:
    contact = message.contact
    if message.chat.type != "private" or not contact or contact.user_id != message.from_user.id:
        await message.answer("Iltimos, shaxsiy chatda o‘zingizning telefon raqamingizni yuboring.")
        return
    db.save_user(message.from_user.id, message.from_user.username, phone=contact.phone_number)
    await state.clear()
    await message.answer("✅ Ro‘yxatdan o‘tdingiz!", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(message)


@router.message(Registration.waiting_phone)
async def require_contact(message: Message) -> None:
    await message.answer("Telefon raqamni Telegram kontakt tugmasi orqali yuboring.", reply_markup=phone_keyboard())


@router.callback_query(F.data == "menu_signal")
async def open_signals_callback(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await call.message.edit_text("📡 Bulldrop Signal\n\nSinov rejimi: demo qiymatlar haqiqiy o‘yin natijalarini bashorat qilmaydi.", reply_markup=signal_keyboard())


@router.message(F.text == "📡 Bulldrop Signal")
async def open_signals_message(message: Message) -> None:
    await message.answer("📡 Bulldrop Signal\n\nSinov rejimi: demo qiymatlar haqiqiy o‘yin natijalarini bashorat qilmaydi.", reply_markup=ReplyKeyboardRemove())
    await message.answer("Bo‘limni tanlang:", reply_markup=signal_keyboard())


@router.callback_query(F.data == "signal_crash")
async def crash_demo(call: CallbackQuery) -> None:
    await call.answer("Demo rejimi; natijani bashorat qilmaydi.", show_alert=True)


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
        await message.answer("ID noto‘g‘ri. 1–80 belgi oralig‘ida yuboring.")
        return
    await state.clear()
    loading = await message.answer("Demo ko‘rinish tayyorlanmoqda...")
    await asyncio.sleep(2)
    green = sorted(random.sample(range(1, 26), 3))
    db.add_saper_result(message.from_user.id, game_id, green)
    rows = [" ".join("🟩" if row * 5 + col + 1 in green else "☑️" for col in range(5)) for row in range(5)]
    await loading.edit_text(f"Demo ID: {game_id}\n\n" + "\n".join(rows) + "\n\nTasodifiy demo kataklar; haqiqiy o‘yin uchun signal emas.", reply_markup=saper_keyboard(green))


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
        await send_account(call.message, call.from_user.id, call.from_user.username)


@router.message(F.text == "👤 Hisobim")
async def account_message(message: Message) -> None:
    await send_account(message, message.from_user.id, message.from_user.username)


async def send_account(message: Message, user_id: int, username: str | None) -> None:
    user = db.get_user(user_id)
    if not user or not user["accepted_terms"]:
        await message.answer("Avval /start orqali ro‘yxatdan o‘ting.")
        return
    await message.answer(f"👤 Hisobim\nFoydalanuvchi: @{username}" if username else f"👤 Hisobim\nTelegram ID: {user_id}")


@router.callback_query(F.data == "menu_support")
async def support_callback(call: CallbackQuery) -> None:
    await call.answer()
    if call.message:
        await send_support(call.message)


@router.message(Command("support"))
@router.message(F.text == "💬 Bot support")
async def support_message(message: Message) -> None:
    await send_support(message)


async def send_support(message: Message) -> None:
    await message.answer(f"💬 Support: https://t.me/{SUPPORT_USERNAME}", reply_markup=main_menu())


@router.callback_query(F.data.in_({"menu_games", "menu_boxes", "menu_rewards", "menu_stats"}))
async def planned_sections(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text("Bu bo‘lim hozircha sinov rejimida.", reply_markup=main_menu())


@router.message(F.text.in_({"🎁 Super Qutilar", "🎮 Botdagi o‘yinlar", "🏆 Yutuqlarim", "📊 Statistika"}))
async def planned_sections_message(message: Message) -> None:
    await message.answer("Bu bo‘lim hozircha sinov rejimida.", reply_markup=main_menu())


@router.message(Command("transactions"))
async def transactions(message: Message) -> None:
    rows = db.recent_transactions(message.from_user.id)
    if not rows:
        await message.answer("Tranzaksiyalar tarixi hozircha bo‘sh.")
        return
    lines = ["🧾 Oxirgi tranzaksiyalar:"]
    for row in rows:
        lines.append(f"{row['created_at']}: {row['kind']} · {row['amount_j']} J🧧 · {row['status']}")
    await message.answer("\n".join(lines))


@router.message(Command("admin"))
async def admin_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat admin uchun.")
        return
    await message.answer("Adminning xavfsiz ko‘rish paneli. Haqiqiy balans o‘zgartirish, to‘lov yoki pul yechish yoqilmagan.")


@router.message()
async def fallback(message: Message) -> None:
    await message.answer("Menyudan tanlang yoki /start yuboring.", reply_markup=main_menu())
