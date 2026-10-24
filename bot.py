
import os
import time
import sqlite3
import logging
import requests

# ============== SOZLAMALAR ==============

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = 5607350126
DB_FILE = "bot_data.db"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN hosting sozlamalarida mavjud emas.")


# ============== TELEGRAM API ==============

def tg(method, data=None, timeout=40):
    try:
        response = requests.post(
            f"{API_URL}/{method}",
            json=data or {},
            timeout=timeout
        )
        result = response.json()

        if not result.get("ok"):
            logging.error(
                "%s xatosi: %s",
                method,
                result.get("description")
            )

        return result
    except Exception:
        logging.exception("Telegram API xatosi")
        return {"ok": False}


def send(chat_id, text, **kwargs):
    return tg("sendMessage", {
        "chat_id": chat_id,
        "text": text,
        **kwargs
    })


# ============== MA'LUMOTLAR BAZASI ==============

def db():
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                last_name TEXT DEFAULT '',
                course TEXT DEFAULT '',
                group_name TEXT DEFAULT '',
                step TEXT DEFAULT 'name',
                registered INTEGER DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS reply_map (
                message_id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL
            )
        """)

        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)")
        }

        migrations = {
            "username": "TEXT DEFAULT ''",
            "first_name": "TEXT DEFAULT ''",
            "last_name": "TEXT DEFAULT ''",
            "course": "TEXT DEFAULT ''",
            "group_name": "TEXT DEFAULT ''",
            "step": "TEXT DEFAULT 'name'",
            "registered": "INTEGER DEFAULT 0"
        }

        for column, definition in migrations.items():
            if column not in columns:
                conn.execute(
                    f"ALTER TABLE users ADD COLUMN {column} {definition}"
                )


def get_user(user_id):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()


def set_field(user_id, field, value):
    allowed = {
        "username", "first_name", "last_name",
        "course", "group_name", "step", "registered"
    }

    if field not in allowed:
        return

    with db() as conn:
        conn.execute(
            f"UPDATE users SET {field} = ? WHERE user_id = ?",
            (value, user_id)
        )


def ensure_user(tg_user):
    with db() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username
        """, (
            tg_user["id"],
            tg_user.get("username") or "",
            tg_user.get("first_name") or ""
        ))


