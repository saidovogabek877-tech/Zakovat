import os
import time
import sqlite3
import logging
import requests
from datetime import datetime

# ==================================================
# SOZLAMALAR
# ==================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = 5607350126
DB_FILE = "bot_data.db"

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN yo'q! Hosting Secrets bo'limiga BOT_TOKEN qo'shing."
    )

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)

http = requests.Session()
db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

# Adminning ommaviy xabar yuborish holati
broadcast_state = None


# ==================================================
# TELEGRAM API
# ==================================================

def tg(method, data=None, timeout=40):
    try:
        response = http.post(
            f"{API}/{method}",
            json=data or {},
            timeout=timeout
        )
        result = response.json()

        if not result.get("ok"):
            logging.error(
                "Telegram %s xatosi: %s",
                method,
                result.get("description", result)
            )

        return result

    except Exception:
        logging.exception("Telegram API so'rovi bajarilmadi: %s", method)
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


def is_admin(user_id):
    return int(user_id) == ADMIN_ID


# ==================================================
# MA'LUMOTLAR BAZASI
# ==================================================

with db:
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            course TEXT DEFAULT '',
            group_name TEXT DEFAULT '',
            username TEXT DEFAULT '',
            state TEXT DEFAULT 'first_name',
            created_at TEXT DEFAULT '',
            blocked INTEGER DEFAULT 0
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS message_map (
            admin_message_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at TEXT,
            total INTEGER,
            delivered INTEGER,
            failed INTEGER
        )
    """)

# Eski baza bilan moslik
columns = {
    row["name"]
    for row in db.execute("PRAGMA table_info(users)").fetchall()
}

if "blocked" not in columns:
    with db:
        db.execute(
            "ALTER TABLE users ADD COLUMN blocked INTEGER DEFAULT 0"
        )


def get_user(user_id):
    return db.execute(
        "SELECT * FROM users WHERE user_id=?",
        (user_id,)
    ).fetchone()


def add_user(user_id, username=""):
    user = get_user(user_id)

    if user is None:
        with db:
            db.execute("""
                INSERT INTO users
                (user_id, username, state, created_at, blocked)
                VALUES (?, ?, 'first_name', ?, 0)
            """, (
                user_id,
                username or "",
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
    else:
        with db:
            db.execute("""
                UPDATE users
                SET username=?, blocked=0
                WHERE user_id=?
            """, (username or "", user_id))


def set_state(user_id, state):
    with db:
        db.execute(
            "UPDATE users SET state=? WHERE user_id=?",
            (state, user_id)
        )


def update_field(user_id, field, value):
    allowed = {
        "first_name", "last_name", "course", "group_name"
    }

    if field not in allowed:
        return

    with db:
        db.execute(
            f"UPDATE users SET {field}=? WHERE user_id=?",
            (value.strip(), user_id)
        )


def map_message(message_id, user_id):
    with db:
        db.execute("""
            INSERT OR REPLACE INTO message_map
            (admin_message_id, user_id)
            VALUES (?, ?)
        """, (message_id, user_id))


def find_user_by_admin_message(message_id):
    row = db.execute(
        "SELECT user_id FROM message_map WHERE admin_message_id=?",
        (message_id,)
    ).fetchone()

    return row["user_id"] if row else None


def registered_users():
    rows = db.execute("""
        SELECT user_id FROM users
        WHERE first_name != ''
          AND last_name != ''
          AND course != ''
          AND group_name != ''
    """).fetchall()

    return [row["user_id"] for row in rows]


# ==================================================
# TUGMALAR
# ==================================================

def user_keyboard():
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
            [
                {"text": "👥 Foydalanuvchilar"},
                {"text": "📊 Statistika"}
            ],
            [
                {"text": "📢 Hammaga xabar"},
                {"text": "❌ Bekor qilish"}
            ]
        ],
        "resize_keyboard": True
    }


# ==================================================
# RO'YXATDAN O'TISH
# ==================================================

def next_registration_state(user):
    if not user["first_name"]:
        return "first_name"
    if not user["last_name"]:
        return "last_name"
    if not user["course"]:
        return "course"
    if not user["group_name"]:
        return "group_name"
    return "ready"


def start_user(user_id):
    user = get_user(user_id)

    if user is None:
        add_user(user_id)
        user = get_user(user_id)

    state = next_registration_state(user)

    if state == "ready":
        set_state(user_id, "ready")

        send(
            user_id,
            "Assalomu alaykum! 👋\n\n"
            "Siz botda ro'yxatdan o'tgansiz.\n"
            "Savol, taklif yoki murojaatingizni yuborishingiz mumkin.\n\n"
            "Xabaringiz adminga yetkaziladi.",
            reply_markup=user_keyboard()
        )
        return

    set_state(user_id, state)

    prompts = {
        "first_name": (
            "Assalomu alaykum! 👋\n\n"
            "Botimizga xush kelibsiz!\n"
            "Boshlash uchun ismingizni kiriting."
        ),
        "last_name": "Rahmat! Endi familiyangizni kiriting.",
        "course": (
            "Qaysi kursda o'qiysiz?\n"
            "Masalan: 1-kurs."
        ),
        "group_name": (
            "Guruhingiz nomini kiriting.\n"
            "Masalan: KI-26.03."
        )
    }

    send(
        user_id,
        prompts[state],
        reply_markup={"remove_keyboard": True}
    )


def registration_step(message, user):
    user_id = message["from"]["id"]
    text = message.get("text", "").strip()
    state = user["state"]

    if not text:
        send(user_id, "Iltimos, javobingizni matn ko'rinishida yuboring.")
        return

    if len(text) > 100:
        send(user_id, "Matn juda uzun. Iltimos, qisqaroq kiriting.")
        return

    fields = {
        "first_name": ("first_name", "Familiyangizni kiriting."),
        "last_name": ("last_name", "Kursingizni kiriting."),
        "course": ("course", "Guruhingizni kiriting."),
        "group_name": ("group_name", None)
    }

    if state not in fields:
        start_user(user_id)
        return

    field, next_prompt = fields[state]
    update_field(user_id, field, text)

    updated = get_user(user_id)
    next_state = next_registration_state(updated)
    set_state(user_id, next_state)

    if next_state == "ready":
        send(
            user_id,
            "✅ Ro'yxatdan o'tish yakunlandi!\n\n"
            "Endi savol, taklif va murojaatlaringizni shu bot orqali "
            "yuborishingiz mumkin.\n\n"
            "Rahmat!",
            reply_markup=user_keyboard()
        )
    else:
        send(user_id, next_prompt)


# ==================================================
# FOYDALANUVCHI XABARINI ADMINGA YETKAZISH
# ==================================================

def forward_to_admin(message, user):
    user_id = user["user_id"]

    username = (
        "@" + user["username"]
        if user["username"]
        else "Username mavjud emas"
    )

    copied = copy_message(
        ADMIN_ID,
        user_id,
        message["message_id"]
    )

    if not copied.get("ok"):
        send(
            user_id,
            "⚠️ Xabaringizni yetkazishda muammo yuz berdi. "
            "Birozdan keyin qayta urinib ko'ring."
        )
        return

    copied_id = copied["result"]["message_id"]
    map_message(copied_id, user_id)

    info = (
        "📩 YANGI MUROJAAT\n\n"
        f"👤 Ism: {user['first_name']}\n"
        f"👤 Familiya: {user['last_name']}\n"
        f"🎓 Kurs: {user['course']}\n"
        f"👥 Guruh: {user['group_name']}\n"
        f"🔗 Username: {username}\n"
        f"🆔 Telegram ID: {user_id}\n\n"
        "Javob berish uchun yuqoridagi nusxaga Reply qiling."
    )

    info_result = send(ADMIN_ID, info)

    if info_result.get("ok"):
        map_message(info_result["result"]["message_id"], user_id)

    send(
        user_id,
        "✅ Xabaringiz adminga yetkazildi!\n\n"
        "Murojaatingiz ko'rib chiqiladi. Javob kelganda "
        "shu bot orqali olasiz. Rahmat!"
    )


# ==================================================
# ADMIN JAVOBI
# ==================================================

def handle_admin_reply(message):
    reply = message.get("reply_to_message")

    if not reply:
        send(
            ADMIN_ID,
            "Javob berish uchun foydalanuvchi xabariga Reply qiling."
        )
        return

    user_id = find_user_by_admin_message(reply["message_id"])

    if not user_id:
        send(
            ADMIN_ID,
            "⚠️ Foydalanuvchi topilmadi. "
            "Foydalanuvchi yuborgan xabar nusxasiga Reply qiling."
        )
        return

    text = message.get("text", "")

    if text.startswith("/"):
        send(
            ADMIN_ID,
            "Buyruqni javob sifatida yubormang. Oddiy matn yoki media yuboring."
        )
        return

    if "text" in message:
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
            "❌ Javob yetkazilmadi. Foydalanuvchi botni bloklagan "
            "bo'lishi yoki Telegramda xato yuz bergan bo'lishi mumkin."
        )


# ==================================================
# ADMIN STATISTIKASI
# ==================================================

def show_users():
    rows = db.execute("""
        SELECT first_name, last_name, course, group_name, user_id
        FROM users
        WHERE first_name != ''
          AND last_name != ''
          AND course != ''
          AND group_name != ''
        ORDER BY created_at DESC
    """).fetchall()

    send(ADMIN_ID, f"👥 Ro'yxatdan o'tganlar: {len(rows)}")

    text = "📋 FOYDALANUVCHILAR\n\n"

    for i, row in enumerate(rows, 1):
        line = (
            f"{i}. {row['first_name']} {row['last_name']}\n"
            f"   {row['course']} | {row['group_name']}\n"
            f"   ID: {row['user_id']}\n\n"
        )

        if len(text) + len(line) > 3500:
            send(ADMIN_ID, text)
            text = ""

        text += line

    if text.strip():
        send(ADMIN_ID, text)


def show_stats():
    total = db.execute(
        "SELECT COUNT(*) AS n FROM users"
    ).fetchone()["n"]

    registered = len(registered_users())

    last = db.execute("""
        SELECT * FROM broadcast_log
        ORDER BY id DESC LIMIT 1
    """).fetchone()

    text = (
        "📊 BOT STATISTIKASI\n\n"
        f"👤 Jami foydalanuvchilar: {total}\n"
        f"✅ Ro'yxatdan o'tganlar: {registered}\n"
    )

    if last:
        text += (
            "\n📢 Oxirgi ommaviy xabar:\n"
            f"🕒 {last['sent_at']}\n"
            f"👥 Jami: {last['total']}\n"
            f"✅ Yetkazildi: {last['delivered']}\n"
            f"❌ Yetkazilmadi: {last['failed']}\n"
        )

    send(ADMIN_ID, text)


# ==================================================
# OMMAVIY XABAR
# ==================================================

def begin_broadcast():
    global broadcast_state
    broadcast_state = {"state": "waiting"}

    send(
        ADMIN_ID,
        "📢 OMMAVIY XABAR\n\n"
        "Barcha ro'yxatdan o'tgan foydalanuvchilarga yuboriladigan "
        "matn, rasm, video yoki boshqa xabarni yuboring.\n\n"
        "Avval ko'rib chiqasiz, keyin tasdiqlaysiz.\n"
        "Bekor qilish: /cancel"
    )


def preview_broadcast(message):
    global broadcast_state

    broadcast_state = {
        "state": "confirm",
        "message_id": message["message_id"]
    }

    send(
        ADMIN_ID,
        "📋 Xabar tayyor.\n\n"
        "Uni barcha ro'yxatdan o'tgan foydalanuvchilarga yuboraymi?",
        reply_markup={
            "inline_keyboard": [[
                {
                    "text": "✅ Yuborish",
                    "callback_data": "broadcast_yes"
                },
                {
                    "text": "❌ Bekor qilish",
                    "callback_data": "broadcast_no"
                }
            ]]
        }
    )


def execute_broadcast():
    global broadcast_state

    if not broadcast_state or broadcast_state.get("state") != "confirm":
        send(ADMIN_ID, "Tasdiqlanadigan xabar topilmadi.")
        return

    source_id = broadcast_state["message_id"]
    users = registered_users()

    if not users:
        send(ADMIN_ID, "Ro'yxatdan o'tgan foydalanuvchilar yo'q.")
        broadcast_state = None
        return

    send(ADMIN_ID, f"⏳ Yuborish boshlandi. Qabul qiluvchilar: {len(users)}")

    delivered = 0
    failed = 0

    for user_id in users:
        result = copy_message(user_id, ADMIN_ID, source_id)

        if result.get("ok"):
            delivered += 1
        else:
            failed += 1

        # Telegram cheklovlariga rioya qilish
        time.sleep(0.05)

    with db:
        db.execute("""
            INSERT INTO broadcast_log
            (sent_at, total, delivered, failed)
            VALUES (?, ?, ?, ?)
        """, (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            len(users),
            delivered,
            failed
        ))

    broadcast_state = None

    send(
        ADMIN_ID,
        "📊 YUBORISH YAKUNLANDI\n\n"
        f"👥 Jami: {len(users)}\n"
        f"✅ Yetkazildi: {delivered}\n"
        f"❌ Yetkazilmadi: {failed}",
        reply_markup=admin_keyboard()
    )


# ==================================================
# CALLBACK TUGMALARI
# ==================================================

def process_callback(callback):
    global broadcast_state

    user_id = callback["from"]["id"]
    data = callback.get("data", "")

    if not is_admin(user_id):
        tg("answerCallbackQuery", {
            "callback_query_id": callback["id"],
            "text": "Bu amal faqat admin uchun."
        })
        return

    tg("answerCallbackQuery", {
        "callback_query_id": callback["id"]
    })

    if data == "broadcast_yes":
        execute_broadcast()

    elif data == "broadcast_no":
        broadcast_state = None
        send(
            ADMIN_ID,
            "❌ Ommaviy xabar bekor qilindi.",
            reply_markup=admin_keyboard()
        )


# ==================================================
# XABARLARNI QAYTA ISHLASH
# ==================================================

def process_message(message):
    sender = message.get("from", {})
    user_id = sender.get("id")

    if not user_id:
        return

    text = message.get("text", "").strip()
    username = sender.get("username", "")

    logging.info(
        "Xabar keldi: user_id=%s, admin=%s, text=%r",
        user_id,
        is_admin(user_id),
        text[:100]
    )

    # -------------------------
    # ADMIN
    # -------------------------
    if is_admin(user_id):

        if text == "/start":
            send(
                ADMIN_ID,
                "Assalomu alaykum, admin! 🛠\n\n"
                "/users — foydalanuvchilar\n"
                "/stats — statistika\n"
                "/broadcast — hammaga xabar\n"
                "/cancel — bekor qilish",
                reply_markup=admin_keyboard()
            )
            return

        if text in ("/users", "👥 Foydalanuvchilar"):
            show_users()
            return

        if text in ("/stats", "📊 Statistika"):
            show_stats()
            return

        if text in ("/broadcast", "📢 Hammaga xabar"):
            begin_broadcast()
            return

        if text in ("/cancel", "❌ Bekor qilish"):
            global broadcast_state
            broadcast_state = None
            send(
                ADMIN_ID,
                "❌ Joriy amal bekor qilindi.",
                reply_markup=admin_keyboard()
            )
            return

        if broadcast_state and broadcast_state["state"] == "waiting":
            if text == "/help":
                send(ADMIN_ID, "Xabar yuboring yoki /cancel yozing.")
                return

            preview_broadcast(message)
            return

        if broadcast_state and broadcast_state["state"] == "confirm":
            send(
                ADMIN_ID,
                "Avval xabarni tasdiqlang yoki bekor qiling."
            )
            return

        if message.get("reply_to_message"):
            handle_admin_reply(message)
            return

        send(
            ADMIN_ID,
            "Admin paneli:\n"
            "/users — foydalanuvchilar\n"
            "/stats — statistika\n"
            "/broadcast — hammaga xabar\n"
            "/cancel — bekor qilish\n\n"
            "Foydalanuvchiga javob berish uchun uning xabariga Reply qiling.",
            reply_markup=admin_keyboard()
        )
        return

    # -------------------------
    # ODDIY FOYDALANUVCHI
    # -------------------------

    # Bot faqat shaxsiy chatda ishlaydi
    if message.get("chat", {}).get("type") != "private":
        return

    add_user(user_id, username)

    # /start har doim birinchi navbatda tekshiriladi
    if text == "/start" or text.startswith("/start "):
        start_user(user_id)
        return

    if text == "/help" or text == "ℹ️ Yordam":
        send(
            user_id,
            "ℹ️ YORDAM\n\n"
            "Admin bilan bog'lanish uchun xabaringizni shu chatga yozing.\n"
            "Xabaringiz adminga yetkaziladi va javob shu yerga keladi.",
            reply_markup=user_keyboard()
        )
        return

    if text == "/cancel":
        user = get_user(user_id)
        if user:
            set_state(user_id, next_registration_state(user))

        send(
            user_id,
            "Joriy amal bekor qilindi.",
            reply_markup=user_keyboard()
        )
        return

    user = get_user(user_id)

    if not user:
        start_user(user_id)
        return

    # Ma'lumotlarni o'zgartirish
    if text == "✏️ Ma'lumotlarimni o'zgartirish":
        set_state(user_id, "edit_choice")
        send(
            user_id,
            "Qaysi ma'lumotni o'zgartirasiz?\n\n"
            "Ism, familiya, kurs yoki guruh deb yozing.\n"
            "Bekor qilish: /cancel"
        )
        return

    if user["state"] == "edit_choice":
        choices = {
            "ism": ("first_name", "Yangi ismingizni kiriting."),
            "familiya": ("last_name", "Yangi familiyangizni kiriting."),
            "kurs": ("course", "Yangi kursingizni kiriting."),
            "guruh": ("group_name", "Yangi guruhingizni kiriting.")
        }

        choice = choices.get(text.lower())

        if not choice:
            send(user_id, "Ism, familiya, kurs yoki guruh deb yozing.")
            return

        field, prompt = choice
        set_state(user_id, "edit_" + field)
        send(user_id, prompt)
        return

    if user["state"].startswith("edit_"):
        field = user["state"][5:]

        if not text:
            send(user_id, "Iltimos, yangi ma'lumotni matn ko'rinishida yuboring.")
            return

        update_field(user_id, field, text)
        set_state(user_id, next_registration_state(get_user(user_id)))
        send(
            user_id,
            "✅ Ma'lumotingiz yangilandi.",
            reply_markup=user_keyboard()
        )
        return

    # Ro'yxatdan o'tish hali tugamagan bo'lsa
    if next_registration_state(user) != "ready":
        set_state(user_id, next_registration_state(user))
        registration_step(message, get_user(user_id))
        return

    # Ro'yxatdan o'tgan foydalanuvchining istalgan xabari
    forward_to_admin(message, user)


# ==================================================
# ISHGA TUSHIRISH
# ==================================================

def main():
    logging.info("Bot ishga tushmoqda...")

    # Webhook polling bilan to'qnashmasligi uchun o'chiriladi
    webhook = tg("deleteWebhook", {"drop_pending_updates": False})

    if not webhook.get("ok"):
        logging.warning("Webhook holatini tekshiring.")

    me = tg("getMe")

    if not me.get("ok"):
        raise RuntimeError(
            "Bot tokeni noto'g'ri yoki Telegram API bilan aloqa yo'q."
        )

    logging.info(
        "Bot faol: @%s | Admin ID: %s",
        me["result"].get("username"),
        ADMIN_ID
    )

    offset = None

    while True:
        try:
            params = {
                "timeout": 25,
                "allowed_updates": ["message", "callback_query"]
            }

            if offset is not None:
                params["offset"] = offset

            updates = tg("getUpdates", params, timeout=35)

            if not updates.get("ok"):
                logging.error(
                    "getUpdates ishlamadi. Boshqa bot nusxasi "
                    "yoki webhook mavjudligini tekshiring."
                )
                time.sleep(3)
                continue

            for update in updates.get("result", []):
                offset = update["update_id"] + 1

                try:
                    if "message" in update:
                        process_message(update["message"])

                    elif "callback_query" in update:
                        process_callback(update["callback_query"])

                except Exception:
                    logging.exception(
                        "Update qayta ishlanmadi: %s",
                        update.get("update_id")
                    )

        except KeyboardInterrupt:
            logging.info("Bot to'xtatildi.")
            break

        except Exception:
            logging.exception("Asosiy siklda xato")
            time.sleep(3)


if __name__ == "__main__":
    main()
