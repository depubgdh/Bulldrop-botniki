"""Admin panel (faqat ADMIN_IDS dagi foydalanuvchilar uchun)."""
import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import db
from common import (
    COIN,
    MENU_ITEMS,
    MENU_STYLES,
    STYLE_EMOJI,
    edit_or_send,
    extract_media,
    fmt_num,
    menu_layout,
    save_menu_layout,
)
from config import ADMIN_IDS

router = Router()
# Bu router'dagi barcha handlerlar faqat adminlar uchun ishlaydi
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))

ADMIN_TITLE = "👑 Admin panel"
RARITIES = {
    "common": "Oddiy",
    "rare": "Noyob",
    "epic": "Epik",
    "legendary": "Afsonaviy",
    "mythic": "Mifik",
}
MEDIA_HINT = "rasm, GIF, stiker yuboring yoki https:// havola yozing. O‘tkazib yuborish uchun «-» yozing"


class AdminStates(StatesGroup):
    # quti yaratish
    waiting_case_name = State()
    waiting_case_price = State()
    waiting_case_desc = State()
    waiting_case_image = State()
    # sovg'a qo'shish
    waiting_item_name = State()
    waiting_item_price = State()
    waiting_item_image = State()
    waiting_item_prob = State()
    waiting_item_rarity = State()
    # boshqa bo'limlar
    waiting_user_query = State()
    waiting_card_coins = State()
    waiting_bonus_target = State()
    waiting_bonus_amount = State()
    waiting_broadcast = State()
    waiting_channel = State()
    waiting_banner_image = State()
    waiting_banner_link = State()
    waiting_home_text = State()
    waiting_home_image = State()
    waiting_free_opens = State()
    # mavjud quti/sovg'aga rasm o'rnatish
    waiting_set_image = State()
    # Mini App bosh sahifasi
    waiting_hero_title = State()
    waiting_hero_text = State()
    waiting_hero_image = State()
    waiting_hero_btn = State()
    waiting_hero_url = State()


# ------------------------------------------------------------------ yordamchilar

def b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(row) for row in rows])


def back_kb() -> InlineKeyboardMarkup:
    return kb([b("🔙 Admin panel", "menu_admin")])


def not_command(message: Message) -> bool:
    """Holat (state) handlerlari /start kabi buyruqlarni yutib yubormasligi uchun."""
    return not (message.text and message.text.startswith("/"))


def parse_int(text, minimum=None):
    try:
        number = int((text or "").strip().replace(" ", ""))
    except ValueError:
        return None
    if minimum is not None and number < minimum:
        return None
    return number


def admin_menu() -> InlineKeyboardMarkup:
    return kb(
        [b("📦 Qutilar", "admin_boxes")],
        [b("👤 Foydalanuvchi kartochkasi", "admin_user")],
        [b("🎉 Bonus yuborish", "admin_bonus"), b("📣 Reklama tarqatish", "admin_broadcast")],
        [b("📢 Majburiy kanal", "admin_channel"), b("📈 Statistika", "admin_stats")],
        [b("🖼 Mini App reklamasi", "admin_banner"), b("🎟 Tekin ochishlar", "admin_free")],
        [b("🏠 Bosh menyu matni va rasmi", "admin_home")],
        [b("📱 Mini App bosh sahifasi", "admin_hero")],
        [b("🧩 Menyu tugmalari (rang/joy)", "admin_mbtn")],
        [b("⬅️ Asosiy menyu", "go_home")],
    )


@router.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(ADMIN_TITLE, reply_markup=admin_menu())


@router.message(Command("cancel"))
async def admin_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=admin_menu())


