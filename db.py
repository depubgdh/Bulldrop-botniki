import os
import random
import re
import sqlite3
from pathlib import Path

# Render'da doimiy disk ulangan bo'lsa, DB_PATH ni shu diskdagi yo'lga qo'ying (masalan /var/data/bulldrop.sqlite3).
# Aks holda baza har deploy'da o'chib ketadi.
DB_PATH = Path(os.getenv("DB_PATH") or Path(__file__).with_name("bulldrop.sqlite3"))

DEFAULT_FREE_OPENS = 10
REF_REWARD_DEFAULT = 800     # do'st ro'yxatdan o'tganda taklif qilgan odamga (virtual coin)
TASK_REWARD_DEFAULT = 1000  # bonus sharti bajarilganda (virtual coin)


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                phone TEXT,
                accepted_terms INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS saper_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                game_id TEXT NOT NULL,
                green_cells TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price INTEGER NOT NULL DEFAULT 0,
                description TEXT,
                image_url TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS case_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                price INTEGER NOT NULL DEFAULT 0,
                image_url TEXT,
                probability REAL NOT NULL DEFAULT 0,
                rarity TEXT NOT NULL DEFAULT 'common',
                is_active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            )
        """)
        # Foydalanuvchiga tushgan sovg'alar. Nom/narx/rasm nusxalab saqlanadi: admin sovg'ani
        # keyin o'chirsa yoki o'zgartirsa ham inventory buzilmaydi.
        con.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                item_id INTEGER,
                case_id INTEGER,
                name TEXT NOT NULL,
                price INTEGER NOT NULL DEFAULT 0,
                image_url TEXT,
                rarity TEXT NOT NULL DEFAULT 'common',
                sold INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sold_at TEXT
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_inventory_user ON inventory(user_id, sold)")
        con.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Eski bazalar uchun yangi ustunlar
        cols = [row["name"] for row in con.execute("PRAGMA table_info(users)")]
        if "referrer_id" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN referrer_id INTEGER")
        if "coins" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN coins INTEGER NOT NULL DEFAULT 0")
        if "opens" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN opens INTEGER NOT NULL DEFAULT 0")
        if "last_daily" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN last_daily TEXT")
        if "ref_paid" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN ref_paid INTEGER NOT NULL DEFAULT 0")
        ccols = [row["name"] for row in con.execute("PRAGMA table_info(cases)")]
        if "bg_color" not in ccols:
            con.execute("ALTER TABLE cases ADD COLUMN bg_color TEXT NOT NULL DEFAULT ''")
        # G'ildirak o'yini: har bir chaqiruv bir marta yoziladi (request_id bo'yicha)
        con.execute("""
            CREATE TABLE IF NOT EXISTS wheel_spins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                user_id INTEGER NOT NULL,
                bet INTEGER NOT NULL,
                count INTEGER NOT NULL,
                results TEXT NOT NULL,
                total_bet INTEGER NOT NULL,
                total_payout INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_wheel_user ON wheel_spins(user_id, id)")
        # Bonus shartlari (admin qo'shadi) va foydalanuvchilarning bajardim so'rovlari
        con.execute("""
            CREATE TABLE IF NOT EXISTS bonus_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '',
                reward INTEGER NOT NULL DEFAULT 1000,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS bonus_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                UNIQUE(task_id, user_id)
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_claims_status ON bonus_claims(status, id)")
        if not con.execute("SELECT 1 FROM settings WHERE key='tasks_seeded'").fetchone():
            con.execute(
                "INSERT INTO bonus_tasks(title, description, url, reward) VALUES (?, ?, ?, ?)",
                ("@nft_webot botiga kiring",
                 "1) Pastdagi havola orqali @nft_webot ga o‘ting va /start bosing.\n"
                 "2) Botdagi Mini App'ni oching.\n"
                 "3) Qaytib kelib «✅ Bajardim» tugmasini bosing — admin tekshirib, tasdiqlaydi.",
                 "https://t.me/nft_webot", TASK_REWARD_DEFAULT),
            )
            con.execute("INSERT INTO settings(key, value) VALUES ('tasks_seeded', '1')")


# ------------------------------------------------------------------ sozlamalar

def get_setting(key, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key, value):
    with connect() as con:
        if value is None:
            con.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            con.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )


def _free_limit(con) -> int:
    row = con.execute("SELECT value FROM settings WHERE key='free_opens'").fetchone()
    try:
        return max(0, int(row["value"])) if row and row["value"] is not None else DEFAULT_FREE_OPENS
    except (TypeError, ValueError):
        return DEFAULT_FREE_OPENS


def free_limit() -> int:
    """Har bir foydalanuvchi uchun nechta ochish tekin."""
    with connect() as con:
        return _free_limit(con)


# ------------------------------------------------------------------ foydalanuvchilar

def ensure_user(user_id, username=None):
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES (?, ?)", (user_id, username))
        if username:
            con.execute("UPDATE users SET username=? WHERE user_id=? AND IFNULL(username, '')<>?",
                        (username, user_id, username))


def register_referral(user_id, referrer_id):
    """Foydalanuvchini taklif qilgan odamga bog'laydi. Faqat hali ro'yxatdan o'tmagan (telefon yubormagan,
    boshqa taklifchisi yo'q) foydalanuvchi uchun ishlaydi."""
    if user_id == referrer_id:
        return False
    with connect() as con:
        if not con.execute("SELECT 1 FROM users WHERE user_id=?", (referrer_id,)).fetchone():
            return False
        me = con.execute("SELECT referrer_id, phone FROM users WHERE user_id=?", (user_id,)).fetchone()
        if me is None:
            con.execute("INSERT INTO users(user_id, referrer_id) VALUES (?, ?)", (user_id, referrer_id))
            return True
        if me["referrer_id"] is None and me["phone"] is None:
            con.execute("UPDATE users SET referrer_id=? WHERE user_id=?", (referrer_id, user_id))
            return True
        return False


def count_referrals(user_id):
    """Ro'yxatdan to'liq o'tgan (telefon yuborgan) taklif qilingan do'stlar soni."""
    with connect() as con:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM users WHERE referrer_id=? AND phone IS NOT NULL",
            (user_id,),
        ).fetchone()
        return int(row["n"])


