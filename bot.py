
import os
import time
import sqlite3
import logging
import requests

from datetime import datetime

# ========== SOZLAMALAR ==========
TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "5607350126"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@zakalgoritm")

API = f"https://api.telegram.org/bot{TOKEN}"
DB_NAME = "zakovat.db"
BOT_USERNAME = ""

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ALGORITM")

session = requests.Session()
states = {}
offset = 0


# ========== BAZA ==========
def connect():
    conn = sqlite3.connect(DB_NAME, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS members (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT ''
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tournaments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            status TEXT DEFAULT 'ready',
            current_number INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tournament_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tournament_id INTEGER,
            number INTEGER,
            question TEXT,
            answer TEXT,
            variants TEXT DEFAULT '',
            duration INTEGER,
            status TEXT DEFAULT 'pending',
            deadline REAL
        );

        CREATE TABLE IF NOT EXISTS tournament_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            user_id INTEGER,
            answer TEXT,
            points_awarded INTEGER DEFAULT 0,
            reviewed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(question_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT,
            answer TEXT,
            variants TEXT DEFAULT '',
            duration INTEGER,
            status TEXT DEFAULT 'draft',
            deadline REAL
        );

        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            user_id INTEGER,
            answer TEXT,
            points_awarded INTEGER DEFAULT 0,
            UNIQUE(question_id, user_id)
        );
        """)


# ========== TELEGRAM API ==========
def api(method, data=None):
    try:
        response = session.post(
            f"{API}/{method}",
            json=data or {},
            timeout=35
        )
        return response.json()
    except Exception as e:
        log.exception("Telegram API xatosi: %s", e)
        return {"ok": False}


def send(chat_id, text, markup=None):
    data = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True
    }
    if markup:
        data["reply_markup"] = markup
    return api("sendMessage", data)


def buttons(rows):
    return {"inline_keyboard": rows}


def admin(user_id):
    return int(user_id) == ADMIN_ID


def member_name(user_id):
    with connect() as c:
        row = c.execute(
            "SELECT username, first_name FROM members WHERE user_id=?",
            (user_id,)
        ).fetchone()

    if not row:
        return str(user_id)

    if row["username"]:
        return "@" + row["username"]

    return row["first_name"] or str(user_id)


def save_member(user):
    uid = user["id"]

    with connect() as c:
        c.execute("""
            INSERT INTO members(user_id, username, first_name)
            VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            first_name=excluded.first_name
        """, (
            uid,
            user.get("username", ""),
            user.get("first_name", "")
        ))

        c.execute(
            "INSERT OR IGNORE INTO scores(user_id,points) VALUES(?,0)",
            (uid,)
        )


def add_points(user_id, points, reason):
    with connect() as c:
        c.execute(
            "INSERT OR IGNORE INTO scores(user_id,points) VALUES(?,0)",
            (user_id,)
        )
        c.execute(
            "UPDATE scores SET points=points+? WHERE user_id=?",
            (points, user_id)
        )
        c.execute("""
            INSERT INTO score_history(user_id,points,reason)
            VALUES(?,?,?)
        """, (user_id, points, reason))


def bot_link(payload):
    return f"https://t.me/{BOT_USERNAME}?start={payload}"


# ========== ADMIN MENYUSI ==========
def admin_keyboard():
    return buttons([
        [
            {"text": "🏆 Turnirlar", "callback_data": "t:list"},
            {"text": "➕ Oddiy savol", "callback_data": "q:new"}
        ],
        [
            {"text": "🏅 Reyting", "callback_data": "rating"},
            {"text": "👥 A'zolar", "callback_data": "members"}
        ],
        [
            {"text": "📊 Statistika", "callback_data": "stats"},
            {"text": "📣 Xabar yuborish", "callback_data": "broadcast"}
        ]
    ])


def show_admin(chat_id):
    send(chat_id, "🛠 ALGORITM ZAKOVAT — ADMIN PANEL", admin_keyboard())


# ========== TURNIR YARATISH ==========
def create_tournament(user_id):
    states[user_id] = {"mode": "t_name"}
    send(user_id, "🏆 Turnir nomini yuboring.\nBekor qilish: /cancel")


def tournament_input(user_id, text):
    st = states[user_id]
    mode = st["mode"]

    if mode == "t_name":
        name = text.strip()

        if not name:
            send(user_id, "Turnir nomini kiriting.")
            return

        with connect() as c:
            c.execute(
                "INSERT INTO tournaments(name,status) VALUES(?,'ready')",
                (name,)
            )
            tid = c.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0]

        states[user_id] = {
            "mode": "t_count",
            "tid": tid,
            "name": name
        }
        send(user_id, "Turnirda nechta savol bo'ladi? 1–100 oralig'ida kiriting.")
        return

    if mode == "t_count":
        try:
            count = int(text)
            if not 1 <= count <= 100:
                raise ValueError
        except ValueError:
            send(user_id, "1 dan 100 gacha butun son kiriting.")
            return

        st["count"] = count
        st["number"] = 1
        st["mode"] = "t_question"
        send(user_id, f"📝 1/{count}-savol matnini yuboring.")
        return

    if mode == "t_question":
        st["question"] = text.strip()
        st["mode"] = "t_answer"
        send(user_id, "To'g'ri javobni yuboring.")
        return

    if mode == "t_answer":
        st["answer"] = text.strip()
        st["mode"] = "t_variants"
        send(
            user_id,
            "Muqobil javoblarni | bilan ajrating.\n"
            "Masalan: Toshkent|TASHKENT\n"
            "Muqobil javob yo'q bo'lsa - yuboring."
        )
        return

    if mode == "t_variants":
        st["variants"] = (
            "" if text.strip() == "-"
            else "|".join(x.strip() for x in text.split("|") if x.strip())
        )
        st["mode"] = "t_duration"
        send(
            user_id,
            "⏱ Javob berish vaqtini soniyada kiriting.\n"
            "2 daqiqa = 120\n3 daqiqa = 180"
        )
        return

    if mode == "t_duration":
        try:
            duration = int(text)
            if not 10 <= duration <= 7200:
                raise ValueError
        except ValueError:
            send(user_id, "10–7200 soniya oralig'ida kiriting.")
            return

        with connect() as c:
            c.execute("""
                INSERT INTO tournament_questions
                (tournament_id,number,question,answer,variants,duration,status)
                VALUES(?,?,?,?,?,?,'pending')
            """, (
                st["tid"],
                st["number"],
                st["question"],
                st["answer"],
                st["variants"],
                duration
            ))

        if st["number"] < st["count"]:
            st["number"] += 1
            st["mode"] = "t_question"
            send(
                user_id,
                f"✅ Savol saqlandi.\n📝 {st['number']}/{st['count']}-savol matnini yuboring."
            )
        else:
            tid = st["tid"]
            name = st["name"]
            states.pop(user_id, None)

            send(
                user_id,
                f"🎉 Turnir saqlandi!\nNomi: {name}\nID: {tid}\n"
                "Turnirlar menyusidan istalgan vaqtda boshlashingiz mumkin.",
                buttons([
                    [{"text": "🏆 Turnirlar", "callback_data": "t:list"}]
                ])
            )


# ========== TURNIRLARNI KO'RISH VA BOSHLASH ==========
def list_tournaments(chat_id):
    with connect() as c:
        tournaments = c.execute(
            "SELECT * FROM tournaments ORDER BY id DESC"
        ).fetchall()

    rows = []
    lines = ["🏆 SAQLANGAN TURNIRLAR\n"]

    for t in tournaments:
        with connect() as c:
            count = c.execute(
                "SELECT COUNT(*) FROM tournament_questions WHERE tournament_id=?",
                (t["id"],)
            ).fetchone()[0]

        lines.append(
            f"#{t['id']} — {t['name']} | {count} ta savol | {t['status']}"
        )

        if t["status"] == "ready" and count > 0:
            rows.append([{
                "text": f"▶️ Boshlash: #{t['id']} {t['name'][:20]}",
                "callback_data": f"t:start:{t['id']}"
            }])

    rows.append([{"text": "➕ Turnir yaratish", "callback_data": "t:new"}])
    rows.append([{"text": "⬅️ Admin panel", "callback_data": "admin"}])

    send(chat_id, "\n".join(lines), buttons(rows))


def start_tournament(tid):
    with connect() as c:
        active = c.execute(
            "SELECT id FROM tournaments WHERE status='running'"
        ).fetchone()

        if active:
            send(ADMIN_ID, "❗ Avval davom etayotgan turnir tugashini kuting.")
            return

        t = c.execute(
            "SELECT * FROM tournaments WHERE id=?",
            (tid,)
        ).fetchone()

        if not t or t["status"] != "ready":
            send(ADMIN_ID, "Turnir topilmadi yoki uni boshlash mumkin emas.")
            return

        q = c.execute("""
            SELECT * FROM tournament_questions
            WHERE tournament_id=?
            ORDER BY number LIMIT 1
        """, (tid,)).fetchone()

        if not q:
            send(ADMIN_ID, "Turnirda savollar yo'q.")
            return

        c.execute(
            "UPDATE tournaments SET status='running',current_number=0 WHERE id=?",
            (tid,)
        )

    publish_tournament_question(q["id"])


def publish_tournament_question(qid):
    with connect() as c:
        q = c.execute(
            "SELECT * FROM tournament_questions WHERE id=?",
            (qid,)
        ).fetchone()

        t = c.execute(
            "SELECT * FROM tournaments WHERE id=?",
            (q["tournament_id"],)
        ).fetchone()

        deadline = time.time() + q["duration"]

        c.execute("""
            UPDATE tournament_questions
            SET status='active',deadline=?
            WHERE id=?
        """, (deadline, qid))

        c.execute(
            "UPDATE tournaments SET current_number=? WHERE id=?",
            (q["number"], q["tournament_id"])
        )

    message = (
        f"🏆 {t['name']}\n"
        f"🧠 {q['number']}-savol\n\n"
        f"{q['question']}\n\n"
        f"⏱ Vaqt: {q['duration']} soniya"
    )

    result = send(
        CHANNEL_ID,
        message,
        buttons([[
            {
                "text": "✍️ Javob berish",
                "url": bot_link(f"ta_{qid}")
            }
        ]])
    )

    send(
        ADMIN_ID,
        f"▶️ Turnir boshlandi: {t['name']}\n"
        f"{q['number']}-savol, vaqt: {q['duration']} soniya."
    )


# ========== TURNIR JAVOBLARI ==========
def submit_tournament_answer(user_id, qid, text):
    with connect() as c:
        q = c.execute(
            "SELECT * FROM tournament_questions WHERE id=?",
            (qid,)
        ).fetchone()

        if not q or q["status"] != "active" or time.time() > q["deadline"]:
            send(user_id, "⏰ Javob berish vaqti tugagan.")
            return

        t = c.execute(
            "SELECT * FROM tournaments WHERE id=?",
            (q["tournament_id"],)
        ).fetchone()

        if not t or t["status"] != "running":
            send(user_id, "Turnir hozir faol emas.")
            return

        try:
            c.execute("""
                INSERT INTO tournament_answers(question_id,user_id,answer)
                VALUES(?,?,?)
            """, (qid, user_id, text))
        except sqlite3.IntegrityError:
            send(user_id, "Siz bu savolga allaqachon javob yuborgansiz.")
            return

        aid = c.execute("SELECT last_insert_rowid()").fetchone()[0]

    send(user_id, "📩 Javobingiz qabul qilindi. Ballni admin belgilaydi.")

    send(
        ADMIN_ID,
        f"📨 TURNIR JAVOBI\n\n"
        f"Turnir: {t['name']}\n"
        f"Savol: {q['number']}\n"
        f"Ishtirokchi: {member_name(user_id)}\n"
        f"Telegram ID: {user_id}\n"
        f"Javob: {text}",
        buttons([[
            {"text": "➕ +1", "callback_data": f"score:t:{aid}:1"},
            {"text": "➖ −1", "callback_data": f"score:t:{aid}:-1"},
            {"text": "0 ball", "callback_data": f"score:t:{aid}:0"}
        ]])
    )


def review_tournament_answer(aid, points):
    with connect() as c:
        a = c.execute(
            "SELECT * FROM tournament_answers WHERE id=?",
            (aid,)
        ).fetchone()

        if not a:
            return "Javob topilmadi."

        old = a["points_awarded"]
        delta = points - old

        c.execute(
            "UPDATE tournament_answers SET points_awarded=?,reviewed=1 WHERE id=?",
            (points, aid)
        )

    if delta:
        add_points(a["user_id"], delta, f"Turnir javobi #{aid}")

    return f"{member_name(a['user_id'])}: {old:+d} → {points:+d} ball."


# ========== SAVOL VAQTI TUGASHI ==========
def check_expired_questions():
    current = time.time()

    with connect() as c:
        expired = c.execute("""
            SELECT * FROM tournament_questions
            WHERE status='active' AND deadline<=?
        """, (current,)).fetchall()

    for q in expired:
        with connect() as c:
            c.execute(
                "UPDATE tournament_questions SET status='closed' WHERE id=?",
                (q["id"],)
            )
            t = c.execute(
                "SELECT * FROM tournaments WHERE id=?",
                (q["tournament_id"],)
            ).fetchone()

            nxt = c.execute("""
                SELECT * FROM tournament_questions
                WHERE tournament_id=? AND number>?
                ORDER BY number LIMIT 1
            """, (q["tournament_id"], q["number"])).fetchone()

        send(
            CHANNEL_ID,
            f"⏰ {t['name']} — {q['number']}-savol yopildi!\n"
            f"Javob: {q['answer']}"
        )

        if nxt:
            publish_tournament_question(nxt["id"])
        else:
            finish_tournament(t["id"])


# ========== TURNIR HISOBOTI ==========
def finish_tournament(tid):
    with connect() as c:
        t = c.execute(
            "SELECT * FROM tournaments WHERE id=?",
            (tid,)
        ).fetchone()

        c.execute(
            "UPDATE tournaments SET status='finished' WHERE id=?",
            (tid,)
        )

        questions = c.execute("""
            SELECT * FROM tournament_questions
            WHERE tournament_id=? ORDER BY number
        """, (tid,)).fetchall()

    report = [f"🏁 TURNIR YAKUNLANDI: {t['name']}", ""]

    with connect() as c:
        ranking = c.execute("""
            SELECT s.user_id,s.points
            FROM scores s
            JOIN (
                SELECT DISTINCT ta.user_id
                FROM tournament_answers ta
                JOIN tournament_questions tq ON tq.id=ta.question_id
                WHERE tq.tournament_id=?
            ) participants ON participants.user_id=s.user_id
            ORDER BY s.points DESC
        """, (tid,)).fetchall()

    report.append("🏅 Reyting:")
    for i, r in enumerate(ranking, 1):
        report.append(f"{i}. {member_name(r['user_id'])} — {r['points']} umumiy ball")

    report.append("\n📋 Batafsil javoblar:")

    for q in questions:
        report.append(
            f"\n{q['number']}-savol: {q['question']}\n"
            f"To'g'ri javob: {q['answer']}"
        )

        with connect() as c:
            answers = c.execute("""
                SELECT * FROM tournament_answers
                WHERE question_id=? ORDER BY id
            """, (q["id"],)).fetchall()

        if not answers:
            report.append("Javob bo'lmadi.")

        for a in answers:
            report.append(
                f"• {member_name(a['user_id'])}: {a['answer']} "
                f"| {a['points_awarded']:+d} ball"
            )

    full = "\n".join(report)

    # Telegram xabar uzunligini cheklash uchun hisobotni bo'lib yuborish.
    for i in range(0, len(full), 3500):
        send(ADMIN_ID, full[i:i + 3500])

    send(CHANNEL_ID, f"🏆 {t['name']} turniri yakunlandi! Ishtirokchilarga rahmat.")


# ========== CALLBACKLAR ==========
def callback_handler(cb):
    data = cb.get("data", "")
    uid = cb["from"]["id"]
    chat_id = cb["message"]["chat"]["id"]
    callback_id = cb["id"]

    api("answerCallbackQuery", {"callback_query_id": callback_id})

    if admin(uid):
        if data == "admin":
            show_admin(chat_id)

        elif data == "t:list":
            list_tournaments(chat_id)

        elif data == "t:new":
            create_tournament(uid)

        elif data.startswith("t:start:"):
            start_tournament(int(data.split(":")[2]))

        elif data == "q:new":
            states[uid] = {"mode": "q_text"}
            send(uid, "Oddiy savol matnini yuboring.")

        elif data.startswith("score:t:"):
            _, _, aid, points = data.split(":")
            result = review_tournament_answer(int(aid), int(points))
            send(ADMIN_ID, "✅ " + result)

        elif data == "rating":
            with connect() as c:
                rows = c.execute(
                    "SELECT user_id,points FROM scores ORDER BY points DESC LIMIT 20"
                ).fetchall()

            lines = ["🏅 REYTING"]
            for i, r in enumerate(rows, 1):
                lines.append(
                    f"{i}. {member_name(r['user_id'])} — {r['points']} ball"
                )
            send(chat_id, "\n".join(lines))

        elif data == "members":
            with connect() as c:
                n = c.execute("SELECT COUNT(*) FROM members").fetchone()[0]
            send(chat_id, f"👥 Botdagi a'zolar: {n}")

        elif data == "stats":
            with connect() as c:
                members = c.execute("SELECT COUNT(*) FROM members").fetchone()[0]
                tournaments = c.execute("SELECT COUNT(*) FROM tournaments").fetchone()[0]
                answers = c.execute("SELECT COUNT(*) FROM tournament_answers").fetchone()[0]
            send(chat_id, f"📊 Statistika\nA'zolar: {members}\nTurnirlar: {tournaments}\nTurnir javoblari: {answers}")

        elif data == "broadcast":
            states[uid] = {"mode": "broadcast"}
            send(uid, "Barcha a'zolarga yuboriladigan xabarni kiriting.")

    else:
        if data == "user:rating":
            with connect() as c:
                rows = c.execute(
                    "SELECT user_id,points FROM scores ORDER BY points DESC LIMIT 10"
                ).fetchall()
            lines = ["🏅 TOP-10"]
            for i, r in enumerate(rows, 1):
                lines.append(f"{i}. {member_name(r['user_id'])} — {r['points']}")
            send(chat_id, "\n".join(lines))


# ========== XABARLARNI QABUL QILISH ==========
def message_handler(message):
    user = message.get("from", {})
    uid = user.get("id")
    chat_id = message["chat"]["id"]
    text = (message.get("text") or "").strip()

    if not uid or not text:
        return

    save_member(user)

    if text == "/cancel":
        states.pop(uid, None)
        send(chat_id, "Amal bekor qilindi.")
        return

    if text.startswith("/start"):
        payload = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else ""

        if payload.startswith("ta_"):
            try:
                qid = int(payload[3:])
            except ValueError:
                send(chat_id, "Savol havolasi noto'g'ri.")
                return

            with connect() as c:
                q = c.execute(
                    "SELECT * FROM tournament_questions WHERE id=?",
                    (qid,)
                ).fetchone()

            if not q or q["status"] != "active" or time.time() > q["deadline"]:
                send(chat_id, "⏰ Bu savol uchun vaqt tugagan.")
                return

            states[uid] = {"mode": "answer_tournament", "qid": qid}
            send(chat_id, f"🧠 Savol:\n{q['question']}\n\nJavobingizni yuboring.")
            return

        if admin(uid):
            show_admin(chat_id)
        else:
            send(
                chat_id,
                "Xush kelibsiz! ALGORITM Zakovat botiga xush kelibsiz.",
                buttons([[
                    {"text": "🏅 Reyting", "callback_data": "user:rating"}
                ]])
            )
        return

    if text == "/admin":
        if admin(uid):
            show_admin(chat_id)
        else:
            send(chat_id, "Bu buyruq faqat admin uchun.")
        return

    st = states.get(uid, {})
    mode = st.get("mode")

    if mode and mode.startswith("t_"):
        tournament_input(uid, text)
        return

    if mode == "answer_tournament":
        qid = st["qid"]
        states.pop(uid, None)
        submit_tournament_answer(uid, qid, text)
        return

    if admin(uid):
        if mode == "q_text":
            st["question"] = text
            st["mode"] = "q_answer"
            send(uid, "To'g'ri javobni yuboring.")

        elif mode == "q_answer":
            st["answer"] = text
            st["mode"] = "q_duration"
            send(uid, "Vaqtni soniyada yuboring. Masalan, 900 = 15 daqiqa.")

        elif mode == "q_duration":
            try:
                duration = int(text)
                if duration < 10:
                    raise ValueError
            except ValueError:
                send(uid, "Kamida 10 soniya kiriting.")
                return

            with connect() as c:
                c.execute("""
                    INSERT INTO questions(question,answer,duration,status)
                    VALUES(?,?,?,'active')
                """, (st["question"], st["answer"], duration))
                qid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
                c.execute(
                    "UPDATE questions SET deadline=? WHERE id=?",
                    (time.time() + duration, qid)
                )

            states.pop(uid, None)
            send(
                CHANNEL_ID,
                f"🧠 ALGORITM ZAKOVAT\n\n{st['question']}\n\n"
                f"⏱ Vaqt: {duration} soniya",
                buttons([[
                    {"text": "✍️ Javob berish", "url": bot_link(f"qa_{qid}")}
                ]])
            )
            send(uid, "✅ Oddiy savol kanalga yuborildi.")
        elif mode == "broadcast":
            states.pop(uid, None)
            with connect() as c:
                users = c.execute("SELECT user_id FROM members").fetchall()

            sent = 0
            for row in users:
                if send(row["user_id"], text).get("ok"):
                    sent += 1
                time.sleep(0.05)

            send(uid, f"📣 Xabar yuborildi: {sent}/{len(users)}")
        else:
            show_admin(uid)

    else:
        send(chat_id, "Savolga javob berish uchun kanal postidagi tugmani bosing.")


# ========== ISHGA TUSHIRISH ==========
def main():
    global offset, BOT_USERNAME

    if not TOKEN:
        print("BOT_TOKEN sozlanmagan. Hosting Secrets bo'limiga kiriting.")
        return

    init_db()
    api("deleteWebhook", {"drop_pending_updates": False})

    me = api("getMe")
    if not me.get("ok"):
        print("Token xato yoki Telegram API bilan aloqa yo'q.")
        return

    BOT_USERNAME = me["result"]["username"]
    send(ADMIN_ID, "✅ ALGORITM Zakovat ishga tushdi.\nAdmin panel: /admin")

    print(f"Bot ishga tushdi: @{BOT_USERNAME}")

    while True:
        try:
            result = api("getUpdates", {
                "offset": offset,
                "timeout": 25,
                "allowed_updates": ["message", "callback_query"]
            })

            if result.get("ok"):
                for update in result.get("result", []):
                    offset = update["update_id"] + 1

                    if "message" in update:
                        message_handler(update["message"])

                    elif "callback_query" in update:
                        callback_handler(update["callback_query"])

            check_expired_questions()

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception("Xatolik: %s", e)
            time.sleep(3)


if __name__ == "__main__":
    main()
