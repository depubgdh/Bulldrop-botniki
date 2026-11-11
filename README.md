# BULLDROP Telegram bot + Mini App prototype

Telegram botning mavjud demo prototipiga Mini App sahifasi va Web App tugmasi qo‘shilgan.

## Holati

Bu **demo/prototip**: real pul qabul qilish, pul yechish, tikish, sovrinli o‘yinlar yoki uchinchi tomon o‘yini natijalarini bashorat qilish yo‘q. `/admin` faqat admin ID ni tekshiradi va demo xabar ko‘rsatadi; balans va to‘lovlarni tahrirlamaydi.

## Render sozlamalari

- Web Service, Python
- Build: `pip install -r requirements.txt`
- Start: `python main.py`
- Health check: `/healthz`
- `BOT_TOKEN`, `ADMIN_IDS`, `BOT_USERNAME`, `SUPPORT_USERNAME`, `WEBAPP_URL` environment variables qo‘shing.
- `WEBAPP_URL` sifatida deploy qilingan saytning HTTPS manzili va `/miniapp` yo‘lini kiriting, masalan `https://your-service.onrender.com/miniapp`.
- Render `PORT` ni avtomatik beradi; qo‘lda belgilamang.

`/` va `/miniapp` Mini App sahifasini beradi; `/healthz` health check uchun. Bot menyusida HTTPS URL bo‘lsa, Mini App tugmasi ko‘rinadi. Telegram ichida ochish uchun hosting manzili HTTPS bo‘lishi kerak.

## Mahalliy ishga tushirish

`.env.example` dan `.env` nusxa yarating, haqiqiy qiymatlarni faqat lokal muhit/Render dashboard’iga kiriting, keyin:

```bash
pip install -r requirements.txt
python main.py
```

Bot tokeni yoki to‘lov sirlarini GitHub’ga commit qilmang. To‘lov va withdrawal ulashdan oldin qonuniy talablar, provayderlar, foydalanuvchi verifikatsiyasi, audit va xatolarni qayta tiklash mexanizmlarini mustaqil tekshirish zarur.
