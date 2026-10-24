import os
import time
import sqlite3
import logging
import requests
from datetime import datetime

# ==================================================
# 1. ASOSIY SOZLAMALAR
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 5607350126

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi! Hosting Secrets bo'limiga qo'shing."
    )

API = f"https://api.telegram.org/bot{BOT_TOKEN}"
DB_FILE = "bot_data.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# Telegram so'rovlari uchun sessiya
session = requests.Session()

# Adminning joriy ommaviy xabar jarayoni
pending_broadcast = {}

# ==================================================
# 2. MA'LUMOTLAR BAZASI
# ==================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT DEFAULT '',
    last_name TEXT DEFAULT '',
    course TEXT DEFAULT '',
    group_name TEXT DEFAULT '',
    username TEXT DEFAULT '',
    state TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    blocked INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS message_map (
    admin_message_id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS broadcast_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT,
    total INTEGER,
    delivered INTEGER,
    failed INTEGER
)
""")

db.commit()

# Eski bazada yangi ustun bo'lmasa, qo'shish
cursor.execute("PRAGMA table_info(users)")
columns = {row["name"] for row in cursor.fetchall()}

if "blocked" not in columns:
    cursor.execute(
        "ALTER TABLE users ADD COLUMN blocked INTEGER DEFAULT 0"
    )
    db.commit()


# ==================================================
# 3. TELEGRAM API FUNKSIYALARI
# ==================================================

def tg(method, data=None, timeout=45):
    try:
        response = session.post(
            f"{API}/{method}",
            json=data or {},
            timeout=timeout
        )
        response.raise_for_status()
        result = response.json()

        if not result.get("ok"):
            logging.warning(
                "%s: %s",
                method,
                result.get("description", "Noma'lum xato")
            )

        return result

    except Exception:
        logging.exception("Telegram API xatosi: %s", method)
        return {"ok": False}


def send(chat_id, text, **kwargs):
    return tg("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        **kwargs
    })


def copy_message(chat_id, from_chat_id, message_id):
    return tg("copyMessage", {
        "chat_id": chat_id,
        "from_chat_id": from_chat_id,
        "message_id": message_id
    })


def safe_answer_callback(callback_id, text=""):
    tg("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text
    })


def main_keyboard():
    return {
        "keyboard": [
            [{"text": "✏️ Ma'lumotlarimni o'zgartirish"}],
            [{"text": "ℹ️ Yordam"}]
        ],
        "resize_keyboard": True
    }


def admin_keyboard():
    return {
        "keyboard": [
            [{"text": "👥 Foydalanuvchilar"},
             {"text": "📊 Statistika"}],
            [{"text": "📢 Hammaga xabar"},
             {"text": "❌ Bekor qilish"}]
        ],
        "resize_keyboard": True
    }


def is_admin(user_id):
    return user_id == ADMIN_ID


# ==================================================
# 4. FOYDALANUVCHILAR BAZASI
# ==================================================

def get_user(user_id):
    cursor.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    )
    return cursor.fetchone()


def add_user(user_id, username=""):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT OR IGNORE INTO users
        (user_id, username, state, created_at, blocked)
        VALUES (?, ?, 'first_name', ?, 0)
    """, (user_id, username or "", now))

    cursor.execute("""
        UPDATE users
        SET username=?, blocked=0
        WHERE user_id=?
    """, (username or "", user_id))

    db.commit()


def set_state(user_id, state):
    cursor.execute(
        "UPDATE users SET state=? WHERE user_id=?",
        (state, user_id)
    )
    db.commit()


def update_field(user_id, field, value):
    allowed = {
        "first_name", "last_name", "course", "group_name"
    }

    if field not in allowed:
        return

    cursor.execute(
        f"UPDATE users SET {field}=? WHERE user_id=?",
        (value.strip(), user_id)
    )
    db.commit()


def save_message_map(admin_message_id, user_id):
    cursor.execute("""
        INSERT OR REPLACE INTO message_map
        (admin_message_id, user_id)
        VALUES (?, ?)
    """, (admin_message_id, user_id))
    db.commit()


