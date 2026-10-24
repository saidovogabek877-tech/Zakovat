
import os
import time
import sqlite3
import logging
import requests
from datetime import datetime

# ==================== SOZLAMALAR ====================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = 5607350126
DB_PATH = "zakovat.db"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s"
)

session = requests.Session()
broadcast_state = {}

# ==================== TELEGRAM API ====================

def tg(method, data=None, files=None, timeout=40):
    if not BOT_TOKEN:
        logging.error("BOT_TOKEN sozlanmagan!")
        return None

    try:
        response = session.post(
            f"{API_URL}/{method}",
            data=data or {},
            files=files,
            timeout=timeout
        )
        result = response.json()

        if not result.get("ok"):
            logging.error(
                "Telegram API xatosi (%s): %s",
                method, result.get("description")
            )
            return None

        return result.get("result")

    except Exception:
        logging.exception("Telegram API bilan ulanishda xato")
        return None


def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        import json
        data["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)
    return tg("sendMessage", data)


def answer_callback(callback_id, text=""):
    return tg("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text
    })


def keyboard(rows):
    return {
        "keyboard": rows,
        "resize_keyboard": True
    }


def inline_keyboard(rows):
    return {"inline_keyboard": rows}


# ==================== MA'LUMOTLAR BAZASI ====================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            course TEXT DEFAULT '',
            group_name TEXT DEFAULT '',
            state TEXT DEFAULT 'ready',
            registered_at TEXT DEFAULT '',
            blocked INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS message_map (
            admin_message_id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at TEXT,
            sent_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0
        )
    """)

    # Eski bazada yetishmayotgan ustunlarni qo'shish.
    cur.execute("PRAGMA table_info(users)")
    columns = {row["name"] for row in cur.fetchall()}

    migrations = {
        "first_name": "TEXT DEFAULT ''",
        "last_name": "TEXT DEFAULT ''",
        "course": "TEXT DEFAULT ''",
        "group_name": "TEXT DEFAULT ''",
        "state": "TEXT DEFAULT 'ready'",
        "registered_at": "TEXT DEFAULT ''",
        "blocked": "INTEGER DEFAULT 0"
    }

    for column, definition in migrations.items():
        if column not in columns:
            cur.execute(
                f"ALTER TABLE users ADD COLUMN {column} {definition}"
            )

    conn.commit()
    conn.close()
    logging.info("Ma'lumotlar bazasi tayyor.")


def get_user(user_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row


def save_user(user_id, **fields):
    allowed = {
        "first_name", "last_name", "course",
        "group_name", "state", "registered_at", "blocked"
    }

    fields = {
        key: value for key, value in fields.items()
        if key in allowed
    }

    if not fields:
        return

    conn = db()
    exists = conn.execute(
        "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()

    if exists:
        assignments = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [user_id]
        conn.execute(
            f"UPDATE users SET {assignments} WHERE user_id = ?", values
        )
    else:
        fields["user_id"] = user_id
        columns = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        conn.execute(
            f"INSERT INTO users ({columns}) VALUES ({placeholders})",
            list(fields.values())
        )

    conn.commit()
    conn.close()


def set_state(user_id, state):
    save_user(user_id, state=state)


def all_users():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM users ORDER BY registered_at DESC"
    ).fetchall()
    conn.close()
    return rows


# ==================== TUGMALAR ====================

def user_menu():
    return keyboard([
        ["✏️ Ma'lumotlarim", "ℹ️ Yordam"],
        ["📩 Adminga murojaat"]
    ])


def admin_menu():
    return keyboard([
        ["📊 Statistika", "👥 A'zolar"],
        ["📢 Xabar yuborish", "📩 Murojaatlar"],
        ["✏️ Ma'lumotlarim", "ℹ️ Yordam"]
    ])


# ==================== RO'YXATDAN O'TISH ====================

def start_user(user_id):
    user = get_user(user_id)

    if user is None:
        save_user(
            user_id,
            first_name="",
            last_name="",
            course="",
            group_name="",
            state="first_name",
            registered_at=datetime.now().isoformat(timespec="seconds"),
            blocked=0
        )
        send_message(
            user_id,
            "Assalomu alaykum! 👋\n\n"
            "Botdan foydalanish uchun ro'yxatdan o'ting.\n"
            "Ismingizni kiriting:"
        )
        return

    if not user["first_name"]:
        set_state(user_id, "first_name")
        send_message(user_id, "Ismingizni kiriting:")
        return

    if not user["last_name"]:
        set_state(user_id, "last_name")
        send_message(user_id, "Familiyangizni kiriting:")
        return

    if not user["course"]:
        set_state(user_id, "course")
        send_message(user_id, "Kursingizni kiriting:")
        return

    if not user["group_name"]:
        set_state(user_id, "group_name")
        send_message(user_id, "Guruhingizni kiriting:")
        return

    set_state(user_id, "ready")
    send_message(
        user_id,
        "Xush kelibsiz! ✅\n\n"
        "Ro'yxatdan o'tgansiz. Xabaringizni yuborishingiz "
        "yoki quyidagi tugmalardan foydalanishingiz mumkin.",
        admin_menu() if user_id == ADMIN_ID else user_menu()
    )


def registration_step(user_id, text):
    user = get_user(user_id)

    if user is None:
        start_user(user_id)
        return True

    state = user["state"] or "ready"

    if state == "first_name":
        save_user(user_id, first_name=text, state="last_name")
        send_message(user_id, "Familiyangizni kiriting:")
        return True

    if state == "last_name":
        save_user(user_id, last_name=text, state="course")
        send_message(user_id, "Kursingizni kiriting (masalan, 1-kurs):")
        return True

    if state == "course":
        save_user(user_id, course=text, state="group_name")
        send_message(user_id, "Guruhingizni kiriting:")
        return True

    if state == "group_name":
        save_user(user_id, group_name=text, state="ready")
        send_message(
            user_id,
            "Ro'yxatdan o'tish muvaffaqiyatli yakunlandi! ✅",
            admin_menu() if user_id == ADMIN_ID else user_menu()
        )
        send_message(
            ADMIN_ID,
            "🆕 Yangi foydalanuvchi ro'yxatdan o'tdi.\n\n"
            + user_info(user_id)
        )
        return True

    return False


def user_info(user_id):
    user = get_user(user_id)
    if not user:
        return f"ID: {user_id}\nMa'lumot topilmadi."

    return (
        f"👤 Ism: {user['first_name']}\n"
        f"👤 Familiya: {user['last_name']}\n"
        f"🎓 Kurs: {user['course']}\n"
        f"👥 Guruh: {user['group_name']}\n"
        f"🆔 Telegram ID: {user_id}"
    )


def edit_profile(user_id):
    save_user(user_id, state="first_name")
    send_message(user_id, "Yangi ismingizni kiriting:")


# ==================== ADMIN FUNKSIYALARI ====================

def show_stats():
    conn = db()
    total = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM users WHERE blocked = 0"
    ).fetchone()[0]
    blocked = conn.execute(
        "SELECT COUNT(*) FROM users WHERE blocked = 1"
    ).fetchone()[0]
    conn.close()

    send_message(
        ADMIN_ID,
        f"📊 STATISTIKA\n\n"
        f"👥 Jami ro'yxatdan o'tganlar: {total}\n"
        f"✅ Faol hisoblar: {active}\n"
        f"🚫 Bloklanganlar: {blocked}"
    )


def show_users():
    users = all_users()
    if not users:
        send_message(ADMIN_ID, "Hozircha foydalanuvchilar yo'q.")
        return

    send_message(ADMIN_ID, f"👥 Jami foydalanuvchilar: {len(users)}")

    # Telegram xabar uzunligi cheklangan; ro'yxat bo'lib yuboriladi.
    chunk = ""
    for user in users:
        item = (
            f"\n• {user['first_name']} {user['last_name']}\n"
            f"  Kurs: {user['course']} | Guruh: {user['group_name']}\n"
            f"  ID: {user['user_id']}\n"
        )
        if len(chunk) + len(item) > 3500:
            send_message(ADMIN_ID, chunk)
            chunk = ""
        chunk += item

    if chunk:
        send_message(ADMIN_ID, chunk)


def save_reply_mapping(admin_message_id, user_id):
    conn = db()
    conn.execute(
        "INSERT OR REPLACE INTO message_map (admin_message_id, user_id) "
        "VALUES (?, ?)",
        (admin_message_id, user_id)
    )
    conn.commit()
    conn.close()


def find_reply_user(admin_message_id):
    conn = db()
    row = conn.execute(
        "SELECT user_id FROM message_map WHERE admin_message_id = ?",
        (admin_message_id,)
    ).fetchone()
    conn.close()
    return row["user_id"] if row else None


def forward_user_message(message, user_id):
    # Foydalanuvchining xabarini admin chatiga nusxalaydi.
    result = tg("copyMessage", {
        "chat_id": ADMIN_ID,
        "from_chat_id": user_id,
        "message_id": message["message_id"]
    })

    if not result:
        send_message(
            user_id,
            "Xabaringizni yuborishda xatolik bo'ldi. "
            "Birozdan so'ng qayta urinib ko'ring."
        )
        return

    admin_message_id = result["message_id"]
    save_reply_mapping(admin_message_id, user_id)

    send_message(
        ADMIN_ID,
        "📩 Yangi murojaat\n\n"
        + user_info(user_id)
        + "\n\nJavob berish uchun yuqoridagi nusxalangan "
          "xabarga Reply orqali javob yozing."
    )

    send_message(user_id, "Xabaringiz adminga yetkazildi. ✅")


def reply_to_user(message, admin_user_id):
    replied = message.get("reply_to_message")
    if not replied:
        return False

    target_user = find_reply_user(replied["message_id"])
    if not target_user:
        return False

    if message.get("text"):
        result = send_message(target_user, "📩 Admin javobi:\n\n" + message["text"])
    else:
        # Matn bo'lmagan admin javobini nusxalash.
        result = tg("copyMessage", {
            "chat_id": target_user,
            "from_chat_id": admin_user_id,
            "message_id": message["message_id"]
        })

    if result:
        send_message(ADMIN_ID, "Javob foydalanuvchiga yuborildi. ✅")
    else:
        send_message(ADMIN_ID, "Javob yuborilmadi. Foydalanuvchi botni bloklagan bo'lishi mumkin.")

    return True


# ==================== XABAR TARQATISH ====================

def broadcast_preview(message):
    if message.get("text", "").startswith("/broadcast"):
        send_message(ADMIN_ID, "Tarqatish uchun /broadcast dan keyin matn yozing.")
        return

    broadcast_state[ADMIN_ID] = message["message_id"]

    send_message(
        ADMIN_ID,
        "📢 Quyidagi xabar tarqatishga tayyor.\n"
        "Yuborish yoki bekor qilishni tanlang.",
        inline_keyboard([
            [
                {"text": "✅ Yuborish", "callback_data": "broadcast_confirm"},
                {"text": "❌ Bekor qilish", "callback_data": "broadcast_cancel"}
            ]
        ])
    )


def do_broadcast():
    source_message_id = broadcast_state.get(ADMIN_ID)
    if not source_message_id:
        send_message(ADMIN_ID, "Tarqatiladigan xabar topilmadi.")
        return

    users = all_users()
    sent = 0
    failed = 0

    for user in users:
        uid = user["user_id"]
        if user["blocked"]:
            continue

        result = tg("copyMessage", {
            "chat_id": uid,
            "from_chat_id": ADMIN_ID,
            "message_id": source_message_id
        })

        if result:
            sent += 1
        else:
            failed += 1
            # Xatolik foydalanuvchi botni bloklagani sababli bo'lishi mumkin.
            # Keyinroq qayta urinib ko'rish uchun hisob o'chirilmaydi.

        time.sleep(0.05)

    conn = db()
    conn.execute(
        "INSERT INTO broadcast_log (sent_at, sent_count, failed_count) "
        "VALUES (?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), sent, failed)
    )
    conn.commit()
    conn.close()

    broadcast_state.pop(ADMIN_ID, None)
    send_message(
        ADMIN_ID,
        f"📢 Tarqatish yakunlandi.\n\n"
        f"✅ Yuborildi: {sent}\n"
        f"⚠️ Yuborilmadi: {failed}",
        admin_menu()
    )


# ==================== CALLBACKLAR ====================

def process_callback(callback):
    data = callback.get("data", "")
    callback_id = callback["id"]
    user_id = callback["from"]["id"]

    if user_id != ADMIN_ID:
        answer_callback(callback_id, "Bu amal faqat admin uchun.")
        return

    if data == "broadcast_confirm":
        answer_callback(callback_id, "Tarqatish boshlandi.")
        do_broadcast()
    elif data == "broadcast_cancel":
        broadcast_state.pop(ADMIN_ID, None)
        answer_callback(callback_id, "Bekor qilindi.")
        send_message(ADMIN_ID, "Tarqatish bekor qilindi.", admin_menu())
    else:
        answer_callback(callback_id)


# ==================== XABARLARNI QAYTA ISHLASH ====================

def process_message(message):
    # global funksiyaning boshida e'lon qilinadi.
    global broadcast_state

    chat = message.get("chat", {})
    user = message.get("from", {})
    user_id = user.get("id")
    chat_id = chat.get("id")

    if not user_id or chat.get("type") != "private":
        return

    text = message.get("text", "").strip()
    is_admin = user_id == ADMIN_ID

    logging.info(
        "Xabar keldi: user_id=%s admin=%s text=%r",
        user_id, is_admin, text[:100]
    )

    # Bot buyruqlari.
    if text == "/start":
        start_user(user_id)
        return

    if text == "/cancel":
        broadcast_state.pop(ADMIN_ID, None)
        set_state(user_id, "ready")
        send_message(
            chat_id,
            "Amal bekor qilindi.",
            admin_menu() if is_admin else user_menu()
        )
        return

    if text == "/help" or text == "ℹ️ Yordam":
        send_message(
            chat_id,
            "ℹ️ YORDAM\n\n"
            "• Ma'lumotlaringizni ro'yxatdan o'tkazing.\n"
            "• Adminga murojaat qilish uchun tugmani bosing.\n"
            "• Ma'lumotlarni tahrirlash mumkin.\n"
            "• Bekor qilish: /cancel",
            admin_menu() if is_admin else user_menu()
        )
        return

    # Admin xabariga Reply orqali javob bersa.
    if is_admin and message.get("reply_to_message"):
        if reply_to_user(message, user_id):
            return

    # Ro'yxatdan o'tish jarayoni.
    current_user = get_user(user_id)
    if current_user is None:
        start_user(user_id)
        return

    if current_user["state"] and current_user["state"] != "ready":
        if text:
            registration_step(user_id, text)
        else:
            send_message(chat_id, "Iltimos, matn ko'rinishida javob kiriting.")
        return

    # Admin buyruqlari.
    if is_admin:
        if text == "/admin":
            send_message(chat_id, "Admin panel:", admin_menu())
            return

        if text == "📊 Statistika" or text == "/stats":
            show_stats()
            return

        if text == "👥 A'zolar" or text == "/users":
            show_users()
            return

        if text == "✏️ Ma'lumotlarim":
            edit_profile(user_id)
            return

        if text == "📩 Murojaatlar":
            send_message(
                ADMIN_ID,
                "📩 Murojaatlar shu chatga keladi. Foydalanuvchiga javob berish "
                "uchun murojaatning nusxalangan xabariga Reply qiling."
            )
            return

        if text == "📢 Xabar yuborish" or text == "/broadcast":
            set_state(ADMIN_ID, "ready")
            broadcast_state.pop(ADMIN_ID, None)
            send_message(
                ADMIN_ID,
                "Tarqatmoqchi bo'lgan matn yoki media xabaringizni yuboring.\n"
                "Bekor qilish: /cancel"
            )
            broadcast_state[ADMIN_ID] = "waiting"
            return

        if broadcast_state.get(ADMIN_ID) == "waiting":
            # Xabar adminning o'zidan kelgani uchun nusxasi shu xabardan olinadi.
            broadcast_state[ADMIN_ID] = message["message_id"]
            send_message(
                ADMIN_ID,
                "📢 Xabarni barcha ro'yxatdan o'tgan foydalanuvchilarga yuboraymi?",
                inline_keyboard([
                    [
                        {"text": "✅ Yuborish", "callback_data": "broadcast_confirm"},
                        {"text": "❌ Bekor qilish", "callback_data": "broadcast_cancel"}
                    ]
                ])
            )
            return

        # Admin oddiy xabar yozsa, unga izoh beramiz.
        send_message(
            ADMIN_ID,
            "Admin paneldan foydalaning yoki foydalanuvchi xabariga "
            "Reply orqali javob bering.",
            admin_menu()
        )
        return

    # Foydalanuvchi menyusi.
    if text == "✏️ Ma'lumotlarim":
        edit_profile(user_id)
        return

    if text == "📩 Adminga murojaat":
        send_message(
            user_id,
            "Xabaringizni yozib yuboring. Adminga yetkazaman."
        )
        set_state(user_id, "contact_message")
        return

    if current_user["state"] == "contact_message":
        if text:
            set_state(user_id, "ready")
            forward_user_message(message, user_id)
        else:
            send_message(user_id, "Iltimos, murojaatingizni matn bilan yuboring.")
        return

    # Ro'yxatdan o'tgan foydalanuvchining oddiy xabari.
    forward_user_message(message, user_id)


# ==================== ASOSIY ISHGA TUSHIRISH ====================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN topilmadi. Hosting Variables/Secrets bo'limida "
            "BOT_TOKEN nomli o'zgaruvchi yarating."
        )

    init_db()

    me = tg("getMe")
    if not me:
        raise RuntimeError(
            "Bot tokeni ishlamayapti yoki Telegram API bilan ulanish bo'lmadi."
        )

    logging.info("Bot ishga tushdi: @%s", me.get("username"))

    # Webhook long polling bilan bir vaqtda ishlamasligi kerak.
    tg("deleteWebhook", {"drop_pending_updates": "false"})

    offset = 0

    while True:
        try:
            updates = tg("getUpdates", {
                "offset": offset,
                "timeout": 25,
                "allowed_updates": '["message","callback_query"]'
            }, timeout=35)

            if updates is None:
                time.sleep(3)
                continue

            for update in updates:
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