def save_reply_map(message_id, user_id):
    with db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO reply_map (message_id, user_id)
            VALUES (?, ?)
        """, (message_id, user_id))


def find_reply_user(message_id):
    with db() as conn:
        row = conn.execute(
            "SELECT user_id FROM reply_map WHERE message_id = ?",
            (message_id,)
        ).fetchone()

    return row["user_id"] if row else None


# ============== RO'YXATDAN O'TISH ==============

def ask(chat_id, step):
    prompts = {
        "name": (
            "Assalomu alaykum! 👋\n\n"
            "Xush kelibsiz!\n"
            "Botdan qulay foydalanishingiz uchun qisqa "
            "ro'yxatdan o'tamiz.\n\n"
            "✍️ Ismingizni kiriting:"
        ),
        "last_name": (
            "Rahmat! 😊\n\n"
            "Endi familiyangizni kiriting:"
        ),
        "course": (
            "🎓 Qaysi kursda tahsil olasiz?\n\n"
            "Masalan: 1-kurs.\n"
            "Agar talaba bo'lmasangiz, «Yo'q» deb yozing."
        ),
        "group_name": (
            "📚 Guruhingiz nomini kiriting.\n\n"
            "Masalan: KI-26.03.\n"
            "Guruhingiz bo'lmasa, «Yo'q» deb yozing."
        )
    }

    send(chat_id, prompts.get(step, prompts["name"]))


def full_name(user):
    first = user["first_name"] or ""
    last = user["last_name"] or ""
    return (first + " " + last).strip() or "Ko'rsatilmagan"


def finish_registration(chat_id, user_id):
    set_field(user_id, "registered", 1)
    set_field(user_id, "step", "done")

    user = get_user(user_id)
    name = full_name(user)
    course = user["course"] or "Ko'rsatilmagan"
    group_name = user["group_name"] or "Ko'rsatilmagan"
    username = "@" + user["username"] if user["username"] else "Mavjud emas"

    send(
        chat_id,
        "🎉 Ro'yxatdan muvaffaqiyatli o'tdingiz!\n\n"
        f"👤 Ism-familiya: {name}\n"
        f"🎓 Kurs: {course}\n"
        f"👥 Guruh: {group_name}\n\n"
        "Endi botdan bemalol foydalanishingiz mumkin. 💬\n"
        "Savol yoki murojaatingiz bo'lsa, xabaringizni yuboring."
    )

    send(
        ADMIN_ID,
        "🆕 YANGI FOYDALANUVCHI RO'YXATDAN O'TDI\n\n"
        f"👤 Ism-familiya: {name}\n"
        f"🎓 Kurs: {course}\n"
        f"👥 Guruh: {group_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 Telegram ID: {user_id}"
    )


def registration_step(message, user):
    user_id = message["from"]["id"]
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if not text:
        send(chat_id, "Iltimos, javobingizni matn ko'rinishida yuboring.")
        return

    step = user["step"]

    if step == "name":
        set_field(user_id, "first_name", text[:100])
        set_field(user_id, "step", "last_name")
        ask(chat_id, "last_name")

    elif step == "last_name":
        set_field(user_id, "last_name", text[:100])
        set_field(user_id, "step", "course")
        ask(chat_id, "course")

    elif step == "course":
        value = "" if text.lower() in ("yo'q", "yo‘q", "yoq", "-", "нет") else text[:100]
        set_field(user_id, "course", value)
        set_field(user_id, "step", "group_name")
        ask(chat_id, "group_name")

    elif step == "group_name":
        value = "" if text.lower() in ("yo'q", "yo‘q", "yoq", "-", "нет") else text[:100]
        set_field(user_id, "group_name", value)
        finish_registration(chat_id, user_id)


# ============== FOYDALANUVCHI XABARI ==============

def forward_to_admin(message, user):
    user_id = user["user_id"]

    name = user["first_name"] or "Ko'rsatilmagan"
    surname = user["last_name"] or "Ko'rsatilmagan"
    course = user["course"] or "Ko'rsatilmagan"
    group_name = user["group_name"] or "Ko'rsatilmagan"
    username = "@" + user["username"] if user["username"] else "Mavjud emas"

    info = (
        "📩 FOYDALANUVCHIDAN YANGI MUROJAAT\n\n"
        f"👤 Ism: {name}\n"
        f"📝 Familiya: {surname}\n"
        f"🎓 Kurs: {course}\n"
        f"👥 Guruh: {group_name}\n"
        f"🔗 Username: {username}\n"
        f"🆔 Telegram ID: {user_id}\n\n"
        "💬 Foydalanuvchi yuborgan xabar quyida.\n"
        "↩️ Javob berish uchun xabar nusxasiga Reply qiling."
    )

    info_result = send(ADMIN_ID, info)

    if info_result.get("ok"):
        save_reply_map(info_result["result"]["message_id"], user_id)

    copied = tg("copyMessage", {
        "chat_id": ADMIN_ID,
        "from_chat_id": message["chat"]["id"],
        "message_id": message["message_id"]
    })

    if copied.get("ok"):
        save_reply_map(copied["result"]["message_id"], user_id)
    else:
        logging.error("Foydalanuvchi xabarini adminga yuborib bo'lmadi.")


# ============== ADMIN JAVOBI ==============

def admin_reply(message):
    reply = message.get("reply_to_message")

    if not reply:
        send(
            ADMIN_ID,
            "Foydalanuvchiga javob berish uchun uning "
            "xabar nusxasiga Reply qiling."
        )
        return

    user_id = find_reply_user(reply["message_id"])

    if not user_id:
        send(
            ADMIN_ID,
            "Foydalanuvchi aniqlanmadi. Bot yuborgan "
            "murojaat xabariga Reply qiling."
        )
        return

    if message.get("text"):
        result = send(
            user_id,
            "📩 Sizga admin tomonidan javob keldi:\n\n"
            + message["text"]
        )
    else:
        result = tg("copyMessage", {
            "chat_id": user_id,
            "from_chat_id": ADMIN_ID,
            "message_id": message["message_id"]
        })

    if result.get("ok"):
        send(ADMIN_ID, "✅ Javob foydalanuvchiga muvaffaqiyatli yuborildi.")
    else:
        send(
            ADMIN_ID,
            "❌ Javob yuborilmadi. Foydalanuvchi botni bloklagan "
            "bo'lishi mumkin."
        )


# ============== XABARLARNI QAYTA ISHLASH ==============

def handle_message(message):
    sender = message.get("from")

    if not sender or sender.get("is_bot"):
        return

    if message.get("chat", {}).get("type") != "private":
        return

    user_id = sender["id"]
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    # Admin
    if user_id == ADMIN_ID:
        if text == "/start":
            send(
                ADMIN_ID,
                "👋 Admin paneliga xush kelibsiz!\n\n"
                "Foydalanuvchi xabariga Reply qilib javob yuboring.\n"
                "/users — foydalanuvchilar statistikasi"
            )
            return

        if text == "/users":
            with db() as conn:
                total = conn.execute(
                    "SELECT COUNT(*) AS n FROM users"
                ).fetchone()["n"]

                registered = conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE registered = 1"
                ).fetchone()["n"]

            send(
                ADMIN_ID,
                "📊 FOYDALANUVCHILAR STATISTIKASI\n\n"
                f"👥 Jami foydalanuvchilar: {total}\n"
                f"✅ Ro'yxatdan o'tganlar: {registered}"
            )
            return

        admin_reply(message)
        return

    # Oddiy foydalanuvchi
    ensure_user(sender)
    user = get_user(user_id)

    if text == "/start":
        if user["registered"]:
            send(
                chat_id,
                "Assalomu alaykum! 👋\n\n"
                "Xush kelibsiz! Siz ro'yxatdan o'tgansiz.\n"
                "Murojaatingizni yuborishingiz mumkin. 💬"
            )
        else:
            ask(chat_id, user["step"])
        return

    if not user["registered"]:
        registration_step(message, user)
        return

    forward_to_admin(message, user)

    send(
        chat_id,
        "✅ Xabaringiz adminga yetkazildi!\n\n"
        "Murojaatingiz uchun rahmat. 😊"
    )


# ============== BOTNI ISHGA TUSHIRISH ==============

def main():
    init_db()

    tg("deleteWebhook", {"drop_pending_updates": False})
    me = tg("getMe")

    if not me.get("ok"):
        raise RuntimeError(
            "Bot tokeni noto'g'ri yoki Telegram bilan aloqa yo'q."
        )

    logging.info(
        "Bot ishga tushdi: @%s",
        me["result"].get("username", "")
    )

    offset = None

    while True:
        try:
            params = {
                "timeout": 30,
                "allowed_updates": ["message"]
            }

            if offset is not None:
                params["offset"] = offset

            result = tg("getUpdates", params, timeout=40)

            if not result.get("ok"):
                time.sleep(3)
                continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1

                if "message" in update:
                    try:
                        handle_message(update["message"])
                    except Exception:
                        logging.exception("Xabarni qayta ishlashda xato")

        except KeyboardInterrupt:
            logging.info("Bot to'xtatildi.")
            break

        except Exception:
            logging.exception("Asosiy siklda xato")
            time.sleep(3)


if __name__ == "__main__":
    init_db()
    main()