def find_message_user(admin_message_id):
    cursor.execute(
        "SELECT user_id FROM message_map WHERE admin_message_id=?",
        (admin_message_id,)
    )
    row = cursor.fetchone()
    return row["user_id"] if row else None


def set_blocked(user_id, blocked=True):
    cursor.execute(
        "UPDATE users SET blocked=? WHERE user_id=?",
        (1 if blocked else 0, user_id)
    )
    db.commit()


def get_registered_users():
    cursor.execute("""
        SELECT user_id FROM users
        WHERE first_name != ''
        AND last_name != ''
        AND course != ''
        AND group_name != ''
        ORDER BY created_at DESC
    """)
    return [row["user_id"] for row in cursor.fetchall()]


# ==================================================
# 5. RO'YXATDAN O'TKAZISH MATNLARI
# ==================================================

WELCOME = (
    "Assalomu alaykum! 👋\n\n"
    "Xush kelibsiz!\n"
    "Ushbu bot orqali admin bilan bog'lanishingiz, "
    "savol, taklif va murojaatlaringizni yuborishingiz mumkin.\n\n"
    "Boshlash uchun ismingizni kiriting."
)

HELP_TEXT = (
    "ℹ️ BOTDAN FOYDALANISH\n\n"
    "• Bu yerda admin bilan bog'lanishingiz mumkin.\n"
    "• Xabar, savol yoki taklifingizni bemalol yuboring.\n"
    "• Admin javobi shu bot orqali keladi.\n"
    "• Ma'lumotlaringizni kerak bo'lsa o'zgartirishingiz mumkin.\n\n"
    "Murojaat yuborish uchun xabaringizni shu chatga yozing."
)


def start_registration(user_id):
    set_state(user_id, "first_name")
    send(
        user_id,
        WELCOME,
        reply_markup={"remove_keyboard": True}
    )


def registration_step(message, user):
    user_id = message["from"]["id"]
    state = user["state"]
    text = message.get("text", "").strip()

    if not text:
        send(user_id, "Iltimos, bu bosqichda matn yuboring.")
        return

    if state == "first_name":
        update_field(user_id, "first_name", text)
        set_state(user_id, "last_name")
        send(user_id, "Rahmat! Endi familiyangizni kiriting.")

    elif state == "last_name":
        update_field(user_id, "last_name", text)
        set_state(user_id, "course")
        send(
            user_id,
            "Qaysi kursda o'qiysiz?\n\n"
            "Masalan: 1-kurs yoki 2-kurs."
        )

    elif state == "course":
        update_field(user_id, "course", text)
        set_state(user_id, "group_name")
        send(
            user_id,
            "Guruhingiz nomini kiriting.\n\n"
            "Masalan: KI-26.03."
        )

    elif state == "group_name":
        update_field(user_id, "group_name", text)
        set_state(user_id, "ready")

        send(
            user_id,
            "✅ Ro'yxatdan o'tish muvaffaqiyatli yakunlandi!\n\n"
            "Endi bot orqali admin bilan erkin bog'lanishingiz "
            "mumkin. Savol, taklif yoki murojaatingizni yuboring.\n\n"
            "Xabaringiz adminga yetkaziladi.",
            reply_markup=main_keyboard()
        )


# ==================================================
# 6. ADMIN UCHUN FOYDALANUVCHI MA'LUMOTLARI
# ==================================================

def forward_to_admin(message, user):
    user_id = user["user_id"]

    username = (
        "@" + user["username"]
        if user["username"]
        else "Username ko'rsatilmagan"
    )

    info = (
        "📩 YANGI MUROJAAT\n\n"
        f"👤 Ism: {user['first_name']}\n"
        f"👤 Familiya: {user['last_name']}\n"
        f"🎓 Kurs: {user['course']}\n"
        f"👥 Guruh: {user['group_name']}\n"
        f"🔗 Username: {username}\n"
        f"🆔 Telegram ID: {user_id}\n\n"
        "↩️ Javob berish uchun quyidagi xabar nusxasiga "
        "Telegram'da Reply qiling."
    )

    copied = copy_message(
        ADMIN_ID,
        user_id,
        message["message_id"]
    )

    if copied.get("ok"):
        save_message_map(
            copied["result"]["message_id"],
            user_id
        )

    info_result = send(ADMIN_ID, info)

    if info_result.get("ok"):
        save_message_map(
            info_result["result"]["message_id"],
            user_id
        )

    if copied.get("ok") and info_result.get("ok"):
        send(
            user_id,
            "✅ Xabaringiz adminga yetkazildi.\n\n"
            "Murojaatingiz ko'rib chiqiladi. Javob kelganda "
            "shu bot orqali xabardor qilinasiz. Rahmat!"
        )
    else:
        send(
            user_id,
            "⚠️ Xabaringizni yetkazishda muammo yuz berdi. "
            "Iltimos, birozdan keyin qayta urinib ko'ring."
        )


