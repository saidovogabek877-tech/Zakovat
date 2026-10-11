
import os
import time
import sqlite3
import html
import requests
from datetime import datetime, timezone, timedelta

# ============================================================
# SOZLAMALAR
# ============================================================

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 5607350126
CHANNEL = "@zakalgoritm"
DB_FILE = "zakovat.db"

TZ = timezone(timedelta(hours=5))
DEFAULT_DURATION = 900
ALLOWED_DURATIONS = {60, 120, 180, 600, 900, 1800, 3600}

if not TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. Hosting sozlamalarini tekshiring.")

API = f"https://api.telegram.org/bot{TOKEN}"
db = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30)
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA busy_timeout=30000")

# Foydalanuvchilarning vaqtinchalik holatlari
states = {}
BOT_USERNAME = ""


# ============================================================
# BAZA
# ============================================================

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
    active INTEGER DEFAULT 0,
    channel_message_id INTEGER
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

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
""")

# Eski baza bilan moslik
columns = {
    row["name"]
    for row in db.execute("PRAGMA table_info(questions)").fetchall()
}
if "channel_message_id" not in columns:
    db.execute("ALTER TABLE questions ADD COLUMN channel_message_id INTEGER")

db.commit()


# ============================================================
# TELEGRAM API
# ============================================================

def tg(method, data=None):
    try:
        response = requests.post(
            f"{API}/{method}",
            json=data or {},
            timeout=40
        )
        result = response.json()
        if not result.get("ok"):
            print(f"Telegram API xatosi ({method}):", result)
        return result
    except Exception as exc:
        print(f"Telegram ulanish xatosi ({method}):", exc)
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


def callback_answer(callback_id, text=""):
    tg("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text
    })


def safe(value):
    return html.escape(str(value or ""))


def now():
    return int(time.time())


def clean(value):
    value = str(value or "").lower().strip()
    return (
        value.replace("’", "'")
        .replace("‘", "'")
        .replace("ʻ", "'")
        .replace("`", "'")
        .replace("ʼ", "'")
        .replace("ё", "е")
        .replace("ў", "у")
        .replace("қ", "к")
    )


def format_duration(seconds):
    minutes = seconds // 60
    return f"{minutes} daqiqa"


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
    except (ValueError, TypeError):
        return DEFAULT_DURATION


# ============================================================
# A'ZOLAR
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
# BALLAR
# ============================================================

def get_score(user_id):
    row = db.execute(
        "SELECT points FROM scores WHERE user_id=?", (user_id,)
    ).fetchone()
    return row["points"] if row else 0


def add_score(user_id, points, reason):
    current = get_score(user_id)
    updated = current + points

    db.execute("""
        INSERT INTO scores(user_id, points)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET points=excluded.points
    """, (user_id, updated))

    db.execute("""
        INSERT INTO score_history(user_id, points, reason, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, points, reason, now()))
    db.commit()


def get_level(points):
    if points < 10:
        return "🌱 Boshlovchi"
    if points < 30:
        return "📘 Bilimdon"
    if points < 60:
        return "🧠 Zakovatchi"
    return "👑 Usta"


# ============================================================
# ADMIN PANEL
# ============================================================

def is_admin(user_id):
    return user_id == ADMIN_ID


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
            {"text": "🎁 Haftalik TOP-3", "callback_data": "admin_winners"}
        ]
    ]


def show_admin(chat_id):
    if not is_admin(chat_id):
        return
    send_message(
        chat_id,
        "<b>⚙️ ALGORITM ZAKOVAT — ADMIN PANEL</b>\n\n"
        "Kerakli bo‘limni tanlang.",
        admin_keyboard()
    )


# ============================================================
# SAVOL YARATISH
# ============================================================

def start_question(chat_id):
    if not is_admin(chat_id):
        return

    states[chat_id] = {
        "state": "question",
        "duration": get_duration()
    }
    send_message(
        chat_id,
        "<b>🧠 Yangi savol yaratish</b>\n\nSavol matnini yuboring.\n"
        "Bekor qilish: /bekor"
    )