def get_user(user_id):
    with connect() as con:
        return con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def save_user(user_id, username=None, phone=None, accepted_terms=None):
    old = get_user(user_id)
    values = {
        "username": username if username is not None else (old["username"] if old else None),
        "phone": phone if phone is not None else (old["phone"] if old else None),
        "accepted_terms": accepted_terms if accepted_terms is not None else (old["accepted_terms"] if old else 0),
    }
    with connect() as con:
        con.execute("""
            INSERT INTO users(user_id, username, phone, accepted_terms)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                phone=excluded.phone,
                accepted_terms=excluded.accepted_terms
        """, (user_id, values["username"], values["phone"], values["accepted_terms"]))


def find_user(query):
    """ID yoki @username bo'yicha foydalanuvchini topadi."""
    q = (query or "").strip()
    if not q:
        return None
    with connect() as con:
        if q.lstrip("-").isdigit():
            return con.execute("SELECT * FROM users WHERE user_id=?", (int(q),)).fetchone()
        return con.execute("SELECT * FROM users WHERE lower(username)=lower(?)", (q.lstrip("@"),)).fetchone()


def all_user_ids():
    with connect() as con:
        return [row["user_id"] for row in con.execute("SELECT user_id FROM users ORDER BY user_id")]


def _wallet(con, user_id) -> dict:
    row = con.execute("SELECT coins, opens FROM users WHERE user_id=?", (user_id,)).fetchone()
    coins = int(row["coins"]) if row else 0
    opens = int(row["opens"]) if row else 0
    return {"coins": coins, "opens": opens, "free_left": max(0, _free_limit(con) - opens)}


def wallet(user_id) -> dict:
    with connect() as con:
        return _wallet(con, user_id)


def add_coins(user_id, delta):
    """Coin qo'shadi (yoki manfiy bo'lsa ayiradi; balans 0 dan pastga tushmaydi). Yangi balansni qaytaradi."""
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        con.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE user_id=?", (int(delta), user_id))
        return int(con.execute("SELECT coins FROM users WHERE user_id=?", (user_id,)).fetchone()["coins"])


def add_coins_all(amount):
    """Ro'yxatdan o'tgan barcha foydalanuvchilarga coin beradi. Nechta foydalanuvchiga berilganini qaytaradi."""
    with connect() as con:
        cur = con.execute("UPDATE users SET coins = coins + ? WHERE phone IS NOT NULL", (int(amount),))
        return cur.rowcount


