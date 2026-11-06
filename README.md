# Bulldrop Telegram bot — test starter

Bu loyiha hozircha **sinov prototipi**. Unda haqiqiy pul qabul qilish, pul yechish, pullik tarif yoki haqiqiy o‘yin natijasini bashorat qilish yo‘q.

## Fayllar
- `main.py` — ishga tushirish nuqtasi
- `bot.py` — Telegram bot va polling
- `features.py` — menyular, ro‘yxatdan o‘tish, Crash/Saper demo oqimlari
- `db.py` — SQLite foydalanuvchi va Saper tarixini saqlash
- `config.py` — `.env` sozlamalari
- `admins.py` — admin ID tekshiruvi
- `index.html` — oddiy Saper Mini App demo
- `requirements.txt` — Python kutubxonalari

## GitHub'ga yuklash va ishga tushirish
1. Barcha fayllarni repozitoriyga alohida yuklang.
2. `.env.example` faylidan nusxa olib, nusxasini `.env` deb nomlang.
3. `.env` ichida `BOT_TOKEN` qiymatiga BotFather bergan tokenni yozing.
4. `ADMIN_IDS` ichiga Telegram numeric user ID'ingizni yozing.
5. Terminalda:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\\Scripts\\activate
   # Linux/macOS:
   source .venv/bin/activate
   pip install -r requirements.txt
   python main.py
   ```

## Muhim
- Bot tokenini GitHub'ga hech qachon yuklamang. `.env` faylini `.gitignore`ga qo‘shing.
- Mini App uchun `index.html` HTTPS manzilda joylashtirilishi kerak. `WEBAPP_URL` hozircha kelajakdagi ulash uchun tayyorlangan.
- Hozirgi Saper kataklari tasodifiy demo. Ular uchinchi tomon o‘yinidagi xavfsiz kataklarni aniqlamaydi.
- Signal koeffitsiyentlari ham tasodifiy demo qiymatlardir.


## Render Web Service sozlamalari

- Service type: **Web Service**
- Runtime: **Python**
- Build Command: `pip install -r requirements.txt`
- Start Command: `python main.py`
- Health Check Path: `/healthz` (agar Render panelida mavjud bo‘lsa)
- Environment Variables: `BOT_TOKEN`, `ADMIN_IDS`, `BOT_USERNAME`, `WEBAPP_URL`
- `PORT` ni qo‘lda belgilamang: Render uni avtomatik beradi.

`main.py` bir jarayonda ikkita vazifani bajaradi:
1. `0.0.0.0:$PORT` manzilida `/` va `/healthz` HTTP endpointlarini ochadi.
2. Telegram botni long polling orqali ishga tushiradi.

Mahalliy sinovda `PORT` berilmagan bo‘lsa, fallback port `10000` ishlatiladi.
Bu Render uchun qattiq kodlangan port emas.
