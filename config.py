import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {
    int(item.strip())
    for item in os.getenv("ADMIN_IDS", "").split(",")
    if item.strip().isdigit()
}
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "x1000dollor").strip().lstrip("@")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()

TERMS_TEXT = (
    "📜 Foydalanish shartlari\n\n"
    "Bu bot hozir sinov rejimida. Kiritilgan Telegram ID va telefon raqami "
    "botning ishlashi uchun ma’lumotlar bazasida saqlanishi mumkin.\n\n"
    "Crash/Saper ko‘rsatmalari tasodifiy demo natijalar; ular haqiqiy "
    "o‘yin natijasini oldindan aytmaydi va yutuqni kafolatlamaydi. "
    "Hozircha pul qabul qilish, pul yechish yoki haqiqiy xarid mavjud emas."
)