def user_card(user_id):
    with connect() as con:
        user = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not user:
            return None
        inv = con.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(price), 0) AS v FROM inventory WHERE user_id=? AND sold=0",
            (user_id,),
        ).fetchone()
        return {
            "user": user,
            "wallet": _wallet(con, user_id),
            "inventory": {"count": int(inv["n"]), "value": int(inv["v"])},
            "referrals": con.execute(
                "SELECT COUNT(*) AS n FROM users WHERE referrer_id=? AND phone IS NOT NULL", (user_id,)
            ).fetchone()["n"],
        }


def stats() -> dict:
    with connect() as con:
        def one(sql, *args):
            return int(con.execute(sql, args).fetchone()[0] or 0)
        return {
            "users": one("SELECT COUNT(*) FROM users"),
            "registered": one("SELECT COUNT(*) FROM users WHERE phone IS NOT NULL"),
            "cases": one("SELECT COUNT(*) FROM cases WHERE is_active=1"),
            "opens": one("SELECT COALESCE(SUM(opens), 0) FROM users"),
            "held": one("SELECT COUNT(*) FROM inventory WHERE sold=0"),
            "held_value": one("SELECT COALESCE(SUM(price), 0) FROM inventory WHERE sold=0"),
            "sold": one("SELECT COUNT(*) FROM inventory WHERE sold=1"),
            "coins": one("SELECT COALESCE(SUM(coins), 0) FROM users"),
        }


# ------------------------------------------------------------------ o'yinlar (demo)

def add_saper_result(user_id, game_id, green_cells):
    with connect() as con:
        con.execute(
            "INSERT INTO saper_history(user_id, game_id, green_cells) VALUES (?, ?, ?)",
            (user_id, game_id, ",".join(map(str, green_cells)))
        )


# ------------------------------------------------------------------ qutilar

def add_case(name, price, description="", image_url=""):
    with connect() as con:
        cur = con.execute(
            "INSERT INTO cases(name, price, description, image_url) VALUES (?, ?, ?, ?)",
            (name, int(price), description or "", image_url or "")
        )
        return cur.lastrowid


def get_cases():
    with connect() as con:
        return con.execute(
            "SELECT * FROM cases WHERE is_active = 1 ORDER BY price ASC, id ASC"
        ).fetchall()


def get_case(case_id):
    with connect() as con:
        return con.execute("SELECT * FROM cases WHERE id=? AND is_active=1", (case_id,)).fetchone()


def deactivate_case(case_id):
    with connect() as con:
        con.execute("UPDATE cases SET is_active=0 WHERE id=?", (int(case_id),))


def set_case_image(case_id, image_url):
    with connect() as con:
        con.execute("UPDATE cases SET image_url=? WHERE id=?", (image_url or "", int(case_id)))


def set_case_bg(case_id, color):
    """Quti orqa foni: '#rrggbb' yoki '' (rasmdan avtomatik)."""
    color = (color or "").strip().lower()
    if color and not re.fullmatch(r"#[0-9a-f]{6}", color):
        raise ValueError("bad_color")
    with connect() as con:
        con.execute("UPDATE cases SET bg_color=? WHERE id=?", (color, int(case_id)))


def update_case(case_id, name=None, price=None, description=None):
    sets, args = [], []
    if name is not None:
        sets.append("name=?"); args.append(name)
    if price is not None:
        sets.append("price=?"); args.append(int(price))
    if description is not None:
        sets.append("description=?"); args.append(description)
    if not sets:
        return
    args.append(int(case_id))
    with connect() as con:
        con.execute(f"UPDATE cases SET {', '.join(sets)} WHERE id=?", args)


def update_item(item_id, name=None, price=None, rarity=None, probability=None):
    sets, args = [], []
    if name is not None:
        sets.append("name=?"); args.append(name)
    if price is not None:
        sets.append("price=?"); args.append(int(price))
    if rarity is not None:
        sets.append("rarity=?"); args.append(rarity)
    if probability is not None:
        sets.append("probability=?"); args.append(float(probability))
    if not sets:
        return
    args.append(int(item_id))
    with connect() as con:
        con.execute(f"UPDATE case_items SET {', '.join(sets)} WHERE id=?", args)


def add_case_item(case_id, name, price, image_url="", probability=0.0, rarity="common"):
    with connect() as con:
        con.execute(
            "INSERT INTO case_items(case_id, name, price, image_url, probability, rarity) VALUES (?, ?, ?, ?, ?, ?)",
            (int(case_id), name, int(price), image_url or "", float(probability), rarity or "common")
        )


def get_case_item(item_id):
    with connect() as con:
        return con.execute("SELECT * FROM case_items WHERE id=? AND is_active=1", (int(item_id),)).fetchone()


