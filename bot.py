
import os
import time
import sqlite3
import html
import requests
from datetime import datetime, timezone, timedelta

# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. FadeHost Environment sozlamalarini tekshiring.")

ADMIN_ID = 5607350126
CHANNEL = "@zakalgoritm"
API = f"https://api.telegram.org/bot{TOKEN}"

TZ = timezone(timedelta(hours=5))
DB_FILE = "zakovat.db"
DEFAULT_DURATION = 900
ALLOWED_DURATIONS = {60, 120, 180, 600, 900, 1800, 3600}

# ============================================================
# DATABASE
# ============================================================

db = sqlite3.connect(DB_FILE, check_same_thread=False)
db.row_factory = sqlite3.Row

db.executescript("""
CREATE TABLE IF NOT EXISTS members (
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    joined_at INTEGER
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    variants TEXT DEFAULT '',
    duration INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    start_time INTEGER,
    active INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    answer TEXT NOT NULL,
    correct INTEGER DEFAULT 0,
    points INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    UNIQUE(question_id, user_id)
);

CREATE TABLE IF NOT EXISTS scores (
    user_id INTEGER PRIMARY KEY,
    points INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS score_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    points INTEGER,
    reason TEXT,
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS prizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_key TEXT UNIQUE,
    winner_user_id INTEGER,
    prize TEXT DEFAULT '',
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
""")
db.commit()

# ============================================================
# TELEGRAM API
# ============================================================

def tg(method, data=None):
    try:
        response = requests.post(
            f"{API}/{method}",
            json=data or {},
            timeout=35
        )
        result = response.json()
        if not result.get("ok"):
            print("Telegram API:", result)
        return result
    except Exception as e:
        print("Telegram ERROR:", e)
        return {}


