# BULLDROP Telegram bot + Mini App prototype

Telegram botning mavjud demo prototipiga Mini App sahifasi va Web App tugmasi qo‘shilgan.

## Holati

Bu **demo/prototip**: real pul qabul qilish, pul yechish, tikish, sovrinli o‘yinlar yoki uchinchi tomon o‘yini natijalarini bashorat qilish yo‘q. `/admin` faqat admin ID ni tekshiradi va demo xabar ko‘rsatadi; balans va to‘lovlarni tahrirlamaydi.

## Yangi: Qurilish o'yini va Bonus bo'limi

**🏗 Qurilish** (Mini App → O'yinlar): kran blokni tebratadi, «Qurish» bosilganda blok tushadi. 12 qavat, shamol har qavatda kuchayadi (0,9 → 9,2 m/s), koeffitsiyent ×1,1 dan ×40 gacha. Shamol minorani yiqitsa — tikish yo'qoladi; istalgan payt yutuqni olish mumkin. Natija o'yin boshida serverda belgilanadi (`crane.py`), bosish vaqti natijaga ta'sir qilmaydi; har qavatda kutiladigan qaytim 95%. Faqat virtual coin.

**💎 Bonus** (bot menyusi): do'st chaqirish havolasi (do'st telefon yuborsa, taklif qilgan odamga +800 coin; admin o'zgartiradi) va admin qo'shadigan shartlar (standart: @nft_webot ga /start va Mini App, +1000 coin).
- Shartda kanal ko'rsatilsa (@kanal) va bot o'sha kanalda admin bo'lsa — a'zolik avtomatik tekshiriladi va bonus darhol beriladi.
- Aks holda «✅ Bajardim» bosilganda adminlarga «✅ Tasdiqlash / ❌ Rad etish» tugmali xabar keladi; tasdiqlansa bonus beriladi, rad etilsa foydalanuvchi qayta yuborishi mumkin.
- Admin panel → «🎯 Bonus shartlari»: shart qo'shish/o'chirish/yoqish, mukofotni o'zgartirish, kutilayotgan so'rovlar.
- Boshqa bot (masalan @nft_webot) ichidagi harakatni Telegram bot tekshira olmaydi — shuning uchun bunday shartlar qo'lda tasdiqlanadi.

## O'yinlar menyusi va Narvon (yangilanish)

- Mini App pastki menyusida alohida **🎮 O'yinlar** bo'limi bor (Narvon, Minora, Saper, G'ildirak, Qurilish kartalari). Bosh sahifadan o'yinlar ro'yxati olib tashlandi.
- Har bir o'yinning chap yuqorisida **orqaga** tugmasi bor (Telegram'ning o'z «orqaga» tugmasi ham ishlaydi); u o'yinlar menyusiga qaytaradi.
- **Narvon**: 12 pog'ona, har birida 20 yo'lak. Chiqish yo'lagini o'yinchi o'zi tanlaydi (bir marta bosish — tanlash, yana bosish yoki «Qadam tashlash» — chiqish). Server tanlangan yo'lakda tosh bor-yo'qligini tekshiradi. Koeffitsiyent = 0,95 / p^k, p = (20 − toshlar) / 20 (3 tosh: ×1,12 … ×6,68; 4 tosh: ×1,19 … ×13,82).

## Dizayn: maxsus belgilar va 60 fps

- Mini App'dagi barcha emoji avtomatik ravishda shishali SVG belgilarga almashtiriladi (`index.html` ichidagi `EMO` jadvali). Yangi belgi qo'shish: `<symbol id="i-...">` qo'shing va `EMO` ga yozing.
- **Qurilish** to'liq ekranda ishlaydi, harakat vaqtga (dt) bog'liq va faqat GPU transform'lari yangilanadi. `BD_FPS_CAP` (30 yoki 60) ekran yangilanishini cheklaydi. FPS'ni ko'rish: Mini App havolasiga `?fps=1` qo'shing.
- **Botdagi maxsus emoji**: admin panel → «✨ Maxsus belgilar». Premium emoji'larni botga yuborsangiz, bot ularning ID sini saqlaydi va tugma/xabarlardagi oddiy emojilarni almashtiradi (`custom_emoji.py`). Telegram talabi: bot egasida Premium bo'lishi yoki bot Fragment'da qo'shimcha username sotib olgan bo'lishi kerak.

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
