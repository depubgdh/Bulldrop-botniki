import asyncio
import random
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, KeyboardButton, ReplyKeyboardMarkup,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

import db
from config import TERMS_TEXT, WEBAPP_URL
from admins import is_admin

router = Router()

class Registration(StatesGroup):
    waiting_phone = State()

class SaperFlow(StatesGroup):
    waiting_game_id = State()

def main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎁 Super Qutilar"), KeyboardButton(text="📡 Bulldrop Signal")],
            [KeyboardButton(text="🎮 Botdagi o‘yinlar"), KeyboardButton(text="👤 Hisobim")],
        ],
        resize_keyboard=True
    )

def terms_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Davom etish", callback_data="accept_terms")
    ]])

def signal_keyboard():
    rows = [
        [InlineKeyboardButton(text="Crash", callback_data="signal_crash")],
        [InlineKeyboardButton(text="Saper", callback_data="signal_saper")],
        [InlineKeyboardButton(text="Narvon", callback_data="signal_ladder")],
        [InlineKeyboardButton(text="Minora", callback_data="signal_tower")],
        [InlineKeyboardButton(text="↩️ Orqaga", callback_data="go_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def saper_keyboard(green_cells):
    buttons = []
    for row in range(5):
        line = []
        for col in range(5):
            n = row * 5 + col + 1
            symbol = "🟩" if n in green_cells else "☑️"
            line.append(InlineKeyboardButton(text=symbol, callback_data="saper_cell"))
        buttons.append(line)
    buttons.append([InlineKeyboardButton(text="✔️ Tugatish", callback_data="go_home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    user = db.get_user(message.from_user.id)
    if not user or not user["accepted_terms"]:
        await message.answer(TERMS_TEXT, reply_markup=terms_keyboard())
        return
    if not user["phone"]:
        await ask_phone(message, state)
        return
    await message.answer("Bosh menyu:", reply_markup=main_menu())

async def ask_phone(message: Message, state: FSMContext):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await state.set_state(Registration.waiting_phone)
    await message.answer("Davom etish uchun telefon raqamingizni yuboring:", reply_markup=kb)

@router.callback_query(F.data == "accept_terms")
async def accept_terms(call: CallbackQuery, state: FSMContext):
    db.save_user(call.from_user.id, call.from_user.username, accepted_terms=1)
    await call.answer()
    await ask_phone(call.message, state)

@router.message(Registration.waiting_phone, F.contact)
async def receive_phone(message: Message, state: FSMContext):
    if message.contact.user_id != message.from_user.id:
        await message.answer("Iltimos, o‘zingizning telefon raqamingizni yuboring.")
        return
    db.save_user(message.from_user.id, message.from_user.username, phone=message.contact.phone_number)
    await state.clear()
    await message.answer("✅ Ro‘yxatdan o‘tdingiz!", reply_markup=main_menu())

@router.message(F.text == "📡 Bulldrop Signal")
async def open_signals(message: Message):
    await message.answer(
        "Bulldrop Signalga xush kelibsiz! Qaysi bo‘limni tanlaysiz?\n\n"
        "Eslatma: hozircha bu sinov rejimi; ko‘rsatiladigan qiymatlar tasodifiy demo.",
        reply_markup=signal_keyboard()
    )

@router.callback_query(F.data == "signal_crash")
async def crash_demo(call: CallbackQuery):
    await call.answer()
    value = random.randint(101, 420) / 100
    await call.message.answer(
        f"🎮 Crash demo qiymati: <b>{value:.2f}x</b>\n"
        "Bu tasodifiy sinov qiymati, haqiqiy o‘yin natijasi yoki bashorat emas."
    )

@router.callback_query(F.data == "signal_saper")
async def saper_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(SaperFlow.waiting_game_id)
    await call.message.answer("Saper o‘yini ID raqamini yuboring:")

@router.message(SaperFlow.waiting_game_id)
async def saper_game_id(message: Message, state: FSMContext):
    game_id = (message.text or "").strip()
    if not game_id or len(game_id) > 80:
        await message.answer("ID noto‘g‘ri. Iltimos, qayta yuboring (1–80 belgi).")
        return
    await state.clear()
    loading = await message.answer("⏳ Signal tayyorlanmoqda...")
    await asyncio.sleep(2)
    green = sorted(random.sample(range(1, 26), 3))
    db.add_saper_result(message.from_user.id, game_id, green)
    rows = []
    for row in range(5):
        cells = []
        for col in range(5):
            n = row * 5 + col + 1
            cells.append("🟩" if n in green else "☑️")
        rows.append(" ".join(cells))
    await loading.edit_text(
        f"Mana [{game_id}] shu ID o‘yini!\n\n" + "\n".join(rows) +
        "\n\n🟩 — tasodifiy tanlangan demo kataklar. Haqiqiy xavfsiz katak ekanini bildirmaydi.",
        reply_markup=saper_keyboard(green)
    )

@router.callback_query(F.data == "saper_cell")
async def saper_cell(call: CallbackQuery):
    await call.answer("Bu faqat demo ko‘rinish.", show_alert=False)

@router.callback_query(F.data == "go_home")
async def go_home(call: CallbackQuery):
    await call.answer()
    await call.message.answer("Bosh menyu:", reply_markup=main_menu())

@router.message(F.text == "👤 Hisobim")
async def account(message: Message):
    user = db.get_user(message.from_user.id)
    username = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    await message.answer(
        f"Hisobim bo‘limi\nHurmatli {username}\n"
        "J🧧 balans: sinov rejimida o‘chirilgan\n"
        "Bot Support: administrator bilan bog‘lanish uchun /support"
    )

@router.message(Command("support"))
async def support(message: Message):
    admins = list(__import__("config").ADMIN_IDS)
    if not admins:
        await message.answer("Support admini hali sozlanmagan.")
        return
    await message.answer("Support bilan bog‘lanish uchun admin username’ini bot egasi sozlashi kerak.")

@router.message(F.text == "🎁 Super Qutilar")
async def boxes(message: Message):
    await message.answer("🎁 Super Qutilar — bu bo‘lim keyingi bosqichda ulanadi.")

@router.message(F.text == "🎮 Botdagi o‘yinlar")
async def games(message: Message):
    await message.answer("🎮 G‘ildirak, Upgrade, Saper va Minora — hozircha ishlab chiqilmoqda.")

@router.message()
async def fallback(message: Message):
    await message.answer("Menyudagi tugmalardan birini tanlang yoki /start yuboring.", reply_markup=main_menu())

@router.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Bu buyruq faqat admin uchun.")
        return
    await message.answer("🛠 Admin panel sinov rejimida. Hozircha /admin faqat admin ekaningizni tekshiradi.")
