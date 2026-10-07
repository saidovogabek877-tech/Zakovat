import os
import re
import json
import time
import sqlite3
import threading
import unicodedata
from datetime import datetime, timedelta, timezone

import requests


# =========================================================
# SOZLAMALAR
# =========================================================

TOKEN = os.environ.get("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi!")

ADMIN_ID = 5607350126
CHANNEL = "@zakalgoritm"

DB_NAME = "zakovat.db"

UZ_TZ = timezone(timedelta(hours=5))

API = f"https://api.telegram.org/bot{TOKEN}"


# =========================================================
# DATABASE
# =========================================================

db_lock = threading.Lock()


def db():
    conn = sqlite3.connect(
        DB_NAME,
        check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            joined_at INTEGER,
            last_seen INTEGER,
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            accepted_answers TEXT DEFAULT '[]',
            created_at INTEGER,
            ends_at INTEGER,
            status TEXT DEFAULT 'active',
            channel_message_id INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            user_id INTEGER,
            answer TEXT,
            is_correct INTEGER DEFAULT 0,
            points_awarded INTEGER DEFAULT 0,
            answered_at INTEGER,
            UNIQUE(question_id, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS weekly_scores (
            week_key TEXT,
            user_id INTEGER,
            points INTEGER DEFAULT 0,
            PRIMARY KEY(week_key, user_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS score_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_key TEXT,
            user_id INTEGER,
            delta INTEGER,
            reason TEXT,
            admin_id INTEGER,
            created_at INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS prizes (
            week_key TEXT PRIMARY KEY,
            winner_user_id INTEGER,
            prize_text TEXT,
            created_at INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()

    # Default vaqt
    cur.execute("""
        INSERT OR IGNORE INTO settings(key, value)
        VALUES('question_time', '900')
    """)

    conn.commit()
    conn.close()


init_db()


# =========================================================
# TELEGRAM API
# =========================================================

def tg(method, data=None):
    try:
        r = requests.post(
            f"{API}/{method}",
            data=data or {},
            timeout=40
        )
        return r.json()
    except Exception as e:
        print("Telegram API xatosi:", e)
        return {"ok": False}


def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }

    if reply_markup:
        data["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False
        )

    return tg("sendMessage", data)


def edit_message(chat_id, message_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML"
    }

    if reply_markup:
        data["reply_markup"] = json.dumps(
            reply_markup,
            ensure_ascii=False
        )

    return tg("editMessageText", data)


def answer_callback(callback_id, text="", show_alert=False):
    return tg(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": show_alert
        }
    )


# =========================================================
# YORDAMCHI FUNKSIYALAR
# =========================================================

def now():
    return int(time.time())


def local_datetime(ts=None):
    if ts is None:
        ts = now()

    return datetime.fromtimestamp(
        ts,
        UZ_TZ
    )


def week_key(ts=None):
    dt = local_datetime(ts)

    return dt.strftime("%G-W%V")


def get_setting(key, default=None):
    conn = db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?",
        (key,)
    ).fetchone()
    conn.close()

    if row:
        return row["value"]

    return default


def set_setting(key, value):
    conn = db()

    conn.execute("""
        INSERT INTO settings(key,value)
        VALUES(?,?)
        ON CONFLICT(key)
        DO UPDATE SET value=excluded.value
    """, (key, str(value)))

    conn.commit()
    conn.close()


def question_seconds():
    return int(get_setting("question_time", 900))


def question_time_text(seconds=None):
    if seconds is None:
        seconds = question_seconds()

    minutes = seconds // 60

    if minutes == 1:
        return "1 daqiqa"

    return f"{minutes} daqiqa"


def normalize_answer(text):
    if not text:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        text
    )

    text = text.casefold()

    # Apostroflarni bir xil ko‘rinishga keltirish
    for x in ["’", "‘", "ʻ", "ʼ", "`", "´"]:
        text = text.replace(x, "'")

    # Ortiqcha bo‘shliqlar
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def answer_is_correct(answer, correct, variants):
    target = normalize_answer(answer)

    accepted = [
        normalize_answer(correct)
    ]

    for item in variants:
        if item.strip():
            accepted.append(
                normalize_answer(item)
            )

    return target in accepted


def user_name(user):
    name = user.get("first_name", "")

    if user.get("last_name"):
        name += " " + user["last_name"]

    return name.strip() or "Foydalanuvchi"


def mention_user(user_id, name):
    return f'<a href="tg://user?id={user_id}">{name}</a>'


def member_upsert(user):
    if not user:
        return

    uid = user["id"]

    first = user.get("first_name", "")
    last = user.get("last_name", "")
    username = user.get("username", "")

    conn = db()

    conn.execute("""
        INSERT INTO members(
            user_id,
            first_name,
            last_name,
            username,
            joined_at,
            last_seen,
            active
        )
        VALUES(?,?,?,?,?,?,1)

        ON CONFLICT(user_id)
        DO UPDATE SET
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            username=excluded.username,
            last_seen=excluded.last_seen,
            active=1
    """, (
        uid,
        first,
        last,
        username,
        now(),
        now()
    ))

    conn.commit()
    conn.close()


def member_info(user_id):
    conn = db()

    row = conn.execute(
        "SELECT * FROM members WHERE user_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    return row


# =========================================================
# BALL TIZIMI
# =========================================================

def add_points(user_id, points, reason=""):
    wk = week_key()

    conn = db()

    conn.execute("""
        INSERT INTO weekly_scores(
            week_key,
            user_id,
            points
        )
        VALUES(?,?,?)

        ON CONFLICT(week_key,user_id)
        DO UPDATE SET
            points=points+excluded.points
    """, (
        wk,
        user_id,
        points
    ))

    conn.execute("""
        INSERT INTO score_history(
            week_key,
            user_id,
            delta,
            reason,
            admin_id,
            created_at
        )
        VALUES(?,?,?,?,?,?)
    """, (
        wk,
        user_id,
        points,
        reason,
        ADMIN_ID,
        now()
    ))

    conn.commit()
    conn.close()


def get_score(user_id, wk=None):
    if wk is None:
        wk = week_key()

    conn = db()

    row = conn.execute("""
        SELECT points
        FROM weekly_scores
        WHERE week_key=? AND user_id=?
    """, (
        wk,
        user_id
    )).fetchone()

    conn.close()

    return row["points"] if row else 0


def get_ranking(wk=None):
    if wk is None:
        wk = week_key()

    conn = db()

    rows = conn.execute("""
        SELECT
            ws.user_id,
            ws.points,
            m.first_name,
            m.last_name,
            m.username

        FROM weekly_scores ws

        LEFT JOIN members m
        ON m.user_id=ws.user_id

        WHERE ws.week_key=?

        ORDER BY ws.points DESC, ws.user_id ASC
    """, (wk,)).fetchall()

    conn.close()

    return rows


# =========================================================
# SAVOL
# =========================================================

def get_active_question():
    conn = db()

    row = conn.execute("""
        SELECT *
        FROM questions
        WHERE status='active'
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    conn.close()

    return row


def get_question(question_id):
    conn = db()

    row = conn.execute(
        "SELECT * FROM questions WHERE id=?",
        (question_id,)
    ).fetchone()

    conn.close()

    return row


def create_question(question, correct, variants, duration):
    conn = db()

    created = now()
    ends = created + duration

    cur = conn.execute("""
        INSERT INTO questions(
            question,
            correct_answer,
            accepted_answers,
            created_at,
            ends_at,
            status
        )
        VALUES(?,?,?,?,?,'active')
    """, (
        question,
        correct,
        json.dumps(
            variants,
            ensure_ascii=False
        ),
        created,
        ends
    ))

    qid = cur.lastrowid

    conn.commit()
    conn.close()

    return qid


def close_question(question_id):
    conn = db()

    conn.execute("""
        UPDATE questions
        SET status='closed'
        WHERE id=?
    """, (question_id,))

    conn.commit()
    conn.close()


# =========================================================
# ADMIN HOLATI
# =========================================================

admin_state = {
    "state": None,
    "data": {}
}


def set_admin_state(state, data=None):
    admin_state["state"] = state
    admin_state["data"] = data or {}


def clear_admin_state():
    admin_state["state"] = None
    admin_state["data"] = {}


# =========================================================
# KEYBOARDLAR
# =========================================================

def main_admin_keyboard():
    return {
        "keyboard": [
            [
                {"text": "🧠 Savol qo‘shish"},
                {"text": "📋 Javoblar"}
            ],
            [
                {"text": "🏆 Reyting"},
                {"text": "👥 A’zolar"}
            ],
            [
                {"text": "📊 Statistika"},
                {"text": "📚 Savollar tarixi"}
            ],
            [
                {"text": "➕ Ball boshqaruvi"},
                {"text": "📢 Xabar yuborish"}
            ],
            [
                {"text": "⏱️ Savol vaqti"},
                {"text": "🎁 G‘oliblar"}
            ]
        ],
        "resize_keyboard": True
    }


def user_keyboard():
    return {
        "keyboard": [
            [
                {"text": "👤 Profil"},
                {"text": "🏆 Reyting"}
            ],
            [
                {"text": "📊 Statistika"},
                {"text": "ℹ️ Yordam"}
            ]
        ],
        "resize_keyboard": True
    }


def answer_button(question_id):
    return {
        "inline_keyboard": [
            [
                {
                    "text": "📝 Javob berish",
                    "callback_data": f"ans:{question_id}"
                }
            ]
        ]
    }


def time_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "⚡ 1 daqiqa", "callback_data": "time:60"},
                {"text": "⏱️ 10 daqiqa", "callback_data": "time:600"}
            ],
            [
                {"text": "⏱️ 15 daqiqa", "callback_data": "time:900"},
                {"text": "⏱️ 30 daqiqa", "callback_data": "time:1800"}
            ],
            [
                {"text": "⏱️ 60 daqiqa", "callback_data": "time:3600"}
            ]
        ]
    }


# =========================================================
# ADMIN PANEL
# =========================================================

def send_admin_panel(chat_id):
    send_message(
        chat_id,
        "<b>⚙️ ADMIN PANEL</b>\n\n"
        "Kerakli bo‘limni tanlang:",
        main_admin_keyboard()
    )


# =========================================================
# SAVOL YARATISH
# =========================================================

def start_question_creation(chat_id):
    active = get_active_question()

    if active:
        send_message(
            chat_id,
            "⚠️ Hozir faol savol mavjud.\n\n"
            "Avval uni tugating yoki `/yopish` buyrug‘idan foydalaning."
        )
        return

    set_admin_state("question_text")

    send_message(
        chat_id,
        "🧠 <b>Yangi savol</b>\n\n"
        "Savol matnini yuboring:"
    )


def finish_question_creation(chat_id):
    data = admin_state["data"]

    question = data["question"]
    correct = data["correct"]
    variants = data["variants"]

    duration = question_seconds()

    qid = create_question(
        question,
        correct,
        variants,
        duration
    )

    ends = local_datetime(
        now() + duration
    ).strftime("%H:%M")

    text = (
        f"🧠 <b>ZAKOVAT SAVOLI #{qid}</b>\n\n"
        f"{question}\n\n"
        f"⏱️ Vaqt: <b>{question_time_text(duration)}</b>\n"
        f"⏰ Tugash vaqti: <b>{ends}</b>"
    )

    result = send_message(
        CHANNEL,
        text,
        answer_button(qid)
    )

    if result.get("ok"):
        message_id = result["result"]["message_id"]

        conn = db()

        conn.execute("""
            UPDATE questions
            SET channel_message_id=?
            WHERE id=?
        """, (
            message_id,
            qid
        ))

        conn.commit()
        conn.close()

    clear_admin_state()

    send_message(
        chat_id,
        "✅ Savol kanalga yuborildi!\n\n"
        f"⏱️ {question_time_text(duration)}"
    )


# =========================================================
# SAVOL NATIJASI
# =========================================================

def finish_expired_question(question):
    qid = question["id"]

    # Yana yopilib ketmasligi
    close_question(qid)

    conn = db()

    rows = conn.execute("""
        SELECT
            a.*,
            m.first_name,
            m.last_name,
            m.username

        FROM answers a

        LEFT JOIN members m
        ON m.user_id=a.user_id

        WHERE a.question_id=?

        ORDER BY a.answered_at ASC
    """, (qid,)).fetchall()

    conn.close()

    correct = []
    incorrect = []

    for row in rows:
        name = (
            row["first_name"] or
            row["username"] or
            "Foydalanuvchi"
        )

        item = f"• {name}"

        if row["is_correct"]:
            correct.append(item)
        else:
            incorrect.append(item)

    result_text = (
        f"⏰ <b>SAVOL #{qid} YAKUNLANDI!</b>\n\n"
        f"🧠 {question['question']}\n\n"
        f"✅ To‘g‘ri javob: "
        f"<b>{question['correct_answer']}</b>\n\n"
        f"👥 Javoblar: {len(rows)}\n"
        f"🟢 To‘g‘ri: {len(correct)}\n"
        f"🔴 Noto‘g‘ri: {len(incorrect)}"
    )

    if correct:
        result_text += "\n\n<b>🟢 To‘g‘ri javob berganlar:</b>\n"
        result_text += "\n".join(correct[:30])

    tg(
        "sendMessage",
        {
            "chat_id": CHANNEL,
            "text": result_text,
            "parse_mode": "HTML"
        }
    )

    # Admin xabari
    send_message(
        ADMIN_ID,
        f"⏰ <b>#{qid} savol tugadi.</b>\n\n"
        f"✅ To‘g‘ri javob: "
        f"<b>{question['correct_answer']}</b>\n"
        f"👥 Javoblar: {len(rows)}"
    )


# =========================================================
# JAVOBLAR
# =========================================================

def show_answers(chat_id):
    question = get_active_question()

    if not question:
        send_message(
            chat_id,
            "📭 Hozir faol savol yo‘q."
        )
        return

    conn = db()

    rows = conn.execute("""
        SELECT
            a.id,
            a.user_id,
            a.answer,
            a.is_correct,
            a.points_awarded,
            m.first_name,
            m.last_name,
            m.username

        FROM answers a

        LEFT JOIN members m
        ON m.user_id=a.user_id

        WHERE a.question_id=?

        ORDER BY a.answered_at ASC
    """, (
        question["id"],
    )).fetchall()

    conn.close()

    if not rows:
        send_message(
            chat_id,
            "📭 Hali hech kim javob bermadi."
        )
        return

    for row in rows:
        name = row["first_name"] or "Foydalanuvchi"

        username = (
            f"@{row['username']}"
            if row["username"]
            else ""
        )

        status = "✅" if row["is_correct"] else "❌"

        text = (
            f"{status} <b>{name}</b> {username}\n"
            f"💬 Javob: <code>{row['answer']}</code>\n"
            f"🆔 {row['user_id']}"
        )

        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ To‘g‘ri +1",
                        "callback_data": f"ok:{row['id']}"
                    },
                    {
                        "text": "➕ 1 ball",
                        "callback_data": f"p1:{row['user_id']}"
                    }
                ],
                [
                    {
                        "text": "➖ 1 ball",
                        "callback_data": f"m1:{row['user_id']}"
                    }
                ]
            ]
        }

        send_message(
            chat_id,
            text,
            keyboard
        )


# =========================================================
# STATISTIKA
# =========================================================

def show_statistics(chat_id):
    conn = db()

    members = conn.execute(
        "SELECT COUNT(*) c FROM members"
    ).fetchone()["c"]

    questions = conn.execute(
        "SELECT COUNT(*) c FROM questions"
    ).fetchone()["c"]

    answers = conn.execute(
        "SELECT COUNT(*) c FROM answers"
    ).fetchone()["c"]

    correct = conn.execute(
        "SELECT COUNT(*) c FROM answers WHERE is_correct=1"
    ).fetchone()["c"]

    conn.close()

    send_message(
        chat_id,
        "<b>📊 STATISTIKA</b>\n\n"
        f"👥 A’zolar: <b>{members}</b>\n"
        f"🧠 Savollar: <b>{questions}</b>\n"
        f"💬 Javoblar: <b>{answers}</b>\n"
        f"✅ To‘g‘ri: <b>{correct}</b>\n"
        f"❌ Noto‘g‘ri: <b>{answers - correct}</b>\n\n"
        f"⏱️ Savol vaqti: "
        f"<b>{question_time_text()}</b>"
    )


# =========================================================
# REYTING
# =========================================================

def ranking_text(wk=None):
    if wk is None:
        wk = week_key()

    rows = get_ranking(wk)

    if not rows:
        return (
            "🏆 <b>HAFTALIK REYTING</b>\n\n"
            "Hali reyting mavjud emas."
        )

    text = (
        "🏆 <b>HAFTALIK REYTING</b>\n"
        f"📅 {wk}\n\n"
    )

    medals = ["🥇", "🥈", "🥉"]

    for i, row in enumerate(rows[:20], 1):
        name = row["first_name"] or "Foydalanuvchi"

        medal = medals[i - 1] if i <= 3 else f"{i}."

        text += (
            f"{medal} <b>{name}</b> — "
            f"<b>{row['points']}</b> ball\n"
        )

    return text


# =========================================================
# PROFIL
# =========================================================

def profile_text(user_id):
    info = member_info(user_id)

    score = get_score(user_id)

    ranking = get_ranking()

    position = "-"

    for i, row in enumerate(ranking, 1):
        if row["user_id"] == user_id:
            position = i
            break

    conn = db()

    total = conn.execute("""
        SELECT COUNT(*)
        FROM answers
        WHERE user_id=?
    """, (user_id,)).fetchone()[0]

    correct = conn.execute("""
        SELECT COUNT(*)
        FROM answers
        WHERE user_id=? AND is_correct=1
    """, (user_id,)).fetchone()[0]

    conn.close()

    if score >= 61:
        level = "💎 Usta"
    elif score >= 31:
        level = "🥇 Zakovatchi"
    elif score >= 11:
        level = "🥈 Bilimdon"
    else:
        level = "🥉 Boshlovchi"

    name = (
        f"{info['first_name']} {info['last_name'] or ''}"
        if info else "Foydalanuvchi"
    )

    return (
        f"👤 <b>{name.strip()}</b>\n\n"
        f"🏆 Ball: <b>{score}</b>\n"
        f"📊 Reyting: <b>#{position}</b>\n"
        f"🧠 Javoblar: <b>{total}</b>\n"
        f"✅ To‘g‘ri: <b>{correct}</b>\n"
        f"🎖️ Daraja: <b>{level}</b>"
    )


# =========================================================
# SAVOLLAR TARIXI
# =========================================================

def question_history(chat_id):
    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM questions
        ORDER BY id DESC
        LIMIT 20
    """).fetchall()

    conn.close()

    if not rows:
        send_message(
            chat_id,
            "📚 Savollar tarixi bo‘sh."
        )
        return

    text = "📚 <b>SAVOLLAR TARIXI</b>\n\n"

    for row in rows:
        created = local_datetime(
            row["created_at"]
        ).strftime("%d.%m.%Y %H:%M")

        text += (
            f"#{row['id']} — "
            f"{created}\n"
            f"🧠 {row['question'][:100]}\n"
            f"✅ {row['correct_answer']}\n"
            f"📌 {row['status']}\n\n"
        )

    send_message(chat_id, text)


# =========================================================
# A'ZOLAR
# =========================================================

def members_list(chat_id):
    conn = db()

    rows = conn.execute("""
        SELECT *
        FROM members
        ORDER BY last_seen DESC
        LIMIT 50
    """).fetchall()

    total = conn.execute(
        "SELECT COUNT(*) c FROM members"
    ).fetchone()["c"]

    conn.close()

    text = (
        f"👥 <b>A’ZOLAR</b>\n\n"
        f"Jami: <b>{total}</b>\n\n"
    )

    for i, row in enumerate(rows, 1):
        name = row["first_name"] or "Nomsiz"

        username = (
            f" @{row['username']}"
            if row["username"]
            else ""
        )

        text += (
            f"{i}. {name}{username}\n"
            f"🆔 <code>{row['user_id']}</code>\n\n"
        )

    send_message(chat_id, text)


# =========================================================
# JAVOBNI QABUL QILISH
# =========================================================

def receive_answer(user, question_id, answer):
    member_upsert(user)

    question = get_question(question_id)

    if not question:
        return "❌ Savol topilmadi."

    if question["status"] != "active":
        return "⏰ Bu savol allaqachon yopilgan."

    if now() >= question["ends_at"]:
        return "⏰ Vaqt tugagan."

    conn = db()

    existing = conn.execute("""
        SELECT id
        FROM answers
        WHERE question_id=? AND user_id=?
    """, (
        question_id,
        user["id"]
    )).fetchone()

    if existing:
        conn.close()

        return (
            "⚠️ Siz bu savolga allaqachon "
            "javob bergansiz."
        )

    variants = json.loads(
        question["accepted_answers"] or "[]"
    )

    correct = answer_is_correct(
        answer,
        question["correct_answer"],
        variants
    )

    conn.execute("""
        INSERT INTO answers(
            question_id,
            user_id,
            answer,
            is_correct,
            points_awarded,
            answered_at
        )
        VALUES(?,?,?,?,?,?)
    """, (
        question_id,
        user["id"],
        answer,
        1 if correct else 0,
        0,
        now()
    ))

    answer_id = conn.execute(
        "SELECT last_insert_rowid()"
    ).fetchone()[0]

    conn.commit()
    conn.close()

    if correct:
        conn = db()

        conn.execute("""
            UPDATE answers
            SET points_awarded=1
            WHERE id=?
        """, (answer_id,))

        conn.commit()
        conn.close()

        add_points(
            user["id"],
            1,
            f"Savol #{question_id}"
        )

        status = "✅ <b>To‘g‘ri!</b>\n🎯 +1 ball"
    else:
        status = "❌ <b>Noto‘g‘ri.</b>"

    # Admin real-time xabari
    name = user_name(user)

    send_message(
        ADMIN_ID,
        "🔔 <b>Yangi javob!</b>\n\n"
        f"👤 {name}\n"
        f"🆔 <code>{user['id']}</code>\n"
        f"🧠 Savol #{question_id}\n"
        f"💬 <code>{answer}</code>\n"
        f"{'✅ To‘g‘ri' if correct else '❌ Noto‘g‘ri'}"
    )

    return status


# =========================================================
# CALLBACK
# =========================================================

def handle_callback(callback):
    data = callback.get("data", "")
    user = callback.get("from", {})
    uid = user.get("id")

    member_upsert(user)

    callback_id = callback["id"]

    # ---------------------------------------------
    # SAVOLGA JAVOB
    # ---------------------------------------------

    if data.startswith("ans:"):
        qid = int(data.split(":")[1])

        question = get_question(qid)

        if not question:
            answer_callback(
                callback_id,
                "Savol topilmadi.",
                True
            )
            return

        if question["status"] != "active":
            answer_callback(
                callback_id,
                "Bu savol yopilgan.",
                True
            )
            return

        if now() >= question["ends_at"]:
            answer_callback(
                callback_id,
                "Vaqt tugagan.",
                True
            )
            return

        conn = db()

        existing = conn.execute("""
            SELECT id
            FROM answers
            WHERE question_id=? AND user_id=?
        """, (
            qid,
            uid
        )).fetchone()

        conn.close()

        if existing:
            answer_callback(
                callback_id,
                "Siz allaqachon javob bergansiz.",
                True
            )
            return

        answer_callback(
            callback_id,
            "Javobingizni botga yuboring.",
            False
        )

        send_message(
            uid,
            f"🧠 <b>Javobingizni yozing:</b>\n\n"
            f"{question['question']}\n\n"
            "✍️ Faqat javobni yuboring."
        )

        set_user_waiting(uid, qid)

        return

    # ---------------------------------------------
    # VAQT
    # ---------------------------------------------

    if data.startswith("time:") and uid == ADMIN_ID:
        seconds = int(data.split(":")[1])

        set_setting(
            "question_time",
            seconds
        )

        answer_callback(
            callback_id,
            f"⏱️ {question_time_text(seconds)} tanlandi."
        )

        send_message(
            ADMIN_ID,
            "✅ Savol vaqti o‘zgartirildi:\n\n"
            f"⏱️ <b>{question_time_text(seconds)}</b>\n\n"
            "Bu vaqt keyingi savollarga qo‘llanadi."
        )

        return

    # ---------------------------------------------
    # JAVOBNI TO‘G‘RI QILISH
    # ---------------------------------------------

    if data.startswith("ok:") and uid == ADMIN_ID:
        answer_id = int(data.split(":")[1])

        conn = db()

        row = conn.execute("""
            SELECT *
            FROM answers
            WHERE id=?
        """, (answer_id,)).fetchone()

        if not row:
            conn.close()
            answer_callback(
                callback_id,
                "Javob topilmadi.",
                True
            )
            return

        if row["points_awarded"] == 0:
            conn.execute("""
                UPDATE answers
                SET is_correct=1,
                    points_awarded=1
                WHERE id=?
            """, (answer_id,))

            conn.commit()

            conn.close()

            add_points(
                row["user_id"],
                1,
                f"Admin tuzatishi — javob #{answer_id}"
            )

            answer_callback(
                callback_id,
                "✅ +1 ball berildi."
            )
        else:
            conn.close()

            answer_callback(
                callback_id,
                "Bu javobga ball allaqachon berilgan."
            )

        return

    # ---------------------------------------------
    # +1
    # ---------------------------------------------

    if data.startswith("p1:") and uid == ADMIN_ID:
        target = int(data.split(":")[1])

        add_points(
            target,
            1,
            "Admin qo‘lda +1"
        )

        answer_callback(
            callback_id,
            "➕ +1 ball qo‘shildi."
        )

        send_message(
            ADMIN_ID,
            f"✅ <code>{target}</code> foydalanuvchiga +1 ball berildi."
        )

        return

    # ---------------------------------------------
    # -1
    # ---------------------------------------------

    if data.startswith("m1:") and uid == ADMIN_ID:
        target = int(data.split(":")[1])

        add_points(
            target,
            -1,
            "Admin qo‘lda -1"
        )

        answer_callback(
            callback_id,
            "➖ 1 ball olib tashlandi."
        )

        return


# =========================================================
# USER WAITING
# =========================================================

waiting_users = {}


def set_user_waiting(user_id, question_id):
    waiting_users[user_id] = question_id


def get_user_waiting(user_id):
    return waiting_users.get(user_id)


def clear_user_waiting(user_id):
    waiting_users.pop(user_id, None)


# =========================================================
# BROADCAST
# =========================================================

def broadcast_message(text):
    conn = db()

    rows = conn.execute("""
        SELECT user_id
        FROM members
        WHERE active=1
    """).fetchall()

    conn.close()

    success = 0
    failed = 0

    for row in rows:
        result = send_message(
            row["user_id"],
            text
        )

        if result.get("ok"):
            success += 1
        else:
            failed += 1

            conn = db()

            conn.execute("""
                UPDATE members
                SET active=0
                WHERE user_id=?
            """, (row["user_id"],))

            conn.commit()
            conn.close()

        time.sleep(0.05)

    return success, failed


# =========================================================
# HAFTALIK G‘OLIB
# =========================================================

def announce_previous_week():
    current = week_key()

    conn = db()

    rows = conn.execute("""
        SELECT DISTINCT week_key
        FROM weekly_scores
        WHERE week_key != ?
        ORDER BY week_key DESC
        LIMIT 1
    """, (current,)).fetchall()

    conn.close()

    if not rows:
        return

    old_week = rows[0]["week_key"]

    # Avval g‘olib e’lon qilinganmi?
    conn = db()

    prize = conn.execute("""
        SELECT *
        FROM prizes
        WHERE week_key=?
    """, (old_week,)).fetchone()

    conn.close()

    if prize:
        return

    ranking = get_ranking(old_week)

    if not ranking:
        return

    winner = ranking[0]

    name = winner["first_name"] or "Foydalanuvchi"

    send_message(
        CHANNEL,
        f"🏆 <b>HAFTA G‘OLIBI!</b>\n\n"
        f"🥇 <b>{name}</b>\n"
        f"⭐ {winner['points']} ball\n\n"
        f"📅 {old_week}\n\n"
        "🎉 Tabriklaymiz!"
    )

    # Placeholder prize yozuvi
    conn = db()

    conn.execute("""
        INSERT OR IGNORE INTO prizes(
            week_key,
            winner_user_id,
            prize_text,
            created_at
        )
        VALUES(?,?,?,?)
    """, (
        old_week,
        winner["user_id"],
        "Admin tomonidan belgilanadi",
        now()
    ))

    conn.commit()
    conn.close()


# =========================================================
# EXPIRED QUESTION CHECK
# =========================================================

def check_expired_question():
    question = get_active_question()

    if not question:
        return

    if now() >= question["ends_at"]:
        finish_expired_question(question)


# =========================================================
# COMMANDLAR
# =========================================================

def handle_message(message):
    user = message.get("from", {})
    chat = message.get("chat", {})

    uid = user.get("id")
    chat_id = chat.get("id")

    text = message.get("text", "").strip()

    if not uid or not chat_id:
        return

    member_upsert(user)

    # ---------------------------------------------
    # USERNING JAVOBI
    # ---------------------------------------------

    waiting = get_user_waiting(uid)

    if waiting and not text.startswith("/"):
        result = receive_answer(
            user,
            waiting,
            text
        )

        clear_user_waiting(uid)

        send_message(
            chat_id,
            result,
            user_keyboard()
        )

        return

    # ---------------------------------------------
    # /start
    # ---------------------------------------------

    if text.startswith("/start"):
        if uid == ADMIN_ID:
            send_admin_panel(chat_id)
        else:
            send_message(
                chat_id,
                "👋 <b>Algoritm Zakovat botiga xush kelibsiz!</b>\n\n"
                "🧠 Zakovat savollarida qatnashing.\n"
                "🏆 Haftalik reytingda yuqoriga chiqing.\n"
                "🎁 G‘olib bo‘ling!",
                user_keyboard()
            )

        return

    # ---------------------------------------------
    # /help
    # ---------------------------------------------

    if text == "/help":
        send_message(
            chat_id,
            "<b>ℹ️ YORDAM</b>\n\n"
            "🧠 Kanalda savol chiqadi.\n"
            "📝 «Javob berish» tugmasini bosing.\n"
            "✍️ Javobingizni botga yuboring.\n\n"
            "🏆 /reyting — haftalik reyting\n"
            "👤 /profil — shaxsiy profil\n"
            "📊 /stat — statistika"
        )

        return

    # ---------------------------------------------
    # USER COMMANDS
    # ---------------------------------------------

    if text in ["/reyting", "🏆 Reyting"]:
        send_message(
            chat_id,
            ranking_text(),
            user_keyboard()
        )
        return

    if text in ["/profil", "👤 Profil"]:
        send_message(
            chat_id,
            profile_text(uid),
            user_keyboard()
        )
        return

    if text in ["/stat", "📊 Statistika"]:
        show_statistics(chat_id)
        return

    if text == "ℹ️ Yordam":
        send_message(
            chat_id,
            "ℹ️ /help orqali bot haqida ma’lumot olishingiz mumkin."
        )
        return

    # =============================================
    # ADMIN
    # =============================================

    if uid != ADMIN_ID:
        return

    # ---------------------------------------------
    # /admin
    # ---------------------------------------------

    if text == "/admin":
        send_admin_panel(chat_id)
        return

    # ---------------------------------------------
    # SAVOL
    # ---------------------------------------------

    if text in ["/savol", "🧠 Savol qo‘shish"]:
        start_question_creation(chat_id)
        return

    # ---------------------------------------------
    # JAVOBLAR
    # ---------------------------------------------

    if text in ["/javoblar", "📋 Javoblar"]:
        show_answers(chat_id)
        return

    # ---------------------------------------------
    # REYTING
    # ---------------------------------------------

    if text == "🏆 Reyting":
        send_message(
            chat_id,
            ranking_text()
        )
        return

    # ---------------------------------------------
    # A'ZOLAR
    # ---------------------------------------------

    if text in ["/azolar", "👥 A’zolar"]:
        members_list(chat_id)
        return

    # ---------------------------------------------
    # STATISTIKA
    # ---------------------------------------------

    if text == "📊 Statistika":
        show_statistics(chat_id)
        return

    # ---------------------------------------------
    # TARIX
    # ---------------------------------------------

    if text in ["/tarix", "📚 Savollar tarixi"]:
        question_history(chat_id)
        return

    # ---------------------------------------------
    # VAQT
    # ---------------------------------------------

    if text in ["/vaqt", "⏱️ Savol vaqti"]:
        current = question_time_text()

        send_message(
            chat_id,
            f"⏱️ <b>Hozirgi vaqt:</b> {current}\n\n"
            "Yangi vaqtni tanlang:",
            time_keyboard()
        )

        return

    # ---------------------------------------------
    # BALL
    # ---------------------------------------------

    if text in ["/ball", "➕ Ball boshqaruvi"]:
        send_message(
            chat_id,
            "➕ <b>BALL BOSHQARUVI</b>\n\n"
            "Eng qulay usul — «📋 Javoblar» bo‘limidan "
            "foydalanuvchi yonidagi tugmalarni bosing.\n\n"
            "U yerdan:\n"
            "✅ To‘g‘ri +1\n"
            "➕ 1 ball\n"
            "➖ 1 ball"
        )

        return

    # ---------------------------------------------
    # XABAR
    # ---------------------------------------------

    if text in ["/xabar", "📢 Xabar yuborish"]:
        set_admin_state("broadcast")

        send_message(
            chat_id,
            "📢 Barcha bot a’zolariga yuboriladigan "
            "xabarni yozing.\n\n"
            "Bekor qilish: /bekor"
        )

        return

    # ---------------------------------------------
    # G‘OLIBLAR
    # ---------------------------------------------

    if text in ["/yutuq", "🎁 G‘oliblar"]:
        rows = get_ranking()

        if not rows:
            send_message(
                chat_id,
                "Hali g‘olib yo‘q."
            )
            return

        winner = rows[0]

        name = winner["first_name"] or "Foydalanuvchi"

        send_message(
            chat_id,
            f"🏆 <b>Joriy hafta yetakchisi</b>\n\n"
            f"🥇 {name}\n"
            f"⭐ {winner['points']} ball\n\n"
            "🎁 Sovrinni admin belgilaydi."
        )

        return

    # ---------------------------------------------
    # /yopish
    # ---------------------------------------------

    if text == "/yopish":
        q = get_active_question()

        if not q:
            send_message(
                chat_id,
                "Faol savol yo‘q."
            )
            return

        finish_expired_question(q)

        return

    # ---------------------------------------------
    # /bekor
    # ---------------------------------------------

    if text == "/bekor":
        clear_admin_state()

        q = get_active_question()

        if q:
            close_question(q["id"])

        send_message(
            chat_id,
            "🛑 Jarayon bekor qilindi."
        )

        return

    # ---------------------------------------------
    # ADMIN STATE
    # ---------------------------------------------

    if admin_state["state"] == "question_text":

        set_admin_state(
            "correct_answer",
            {
                "question": text
            }
        )

        send_message(
            chat_id,
            "✅ Savol qabul qilindi.\n\n"
            "Endi asosiy <b>to‘g‘ri javobni</b> yuboring:"
        )

        return

    if admin_state["state"] == "correct_answer":

        data = admin_state["data"]

        data["correct"] = text

        set_admin_state(
            "variants",
            data
        )

        send_message(
            chat_id,
            "✍️ Qo‘shimcha qabul qilinadigan javob "
            "variantlarini yuboring.\n\n"
            "Masalan:\n"
            "<code>Tashkent, Toshkent, Тошкент</code>\n\n"
            "Kerak bo‘lmasa <code>-</code> yuboring."
        )

        return

    if admin_state["state"] == "variants":

        data = admin_state["data"]

        if text == "-":
            variants = []
        else:
            variants = [
                x.strip()
                for x in text.split(",")
                if x.strip()
            ]

        data["variants"] = variants

        set_admin_state(
            "preview",
            data
        )

        variants_text = (
            ", ".join(variants)
            if variants
            else "Yo‘q"
        )

        send_message(
            chat_id,
            "<b>📋 SAVOL PREVIEW</b>\n\n"
            f"🧠 {data['question']}\n\n"
            f"✅ Asosiy javob: <b>{data['correct']}</b>\n"
            f"🔄 Variantlar: {variants_text}\n"
            f"⏱️ Vaqt: <b>{question_time_text()}</b>\n\n"
            "Savolni kanalga yuboraymi?\n"
            "Yuborish uchun: <code>/tasdiq</code>\n"
            "Bekor qilish: <code>/bekor</code>"
        )

        return

    if admin_state["state"] == "broadcast":

        success, failed = broadcast_message(text)

        clear_admin_state()

        send_message(
            chat_id,
            "📢 <b>Xabar yuborildi!</b>\n\n"
            f"✅ Yetkazildi: {success}\n"
            f"❌ Yetkazilmadi: {failed}"
        )

        return

    # ---------------------------------------------
    # /tasdiq
    # ---------------------------------------------

    if text == "/tasdiq":

        if admin_state["state"] != "preview":
            send_message(
                chat_id,
                "Tasdiqlanadigan savol yo‘q."
            )
            return

        finish_question_creation(chat_id)

        return


# =========================================================
# POLLING
# =========================================================

offset = 0


def polling():
    global offset

    print("🤖 Algoritm Zakovat bot ishga tushdi!")

    while True:

        try:
            check_expired_question()

            result = tg(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": json.dumps([
                        "message",
                        "callback_query"
                    ])
                }
            )

            if not result.get("ok"):
                time.sleep(3)
                continue

            updates = result.get(
                "result",
                []
            )

            for update in updates:

                offset = update["update_id"] + 1

                if "message" in update:
                    handle_message(
                        update["message"]
                    )

                elif "callback_query" in update:
                    handle_callback(
                        update["callback_query"]
                    )

            check_expired_question()

        except Exception as e:
            print("MAIN ERROR:", repr(e))
            time.sleep(3)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    polling()