def set_item_image(item_id, image_url):
    with connect() as con:
        con.execute("UPDATE case_items SET image_url=? WHERE id=?", (image_url or "", int(item_id)))


def deactivate_item(item_id):
    """Sovg'ani o'chiradi va u tegishli bo'lgan quti ID sini qaytaradi."""
    item = get_case_item(item_id)
    if not item:
        return None
    with connect() as con:
        con.execute("UPDATE case_items SET is_active=0 WHERE id=?", (int(item_id),))
    return item["case_id"]


def get_case_items(case_id):
    with connect() as con:
        return con.execute(
            "SELECT * FROM case_items WHERE case_id=? AND is_active=1 ORDER BY probability ASC, id ASC",
            (int(case_id),),
        ).fetchall()


def _pick(items):
    total = sum(float(item["probability"]) for item in items)
    if total <= 0:
        return items[0]
    roll = random.random() * total
    running = 0.0
    for item in items:
        running += float(item["probability"])
        if roll <= running:
            return item
    return items[-1]


def pick_case_item(case_id):
    items = get_case_items(case_id)
    return _pick(items) if items else None


def case_ev(case_id) -> float:
    """Quti bir marta ochilganda tushadigan sovg'aning o'rtacha qiymati (coin)."""
    items = get_case_items(case_id)
    total = sum(float(i["probability"]) for i in items)
    if total <= 0:
        return 0.0
    return sum(float(i["price"]) * float(i["probability"]) for i in items) / total


# ------------------------------------------------------------------ ochish, inventory, sotish

OPEN_COUNTS = (1, 2, 3, 5, 10)