def process_question(chat_id, text):
    state = states.get(chat_id)
    if not state or not is_admin(chat_id):
        return False

    if state["state"] == "question":
        state["question"] = text
        state["state"] = "correct_answer"
        send_message(chat_id, "✅ To‘g‘ri javobni yuboring.")
        return True

    if state["state"] == "correct_answer":
        state["answer"] = text
        state["state"] = "variants"
        send_message(
            chat_id,
            "🔤 Qabul qilinadigan boshqa javoblarni vergul bilan yozing.\n\n"
            "Masalan: <code>Toshkent, Tashkent, Тошкент</code>\n"
            "Variant kerak bo‘lmasa, <code>-</code> yuboring."
        )
        return True

    if state["state"] == "variants":
        state["variants"] = "" if text.strip() == "-" else text
        state["state"] = "preview"

        send_message(
            chat_id,
            "<b>📋 SAVOL PREVYU</b>\n\n"
            f"🧠 {safe(state['question'])}\n\n"
            f"✅ Javob: {safe(state['answer'])}\n"
            f"🔤 Variantlar: {safe(state['variants'] or 'yo‘q')}\n"
            f"⏱ Vaqt: {format_duration(state['duration'])}",
            [[
                {"text": "📢 Kanalga chiqarish", "callback_data": "question_publish"},
                {"text": "❌ Bekor qilish", "callback_data": "question_cancel"}
            ]]
        )
        return True

    return False


def publish_question(chat_id):
    state = states.get(chat_id)
    if not is_admin(chat_id) or not state or state.get("state") != "preview":
        return "Savol holati topilmadi."

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
    qid = cur.lastrowid

    # Kanal postidagi havola botning shaxsiy chatini ochadi.
    # Foydalanuvchi botni avval /start orqali ishga tushirishi kerak.
    link = f"https://t.me/{BOT_USERNAME}?start=answer_{qid}"

    keyboard = [[{
        "text": "📝 Javob berish",
        "url": link
    }]]

    post = send_message(
        CHANNEL,
        "<b>🧠 ALGORITM ZAKOVAT — SAVOL</b>\n\n"
        f"{safe(state['question'])}\n\n"
        f"⏱ Vaqt: <b>{format_duration(state['duration'])}</b>\n\n"
        "👇 Javob berish tugmasini bosing.",
        keyboard
    )

    if post.get("ok"):
        db.execute(
            "UPDATE questions SET channel_message_id=? WHERE id=?",
            (post["result"]["message_id"], qid)
        )
        db.commit()
        states.pop(chat_id, None)
        return f"✅ Savol kanalga chiqarildi. ID: #{qid}"

    db.execute("UPDATE questions SET active=0 WHERE id=?", (qid,))
    db.commit()
    return (
        "❌ Kanalga yuborilmadi.\n"
        "Bot kanal admini ekanini va post yuborish huquqini tekshiring."
    )


# ============================================================
# JAVOB QABUL QILISH
# ============================================================

def is_correct(user_answer, correct_answer, variants):
    possible = [correct_answer]
    if variants:
        possible.extend(
            item.strip()
            for item in variants.split(",")
            if item.strip()
        )
    return any(clean(user_answer) == clean(item) for item in possible)


def request_answer(user_id, question_id):
    states[user_id] = {
        "state": "answering",
        "question_id": question_id
    }
    send_message(
        user_id,
        f"📝 <b>#{question_id}-savol</b>\n\nJavobingizni yuboring.\n"
        "Bekor qilish: /bekor"
    )