@router.callback_query(F.data == "menu_admin")
async def menu_admin(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    if call.message:
        await edit_or_send(call.message, ADMIN_TITLE, admin_menu())


# ------------------------------------------------------------------ 📦 Qutilar

def boxes_keyboard() -> InlineKeyboardMarkup:
    rows = [[b("➕ Quti yaratish", "admin_add_case")]]
    for case in db.get_cases():
        rows.append([b(f"📦 {case['name']} — {fmt_num(case['price'])} {COIN}", f"admin_case_{case['id']}")])
    rows.append([b("🔙 Admin panel", "menu_admin")])
    return kb(*rows)


def case_keyboard(case_id: int) -> InlineKeyboardMarkup:
    rows = [
        [b("🎁 Sovg‘a qo‘shish", f"admin_item_{case_id}")],
        [b("🖼 Quti rasmi / GIF", f"admin_cimg_{case_id}")],
    ]
    for item in db.get_case_items(case_id):
        rows.append([b(f"✏️ {item['name']}", f"admin_it_{item['id']}")])
    rows.append([b("🗑 Qutini o‘chirish", f"admin_dc_{case_id}")])
    rows.append([b("🔙 Qutilar", "admin_boxes")])
    return kb(*rows)


def case_text(case_id: int) -> str:
    case = db.get_case(case_id)
    if not case:
        return "Quti topilmadi."
    items = db.get_case_items(case_id)
    price = int(case["price"])
    lines = [f"📦 {case['name']} (ID: {case['id']})", f"💰 Narx: {fmt_num(price)} {COIN}"]
    if case["description"]:
        lines.append(case["description"])
    lines.append("🖼 Rasm: " + ("bor" if case["image_url"] else "yo‘q"))
    lines.append("")
    if items:
        total = sum(float(i["probability"]) for i in items)
        lines.append(f"🎁 Sovg‘alar ({len(items)}):")
        for n, item in enumerate(items, 1):
            lines.append(
                f"{n}. {item['name']}{' 🖼' if item['image_url'] else ''} — {fmt_num(item['price'])} {COIN} — "
                f"{RARITIES.get(item['rarity'], item['rarity'])} — {item['probability']}%"
            )
        ev = db.case_ev(case_id)
        lines.append(f"\nFoizlar yig‘indisi: {round(total, 2)}")
        lines.append(f"📊 Kutilgan qiymat: {ev:.0f} {COIN} (quti narxi: {fmt_num(price)} {COIN})")
        if ev > price > 0:
            lines.append("⚠️ Kutilgan qiymat quti narxidan yuqori: foydalanuvchilar sotib-ochib coin ko‘paytiradi.")
    else:
        lines.append("Hozircha sovg‘a yo‘q. «🎁 Sovg‘a qo‘shish» tugmasini bosing.")
    return "\n".join(lines)


@router.callback_query(F.data == "admin_boxes")
async def admin_boxes(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    if call.message:
        text = "📦 Qutilar\n\nQuti tanlang yoki yangisini yarating:" if db.get_cases() else "📦 Qutilar\n\nHozircha quti yo‘q. Birinchisini yarating:"
        await edit_or_send(call.message, text, boxes_keyboard())


@router.callback_query(F.data == "admin_add_case")
async def admin_add_case(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_case_name)
    if call.message:
        await edit_or_send(call.message, "Quti nomini kiriting:")


@router.callback_query(F.data.startswith("admin_case_"))
async def admin_case_view(call: CallbackQuery, state: FSMContext) -> None:
    case_id = int(call.data.replace("admin_case_", ""))
    if not db.get_case(case_id):
        await call.answer("Quti topilmadi.", show_alert=True)
        return
    await call.answer()
    await state.clear()
    if call.message:
        await edit_or_send(call.message, case_text(case_id), case_keyboard(case_id))


@router.callback_query(F.data.startswith("admin_item_"))
async def admin_add_item(call: CallbackQuery, state: FSMContext) -> None:
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
    case_id = db.deactivate_item(int(call.data.replace("admin_di_", "")))
    if case_id is None:
        await call.answer("Sovg‘a topilmadi.", show_alert=True)
        return
    await call.answer("Sovg‘a o‘chirildi.")
    if call.message:
        await edit_or_send(call.message, case_text(case_id), case_keyboard(case_id))


@router.callback_query(F.data.startswith("admin_dc_"))
async def admin_delete_case(call: CallbackQuery) -> None:
    db.deactivate_case(int(call.data.replace("admin_dc_", "")))
    await call.answer("Quti o‘chirildi.")
    if call.message:
        await edit_or_send(call.message, "📦 Qutilar", boxes_keyboard())


@router.callback_query(F.data.startswith("admin_it_"))
async def admin_item_card(call: CallbackQuery) -> None:
    item = db.get_case_item(int(call.data.replace("admin_it_", "")))
    if not item:
        await call.answer("Sovg‘a topilmadi.", show_alert=True)
        return
    await call.answer()
    text = (
        f"🎁 {item['name']}\n"
        f"{COIN} Qiymat: {fmt_num(item['price'])}\n"
        f"🎲 Tushish foizi: {item['probability']}%\n"
        f"✨ Daraja: {RARITIES.get(item['rarity'], item['rarity'])}\n"
        f"🖼 Rasm: {'bor' if item['image_url'] else 'yo‘q'}"
    )
    if call.message:
        await edit_or_send(
            call.message,
            text,
            kb(
                [b("🖼 Rasm / GIF / stiker", f"admin_iimg_{item['id']}")],
                [b("🗑 O‘chirish", f"admin_di_{item['id']}")],
                [b("🔙 Quti", f"admin_case_{item['case_id']}")],
            ),
        )


@router.callback_query(F.data.startswith("admin_cimg_") | F.data.startswith("admin_iimg_"))
async def admin_set_image_start(call: CallbackQuery, state: FSMContext) -> None:
    kind = "case" if call.data.startswith("admin_cimg_") else "item"
    target = int(call.data.rsplit("_", 1)[1])
    exists = db.get_case(target) if kind == "case" else db.get_case_item(target)
    if not exists:
        await call.answer("Topilmadi.", show_alert=True)
        return
    await call.answer()
    await state.update_data(img_kind=kind, img_target=target)
    await state.set_state(AdminStates.waiting_set_image)
    if call.message:
        await call.message.answer(
            "Yangi rasm, GIF yoki stiker yuboring (yoki https:// havola yozing).\n"
            "Rasmni olib tashlash uchun «-» yozing. Bekor qilish: /cancel"
        )


@router.message(AdminStates.waiting_set_image, not_command)
async def admin_set_image_value(message: Message, state: FSMContext) -> None:
    image = extract_media(message)
    if image is None:
        await message.answer("Tushunmadim. Rasm, GIF, stiker yuboring yoki https:// havola yozing («-» — olib tashlash):")
        return
    data = await state.get_data()
    await state.clear()
    target = data.get("img_target")
    if data.get("img_kind") == "case":
        db.set_case_image(target, image)
        case_id = target
    else:
        item = db.get_case_item(target)
        if not item:
            await message.answer("Sovg‘a topilmadi.", reply_markup=admin_menu())
            return
        db.set_item_image(target, image)
        case_id = item["case_id"]
    await message.answer("✅ Rasm saqlandi.\n\n" + case_text(case_id), reply_markup=case_keyboard(case_id))


@router.message(AdminStates.waiting_case_name, not_command)
async def admin_case_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Quti nomini matn bilan yozing:")
        return
    await state.update_data(case_name=name)
    await state.set_state(AdminStates.waiting_case_price)
    await message.answer(f"Quti ochish narxini {COIN} coin bilan, son qilib kiriting (tekin qutilar uchun 0):")


@router.message(AdminStates.waiting_case_price, not_command)
async def admin_case_price(message: Message, state: FSMContext) -> None:
    price = parse_int(message.text, minimum=0)
    if price is None:
        await message.answer("Narx 0 yoki undan katta son bo‘lishi kerak. Qayta kiriting:")
        return
    await state.update_data(case_price=price)
    await state.set_state(AdminStates.waiting_case_desc)
    await message.answer("Quti haqida qisqa ma’lumot yozing («-» — bo‘sh qoldirish):")


@router.message(AdminStates.waiting_case_desc, not_command)
async def admin_case_desc(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    await state.update_data(case_desc="" if text == "-" else text)
    await state.set_state(AdminStates.waiting_case_image)
    await message.answer(f"Quti uchun {MEDIA_HINT}:")


@router.message(AdminStates.waiting_case_image, not_command)
async def admin_case_image(message: Message, state: FSMContext) -> None:
    image = extract_media(message)
    if image is None:
        await message.answer(f"Tushunmadim. {MEDIA_HINT}:")
        return
    data = await state.get_data()
    case_id = db.add_case(
        name=data["case_name"],
        price=data["case_price"],
        description=data.get("case_desc", ""),
        image_url=image,
    )
    await state.clear()
    await message.answer("✅ Quti yaratildi!\n\n" + case_text(case_id), reply_markup=case_keyboard(case_id))


@router.message(AdminStates.waiting_item_name, not_command)
async def admin_item_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Sovg‘a nomini matn bilan yozing:")
        return
    await state.update_data(item_name=name)
    await state.set_state(AdminStates.waiting_item_price)
    await message.answer(f"Sovg‘aning qiymatini {COIN} coin bilan kiriting (sotilganda shuncha coin qaytadi):")


@router.message(AdminStates.waiting_item_price, not_command)
async def admin_item_price(message: Message, state: FSMContext) -> None:
    price = parse_int(message.text, minimum=0)
    if price is None:
        await message.answer("Qiymat 0 yoki undan katta son bo‘lishi kerak. Qayta kiriting:")
        return
    await state.update_data(item_price=price)
    await state.set_state(AdminStates.waiting_item_image)
    await message.answer(f"Sovg‘a uchun {MEDIA_HINT}:")


@router.message(AdminStates.waiting_item_image, not_command)
async def admin_item_image(message: Message, state: FSMContext) -> None:
    image = extract_media(message)
    if image is None:
        await message.answer(f"Tushunmadim. {MEDIA_HINT}:")
        return
    await state.update_data(item_image=image)
    await state.set_state(AdminStates.waiting_item_prob)
    await message.answer("Tushish foizini kiriting (masalan: 10.5):")


@router.message(AdminStates.waiting_item_prob, not_command)
async def admin_item_prob(message: Message, state: FSMContext) -> None:
    try:
        probability = float((message.text or "").strip().replace(",", "."))
    except ValueError:
        await message.answer("Foiz son bo‘lishi kerak. Qayta kiriting:")
        return
    if probability <= 0:
        await message.answer("Foiz 0 dan katta bo‘lishi kerak. Qayta kiriting:")
        return
    await state.update_data(item_prob=probability)
    await state.set_state(AdminStates.waiting_item_rarity)
    await message.answer(
        "Noyoblik darajasini tanlang:",
        reply_markup=kb(
            [b("⚪ Oddiy", "admin_rar_common"), b("🔵 Noyob", "admin_rar_rare")],
            [b("🟣 Epik", "admin_rar_epic"), b("🟡 Afsonaviy", "admin_rar_legendary")],
            [b("🔴 Mifik", "admin_rar_mythic")],
        ),
    )


@router.callback_query(AdminStates.waiting_item_rarity, F.data.startswith("admin_rar_"))
async def admin_item_rarity(call: CallbackQuery, state: FSMContext) -> None:
    rarity = call.data.replace("admin_rar_", "")
    if rarity not in RARITIES:
        await call.answer("Noto‘g‘ri daraja.", show_alert=True)
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
    await call.answer("Sovg‘a qo‘shildi.")
    case_id = data["item_case_id"]
    if call.message:
        await edit_or_send(call.message, "✅ Sovg‘a qo‘shildi!\n\n" + case_text(case_id), case_keyboard(case_id))


# ------------------------------------------------------------------ 👤 Foydalanuvchi kartochkasi

def user_card_text(user_id: int) -> str:
    card = db.user_card(user_id)
    if not card:
        return "Foydalanuvchi topilmadi."
    user, wallet, inv = card["user"], card["wallet"], card["inventory"]
    username = f"@{user['username']}" if user["username"] else "—"
    return (
        "👤 Foydalanuvchi kartochkasi\n\n"
        f"ID: {user['user_id']}\n"
        f"Username: {username}\n"
        f"Telefon: {user['phone'] or '—'}\n"
        f"Ro‘yxatdan o‘tgan: {user['created_at']}\n\n"
        f"{COIN} Coin: {fmt_num(wallet['coins'])}\n"
        f"🎁 Ochishlar: {wallet['opens']} (tekin qolgan: {wallet['free_left']})\n"
        f"🎒 Inventory: {inv['count']} ta ({fmt_num(inv['value'])} {COIN})\n"
        f"👥 Takliflar: {card['referrals']}"
    )


def user_card_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return kb(
        [b(f"➕ {COIN} qo‘shish", f"admin_cadd_{user_id}"), b(f"➖ {COIN} ayirish", f"admin_csub_{user_id}")],
        [b("🔙 Admin panel", "menu_admin")],
    )


@router.callback_query(F.data == "admin_user")
async def admin_user(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_user_query)
    if call.message:
        await edit_or_send(call.message, "Foydalanuvchi ID raqami yoki @username ni yuboring:", back_kb())


@router.message(AdminStates.waiting_user_query, not_command)
async def admin_user_query(message: Message, state: FSMContext) -> None:
    user = db.find_user(message.text)
    if not user:
        await message.answer("Foydalanuvchi topilmadi. Boshqa ID yoki @username yuboring:", reply_markup=back_kb())
        return
    await state.clear()
    await message.answer(user_card_text(user["user_id"]), reply_markup=user_card_keyboard(user["user_id"]))


@router.callback_query(F.data.startswith("admin_cadd_") | F.data.startswith("admin_csub_"))
async def admin_card_coins(call: CallbackQuery, state: FSMContext) -> None:
    sign = 1 if call.data.startswith("admin_cadd_") else -1
    target = int(call.data.split("_")[-1])
    await call.answer()
    await state.update_data(card_target=target, card_sign=sign)
    await state.set_state(AdminStates.waiting_card_coins)
    if call.message:
        await call.message.answer(f"Necha {COIN} coin {'qo‘shilsin' if sign > 0 else 'ayirilsin'}? Son kiriting:")


@router.message(AdminStates.waiting_card_coins, not_command)
async def admin_card_coins_amount(message: Message, state: FSMContext) -> None:
    amount = parse_int(message.text, minimum=1)
    if amount is None:
        await message.answer("Musbat son kiriting:")
        return
    data = await state.get_data()
    db.add_coins(data["card_target"], data["card_sign"] * amount)
    await state.clear()
    await message.answer(
        "✅ Yangilandi.\n\n" + user_card_text(data["card_target"]),
        reply_markup=user_card_keyboard(data["card_target"]),
    )


# ------------------------------------------------------------------ 🎉 Bonus yuborish

async def notify(bot, user_id: int, text: str) -> bool:
    try:
        await bot.send_message(user_id, text)
        return True
    except Exception:
        return False


@router.callback_query(F.data == "admin_bonus")
async def admin_bonus(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_bonus_target)
    if call.message:
        await edit_or_send(
            call.message,
            "🎉 Bonus yuborish\n\nFoydalanuvchi ID raqami yoki @username ni yuboring:",
            kb([b("👥 Hammaga", "admin_bonus_all")], [b("🔙 Admin panel", "menu_admin")]),
        )


@router.callback_query(F.data == "admin_bonus_all")
async def admin_bonus_all(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.update_data(bonus_target="all")
    await state.set_state(AdminStates.waiting_bonus_amount)
    if call.message:
        await call.message.answer(f"Ro‘yxatdan o‘tgan HAMMA foydalanuvchiga necha {COIN} coin berilsin?")


@router.message(AdminStates.waiting_bonus_target, not_command)
async def admin_bonus_target(message: Message, state: FSMContext) -> None:
    user = db.find_user(message.text)
    if not user:
        await message.answer("Foydalanuvchi topilmadi. Boshqa ID yoki @username yuboring:", reply_markup=back_kb())
        return
    await state.update_data(bonus_target=user["user_id"])
    await state.set_state(AdminStates.waiting_bonus_amount)
    await message.answer(f"Necha {COIN} coin berilsin?")


@router.message(AdminStates.waiting_bonus_amount, not_command)
async def admin_bonus_amount(message: Message, state: FSMContext) -> None:
    amount = parse_int(message.text, minimum=1)
    if amount is None:
        await message.answer("Musbat son kiriting:")
        return
    data = await state.get_data()
    await state.clear()
    text = f"🎉 Sizga {fmt_num(amount)} {COIN} coin bonus berildi!"
    if data.get("bonus_target") == "all":
        count = db.add_coins_all(amount)
        await message.answer(f"✅ {count} ta foydalanuvchiga {fmt_num(amount)} {COIN} coin berildi. Xabar yuborilmoqda...")
        sent = 0
        for user_id in db.all_user_ids():
            if await notify(message.bot, user_id, text):
                sent += 1
            await asyncio.sleep(0.05)
        await message.answer(f"📨 Xabar yetib bordi: {sent} ta.", reply_markup=admin_menu())
        return
    target = data["bonus_target"]
    balance = db.add_coins(target, amount)
    delivered = await notify(message.bot, target, text)
    await message.answer(
        f"✅ {target} ga {fmt_num(amount)} {COIN} coin berildi. Balans: {fmt_num(balance)} {COIN}."
        + ("" if delivered else "\n(Foydalanuvchiga xabar yetmadi, lekin coin qo‘shildi.)"),
        reply_markup=admin_menu(),
    )


# ------------------------------------------------------------------ 📣 Reklama tarqatish

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_broadcast)
    if call.message:
        await edit_or_send(
            call.message,
            "📣 Reklama tarqatish\n\nYuboriladigan xabarni yuboring (matn, rasm, GIF, video — istalgani). "
            "Bekor qilish: /cancel",
            back_kb(),
        )


@router.message(AdminStates.waiting_broadcast, not_command)
async def admin_broadcast_message(message: Message, state: FSMContext) -> None:
    await state.update_data(bc_chat=message.chat.id, bc_msg=message.message_id)
    total = len(db.all_user_ids())
    await message.answer("👆 Xabar shunday ko‘rinadi.")
    await message.copy_to(message.chat.id)
    await message.answer(
        f"{total} ta foydalanuvchiga yuborilsinmi?",
        reply_markup=kb([b("✅ Yuborish", "admin_bc_go"), b("❌ Bekor qilish", "admin_bc_no")]),
    )


@router.callback_query(F.data == "admin_bc_no")
async def admin_broadcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer("Bekor qilindi.")
    await state.clear()
    if call.message:
        await edit_or_send(call.message, ADMIN_TITLE, admin_menu())


@router.callback_query(F.data == "admin_bc_go")
async def admin_broadcast_go(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if "bc_msg" not in data:
        await call.answer("Xabar topilmadi. Qaytadan boshlang.", show_alert=True)
        return
    await call.answer("Yuborilmoqda...")
    await state.clear()
    ids = db.all_user_ids()
    sent = failed = 0
    for user_id in ids:
        try:
            await call.bot.copy_message(user_id, data["bc_chat"], data["bc_msg"])
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    if call.message:
        await call.message.answer(
            f"✅ Tugadi.\nYuborildi: {sent}\nYetib bormadi: {failed}",
            reply_markup=admin_menu(),
        )


# ------------------------------------------------------------------ 📢 Majburiy kanal

def channel_keyboard(has_channel: bool) -> InlineKeyboardMarkup:
    rows = [[b("✏️ Kanalni o‘zgartirish", "admin_channel_set")]]
    if has_channel:
        rows.append([b("🗑 O‘chirish", "admin_channel_off")])
    rows.append([b("🔙 Admin panel", "menu_admin")])
    return kb(*rows)


@router.callback_query(F.data == "admin_channel")
async def admin_channel(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    channel = db.get_setting("required_channel")
    text = (
        "📢 Majburiy kanal\n\n"
        + (f"Hozirgi kanal: {channel}" if channel else "Hozir o‘chiq.")
        + "\n\nYoqilganda foydalanuvchilar botdan va Mini App’dan foydalanish uchun kanalga a‘zo bo‘lishi kerak."
    )
    if call.message:
        await edit_or_send(call.message, text, channel_keyboard(bool(channel)))


@router.callback_query(F.data == "admin_channel_set")
async def admin_channel_set(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_channel)
    if call.message:
        await call.message.answer(
            "Kanal @username yoki ID raqamini (-100...) yuboring.\n"
            "Muhim: bot shu kanalda ADMIN bo‘lishi kerak."
        )


@router.callback_query(F.data == "admin_channel_off")
async def admin_channel_off(call: CallbackQuery) -> None:
    db.set_setting("required_channel", None)
    await call.answer("Majburiy kanal o‘chirildi.")
    if call.message:
        await edit_or_send(call.message, "📢 Majburiy kanal\n\nHozir o‘chiq.", channel_keyboard(False))


@router.message(AdminStates.waiting_channel, not_command)
async def admin_channel_value(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Kanal @username yoki ID raqamini yuboring:")
        return
    if raw.lstrip("-").isdigit():
        chat_ref = int(raw)
    else:
        chat_ref = raw if raw.startswith("@") else "@" + raw.rsplit("/", 1)[-1]
    try:
        chat = await message.bot.get_chat(chat_ref)
        me = await message.bot.me()
        member = await message.bot.get_chat_member(chat.id, me.id)
    except Exception:
        await message.answer("Kanal topilmadi yoki bot kanalda yo‘q. Botni kanalga admin qiling va qaytadan yuboring:")
        return
    if member.status not in ("administrator", "creator"):
        await message.answer("Bot kanalda admin emas. Botni admin qiling va qaytadan yuboring:")
        return
    saved = f"@{chat.username}" if getattr(chat, "username", None) else str(chat.id)
    db.set_setting("required_channel", saved)
    await state.clear()
    await message.answer(f"✅ Majburiy kanal: {saved}", reply_markup=admin_menu())


# ------------------------------------------------------------------ 📈 Statistika

@router.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery) -> None:
    await call.answer()
    s = db.stats()
    text = (
        "📈 Statistika\n\n"
        f"👥 Foydalanuvchilar: {s['users']} (ro‘yxatdan o‘tgan: {s['registered']})\n"
        f"📦 Faol qutilar: {s['cases']}\n"
        f"🎁 Jami ochishlar: {fmt_num(s['opens'])}\n"
        f"🎒 Inventarda: {fmt_num(s['held'])} ta ({fmt_num(s['held_value'])} {COIN})\n"
        f"💰 Sotilgan sovg‘alar: {fmt_num(s['sold'])}\n"
        f"{COIN} Aylanmadagi coin: {fmt_num(s['coins'])}\n"
        f"🎟 Tekin ochishlar (har kimga): {db.free_limit()}"
    )
    if call.message:
        await edit_or_send(call.message, text, back_kb())


# ------------------------------------------------------------------ 🖼 Mini App reklamasi

def banner_text() -> str:
    image = db.get_setting("banner_image")
    link = db.get_setting("banner_link")
    return (
        "🖼 Mini App reklamasi\n\n"
        "Bosh sahifada ko‘rinadigan banner.\n"
        f"Rasm: {'o‘rnatilgan' if image else 'yo‘q'}\n"
        f"Havola: {link or 'yo‘q'}"
    )


def banner_keyboard() -> InlineKeyboardMarkup:
    return kb(
        [b("🖼 Rasm / GIF yuklash", "admin_banner_img"), b("🔗 Havola", "admin_banner_link")],
        [b("🗑 Bannerni o‘chirish", "admin_banner_off")],
        [b("🔙 Admin panel", "menu_admin")],
    )


@router.callback_query(F.data == "admin_banner")
async def admin_banner(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    if call.message:
        await edit_or_send(call.message, banner_text(), banner_keyboard())


@router.callback_query(F.data == "admin_banner_img")
async def admin_banner_img(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_banner_image)
    if call.message:
        await call.message.answer("Banner uchun rasm yoki GIF yuboring (yoki https:// havola):")


@router.message(AdminStates.waiting_banner_image, not_command)
async def admin_banner_image_value(message: Message, state: FSMContext) -> None:
    image = extract_media(message)
    if not image:
        await message.answer("Rasm, GIF yoki https:// havola yuboring:")
        return
    db.set_setting("banner_image", image)
    await state.clear()
    await message.answer("✅ Banner rasmi saqlandi.\n\n" + banner_text(), reply_markup=banner_keyboard())


@router.callback_query(F.data == "admin_banner_link")
async def admin_banner_link(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_banner_link)
    if call.message:
        await call.message.answer("Banner bosilganda ochiladigan havolani yuboring (https://... yoki https://t.me/...). Olib tashlash: «-»")


@router.message(AdminStates.waiting_banner_link, not_command)
async def admin_banner_link_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if text == "-":
        db.set_setting("banner_link", None)
    elif text.lower().startswith("https://"):
        db.set_setting("banner_link", text)
    else:
        await message.answer("Havola https:// bilan boshlanishi kerak. Qayta yuboring (yoki «-»):")
        return
    await state.clear()
    await message.answer("✅ Saqlandi.\n\n" + banner_text(), reply_markup=banner_keyboard())


@router.callback_query(F.data == "admin_banner_off")
async def admin_banner_off(call: CallbackQuery) -> None:
    db.set_setting("banner_image", None)
    db.set_setting("banner_link", None)
    await call.answer("Banner o‘chirildi.")
    if call.message:
        await edit_or_send(call.message, banner_text(), banner_keyboard())


# ------------------------------------------------------------------ 🏠 Bosh menyu matni va rasmi

def home_text_view() -> str:
    text = db.get_setting("home_text")
    image = db.get_setting("home_image")
    return (
        "🏠 Bosh menyu matni va rasmi\n\n"
        f"Matn: {text if text else 'standart (BULLDROP bosh menyusi:)'}\n"
        f"Rasm: {'o‘rnatilgan' if image else 'yo‘q'}"
    )


def home_keyboard() -> InlineKeyboardMarkup:
    return kb(
        [b("✏️ Matn", "admin_home_text"), b("🖼 Rasm", "admin_home_img")],
        [b("♻️ Asl holatga qaytarish", "admin_home_reset")],
        [b("🔙 Admin panel", "menu_admin")],
    )


@router.callback_query(F.data == "admin_home")
async def admin_home(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    if call.message:
        await edit_or_send(call.message, home_text_view(), home_keyboard())


@router.callback_query(F.data == "admin_home_text")
async def admin_home_text(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_home_text)
    if call.message:
        await call.message.answer("Bosh menyu uchun yangi matnni yuboring (1000 belgigacha):")


@router.message(AdminStates.waiting_home_text, not_command)
async def admin_home_text_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 1000:
        await message.answer("Matn 1 dan 1000 belgigacha bo‘lishi kerak. Qayta yuboring:")
        return
    db.set_setting("home_text", text)
    await state.clear()
    await message.answer("✅ Saqlandi.\n\n" + home_text_view(), reply_markup=home_keyboard())


@router.callback_query(F.data == "admin_home_img")
async def admin_home_img(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_home_image)
    if call.message:
        await call.message.answer("Bosh menyu uchun rasm yuboring (oddiy rasm sifatida):")


@router.message(AdminStates.waiting_home_image, not_command)
async def admin_home_image_value(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Rasm yuboring (fayl emas, oddiy rasm sifatida):")
        return
    db.set_setting("home_image", message.photo[-1].file_id)
    await state.clear()
    await message.answer("✅ Saqlandi.\n\n" + home_text_view(), reply_markup=home_keyboard())


@router.callback_query(F.data == "admin_home_reset")
async def admin_home_reset(call: CallbackQuery) -> None:
    db.set_setting("home_text", None)
    db.set_setting("home_image", None)
    await call.answer("Asl holatga qaytarildi.")
    if call.message:
        await edit_or_send(call.message, home_text_view(), home_keyboard())


# ------------------------------------------------------------------ 🎟 Tekin ochishlar

@router.callback_query(F.data == "admin_free")
async def admin_free(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(AdminStates.waiting_free_opens)
    if call.message:
        await edit_or_send(
            call.message,
            f"🎟 Tekin ochishlar\n\nHar bir foydalanuvchi uchun hozir {db.free_limit()} ta tekin ochish bor "
            "(foydalanuvchi ochgan jami ochishlar sonidan hisoblanadi).\n\n"
            "Yangi sonni yuboring (0 — tekin ochish yo‘q):",
            back_kb(),
        )


@router.message(AdminStates.waiting_free_opens, not_command)
async def admin_free_value(message: Message, state: FSMContext) -> None:
    number = parse_int(message.text, minimum=0)
    if number is None or number > 100000:
        await message.answer("0 dan 100000 gacha son kiriting:")
        return
    db.set_setting("free_opens", number)
    await state.clear()
    await message.answer(f"✅ Endi har kimga {number} ta tekin ochish beriladi.", reply_markup=admin_menu())


# ------------------------------------------------------------------ 🧩 Menyu tugmalari (rang/joy)

def mbtn_text() -> str:
    return (
        "🧩 Menyu tugmalari\n\n"
        "Bot bosh menyusidagi tugmalar:\n"
        "• nomini bossangiz rangi almashadi (⚪ 🔵 🟢 🔴)\n"
        "• ⬆️ ⬇️ — joyini o‘zgartiradi\n"
        "• 👁 / 🚫 — ko‘rsatish yoki yashirish\n\n"
        "Ranglar Telegram’ning yangi tugma ranglari imkoniyatiga tayanadi: eski ilovalarda rang ko‘rinmasligi mumkin."
    )


def mbtn_keyboard() -> InlineKeyboardMarkup:
    layout = menu_layout()
    rows = []
    for item in layout["order"]:
        style = layout["style"].get(item)
        hidden = item in layout["hidden"]
        rows.append([
            b(f"{STYLE_EMOJI[style]} {MENU_ITEMS[item]}", f"admin_mc_{item}"),
            b("⬆️", f"admin_mu_{item}"),
            b("⬇️", f"admin_md_{item}"),
            b("🚫" if hidden else "👁", f"admin_mv_{item}"),
        ])
    rows.append([b("♻️ Asl holatga qaytarish", "admin_mreset")])
    rows.append([b("🔙 Admin panel", "menu_admin")])
    return kb(*rows)


@router.callback_query(F.data == "admin_mbtn")
async def admin_mbtn(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.clear()
    if call.message:
        await edit_or_send(call.message, mbtn_text(), mbtn_keyboard())


@router.callback_query(F.data.regexp(r"^admin_m[cudv]_[a-z]+$"))
async def admin_mbtn_action(call: CallbackQuery) -> None:
    action = call.data[7]
    item = call.data.split("_", 2)[2]
    if item not in MENU_ITEMS:
        await call.answer("Tugma topilmadi.", show_alert=True)
        return
    layout = menu_layout()
    order = layout["order"]
    if action == "c":  # rangni aylantirish
        current = layout["style"].get(item)
        following = MENU_STYLES[(MENU_STYLES.index(current) + 1) % len(MENU_STYLES)]
        if following is None:
            layout["style"].pop(item, None)
        else:
            layout["style"][item] = following
    elif action in ("u", "d"):  # joyini almashtirish
        index = order.index(item)
        target = index - 1 if action == "u" else index + 1
        if not 0 <= target < len(order):
            await call.answer()
            return
        order[index], order[target] = order[target], order[index]
    else:  # "v": ko'rsatish / yashirish
        if item in layout["hidden"]:
            layout["hidden"].remove(item)
        else:
            layout["hidden"].append(item)
    save_menu_layout(layout)
    await call.answer()
    if call.message:
        await edit_or_send(call.message, mbtn_text(), mbtn_keyboard())


@router.callback_query(F.data == "admin_mreset")
async def admin_mbtn_reset(call: CallbackQuery) -> None:
    db.set_setting("menu_layout", None)
    await call.answer("Asl holatga qaytarildi.")
    if call.message:
        await edit_or_send(call.message, mbtn_text(), mbtn_keyboard())


# ------------------------------------------------------------------ 📱 Mini App bosh sahifasi

HERO_DEFAULT_TITLE = "BULLDROP"
HERO_DEFAULT_TEXT = "Har kim {free} ta bepul ochadi. Keyin tushgan sovg‘ani sotib, coin bilan yana oching."
HERO_DEFAULT_BTN = "🎁 Qutilarga o‘tish"
HERO_DEFAULT_TARGET = "tab:case"
TARGET_TABS = {
    "case": "🎁 Qutilar bo‘limi",
    "inv": "🎒 Buyumlar",
    "friends": "👥 Do‘stlar",
    "home": "🏠 Bosh sahifa",
}


def _is_admin(call) -> bool:
    return call.from_user.id in ADMIN_IDS


def target_label(target: str) -> str:
    if target.startswith("tab:") and target[4:] in TARGET_TABS:
        return TARGET_TABS[target[4:]]
    if target.startswith("case:"):
        case = db.get_case(int(target[5:])) if target[5:].isdigit() else None
        return f"📦 Quti: {case['name']}" if case else "📦 Quti (topilmadi)"
    if target.startswith("url:"):
        return f"🔗 Havola: {target[4:]}"
    return TARGET_TABS["case"]


def hero_view() -> str:
    text = db.get_setting("app_hero_text") or HERO_DEFAULT_TEXT
    return (
        "📱 Mini App bosh sahifasi\n\n"
        f"Sarlavha: {db.get_setting('app_hero_title') or HERO_DEFAULT_TITLE}\n"
        f"Matn: {text}\n"
        f"Rasm/fon: {'o‘rnatilgan' if db.get_setting('app_hero_image') else 'yo‘q (pushti fon)'}\n"
        f"Tugma matni: {db.get_setting('app_hero_btn_text') or HERO_DEFAULT_BTN}\n"
        f"Tugma bosilganda: {target_label(db.get_setting('app_hero_btn_target') or HERO_DEFAULT_TARGET)}\n\n"
        "Matnda {free} yozsangiz, bepul ochishlar soni avtomatik qo‘yiladi."
    )


def hero_keyboard() -> InlineKeyboardMarkup:
    return kb(
        [b("✏️ Sarlavha", "admin_hero_title"), b("✏️ Matn", "admin_hero_text")],
        [b("🖼 Rasm / fon", "admin_hero_img"), b("🔤 Tugma matni", "admin_hero_btn")],
        [b("🎯 Tugma yo‘nalishi", "admin_hero_target")],
        [b("♻️ Asl holatga qaytarish", "admin_hero_reset")],
        [b("🔙 Admin panel", "menu_admin")],
    )


def hero_target_keyboard() -> InlineKeyboardMarkup:
    rows = [[b(label, f"admin_hero_tt_{key}")] for key, label in TARGET_TABS.items()]
    rows.append([b("📦 Bitta quti", "admin_hero_tcase"), b("🔗 Havola", "admin_hero_turl")])
    rows.append([b("🔙 Orqaga", "admin_hero")])
    return kb(*rows)


@router.callback_query(F.data == "admin_hero")
async def admin_hero(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call):
        await call.answer("Ruxsat yo‘q.", show_alert=True)
        return
    await call.answer()
    await state.clear()
    if call.message:
        await edit_or_send(call.message, hero_view(), hero_keyboard())


@router.callback_query(F.data == "admin_hero_title")
async def admin_hero_title(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call):
        return
    await call.answer()
    await state.set_state(AdminStates.waiting_hero_title)
    if call.message:
        await call.message.answer("Yangi sarlavhani yuboring (60 belgigacha):")


@router.message(AdminStates.waiting_hero_title, not_command)
async def admin_hero_title_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 60:
        await message.answer("Sarlavha 1 dan 60 belgigacha bo‘lishi kerak. Qayta yuboring:")
        return
    db.set_setting("app_hero_title", text)
    await state.clear()
    await message.answer("✅ Saqlandi.\n\n" + hero_view(), reply_markup=hero_keyboard())


@router.callback_query(F.data == "admin_hero_text")
async def admin_hero_text(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call):
        return
    await call.answer()
    await state.set_state(AdminStates.waiting_hero_text)
    if call.message:
        await call.message.answer("Yangi matnni yuboring (300 belgigacha). Bepul ochishlar sonini {free} deb yozing:")


@router.message(AdminStates.waiting_hero_text, not_command)
async def admin_hero_text_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 300:
        await message.answer("Matn 1 dan 300 belgigacha bo‘lishi kerak. Qayta yuboring:")
        return
    db.set_setting("app_hero_text", text)
    await state.clear()
    await message.answer("✅ Saqlandi.\n\n" + hero_view(), reply_markup=hero_keyboard())


@router.callback_query(F.data == "admin_hero_img")
async def admin_hero_img(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call):
        return
    await call.answer()
    await state.set_state(AdminStates.waiting_hero_image)
    if call.message:
        await call.message.answer(
            "Fon uchun rasm, GIF yoki stiker yuboring (yoki https:// havola).\n"
            "Olib tashlash uchun «-» yozing."
        )


@router.message(AdminStates.waiting_hero_image, not_command)
async def admin_hero_image_value(message: Message, state: FSMContext) -> None:
    image = extract_media(message)
    if image is None:
        await message.answer("Tushunmadim. Rasm, GIF yoki stiker yuboring, yoki https:// havola yozing («-» — olib tashlash):")
        return
    db.set_setting("app_hero_image", image or None)
    await state.clear()
    await message.answer("✅ Saqlandi.\n\n" + hero_view(), reply_markup=hero_keyboard())


@router.callback_query(F.data == "admin_hero_btn")
async def admin_hero_btn(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call):
        return
    await call.answer()
    await state.set_state(AdminStates.waiting_hero_btn)
    if call.message:
        await call.message.answer("Tugma matnini yuboring (40 belgigacha, emoji ham bo‘lishi mumkin):")


@router.message(AdminStates.waiting_hero_btn, not_command)
async def admin_hero_btn_value(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 40:
        await message.answer("Tugma matni 1 dan 40 belgigacha bo‘lishi kerak. Qayta yuboring:")
        return
    db.set_setting("app_hero_btn_text", text)
    await state.clear()
    await message.answer("✅ Saqlandi.\n\n" + hero_view(), reply_markup=hero_keyboard())


@router.callback_query(F.data == "admin_hero_target")
async def admin_hero_target(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call):
        return
    await call.answer()
    await state.clear()
    if call.message:
        await edit_or_send(call.message, "Tugma bosilganda qayerga o‘tsin?", hero_target_keyboard())


@router.callback_query(F.data.startswith("admin_hero_tt_"))
async def admin_hero_tab_target(call: CallbackQuery) -> None:
    if not _is_admin(call):
        return
    key = call.data.replace("admin_hero_tt_", "")
    if key not in TARGET_TABS:
        await call.answer("Noto‘g‘ri bo‘lim.", show_alert=True)
        return
    db.set_setting("app_hero_btn_target", f"tab:{key}")
    await call.answer("Saqlandi.")
    if call.message:
        await edit_or_send(call.message, hero_view(), hero_keyboard())


@router.callback_query(F.data == "admin_hero_tcase")
async def admin_hero_case_list(call: CallbackQuery) -> None:
    if not _is_admin(call):
        return
    await call.answer()
    cases = db.get_cases()
    if not cases:
        if call.message:
            await edit_or_send(call.message, "Hozircha quti yo‘q. Avval quti yarating.", kb([b("🔙 Orqaga", "admin_hero_target")]))
        return
    rows = [[b(f"📦 {c['name']}", f"admin_hero_tc_{c['id']}")] for c in cases]
    rows.append([b("🔙 Orqaga", "admin_hero_target")])
    if call.message:
        await edit_or_send(call.message, "Qaysi quti ochilsin?", kb(*rows))


@router.callback_query(F.data.startswith("admin_hero_tc_"))
async def admin_hero_case_target(call: CallbackQuery) -> None:
    if not _is_admin(call):
        return
    case_id = call.data.replace("admin_hero_tc_", "")
    if not case_id.isdigit() or not db.get_case(int(case_id)):
        await call.answer("Quti topilmadi.", show_alert=True)
        return
    db.set_setting("app_hero_btn_target", f"case:{int(case_id)}")
    await call.answer("Saqlandi.")
    if call.message:
        await edit_or_send(call.message, hero_view(), hero_keyboard())


@router.callback_query(F.data == "admin_hero_turl")
async def admin_hero_url(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call):
        return
    await call.answer()
    await state.set_state(AdminStates.waiting_hero_url)
    if call.message:
        await call.message.answer("Havolani yuboring (https:// bilan boshlansin):")


@router.message(AdminStates.waiting_hero_url, not_command)
async def admin_hero_url_value(message: Message, state: FSMContext) -> None:
    url = (message.text or "").strip()
    if not url.startswith("https://") or len(url) > 300:
        await message.answer("Havola https:// bilan boshlanishi kerak. Qayta yuboring:")
        return
    db.set_setting("app_hero_btn_target", f"url:{url}")
    await state.clear()
    await message.answer("✅ Saqlandi.\n\n" + hero_view(), reply_markup=hero_keyboard())


@router.callback_query(F.data == "admin_hero_reset")
async def admin_hero_reset(call: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(call):
        return
    for key in ("app_hero_title", "app_hero_text", "app_hero_image", "app_hero_btn_text", "app_hero_btn_target"):
        db.set_setting(key, None)
    await state.clear()
    await call.answer("Asl holatga qaytarildi.")
    if call.message:
        await edit_or_send(call.message, hero_view(), hero_keyboard())