def open_case(user_id, case_id, count=1) -> dict:
    """Qutini count marta (1, 2, 3, 5 yoki 10) ochadi. Avval bepul ochishlar ishlatiladi, qolganlari uchun quti narxi
    coin'dan yechiladi. Hammasi bitta tranzaksiyada: coin yechish, sovg'alarni tanlash va inventoryga yozish
    (coin yetmasa — hech narsa o'zgarmaydi)."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_count"}
    if count not in OPEN_COUNTS:
        return {"ok": False, "error": "bad_count"}
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        case = con.execute("SELECT * FROM cases WHERE id=? AND is_active=1", (int(case_id),)).fetchone()
        if not case:
            con.rollback()
            return {"ok": False, "error": "no_case"}
        items = con.execute(
            "SELECT * FROM case_items WHERE case_id=? AND is_active=1 ORDER BY probability ASC, id ASC",
            (int(case_id),),
        ).fetchall()
        if not items:
            con.rollback()
            return {"ok": False, "error": "no_items"}

        wallet_before = _wallet(con, user_id)
        price = int(case["price"])
        free_n = count if price <= 0 else min(count, wallet_before["free_left"])
        cost = (count - free_n) * price
        if wallet_before["coins"] < cost:
            con.rollback()
            return {"ok": False, "error": "no_funds", "price": price, "coins": wallet_before["coins"]}

        con.execute("UPDATE users SET coins = coins - ?, opens = opens + ? WHERE user_id=?", (cost, count, user_id))
        won = []
        for _ in range(count):
            winner = _pick(items)
            cur = con.execute(
                "INSERT INTO inventory(user_id, item_id, case_id, name, price, image_url, rarity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, winner["id"], case["id"], winner["name"], int(winner["price"]),
                 winner["image_url"] or "", winner["rarity"]),
            )
            won.append(con.execute("SELECT * FROM inventory WHERE id=?", (cur.lastrowid,)).fetchone())
        result = {
            "ok": True,
            "free": free_n == count,
            "free_used": free_n,
            "cost": cost,
            "item": won[0],
            "items": won,
            "wallet": _wallet(con, user_id),
        }
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def sell_items(user_id, ids) -> dict:
    """Tanlangan buyumlarni (faqat shu foydalanuvchiniki va sotilmaganlarini) bitta tranzaksiyada sotadi."""
    ids = sorted({int(i) for i in ids})[:50]
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        gained = count = 0
        for inv_id in ids:
            row = con.execute("SELECT * FROM inventory WHERE id=? AND user_id=? AND sold=0", (inv_id, user_id)).fetchone()
            if not row:
                continue
            con.execute("UPDATE inventory SET sold=1, sold_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
            gained += int(row["price"])
            count += 1
        if not count:
            con.rollback()
            return {"ok": False, "error": "not_found"}
        con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (gained, user_id))
        result = {"ok": True, "count": count, "gained": gained, "wallet": _wallet(con, user_id)}
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def inventory_list(user_id):
    with connect() as con:
        return con.execute(
            "SELECT * FROM inventory WHERE user_id=? AND sold=0 ORDER BY id DESC", (user_id,)
        ).fetchall()


def sell_item(user_id, inv_id) -> dict:
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM inventory WHERE id=? AND user_id=? AND sold=0", (int(inv_id), user_id)
        ).fetchone()
        if not row:
            con.rollback()
            return {"ok": False, "error": "not_found"}
        con.execute("UPDATE inventory SET sold=1, sold_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (int(row["price"]), user_id))
        result = {"ok": True, "count": 1, "gained": int(row["price"]), "wallet": _wallet(con, user_id)}
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def sell_all(user_id) -> dict:
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(price), 0) AS v FROM inventory WHERE user_id=? AND sold=0",
            (user_id,),
        ).fetchone()
        if not row["n"]:
            con.rollback()
            return {"ok": False, "error": "not_found"}
        con.execute(
            "UPDATE inventory SET sold=1, sold_at=CURRENT_TIMESTAMP WHERE user_id=? AND sold=0", (user_id,)
        )
        con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (int(row["v"]), user_id))
        result = {"ok": True, "count": int(row["n"]), "gained": int(row["v"]), "wallet": _wallet(con, user_id)}
        con.commit()
        return result
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ------------------------------------------------------------------ media

def media_known(ref) -> bool:
    """'tg:<tur>:<file_id>' havolasi bazada (quti, sovg'a, inventory yoki sozlama) ishlatilganmi."""
    with connect() as con:
        row = con.execute(
            "SELECT 1 FROM cases WHERE image_url=? "
            "UNION ALL SELECT 1 FROM case_items WHERE image_url=? "
            "UNION ALL SELECT 1 FROM inventory WHERE image_url=? "
            "UNION ALL SELECT 1 FROM settings WHERE value=? LIMIT 1",
            (ref, ref, ref, ref),
        ).fetchone()
    return row is not None


# ------------------------------------------------------------------ bonus: do'st taklifi va shartlar

def ref_reward() -> int:
    raw = get_setting("ref_reward")
    try:
        return max(0, int(raw)) if raw is not None else REF_REWARD_DEFAULT
    except (TypeError, ValueError):
        return REF_REWARD_DEFAULT


def pay_referral(user_id):
    """Do'st ro'yxatdan to'liq o'tganda (telefon yuborganda) taklif qilgan odamga bir marta bonus beradi.
    Qaytaradi: {"referrer_id", "amount"} yoki None (taklifchi yo'q / allaqachon to'langan / hali ro'yxatdan o'tmagan)."""
    amount = ref_reward()
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT referrer_id, ref_paid, phone FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row or not row["referrer_id"] or row["ref_paid"] or not row["phone"]:
            con.rollback()
            return None
        con.execute("UPDATE users SET ref_paid=1 WHERE user_id=?", (user_id,))
        paid = 0
        if amount > 0 and con.execute("SELECT 1 FROM users WHERE user_id=?", (row["referrer_id"],)).fetchone():
            con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (amount, row["referrer_id"]))
            paid = amount
        con.commit()
        return {"referrer_id": int(row["referrer_id"]), "amount": paid}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def add_task(title, description="", url="", channel="", reward=TASK_REWARD_DEFAULT):
    with connect() as con:
        cur = con.execute(
            "INSERT INTO bonus_tasks(title, description, url, channel, reward) VALUES (?, ?, ?, ?, ?)",
            (title, description or "", url or "", channel or "", max(0, int(reward))),
        )
        return cur.lastrowid


def get_tasks(active_only=True):
    with connect() as con:
        sql = "SELECT * FROM bonus_tasks" + (" WHERE is_active=1" if active_only else "") + " ORDER BY id"
        return con.execute(sql).fetchall()


def get_task(task_id):
    with connect() as con:
        return con.execute("SELECT * FROM bonus_tasks WHERE id=?", (int(task_id),)).fetchone()


def update_task(task_id, **fields):
    allowed = {"title", "description", "url", "channel", "reward", "is_active"}
    sets = [(k, v) for k, v in fields.items() if k in allowed]
    if not sets:
        return
    with connect() as con:
        con.execute(
            f"UPDATE bonus_tasks SET {', '.join(k + '=?' for k, _ in sets)} WHERE id=?",
            [int(v) if k in ("reward", "is_active") else v for k, v in sets] + [int(task_id)],
        )