def process_user_answer(message):
    user = message["from"]
    user_id = user["id"]
    state = states.get(user_id)

    if not state or state.get("state") != "answering":
        return False

    text = message.get("text", "").strip()
    if not text:
        send_message(user_id, "Iltimos, javobni matn ko‘rinishida yuboring.")
        return True

    qid = state["question_id"]
    q = db.execute(
        "SELECT * FROM questions WHERE id=?", (qid,)
    ).fetchone()

    if not q:
        states.pop(user_id, None)
        send_message(user_id, "❌ Savol topilmadi.")
        return True

    if not q["active"] or not q["start_time"]:
        states.pop(user_id, None)
        send_message(user_id, "⏰ Bu savol yopilgan.")
        return True

    if now() >= q["start_time"] + q["duration"]:
        db.execute("UPDATE questions SET active=0 WHERE id=?", (qid,))
        db.commit()
        states.pop(user_id, None)
        send_message(user_id, "⏰ Savol vaqti tugagan.")
        return True

    existing = db.execute("""
        SELECT id FROM answers WHERE question_id=? AND user_id=?
    """, (qid, user_id)).fetchone()

    if existing:
        states.pop(user_id, None)
        send_message(user_id, "⚠️ Siz bu savolga allaqachon javob bergansiz.")
        return True

    correct = is_correct(text, q["correct_answer"], q["variants"])
    points = 1 if correct else 0

    try:
        db.execute("""
            INSERT INTO answers
            (question_id, user_id, username, first_name, answer,
             correct, points, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            qid,
            user_id,
            user.get("username", ""),
            user.get("first_name", ""),
            text,
            int(correct),
            points,
            now()
        ))
        db.commit()
    except sqlite3.IntegrityError:
        states.pop(user_id, None)
        send_message(user_id, "⚠️ Javobingiz oldin qabul qilingan.")
        return True

    if points:
        add_score(user_id, 1, f"Savol #{qid}")
        send_message(user_id, "✅ <b>To‘g‘ri javob!</b>\n🏆 Sizga +1 ball berildi.")
    else:
        send_message(
            user_id,
            "❌ <b>Javob noto‘g‘ri.</b>\nKeyingi savolda omad!"
        )

    name = user.get("first_name") or "Noma’lum"
    username = user.get("username", "")
    answer_id = db.execute(
        "SELECT id FROM answers WHERE question_id=? AND user_id=?",
        (qid, user_id)
    ).fetchone()["id"]

    send_message(
        ADMIN_ID,
        "<b>📩 YANGI JAVOB</b>\n\n"
        f"🧠 Savol: #{qid}\n"
        f"👤 {safe(name)}\n"
        f"🔗 {safe('@' + username if username else 'username yo‘q')}\n"
        f"🆔 <code>{user_id}</code>\n"
        f"📝 {safe(text)}\n"
        f"🤖 Avtomatik baho: {'to‘g‘ri' if correct else 'noto‘g‘ri'}\n"
        f"🏆 Hozirgi ball: {points}",
        [[
            {"text": "🏆 1 ball", "callback_data": f"grade:{answer_id}:1"},
            {"text": "0 ball", "callback_data": f"grade:{answer_id}:0"},
            {"text": "➖ −1 ball", "callback_data": f"grade:{answer_id}:-1"}
        ]]
    )

    states.pop(user_id, None)
    return True


# ============================================================
# JAVOBNI QAYTA BAHOLASH
# ============================================================

def set_answer_points(answer_id, new_points):
    row = db.execute(
        "SELECT * FROM answers WHERE id=?", (answer_id,)
    ).fetchone()

    if not row:
        return "❌ Javob topilmadi."

    old_points = int(row["points"])
    delta = new_points - old_points

    if delta == 0:
        return f"ℹ️ Javob allaqachon {new_points} ball bilan baholangan."

    db.execute(
        "UPDATE answers SET points=?, correct=? WHERE id=?",
        (new_points, int(new_points > 0), answer_id)
    )
    db.commit()

    add_score(
        row["user_id"],
        delta,
        f"Admin bahosi: javob #{answer_id}"
    )

    return (
        f"✅ Javob #{answer_id} yangilandi.\n"
        f"Oldingi ball: {old_points}\n"
        f"Yangi ball: {new_points}\n"
        f"Hisobga kiritilgan o‘zgarish: {delta:+d}"
    )


# ============================================================
# PROFIL — FAQAT SHAXSIY NATIJA
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
    name = member["first_name"] if member else "Foydalanuvchi"

    # Eslatma: profil ichida reytingdagi o'rin ko'rsatilmaydi.
    send_message(
        chat_id,
        "<b>👤 SHAXSIY PROFIL</b>\n\n"
        f"👤 Ism: {safe(name)}\n"
        f"🏆 Jami ball: <b>{score}</b>\n"
        f"📝 Javoblar soni: {total}\n"
        f"✅ To‘g‘ri javoblar: {correct}\n"
        f"🎖 Daraja: {get_level(score)}"
    )


# ============================================================
# REYTING — FAQAT ADMIN
# ============================================================

def show_rating(chat_id):
    if not is_admin(chat_id):
        send_message(chat_id, "🔒 Reyting faqat admin uchun ochiq.")
        return

    rows = db.execute("""
        SELECT s.user_id, s.points, m.first_name, m.username
        FROM scores s
        LEFT JOIN members m ON m.user_id=s.user_id
        ORDER BY s.points DESC, s.user_id ASC
        LIMIT 50
    """).fetchall()

    if not rows:
        send_message(chat_id, "🏆 Reyting hozircha bo‘sh.")
        return

    text = "<b>🏆 ADMIN UCHUN REYTING</b>\n\n"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}

    for i, row in enumerate(rows, 1):
        name = row["first_name"] or row["username"] or str(row["user_id"])
        text += (
            f"{medals.get(i, str(i) + '.')}"
            f" {safe(name)} — <b>{row['points']}</b> ball\n"
        )

    send_message(chat_id, text)


# ============================================================
# JAVOBLAR RO'YXATI
# ============================================================

def show_answers(chat_id):
    if not is_admin(chat_id):
        return

    rows = db.execute("""
        SELECT * FROM answers ORDER BY id DESC LIMIT 20
    """).fetchall()

    if not rows:
        send_message(chat_id, "📋 Hozircha javoblar yo‘q.")
        return

    for row in rows:
        name = row["first_name"] or row["username"] or str(row["user_id"])
        text = (
            f"<b>📋 Javob #{row['id']}</b>\n\n"
            f"🧠 Savol: #{row['question_id']}\n"
            f"👤 {safe(name)}\n"
            f"🆔 <code>{row['user_id']}</code>\n"
            f"📝 {safe(row['answer'])}\n"
            f"🏆 Joriy ball: <b>{row['points']}</b>"
        )
        send_message(
            chat_id,
            text,
            [[
                {"text": "+1 ball", "callback_data": f"grade:{row['id']}:1"},
                {"text": "0 ball", "callback_data": f"grade:{row['id']}:0"},
                {"text": "−1 ball", "callback_data": f"grade:{row['id']}:-1"}
            ]]
        )


# ============================================================
# A'ZOLAR / STATISTIKA / TARIX
# ============================================================

def show_members(chat_id):
    if not is_admin(chat_id):
        return

    total = db.execute(
        "SELECT COUNT(*) AS c FROM members"
    ).fetchone()["c"]

    rows = db.execute("""
        SELECT first_name, username, user_id
        FROM members ORDER BY joined_at DESC LIMIT 30
    """).fetchall()

    text = f"<b>👥 A’ZOLAR</b>\nJami: <b>{total}</b>\n\n"
    for row in rows:
        name = row["first_name"] or row["username"] or "Noma’lum"
        text += f"• {safe(name)} — <code>{row['user_id']}</code>\n"

    send_message(chat_id, text)


def show_stats(chat_id):
    if not is_admin(chat_id):
        return

    members = db.execute("SELECT COUNT(*) c FROM members").fetchone()["c"]
    questions = db.execute("SELECT COUNT(*) c FROM questions").fetchone()["c"]
    answers = db.execute("SELECT COUNT(*) c FROM answers").fetchone()["c"]
    correct = db.execute(
        "SELECT COUNT(*) c FROM answers WHERE correct=1"
    ).fetchone()["c"]
    active = db.execute(
        "SELECT COUNT(*) c FROM questions WHERE active=1"
    ).fetchone()["c"]

    send_message(
        chat_id,
        "<b>📊 BOT STATISTIKASI</b>\n\n"
        f"👥 A’zolar: {members}\n"
        f"🧠 Savollar: {questions}\n"
        f"📝 Javoblar: {answers}\n"
        f"✅ To‘g‘ri deb baholangan javoblar: {correct}\n"
        f"❌ Boshqa javoblar: {answers - correct}\n"
        f"🟢 Faol savollar: {active}"
    )


def show_history(chat_id):
    if not is_admin(chat_id):
        return

    rows = db.execute("""
        SELECT id, question, duration, created_at, active
        FROM questions ORDER BY id DESC LIMIT 20
    """).fetchall()

    if not rows:
        send_message(chat_id, "📚 Savollar tarixi bo‘sh.")
        return

    for row in rows:
        status = "🟢 Faol" if row["active"] else "🔴 Yopilgan"
        send_message(
            chat_id,
            f"<b>🧠 Savol #{row['id']}</b>\n\n"
            f"{safe(row['question'][:250])}\n\n"
            f"⏱ Vaqt: {format_duration(row['duration'])}\n"
            f"Holat: {status}"
        )


# ============================================================
# SAVOL VAQTI
# ============================================================

def show_time_menu(chat_id):
    if not is_admin(chat_id):
        return

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
        "<b>⏱ SAVOL VAQTI</b>\n\n"
        f"Joriy vaqt: <b>{format_duration(get_duration())}</b>\n"
        "Tanlov keyingi savollarga qo‘llanadi.",
        keyboard
    )


# ============================================================
# HAFTALIK TOP-3
# ============================================================

def week_start_timestamp():
    dt = datetime.now(TZ)
    monday = (dt - timedelta(days=dt.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(monday.timestamp())


def show_weekly_top(chat_id):
    if not is_admin(chat_id):
        return

    rows = db.execute("""
        SELECT h.user_id, SUM(h.points) AS points,
               m.first_name, m.username
        FROM score_history h
        LEFT JOIN members m ON m.user_id=h.user_id
        WHERE h.created_at >= ?
        GROUP BY h.user_id
        ORDER BY points DESC
        LIMIT 3
    """, (week_start_timestamp(),)).fetchall()

    if not rows:
        send_message(chat_id, "🎁 Bu haftada hali natija yo‘q.")
        return

    text = "<b>🎁 HAFTALIK TOP-3</b>\n\n"
    for i, row in enumerate(rows, 1):
        name = row["first_name"] or row["username"] or str(row["user_id"])
        text += f"{i}. {safe(name)} — <b>{row['points']}</b> ball\n"

    send_message(chat_id, text)


# ============================================================
# XABAR TARQATISH
# ============================================================

def start_broadcast(chat_id):
    if not is_admin(chat_id):
        return
    states[chat_id] = {"state": "broadcast"}
    send_message(
        chat_id,
        "📢 A’zolarga yuboriladigan xabarni yozing.\n"
        "Bekor qilish: /bekor"
    )


def do_broadcast(chat_id, text):
    if not is_admin(chat_id):
        return

    users = db.execute("SELECT user_id FROM members").fetchall()
    success = 0
    failed = 0

    send_message(chat_id, "⏳ Xabar tarqatish boshlandi.")

    for row in users:
        result = send_message(row["user_id"], safe(text))
        if result.get("ok"):
            success += 1
        else:
            failed += 1
        time.sleep(0.05)

    send_message(
        chat_id,
        "<b>📢 TARQATISH YAKUNLANDI</b>\n\n"
        f"✅ Yetkazildi: {success}\n"
        f"❌ Yetkazilmadi: {failed}"
    )


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

    # Admin paneldagi har bir amal server tomonda tekshiriladi.
    admin_only = (
        data.startswith("admin_")
        or data in ("question_publish", "question_cancel")
        or data.startswith("time:")
        or data.startswith("grade:")
    )

    if admin_only and not is_admin(user_id):
        callback_answer(query["id"], "🔒 Bu amal faqat admin uchun.")
        return

    if data == "contact_admin":
        states[user_id] = {"state": "contact_message"}
        send_message(
            user_id,
            "📩 Adminga yuboriladigan xabaringizni yozing.\n"
            "Bekor qilish: /bekor"
        )
        callback_answer(query["id"])
        return

    if data.startswith("contact_reply:"):
        if not is_admin(user_id):
            callback_answer(query["id"], "Bu amal faqat admin uchun.")
            return

        try:
            target = int(data.split(":", 1)[1])
        except ValueError:
            callback_answer(query["id"], "Foydalanuvchi ID xato.")
            return

        states[ADMIN_ID] = {
            "state": "contact_reply",
            "target_id": target
        }
        send_message(ADMIN_ID, "✍️ Javob matnini yuboring. Bekor qilish: /bekor")
        callback_answer(query["id"])
        return

    if data == "admin_add":
        start_question(chat_id)
    elif data == "admin_answers":
        show_answers(chat_id)
    elif data == "admin_rating":
        show_rating(chat_id)
    elif data == "admin_members":
        show_members(chat_id)
    elif data == "admin_stats":
        show_stats(chat_id)
    elif data == "admin_history":
        show_history(chat_id)
    elif data == "admin_points":
        send_message(
            chat_id,
            "➕ Ball boshqaruvi uchun «📋 Javoblar» bo‘limiga kiring."
        )
    elif data == "admin_broadcast":
        start_broadcast(chat_id)
    elif data == "admin_time":
        show_time_menu(chat_id)
    elif data == "admin_winners":
        show_weekly_top(chat_id)
    elif data.startswith("time:"):
        try:
            seconds = int(data.split(":", 1)[1])
        except ValueError:
            callback_answer(query["id"], "Vaqt qiymati xato.")
            return

        if seconds not in ALLOWED_DURATIONS:
            callback_answer(query["id"], "Noto‘g‘ri vaqt.")
            return

        set_setting("question_duration", seconds)
        send_message(
            chat_id,
            f"✅ Savol vaqti {format_duration(seconds)} qilib saqlandi."
        )
    elif data == "question_publish":
        send_message(chat_id, publish_question(chat_id))
    elif data == "question_cancel":
        states.pop(ADMIN_ID, None)
        send_message(chat_id, "❌ Savol yaratish bekor qilindi.")
    elif data.startswith("grade:"):
        try:
            _, answer_id, points = data.split(":")
            answer_id = int(answer_id)
            points = int(points)
            if points not in (-1, 0, 1):
                raise ValueError
        except ValueError:
            callback_answer(query["id"], "Baholash qiymati xato.")
            return

        send_message(chat_id, set_answer_points(answer_id, points))
    else:
        callback_answer(query["id"], "Noma’lum amal.")
        return

    callback_answer(query["id"])


# ============================================================
# MESSAGE HANDLER
# ============================================================

def handle_message(message):
    user = message.get("from", {})
    if not user:
        return

    user_id = user["id"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    save_member(user)
    state = states.get(user_id)

    # Murojaat foydalanuvchidan adminga
    if state and state.get("state") == "contact_message":
        if text == "/bekor":
            states.pop(user_id, None)
            send_message(chat_id, "❌ Murojaat bekor qilindi.")
            return

        if not text:
            send_message(chat_id, "Matnli xabar yuboring.")
            return

        name = safe(user.get("first_name", "Foydalanuvchi"))
        username = user.get("username", "")
        result = send_message(
            ADMIN_ID,
            "<b>📩 YANGI MUROJAAT</b>\n\n"
            f"👤 {name}\n"
            f"🔗 {safe('@' + username if username else 'username yo‘q')}\n"
            f"🆔 <code>{user_id}</code>\n\n"
            f"💬 {safe(text)}",
            [[{
                "text": "↩️ Javob berish",
                "callback_data": f"contact_reply:{user_id}"
            }]]
        )

        send_message(
            chat_id,
            "✅ Murojaat adminga yuborildi."
            if result.get("ok")
            else "❌ Xabar yuborilmadi. Keyinroq urinib ko‘ring."
        )
        states.pop(user_id, None)
        return

    # Admin foydalanuvchiga javob yozmoqda
    if is_admin(user_id) and state and state.get("state") == "contact_reply":
        if text == "/bekor":
            states.pop(user_id, None)
            send_message(chat_id, "❌ Javob bekor qilindi.")
            return

        target_id = state["target_id"]
        result = send_message(
            target_id,
            "📩 <b>Admin javobi:</b>\n\n" + safe(text)
        )
        send_message(
            chat_id,
            "✅ Javob yuborildi." if result.get("ok")
            else "❌ Javob yuborilmadi. Foydalanuvchi botni ishga tushirganini tekshiring."
        )
        states.pop(user_id, None)
        return

    if text == "/bekor":
        if user_id in states:
            states.pop(user_id, None)
            send_message(chat_id, "❌ Amal bekor qilindi.")
        return

    # Admin xabar tarqatmoqda
    if is_admin(user_id) and state and state.get("state") == "broadcast":
        do_broadcast(chat_id, text)
        states.pop(user_id, None)
        return

    # Admin yangi savol ma'lumotlarini kiritmoqda
    if is_admin(user_id) and state and state.get("state") in (
        "question", "correct_answer", "variants"
    ):
        process_question(chat_id, text)
        return

    # Foydalanuvchi savolga javob bermoqda
    if process_user_answer(message):
        return

    if text.startswith("/start"):
        parts = text.split(maxsplit=1)

        # Kanal postidagi start=answer_ID havolasi
        if len(parts) == 2 and parts[1].startswith("answer_"):
            try:
                qid = int(parts[1].split("_", 1)[1])
            except ValueError:
                send_message(chat_id, "❌ Savol havolasi noto‘g‘ri.")
                return

            q = db.execute(
                "SELECT * FROM questions WHERE id=?", (qid,)
            ).fetchone()

            if not q or not q["active"]:
                send_message(chat_id, "⏰ Bu savol yopilgan yoki topilmadi.")
                return

            if now() >= q["start_time"] + q["duration"]:
                db.execute("UPDATE questions SET active=0 WHERE id=?", (qid,))
                db.commit()
                send_message(chat_id, "⏰ Bu savolning vaqti tugagan.")
                return

            existing = db.execute(
                "SELECT id FROM answers WHERE question_id=? AND user_id=?",
                (qid, user_id)
            ).fetchone()

            if existing:
                send_message(chat_id, "⚠️ Siz bu savolga allaqachon javob bergansiz.")
                return

            request_answer(user_id, qid)
            return

        send_message(
            chat_id,
            "<b>👋 Assalomu alaykum!</b>\n\n"
            "🧠 <b>ALGORITM ZAKOVAT</b> botiga xush kelibsiz!\n\n"
            "Savollarda qatnashing, javoblaringiz uchun ball to‘plang.\n\n"
            "👤 /profil — shaxsiy natijalaringiz\n"
            "⚙️ /admin — admin paneli (faqat admin)\n\n"
            "🔒 Umumiy reyting faqat admin uchun ochiq.",
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
        if is_admin(user_id):
            show_rating(chat_id)
        else:
            send_message(chat_id, "🔒 Reyting faqat admin uchun ochiq.")
        return

    if text == "/admin":
        if is_admin(user_id):
            show_admin(chat_id)
        else:
            send_message(chat_id, "❌ Siz admin emassiz.")
        return

    # Boshqa admin buyruqlari
    if is_admin(user_id):
        commands = {
            "/javoblar": show_answers,
            "/a'zolar": show_members,
            "/statistika": show_stats,
            "/tarix": show_history,
            "/vaqt": show_time_menu,
        }
        if text in commands:
            commands[text](chat_id)
            return


# ============================================================
# MUDDATI TUGAGAN SAVOLLAR
# ============================================================

def check_expired_questions():
    rows = db.execute("""
        SELECT id, start_time, duration
        FROM questions WHERE active=1
    """).fetchall()

    for row in rows:
        if row["start_time"] and now() >= row["start_time"] + row["duration"]:
            db.execute(
                "UPDATE questions SET active=0 WHERE id=? AND active=1",
                (row["id"],)
            )
            db.commit()

            qid = row["id"]
            question = db.execute(
                "SELECT correct_answer FROM questions WHERE id=?", (qid,)
            ).fetchone()

            send_message(
                ADMIN_ID,
                f"⏰ <b>#{qid}-savol yopildi.</b>\n"
                f"✅ To‘g‘ri javob: {safe(question['correct_answer'])}"
            )


# ============================================================
# ISHGA TUSHIRISH
# ============================================================

def main():
    global BOT_USERNAME

    me = tg("getMe")
    if not me.get("ok"):
        raise RuntimeError(
            "Bot tokeni ishlamadi. BOT_TOKEN qiymatini tekshiring."
        )

    BOT_USERNAME = me["result"]["username"]
    print(f"🤖 @{BOT_USERNAME} ishga tushdi.")

    # Boshqa webhook mavjud bo'lsa, polling ishlashi uchun o'chiriladi.
    tg("deleteWebhook", {"drop_pending_updates": False})

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
                except Exception as exc:
                    print("UPDATE xatosi:", exc)

            if now() - last_check >= 10:
                check_expired_questions()
                last_check = now()

        except KeyboardInterrupt:
            print("Bot to‘xtatildi.")
            break
        except Exception as exc:
            print("Asosiy sikl xatosi:", exc)
            time.sleep(5)


if __name__ == "__main__":
    main()