# ==================================================
# 7. ADMIN JAVOBINI FOYDALANUVCHIGA YETKAZISH
# ==================================================

def handle_admin_reply(message):
    reply = message.get("reply_to_message")

    if not reply:
        send(
            ADMIN_ID,
            "💬 Javob yuborish uchun foydalanuvchi xabariga "
            "Reply qiling.\n\n"
            "Ommaviy xabar uchun /broadcast buyrug'idan foydalaning."
        )
        return

    user_id = find_message_user(reply["message_id"])

    if not user_id:
        send(
            ADMIN_ID,
            "⚠️ Bu xabarning egasi topilmadi. "
            "Foydalanuvchi xabari nusxasiga Reply qiling."
        )
        return

    if message.get("text", "").startswith("/"):
        send(
            ADMIN_ID,
            "Buyruqlarni foydalanuvchiga javob sifatida yubormang. "
            "Oddiy matn yoki media yuboring."
        )
        return

    if message.get("text") is not None:
        result = send(
            user_id,
            "📩 ADMIN JAVOBI\n\n" + message["text"]
        )
    else:
        result = copy_message(
            user_id,
            ADMIN_ID,
            message["message_id"]
        )

    if result.get("ok"):
        send(ADMIN_ID, "✅ Javob foydalanuvchiga yuborildi.")
    else:
        send(
            ADMIN_ID,
            "❌ Javob yuborilmadi. Foydalanuvchi botni "
            "bloklagan yoki Telegram xatosi yuz bergan bo'lishi mumkin."
        )


# ==================================================
# 8. FOYDALANUVCHILAR VA STATISTIKA
# ==================================================

def show_users():
    users = get_registered_users()

    send(
        ADMIN_ID,
        f"👥 Ro'yxatdan o'tgan foydalanuvchilar: {len(users)}"
    )

    if not users:
        return

    cursor.execute("""
        SELECT first_name, last_name, course, group_name, user_id
        FROM users
        WHERE first_name != ''
        AND last_name != ''
        AND course != ''
        AND group_name != ''
        ORDER BY created_at DESC
        LIMIT 30
    """)

    rows = cursor.fetchall()
    text = "📋 SO'NGGI FOYDALANUVCHILAR\n\n"

    for index, row in enumerate(rows, 1):
        text += (
            f"{index}. {row['first_name']} {row['last_name']}\n"
            f"   Kurs: {row['course']} | Guruh: {row['group_name']}\n"
            f"   ID: {row['user_id']}\n\n"
        )

        if len(text) > 3000:
            send(ADMIN_ID, text)
            text = ""

    if text:
        send(ADMIN_ID, text)


def show_stats():
    cursor.execute("SELECT COUNT(*) AS n FROM users")
    total = cursor.fetchone()["n"]

    cursor.execute("""
        SELECT COUNT(*) AS n FROM users
        WHERE first_name != ''
        AND last_name != ''
        AND course != ''
        AND group_name != ''
    """)
    registered = cursor.fetchone()["n"]

    cursor.execute(
        "SELECT COUNT(*) AS n FROM users WHERE blocked=1"
    )
    blocked = cursor.fetchone()["n"]

    cursor.execute("""
        SELECT sent_at, total, delivered, failed
        FROM broadcast_log
        ORDER BY id DESC LIMIT 1
    """)
    last = cursor.fetchone()

    text = (
        "📊 BOT STATISTIKASI\n\n"
        f"👤 Jami foydalanuvchilar: {total}\n"
        f"✅ Ro'yxatdan o'tganlar: {registered}\n"
        f"🚫 Bloklaganlar / yetib bo'lmaganlar: {blocked}\n"
    )

    if last:
        text += (
            "\n📢 Oxirgi ommaviy xabar:\n"
            f"🕒 {last['sent_at']}\n"
            f"👥 Qabul qiluvchilar: {last['total']}\n"
            f"✅ Yetkazildi: {last['delivered']}\n"
            f"❌ Yetkazilmadi: {last['failed']}\n"
        )

    send(ADMIN_ID, text)