def send_message(chat_id, text, keyboard=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if keyboard:
        data["reply_markup"] = {"inline_keyboard": keyboard}
    return tg("sendMessage", data)


def edit_message(chat_id, message_id, text, keyboard=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if keyboard:
        data["reply_markup"] = {"inline_keyboard": keyboard}
    return tg("editMessageText", data)


def callback_answer(callback_id, text=""):
    tg("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text
    })


# ============================================================
# HELPERS
# ============================================================

def now():
    return int(time.time())


def clean(text):
    if not text:
        return ""
    return (
        text.lower().strip()
        .replace("’", "'")
        .replace("‘", "'")
        .replace("`", "'")
    )


def get_setting(key, default=None):
    row = db.execute(
        "SELECT value FROM settings WHERE key=?", (key,)
    ).fetchone()
    return row["value"] if row else default


def set_setting(key, value):
    db.execute("""
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, str(value)))
    db.commit()


def get_duration():
    try:
        value = int(get_setting("question_duration", DEFAULT_DURATION))
        return value if value in ALLOWED_DURATIONS else DEFAULT_DURATION
    except (TypeError, ValueError):
        return DEFAULT_DURATION


def format_duration(seconds):
    return f"{seconds // 60} daqiqa"


def safe_text(value):
    return html.escape(str(value or ""))


# ============================================================
# MEMBERS
# ============================================================

def save_member(user):
    db.execute("""
        INSERT INTO members(user_id, username, first_name, joined_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
    """, (
        user["id"],
        user.get("username", ""),
        user.get("first_name", ""),
        now()
    ))
    db.commit()


# ============================================================
# SCORES AND LEVELS
# ============================================================

def get_score(user_id):
    row = db.execute(
        "SELECT points FROM scores WHERE user_id=?", (user_id,)
    ).fetchone()
    return row["points"] if row else 0


def add_score(user_id, points, reason):
    new_score = get_score(user_id) + points

    db.execute("""
        INSERT INTO scores(user_id, points)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET points=excluded.points
    """, (user_id, new_score))

    db.execute("""
        INSERT INTO score_history(user_id, points, reason, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, points, reason, now()))

    db.commit()


def get_level(points):
    if points <= 10:
        return "🌱 Beginner"
    if points <= 30:
        return "📘 Bilimdon"
    if points <= 60:
        return "🧠 Zakovatchi"
    return "👑 Usta"


# Temporary states: cleared if the bot restarts.
states = {}


# ============================================================
# ADMIN PANEL
# ============================================================

def admin_keyboard():
    return [
        [
            {"text": "🧠 Savol qo‘shish", "callback_data": "admin_add"},
            {"text": "📋 Javoblar", "callback_data": "admin_answers"}
        ],
        [
            {"text": "🏆 Reyting", "callback_data": "admin_rating"},
            {"text": "👥 A’zolar", "callback_data": "admin_members"}
        ],
        [
            {"text": "📊 Statistika", "callback_data": "admin_stats"},
            {"text": "📚 Savollar tarixi", "callback_data": "admin_history"}
        ],
        [
            {"text": "➕ Ball boshqaruvi", "callback_data": "admin_points"},
            {"text": "📢 Xabar yuborish", "callback_data": "admin_broadcast"}
        ],
        [
            {"text": "⏱️ Savol vaqti", "callback_data": "admin_time"},
            {"text": "🎁 Haftalik g‘oliblar", "callback_data": "admin_winners"}
        ]
    ]


def show_admin(chat_id):
    if chat_id != ADMIN_ID:
        return
    send_message(
        chat_id,
        "<b>⚙️ ADMIN PANEL</b>\n\nKerakli bo‘limni tanlang:",
        admin_keyboard()
    )


# ============================================================
# QUESTION CREATION
# ============================================================

def start_question(chat_id):
    if chat_id != ADMIN_ID:
        return

    states[chat_id] = {
        "state": "question",
        "duration": get_duration()
    }
    send_message(chat_id, "<b>🧠 Yangi savol</b>\n\nSavol matnini yuboring.")


def process_question(chat_id, text):
    state = states.get(chat_id)
    if not state:
        return False

    if state["state"] == "question":
        state["question"] = text
        state["state"] = "answer"
        send_message(chat_id, "✅ Endi <b>to‘g‘ri javobni</b> yuboring.")
        return True

    if state["state"] == "answer":
        state["answer"] = text
        state["state"] = "variants"
        send_message(
            chat_id,
            "🔤 Qabul qilinadigan javob variantlarini vergul bilan yozing.\n\n"
            "Masalan: <code>Toshkent,tashkent,Тошкент</code>\n\n"
            "Variant kerak bo‘lmasa <code>-</code> yuboring."
        )
        return True

    if state["state"] == "variants":
        variants = "" if text.strip() == "-" else text
        state["variants"] = variants
        state["state"] = "preview"

        send_message(
            chat_id,
            "<b>📋 SAVOL PREVYU</b>\n\n"
            f"🧠 {safe_text(state['question'])}\n\n"
            f"✅ Javob: {safe_text(state['answer'])}\n"
            f"🔤 Variantlar: {safe_text(variants or 'yo‘q')}\n"
            f"⏱️ Vaqt: {format_duration(state['duration'])}",
            [[
                {"text": "📢 Tasdiqlash", "callback_data": "question_publish"},
                {"text": "❌ Bekor qilish", "callback_data": "question_cancel"}
            ]]
        )
        return True

    return False


def publish_question(chat_id):
    state = states.get(chat_id)
    if chat_id != ADMIN_ID or not state or state.get("state") != "preview":
        return

    start = now()
    cur = db.execute("""
        INSERT INTO questions
        (question, correct_answer, variants, duration, created_at, start_time, active)
        VALUES (?, ?, ?, ?, ?, ?, 1)
    """, (
        state["question"],
        state["answer"],
        state["variants"],
        state["duration"],
        start,
        start
    ))
    db.commit()
    question_id = cur.lastrowid

    keyboard = [[{
        "text": "📝 Javob berish",
        "callback_data": f"answer:{question_id}"
    }]]

    text = (
        "<b>🧠 ZAKOVAT SAVOLI</b>\n\n"
        f"{safe_text(state['question'])}\n\n"
        f"⏱️ Vaqt: {format_duration(state['duration'])}\n\n"
        "👇 Javob berish uchun tugmani bosing."
    )

    result = send_message(CHANNEL, text, keyboard)
    if result.get("ok"):
        send_message(chat_id, "✅ Savol kanalga muvaffaqiyatli yuborildi!")
        states.pop(chat_id, None)
    else:
        db.execute("UPDATE questions SET active=0 WHERE id=?", (question_id,))
        db.commit()
        send_message(
            chat_id,
            "❌ Kanalga yuborishda xatolik yuz berdi.\n\n"
            "Bot kanalga admin ekanini va post yozish huquqini tekshiring."
        )


# ============================================================
# ANSWER CHECKING
# ============================================================

def is_correct(user_answer, correct_answer, variants):
    possible = [correct_answer]
    if variants:
        possible += [x.strip() for x in variants.split(",") if x.strip()]
    user_answer = clean(user_answer)
    return any(clean(answer) == user_answer for answer in possible)


def request_answer(user_id, question_id):
    states[user_id] = {
        "state": "answering",
        "question_id": question_id
    }
    send_message(user_id, "📝 Javobingizni yozing:")


def process_user_answer(message):
    user = message["from"]
    user_id = user["id"]
    state = states.get(user_id)

    if not state or state.get("state") != "answering":
        return False

    question_id = state["question_id"]
    text = message.get("text", "").strip()

    q = db.execute(
        "SELECT * FROM questions WHERE id=?", (question_id,)
    ).fetchone()

    if not q:
        send_message(user_id, "❌ Savol topilmadi.")
        states.pop(user_id, None)
        return True

    if not q["active"]:
        send_message(user_id, "⏰ Bu savol yopilgan.")
        states.pop(user_id, None)
        return True

    if now() >= q["start_time"] + q["duration"]:
        db.execute("UPDATE questions SET active=0 WHERE id=?", (question_id,))
        db.commit()
        send_message(user_id, "⏰ Savol vaqti tugagan.")
        states.pop(user_id, None)
        return True

    existing = db.execute("""
        SELECT id FROM answers WHERE question_id=? AND user_id=?
    """, (question_id, user_id)).fetchone()

    if existing:
        send_message(user_id, "⚠️ Siz bu savolga allaqachon javob bergansiz.")
        states.pop(user_id, None)
        return True

    correct = is_correct(text, q["correct_answer"], q["variants"])
    points = 1 if correct else 0

    db.execute("""
        INSERT INTO answers
        (question_id, user_id, username, first_name, answer, correct, points, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        question_id,
        user_id,
        user.get("username", ""),
        user.get("first_name", ""),
        text,
        int(correct),
        points,
        now()
    ))
    db.commit()

    if correct:
        add_score(user_id, 1, f"Savol #{question_id}")
        send_message(user_id, "✅ <b>To‘g‘ri javob!</b>\n\n🏆 +1 ball")
    else:
        send_message(user_id, "❌ <b>Noto‘g‘ri javob.</b>\n\nKeyingi savolda omad!")

    username = user.get("username", "")
    name = user.get("first_name", "Noma’lum")

    send_message(
        ADMIN_ID,
        "<b>📩 Yangi javob!</b>\n\n"
        f"👤 {safe_text(name)}\n"
        f"🔗 {safe_text('@' + username if username else 'username yo‘q')}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"📝 {safe_text(text)}\n"
        f"{'✅ To‘g‘ri' if correct else '❌ Noto‘g‘ri'}\n"
        f"🏆 Ball: {points}"
    )

    states.pop(user_id, None)
    return True


# ============================================================
# PROFILE
# ============================================================

def show_profile(chat_id, user_id):
    member = db.execute(
        "SELECT * FROM members WHERE user_id=?", (user_id,)
    ).fetchone()

    score = get_score(user_id)

    row = db.execute("""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS correct
        FROM answers WHERE user_id=?
    """, (user_id,)).fetchone()

    total = row["total"] or 0
    correct = row["correct"] or 0

    rank = db.execute(
        "SELECT COUNT(*) + 1 AS rank FROM scores WHERE points > ?",
        (score,)
    ).fetchone()["rank"]

    name = member["first_name"] if member else "Foydalanuvchi"

    send_message(
        chat_id,
        "<b>👤 PROFIL</b>\n\n"
        f"👤 {safe_text(name)}\n"
        f"🏆 Ball: <b>{score}</b>\n"
        f"🥇 O‘rin: <b>{rank}</b>\n"
        f"📝 Javoblar: {total}\n"
        f"✅ To‘g‘ri: {correct}\n"
        f"🎖️ Daraja: {get_level(score)}"
    )


# ============================================================
# RATING: ADMIN ONLY
# ============================================================

def show_rating(chat_id):
    if chat_id != ADMIN_ID:
        send_message(chat_id, "🔒 Reyting faqat admin uchun ochiq.")
        return

    rows = db.execute("""
        SELECT s.user_id, s.points, m.first_name, m.username
        FROM scores s
        LEFT JOIN members m ON m.user_id=s.user_id
        ORDER BY s.points DESC
        LIMIT 50
    """).fetchall()

    if not rows:
        send_message(chat_id, "🏆 Hozircha reyting bo‘sh.")
        return

    text = "<b>🏆 ZAKOVAT REYTINGI</b>\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for i, row in enumerate(rows, 1):
        name = row["first_name"] or row["username"] or "Noma’lum"
        text += (
            f"{medals.get(i, str(i) + '.')}"
            f" {safe_text(name)} — <b>{row['points']}</b> ball\n"
        )

    send_message(chat_id, text)


# ============================================================
# ADMIN ANSWERS AND MANUAL POINTS
# ============================================================

def show_answers(chat_id):
    if chat_id != ADMIN_ID:
        return

    rows = db.execute("""
        SELECT * FROM answers ORDER BY id DESC LIMIT 30
    """).fetchall()

    if not rows:
        send_message(chat_id, "📋 Hozircha javoblar yo‘q.")
        return

    text = "<b>📋 SO‘NGGI JAVOBLAR</b>\n\n"
    keyboard = []

    for row in rows:
        name = row["first_name"] or row["username"] or str(row["user_id"])
        status = "✅" if row["correct"] else "❌"
        text += (
            f"{status} <b>{safe_text(name)}</b>\n"
            f"📝 {safe_text(row['answer'])}\n"
            f"🏆 {row['points']} ball\n\n"
        )
        keyboard.append([
            {"text": f"✅ +1 #{row['id']}", "callback_data": f"correct:{row['id']}"},
            {"text": f"➕ #{row['id']}", "callback_data": f"plus:{row['id']}"},
            {"text": f"➖ #{row['id']}", "callback_data": f"minus:{row['id']}"}
        ])

    send_message(chat_id, text, keyboard)


def manual_correct(answer_id):
    row = db.execute("SELECT * FROM answers WHERE id=?", (answer_id,)).fetchone()
    if not row:
        return "Javob topilmadi."
    if row["points"] >= 1:
        return "Bu javob uchun ball allaqachon berilgan."

    db.execute("UPDATE answers SET correct=1, points=1 WHERE id=?", (answer_id,))
    db.commit()
    add_score(row["user_id"], 1, f"Admin tasdiqladi #{answer_id}")
    return "✅ +1 ball berildi."


def manual_plus(answer_id):
    row = db.execute("SELECT * FROM answers WHERE id=?", (answer_id,)).fetchone()
    if not row:
        return "Javob topilmadi."

    db.execute("UPDATE answers SET points=points+1 WHERE id=?", (answer_id,))
    db.commit()
    add_score(row["user_id"], 1, f"Admin +1 #{answer_id}")
    return "➕ +1 ball berildi."


def manual_minus(answer_id):
    row = db.execute("SELECT * FROM answers WHERE id=?", (answer_id,)).fetchone()
    if not row:
        return "Javob topilmadi."
    if row["points"] <= 0:
        return "Bu javobda kamaytirish uchun ball yo‘q."

    db.execute("UPDATE answers SET points=points-1 WHERE id=?", (answer_id,))
    db.commit()
    add_score(row["user_id"], -1, f"Admin -1 #{answer_id}")
    return "➖ 1 ball olib tashlandi."


# ============================================================
# MEMBERS AND STATISTICS
# ============================================================

def show_members(chat_id):
    if chat_id != ADMIN_ID:
        return

    total = db.execute("SELECT COUNT(*) AS c FROM members").fetchone()["c"]
    rows = db.execute("""
        SELECT first_name, username, user_id
        FROM members ORDER BY joined_at DESC LIMIT 30
    """).fetchall()

    text = f"<b>👥 A’ZOLAR</b>\n\nJami: <b>{total}</b>\n\n"
    for row in rows:
        name = row["first_name"] or row["username"] or "Noma’lum"
        text += f"• {safe_text(name)} <code>{row['user_id']}</code>\n"

    send_message(chat_id, text)


def show_stats(chat_id):
    if chat_id != ADMIN_ID:
        return

    members = db.execute("SELECT COUNT(*) AS c FROM members").fetchone()["c"]
    questions = db.execute("SELECT COUNT(*) AS c FROM questions").fetchone()["c"]
    answers = db.execute("SELECT COUNT(*) AS c FROM answers").fetchone()["c"]
    correct = db.execute(
        "SELECT COUNT(*) AS c FROM answers WHERE correct=1"
    ).fetchone()["c"]
    active = db.execute(
        "SELECT COUNT(*) AS c FROM questions WHERE active=1"
    ).fetchone()["c"]

    send_message(
        chat_id,
        "<b>📊 STATISTIKA</b>\n\n"
        f"👥 A’zolar: {members}\n"
        f"🧠 Savollar: {questions}\n"
        f"📝 Javoblar: {answers}\n"
        f"✅ To‘g‘ri: {correct}\n"
        f"❌ Noto‘g‘ri: {answers - correct}\n"
        f"🟢 Faol savollar: {active}"
    )


def show_history(chat_id):
    if chat_id != ADMIN_ID:
        return

    rows = db.execute("""
        SELECT id, question, duration, created_at, active
        FROM questions ORDER BY id DESC LIMIT 20
    """).fetchall()

    if not rows:
        send_message(chat_id, "📚 Savollar tarixi bo‘sh.")
        return

    text = "<b>📚 SAVOLLAR TARIXI</b>\n\n"
    for row in rows:
        status = "🟢" if row["active"] else "🔴"
        text += (
            f"{status} <b>#{row['id']}</b>\n"
            f"{safe_text(row['question'][:120])}\n"
            f"⏱️ {format_duration(row['duration'])}\n\n"
        )
    send_message(chat_id, text)


# ============================================================
# QUESTION DURATION MENU
# ============================================================

def show_time_menu(chat_id):
    if chat_id != ADMIN_ID:
        return

    current = get_duration()
    keyboard = [
        [
            {"text": "1 daqiqa", "callback_data": "time:60"},
            {"text": "2 daqiqa", "callback_data": "time:120"}
        ],
        [
            {"text": "3 daqiqa", "callback_data": "time:180"},
            {"text": "10 daqiqa", "callback_data": "time:600"}
        ],
        [
            {"text": "15 daqiqa", "callback_data": "time:900"},
            {"text": "30 daqiqa", "callback_data": "time:1800"}
        ],
        [{"text": "60 daqiqa", "callback_data": "time:3600"}]
    ]

    send_message(
        chat_id,
        "<b>⏱️ SAVOL VAQTI</b>\n\n"
        f"Joriy vaqt: <b>{format_duration(current)}</b>\n\n"
        "Yangi vaqtni tanlang:",
        keyboard
    )


# ============================================================
# BROADCAST
# ============================================================

def start_broadcast(chat_id):
    if chat_id != ADMIN_ID:
        return

    states[chat_id] = {"state": "broadcast"}
    send_message(
        chat_id,
        "📢 Barcha a’zolarga yuboriladigan xabarni yozing.\n\n"
        "Bekor qilish uchun /bekor yuboring."
    )


def do_broadcast(chat_id, text):
    if chat_id != ADMIN_ID:
        return

    rows = db.execute("SELECT user_id FROM members").fetchall()
    success = 0
    failed = 0

    for row in rows:
        result = send_message(row["user_id"], safe_text(text))
        if result.get("ok"):
            success += 1
        else:
            failed += 1
        time.sleep(0.08)

    send_message(
        chat_id,
        "<b>📢 XABAR YUBORILDI</b>\n\n"
        f"✅ Yetib bordi: {success}\n"
        f"❌ Yetib bormadi: {failed}"
    )


# ============================================================
# WEEKLY TOP: SCORE HISTORY FOR CURRENT WEEK
# ============================================================

def week_start_timestamp():
    dt = datetime.now(TZ)
    monday = (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(monday.timestamp())


def weekly_top():
    start = week_start_timestamp()

    return db.execute("""
        SELECT
            h.user_id,
            SUM(h.points) AS points,
            m.first_name,
            m.username
        FROM score_history h
        LEFT JOIN members m ON m.user_id=h.user_id
        WHERE h.created_at >= ?
        GROUP BY h.user_id
        ORDER BY points DESC
        LIMIT 3
    """, (start,)).fetchall()


# ============================================================
# CALLBACK HANDLER
# ============================================================

def handle_callback(query):
    user = query["from"]
    user_id = user["id"]
    data = query.get("data", "")
    message = query.get("message", {})
    chat_id = message.get("chat", {}).get("id", user_id)

    save_member(user)

    # Contact button: user asks to contact admin.
    if data == "contact_admin":
        states[user_id] = {"state": "contact_message"}
        send_message(
            user_id,
            "📩 Adminga yubormoqchi bo‘lgan xabaringizni yozing.\n\n"
            "Bekor qilish uchun /bekor yuboring."
        )
        callback_answer(query["id"])
        return

    # Reply to a user's contact message.
    if data.startswith("contact_reply:"):
        if user_id != ADMIN_ID:
            callback_answer(query["id"], "Bu amal faqat admin uchun.")
            return

        try:
            target_id = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            callback_answer(query["id"], "Foydalanuvchi ID xato.")
            return

        states[ADMIN_ID] = {
            "state": "contact_reply",
            "target_id": target_id
        }
        send_message(
            ADMIN_ID,
            "✍️ Foydalanuvchiga yuboriladigan javobni yozing.\n\n"
            "Bekor qilish uchun /bekor yuboring."
        )
        callback_answer(query["id"])
        return

    # All admin callbacks must be restricted.
    admin_callbacks = {
        "admin_add", "admin_answers", "admin_rating",
        "admin_members", "admin_stats", "admin_history",
        "admin_points", "admin_broadcast", "admin_time",
        "admin_winners", "question_publish", "question_cancel"
    }

    if data in admin_callbacks or data.startswith(
        ("correct:", "plus:", "minus:", "time:")
    ):
        if user_id != ADMIN_ID:
            callback_answer(query["id"], "❌ Bu amal faqat admin uchun.")
            return

    if data == "admin_add":
        start_question(chat_id)
        callback_answer(query["id"])
        return

    if data == "admin_answers":
        show_answers(chat_id)
        callback_answer(query["id"])
        return

    if data == "admin_rating":
        show_rating(chat_id)
        callback_answer(query["id"])
        return

    if data == "admin_members":
        show_members(chat_id)
        callback_answer(query["id"])
        return

    if data == "admin_stats":
        show_stats(chat_id)
        callback_answer(query["id"])
        return

    if data == "admin_history":
        show_history(chat_id)
        callback_answer(query["id"])
        return

    if data == "admin_points":
        send_message(
            chat_id,
            "➕/➖ Ball boshqaruvi\n\n"
            "📋 Javoblar bo‘limidan kerakli javob yonidagi "
            "tugmalar orqali ball bering yoki olib tashlang."
        )
        callback_answer(query["id"])
        return

    if data == "admin_broadcast":
        start_broadcast(chat_id)
        callback_answer(query["id"])
        return

    if data == "admin_time":
        show_time_menu(chat_id)
        callback_answer(query["id"])
        return

    if data == "admin_winners":
        rows = weekly_top()
        if not rows:
            send_message(chat_id, "🎁 Bu hafta uchun g‘oliblar hozircha yo‘q.")
        else:
            text = "<b>🎁 HAFTALIK TOP-3</b>\n\n"
            for i, row in enumerate(rows, 1):
                name = row["first_name"] or row["username"] or "Noma’lum"
                text += f"{i}. {safe_text(name)} — <b>{row['points']}</b> ball\n"
            send_message(chat_id, text)
        callback_answer(query["id"])
        return

    if data.startswith("time:"):
        try:
            seconds = int(data.split(":", 1)[1])
        except ValueError:
            callback_answer(query["id"], "Vaqt qiymati xato.")
            return

        if seconds not in ALLOWED_DURATIONS:
            callback_answer(query["id"], "Bu vaqt varianti mavjud emas.")
            return

        set_setting("question_duration", seconds)
        send_message(
            chat_id,
            f"✅ Keyingi savollar uchun vaqt "
            f"<b>{format_duration(seconds)}</b> qilib o‘rnatildi."
        )
        callback_answer(query["id"], "Vaqt saqlandi.")
        return

    if data == "question_publish":
        publish_question(chat_id)
        callback_answer(query["id"], "Bajarildi.")
        return

    if data == "question_cancel":
        states.pop(ADMIN_ID, None)
        send_message(chat_id, "❌ Savol bekor qilindi.")
        callback_answer(query["id"], "Bekor qilindi.")
        return

    if data.startswith("answer:"):
        try:
            question_id = int(data.split(":", 1)[1])
        except ValueError:
            callback_answer(query["id"], "Savol ID xato.")
            return

        q = db.execute(
            "SELECT * FROM questions WHERE id=?", (question_id,)
        ).fetchone()

        if not q:
            callback_answer(query["id"], "❌ Savol topilmadi.")
            return

        if not q["active"]:
            callback_answer(query["id"], "⏰ Savol yopilgan.")
            return

        if now() >= q["start_time"] + q["duration"]:
            db.execute("UPDATE questions SET active=0 WHERE id=?", (question_id,))
            db.commit()
            callback_answer(query["id"], "⏰ Vaqt tugagan.")
            return

        request_answer(user_id, question_id)
        callback_answer(query["id"])
        return

    # These buttons change scores, so admin permission is required.
    if data.startswith("correct:"):
        result = manual_correct(int(data.split(":", 1)[1]))
        send_message(chat_id, result)
        callback_answer(query["id"])
        return

    if data.startswith("plus:"):
        result = manual_plus(int(data.split(":", 1)[1]))
        send_message(chat_id, result)
        callback_answer(query["id"])
        return

    if data.startswith("minus:"):
        result = manual_minus(int(data.split(":", 1)[1]))
        send_message(chat_id, result)
        callback_answer(query["id"])
        return


# ============================================================
# MESSAGE HANDLER
# ============================================================

def handle_message(message):
    user = message["from"]
    user_id = user["id"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    save_member(user)

    # Handle contact message first.
    state = states.get(user_id)

    if state and state.get("state") == "contact_message":
        if text == "/bekor":
            states.pop(user_id, None)
            send_message(chat_id, "❌ Murojaat bekor qilindi.")
            return

        if not text:
            send_message(chat_id, "Iltimos, matnli xabar yuboring.")
            return

        name = safe_text(user.get("first_name", "Foydalanuvchi"))
        username = user.get("username", "")
        safe_username = safe_text("@" + username) if username else "username yo‘q"

        result = send_message(
            ADMIN_ID,
            "<b>📩 YANGI MUROJAAT</b>\n\n"
            f"👤 {name}\n"
            f"🔗 {safe_username}\n"
            f"🆔 <code>{user_id}</code>\n\n"
            f"💬 {safe_text(text)}",
            [[{
                "text": "↩️ Javob berish",
                "callback_data": f"contact_reply:{user_id}"
            }]]
        )

        if result.get("ok"):
            send_message(chat_id, "✅ Murojaatingiz adminga yuborildi.")
        else:
            send_message(chat_id, "❌ Xabar yuborilmadi. Keyinroq urinib ko‘ring.")

        states.pop(user_id, None)
        return

    # Handle admin's reply to a contact message.
    if user_id == ADMIN_ID and state and state.get("state") == "contact_reply":
        if text == "/bekor":
            states.pop(ADMIN_ID, None)
            send_message(chat_id, "❌ Javob yuborish bekor qilindi.")
            return

        if not text:
            send_message(chat_id, "Iltimos, javob matnini yozing.")
            return

        target_id = state["target_id"]
        result = send_message(
            target_id,
            "📩 <b>Admin javobi:</b>\n\n" + safe_text(text)
        )

        if result.get("ok"):
            send_message(chat_id, "✅ Javob foydalanuvchiga yuborildi.")
        else:
            send_message(
                chat_id,
                "❌ Javob yuborilmadi. Foydalanuvchi botni /start orqali ishga tushirganini tekshiring."
            )

        states.pop(ADMIN_ID, None)
        return

    # Cancel pending user answer.
    if text == "/bekor":
        if user_id in states:
            states.pop(user_id, None)
            send_message(chat_id, "❌ Amal bekor qilindi.")
        return

    # Answer flow.
    if process_user_answer(message):
        return

    # Start command.
    if text == "/start":
        send_message(
            chat_id,
            "<b>👋 Assalomu alaykum!</b>\n\n"
            "🧠 <b>Algoritm Zakovat</b> botiga xush kelibsiz!\n\n"
            "Savollarda qatnashing va bilimingizni sinang.\n"
            "🏆 To‘g‘ri javoblar uchun ball to‘plang.\n\n"
            "👤 /profil — profilingiz\n"
            "🔒 Reyting faqat admin uchun ochiq.\n\n"
            "📩 Savol yoki taklif bo‘lsa, adminga yozing.",
            [[{
                "text": "📩 Adminga murojaat",
                "callback_data": "contact_admin"
            }]]
        )
        return

    if text == "/profil":
        show_profile(chat_id, user_id)
        return

    if text == "/reyting":
        if user_id == ADMIN_ID:
            show_rating(chat_id)
        else:
            send_message(chat_id, "🔒 Reyting faqat admin uchun ochiq.")
        return

    if text == "/admin":
        if user_id == ADMIN_ID:
            show_admin(chat_id)
        else:
            send_message(chat_id, "❌ Siz admin emassiz.")
        return

    # All commands below are admin-only.
    if user_id == ADMIN_ID:
        if text == "/javoblar":
            show_answers(chat_id)
            return

        if text == "/a'zolar":
            show_members(chat_id)
            return

        if text == "/statistika":
            show_stats(chat_id)
            return

        if text == "/tarix":
            show_history(chat_id)
            return

        if text == "/vaqt":
            show_time_menu(chat_id)
            return

        state = states.get(ADMIN_ID)

        if state and state.get("state") == "broadcast":
            do_broadcast(chat_id, text)
            states.pop(ADMIN_ID, None)
            return

        if state and state.get("state") in ("question", "answer", "variants"):
            process_question(chat_id, text)
            return


# ============================================================
# CLOSE EXPIRED QUESTIONS
# ============================================================

def check_expired_questions():
    rows = db.execute("""
        SELECT id, start_time, duration
        FROM questions WHERE active=1
    """).fetchall()

    for row in rows:
        if now() >= row["start_time"] + row["duration"]:
            db.execute(
                "UPDATE questions SET active=0 WHERE id=?",
                (row["id"],)
            )
            db.commit()
            send_message(
                ADMIN_ID,
                f"⏰ <b>#{row['id']}</b>-savol vaqti tugadi."
            )


# ============================================================
# MAIN LOOP
# ============================================================

def main():
    print("🤖 ALGORITM ZAKOVAT BOT ISHGA TUSHDI")

    tg("deleteWebhook", {"drop_pending_updates": True})

    offset = 0
    last_check = 0

    while True:
        try:
            result = tg(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": ["message", "callback_query"]
                }
            )

            if not result.get("ok"):
                time.sleep(5)
                continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1

                try:
                    if "message" in update:
                        handle_message(update["message"])
                    elif "callback_query" in update:
                        handle_callback(update["callback_query"])
                except Exception as e:
                    print("UPDATE ERROR:", e)

            if now() - last_check >= 20:
                check_expired_questions()
                last_check = now()

        except Exception as e:
            print("MAIN LOOP ERROR:", e)
            time.sleep(5)


if __name__ == "__main__":
    main()