def delete_task(task_id):
    with connect() as con:
        con.execute("DELETE FROM bonus_tasks WHERE id=?", (int(task_id),))
        con.execute("DELETE FROM bonus_claims WHERE task_id=? AND status='pending'", (int(task_id),))


def claim_statuses(user_id) -> dict:
    """{task_id: 'pending' | 'approved' | 'rejected'}"""
    with connect() as con:
        return {r["task_id"]: r["status"] for r in con.execute(
            "SELECT task_id, status FROM bonus_claims WHERE user_id=?", (user_id,))}


def submit_claim(task_id, user_id) -> dict:
    """Foydalanuvchi «Bajardim» bosdi. ok=True — admin tasdig'iga yangi so'rov yaratildi."""
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        row = con.execute("SELECT * FROM bonus_claims WHERE task_id=? AND user_id=?", (int(task_id), user_id)).fetchone()
        if row and row["status"] in ("approved", "pending"):
            con.rollback()
            return {"ok": False, "status": row["status"], "claim_id": row["id"]}
        if row:  # rad etilgan edi — qayta yuboradi
            con.execute("UPDATE bonus_claims SET status='pending', created_at=CURRENT_TIMESTAMP, resolved_at=NULL WHERE id=?",
                        (row["id"],))
            claim_id = row["id"]
        else:
            claim_id = con.execute("INSERT INTO bonus_claims(task_id, user_id) VALUES (?, ?)",
                                   (int(task_id), user_id)).lastrowid
        con.commit()
        return {"ok": True, "status": "pending", "claim_id": claim_id}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def auto_approve(task_id, user_id) -> dict:
    """Kanal a'zoligi bot tomonidan tekshirilgan: so'rovsiz darhol bonus beradi (bir marta)."""
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        task = con.execute("SELECT * FROM bonus_tasks WHERE id=?", (int(task_id),)).fetchone()
        if not task:
            con.rollback()
            return {"ok": False, "status": "no_task"}
        con.execute("INSERT OR IGNORE INTO users(user_id) VALUES (?)", (user_id,))
        row = con.execute("SELECT * FROM bonus_claims WHERE task_id=? AND user_id=?", (int(task_id), user_id)).fetchone()
        if row and row["status"] == "approved":
            con.rollback()
            return {"ok": False, "status": "approved"}
        if row:
            con.execute("UPDATE bonus_claims SET status='approved', resolved_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
        else:
            con.execute("INSERT INTO bonus_claims(task_id, user_id, status, resolved_at) VALUES (?, ?, 'approved', CURRENT_TIMESTAMP)",
                        (int(task_id), user_id))
        reward = int(task["reward"])
        if reward > 0:
            con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (reward, user_id))
        con.commit()
        return {"ok": True, "reward": reward, "title": task["title"]}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def resolve_claim(claim_id, approve: bool):
    """Admin qarori. Faqat kutilayotgan so'rov uchun va faqat bir marta ishlaydi (ikki marta bosish bonusni ikkilantirmaydi).
    Qaytaradi: {"user_id", "title", "reward", "approved"} yoki None."""
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE")
        claim = con.execute("SELECT * FROM bonus_claims WHERE id=? AND status='pending'", (int(claim_id),)).fetchone()
        if not claim:
            con.rollback()
            return None
        task = con.execute("SELECT * FROM bonus_tasks WHERE id=?", (claim["task_id"],)).fetchone()
        reward = int(task["reward"]) if task else 0
        con.execute("UPDATE bonus_claims SET status=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
                    ("approved" if approve else "rejected", claim["id"]))
        if approve and reward > 0:
            con.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (reward, claim["user_id"]))
        con.commit()
        return {"user_id": int(claim["user_id"]), "title": task["title"] if task else "Shart",
                "reward": reward if approve else 0, "approved": bool(approve)}
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def pending_claims(limit=10):
    with connect() as con:
        return con.execute(
            "SELECT c.id, c.user_id, c.created_at, t.title, t.reward, u.username "
            "FROM bonus_claims c LEFT JOIN bonus_tasks t ON t.id=c.task_id LEFT JOIN users u ON u.user_id=c.user_id "
            "WHERE c.status='pending' ORDER BY c.id LIMIT ?", (int(limit),)).fetchall()


def count_pending_claims() -> int:
    with connect() as con:
        return int(con.execute("SELECT COUNT(*) FROM bonus_claims WHERE status='pending'").fetchone()[0])