# ==================================================
# 9. OMMAVIY XABAR YUBORISH
# ==================================================

def begin_broadcast():
    pending_broadcast[ADMIN_ID] = {"state": "waiting_message"}

    send(
        ADMIN_ID,
        "📢 OMMAVIY XABAR YUBORISH\n\n"
        "Barcha ro'yxatdan o'tgan foydalanuvchilarga yubormoqchi "
        "bo'lgan xabaringizni yuboring.\n\n"
        "Matn, rasm, video, hujjat yoki boshqa Telegram xabarini "
        "yuborishingiz mumkin.\n\n"
        "Xabarni yuborishdan oldin tasdiqlaysiz.\n"
        "Bekor qilish uchun /cancel yozing."
    )


def preview_broadcast(message):
    pending_broadcast[ADMIN_ID] = {
        "state": "confirm",
        "message_id": message["message_id"]
    }

    copied = copy_message(
        ADMIN_ID,
        ADMIN_ID,
        message["message_id"]
    )

    if copied.get("ok"):
        pending_broadcast[ADMIN_ID]["preview_id"] = (
            copied["result"]["message_id"]
        )

    send(
        ADMIN_ID,
        "👆 Yuqorida ommaviy xabar namunasi.\n\n"
        "Ushbu xabar barcha ro'yxatdan o'tgan foydalanuvchilarga "
        "yuborilsinmi?",
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "✅ Ha, yuborish",
                        "callback_data": "broadcast_yes"
                    },
                    {
                        "text": "❌ Bekor qilish",
                        "callback_data": "broadcast_no"
                    }
                ]
            ]
        }
    )


def execute_broadcast():
    pending = pending_broadcast.get(ADMIN_ID)

    if not pending or pending.get("state") != "confirm":
        send(ADMIN_ID, "⚠️ Tasdiqlash uchun ommaviy xabar topilmadi.")
        return

    source_message_id = pending["message_id"]
    users = get_registered_users()

    if not users:
        send(ADMIN_ID, "Hozircha ro'yxatdan o'tgan foydalanuvchilar yo'q.")
        pending_broadcast.pop(ADMIN_ID, None)
        return

    send(
        ADMIN_ID,
        f"⏳ Yuborish boshlandi.\nQabul qiluvchilar: {len(users)}"
    )

    delivered = 0
    failed = 0
    blocked_ids = []

    for user_id in users:
        result = copy_message(
            user_id,
            ADMIN_ID,
            source_message_id
        )

        if result.get("ok"):
            delivered += 1
            set_blocked(user_id, False)
        else:
            failed += 1

            description = str(
                result.get("description", "")
            ).lower()

            if (
                "blocked by the user" in description
                or "user is deactivated" in description
                or "chat not found" in description
            ):
                blocked_ids.append(user_id)
                set_blocked(user_id, True)

        # Telegram cheklovlariga ehtiyotkorlik bilan rioya qilish
        time.sleep(0.05)

    sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO broadcast_log
        (sent_at, total, delivered, failed)
        VALUES (?, ?, ?, ?)
    """, (sent_at, len(users), delivered, failed))
    db.commit()

    pending_broadcast.pop(ADMIN_ID, None)

    send(
        ADMIN_ID,
        "📊 OMMAVIY YUBORISH YAKUNLANDI\n\n"
        f"👥 Jami: {len(users)}\n"
        f"✅ Yetkazildi: {delivered}\n"
        f"❌ Yetkazilmadi: {failed}\n"
        f"🚫 Bloklangan yoki mavjud bo'lmagan chatlar: "
        f"{len(blocked_ids)}\n\n"
        "Eslatma: Telegram ayrim foydalanuvchilarga xabar "
        "yetkazishni cheklashi mumkin.",
        reply_markup=admin_keyboard()
    )


# ==================================================
# 10. CALLBACK — TASDIQLASH TUGMALARI
# ==================================================

def handle_callback(callback):
    callback_id = callback["id"]
    user_id = callback["from"]["id"]
    data = callback.get("data", "")

    if not is_admin(user_id):
        safe_answer_callback(callback_id, "Bu amal faqat admin uchun.")
        return

    if data == "broadcast_yes":
        safe_answer_callback(callback_id, "Yuborish boshlandi.")
        execute_broadcast()

    elif data == "broadcast_no":
        pending_broadcast.pop(ADMIN_ID, None)
        safe_answer_callback(callback_id, "Bekor qilindi.")

        send(
            ADMIN_ID,
            "❌ Ommaviy xabar yuborish bekor qilindi.",
            reply_markup=admin_keyboard()
        )


# ==================================================
# 11. ASOSIY XABARLARNI QAYTA ISHLASH
# ==================================================

def process_message(message):
    sender = message.get("from", {})
    user_id = sender.get("id")

    if not user_id:
        return

    text = message.get("text", "")
    username = sender.get("username", "")

    # Admin uchun buyruqlar
    if is_admin(user_id):
        if text == "/start":
            send(
                ADMIN_ID,
                "Assalomu alaykum, admin!\n\n"
                "Bot boshqaruv paneliga xush kelibsiz.\n\n"
                "Kerakli amalni tanlang yoki buyruq yuboring.\n\n"
                "/users — foydalanuvchilar\n"
                "/stats — statistika\n"
                "/broadcast — hammaga xabar\n"
                "/cancel — bekor qilish",
                reply_markup=admin_keyboard()
            )
            return

        if text == "/users" or text == "👥 Foydalanuvchilar":
            show_users()
            return

        if text == "/stats" or text == "📊 Statistika":
            show_stats()
            return

        if text == "/broadcast" or text == "📢 Hammaga xabar":
            begin_broadcast()
            return

        if text == "/cancel" or text == "❌ Bekor qilish":
            pending_broadcast.pop(ADMIN_ID, None)
            send(
                ADMIN_ID,
                "❌ Joriy amal bekor qilindi.",
                reply_markup=admin_keyboard()
            )
            return

        pending = pending_broadcast.get(ADMIN_ID)

        if pending and pending.get("state") == "waiting_message":
            if text == "/help":
                send(ADMIN_ID, ADMIN_HELP)
                return

            preview_broadcast(message)
            return

        if pending and pending.get("state") == "confirm":
            send(
                ADMIN_ID,
                "⚠️ Avval xabarni tasdiqlang yoki bekor qiling."
            )
            return

        # Adminning Reply orqali javobi
        if message.get("reply_to_message"):
            handle_admin_reply(message)
            return

        if text == "/help":
            send(ADMIN_ID, ADMIN_HELP)
            return

        send(
            ADMIN_ID,
            "Admin paneli:\n\n"
            "/users — foydalanuvchilar\n"
            "/stats — statistika\n"
            "/broadcast — hammaga xabar\n"
            "/cancel — bekor qilish\n\n"
            "Foydalanuvchiga javob berish uchun uning xabariga "
            "Reply qiling."
        )
        return

    # Bot guruhda ishlatilsa, oddiy guruh xabarlarini qayta ishlamaslik
    if message.get("chat", {}).get("type") != "private":
        return

    # Oddiy foydalanuvchi
    add_user(user_id, username)
    user = get_user(user_id)

    if text.startswith("/start"):
        if (
            user
            and user["first_name"]
            and user["last_name"]
            and user["course"]
            and user["group_name"]
        ):
            set_state(user_id, "ready")
            send(
                user_id,
                "Assalomu alaykum! 👋\n\n"
                "Siz botda ro'yxatdan o'tgansiz.\n"
                "Savol, taklif yoki murojaatingizni shu yerga "
                "yozishingiz mumkin.",
                reply_markup=main_keyboard()
            )
        else:
            start_registration(user_id)
        return

    if text == "/cancel":
        set_state(user_id, "ready")
        send(
            user_id,
            "Joriy amal bekor qilindi. Xohlagan vaqtingiz "
            "murojaat yuborishingiz mumkin.",
            reply_markup=main_keyboard()
        )
        return

    if text == "ℹ️ Yordam" or text == "/help":
        send(user_id, HELP_TEXT, reply_markup=main_keyboard())
        return

    if text == "✏️ Ma'lumotlarimni o'zgartirish":
        set_state(user_id, "edit_choice")
        send(
            user_id,
            "Qaysi ma'lumotingizni o'zgartirmoqchisiz?\n\n"
            "first_name — ism\n"
            "last_name — familiya\n"
            "course — kurs\n"
            "group_name — guruh\n\n"
            "Kerakli nomni yozing. Bekor qilish uchun /cancel."
        )
        return

    # Ma'lumotlarni tahrirlash jarayoni
    if user["state"] == "edit_choice":
        fields = {
            "ism": ("first_name", "Yangi ismingizni kiriting."),
            "first_name": ("first_name", "Yangi ismingizni kiriting."),
            "familiya": ("last_name", "Yangi familiyangizni kiriting."),
            "last_name": ("last_name", "Yangi familiyangizni kiriting."),
            "kurs": ("course", "Yangi kursingizni kiriting."),
            "course": ("course", "Yangi kursingizni kiriting."),
            "guruh": ("group_name", "Yangi guruhingizni kiriting."),
            "group_name": ("group_name", "Yangi guruhingizni kiriting.")
        }

        chosen = fields.get(text.lower())

        if not chosen:
            send(
                user_id,
                "Iltimos, quyidagilardan birini yozing:\n"
                "ism, familiya, kurs yoki guruh."
            )
            return

        field, prompt = chosen
        set_state(user_id, "edit_" + field)
        send(user_id, prompt)
        return

    if user["state"].startswith("edit_"):
        field = user["state"][5:]

        if text:
            update_field(user_id, field, text)
            set_state(user_id, "ready")
            send(
                user_id,
                "✅ Ma'lumotingiz muvaffaqiyatli yangilandi.",
                reply_markup=main_keyboard()
            )
        else:
            send(user_id, "Iltimos, yangi ma'lumotni matn shaklida kiriting.")
        return

    # Ro'yxatdan o'tish tugallanmagan bo'lsa
    if user["state"] in (
        "first_name", "last_name", "course", "group_name"
    ):
        registration_step(message, user)
        return

    # To'liq ro'yxatdan o'tgan foydalanuvchi murojaati
    if (
        user["first_name"]
        and user["last_name"]
        and user["course"]
        and user["group_name"]
    ):
        forward_to_admin(message, user)
        return

    start_registration(user_id)


# ==================================================
# 12. BOTNI ISHGA TUSHIRISH
# ==================================================

def main():
    logging.info("Bot ishga tushmoqda...")

    # Webhook ishlayotgan bo'lsa, polling uchun o'chirish
    tg("deleteWebhook", {"drop_pending_updates": False})

    # Bot ishlayotganini tekshirish
    me = tg("getMe")

    if not me.get("ok"):
        raise RuntimeError(
            "Bot Telegram bilan bog'lana olmadi. BOT_TOKENni tekshiring."
        )

    bot_name = me["result"].get("username", "noma'lum")
    logging.info("Bot ishga tushdi: @%s", bot_name)

    offset = None

    while True:
        try:
            params = {
                "timeout": 30,
                "allowed_updates": ["message", "callback_query"]
            }

            if offset is not None:
                params["offset"] = offset

            result = tg("getUpdates", params, timeout=40)

            if not result.get("ok"):
                time.sleep(3)
                continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1

                try:
                    if "message" in update:
                        process_message(update["message"])

                    elif "callback_query" in update:
                        handle_callback(update["callback_query"])

                except Exception:
                    logging.exception("Yangilanishni qayta ishlashda xato")

        except KeyboardInterrupt:
            logging.info("Bot to'xtatildi.")
            break

        except Exception:
            logging.exception("Asosiy siklda xato")
            time.sleep(3)


if __name__ == "__main__":
    main()
