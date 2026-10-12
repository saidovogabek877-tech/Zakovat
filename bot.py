import os, time, sqlite3, html, requests
from datetime import datetime, timezone, timedelta

# ================= CONFIG =================
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise RuntimeError('BOT_TOKEN topilmadi. Hosting Environment sozlamalarini tekshiring.')
ADMIN_ID = 5607350126
CHANNEL = '@zakalgoritm'
API = f'https://api.telegram.org/bot{TOKEN}'
TZ = timezone(timedelta(hours=5))
DB_FILE = 'zakovat.db'
DEFAULT_DURATION = 900
ALLOWED_DURATIONS = {60, 120, 180, 600, 900, 1800, 3600}

# ================= DATABASE =================
db = sqlite3.connect(DB_FILE, check_same_thread=False, timeout=30)
db.row_factory = sqlite3.Row
db.execute('PRAGMA journal_mode=WAL')
db.executescript(''' CREATE TABLE IF NOT EXISTS members(user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '', joined_at INTEGER); CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, correct_answer TEXT NOT NULL, variants TEXT DEFAULT '', duration INTEGER NOT NULL, created_at INTEGER NOT NULL, start_time INTEGER, active INTEGER DEFAULT 0, channel_message_id INTEGER); CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY AUTOINCREMENT, question_id INTEGER NOT NULL, user_id INTEGER NOT NULL, username TEXT DEFAULT '', first_name TEXT DEFAULT '', answer TEXT NOT NULL, correct INTEGER DEFAULT 0, points INTEGER DEFAULT 0, created_at INTEGER NOT NULL, UNIQUE(question_id,user_id)); CREATE TABLE IF NOT EXISTS scores(user_id INTEGER PRIMARY KEY, points INTEGER DEFAULT 0); CREATE TABLE IF NOT EXISTS score_history(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, points INTEGER, reason TEXT, created_at INTEGER); CREATE TABLE IF NOT EXISTS prizes(id INTEGER PRIMARY KEY AUTOINCREMENT, week_key TEXT UNIQUE, winner_user_id INTEGER, prize TEXT DEFAULT '', created_at INTEGER); CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT); CREATE TABLE IF NOT EXISTS tournaments(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', created_at INTEGER NOT NULL, started_at INTEGER, finished_at INTEGER); CREATE TABLE IF NOT EXISTS tournament_questions(id INTEGER PRIMARY KEY AUTOINCREMENT, tournament_id INTEGER NOT NULL, question_no INTEGER NOT NULL, question TEXT NOT NULL, correct_answer TEXT NOT NULL, variants TEXT DEFAULT '', duration INTEGER NOT NULL, start_time INTEGER, active INTEGER DEFAULT 0, channel_message_id INTEGER, UNIQUE(tournament_id,question_no)); CREATE TABLE IF NOT EXISTS tournament_answers(id INTEGER PRIMARY KEY AUTOINCREMENT, tournament_id INTEGER NOT NULL, question_id INTEGER NOT NULL, user_id INTEGER NOT NULL, username TEXT DEFAULT '', first_name TEXT DEFAULT '', answer TEXT NOT NULL, points_awarded INTEGER DEFAULT 0, reviewed INTEGER DEFAULT 0, created_at INTEGER NOT NULL, UNIQUE(question_id,user_id)); ''')
# Add column safely for databases created by earlier versions.
cols = {r['name'] for r in db.execute('PRAGMA table_info(questions)').fetchall()}
if 'channel_message_id' not in cols:
    db.execute('ALTER TABLE questions ADD COLUMN channel_message_id INTEGER')
db.commit()
states = {}
BOT_USERNAME = ''

# ================= TELEGRAM / HELPERS =================
def tg(method, data=None):
    try:
        r = requests.post(f'{API}/{method}', json=data or {}, timeout=35)
        out = r.json()
        if not out.get('ok'): print('Telegram API:', method, out)
        return out
    except Exception as e:
        print('Telegram ERROR:', e)
        return {}

def send_message(chat_id, text, keyboard=None):
    data = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    if keyboard: data['reply_markup'] = {'inline_keyboard': keyboard}
    return tg('sendMessage', data)

def edit_message(chat_id, message_id, text, keyboard=None):
    data = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'parse_mode': 'HTML'}
    if keyboard: data['reply_markup'] = {'inline_keyboard': keyboard}
    return tg('editMessageText', data)

def callback_answer(cid, text=''):
    tg('answerCallbackQuery', {'callback_query_id': cid, 'text': text})

def now(): return int(time.time())
def safe_text(x): return html.escape(str(x or ''))
def clean(x):
    return str(x or '').casefold().strip().replace('’', "'").replace('‘', "'").replace('ʻ', "'").replace('`', "'")
def is_admin(uid): return uid == ADMIN_ID

def format_duration(seconds):
    return f'{seconds // 60} daqiqa' if seconds % 60 == 0 else f'{seconds} soniya'

def get_setting(key, default=None):
    r = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return r['value'] if r else default

def set_setting(key, value):
    db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))
    db.commit()

def get_duration():
    try:
        n = int(get_setting('question_duration', DEFAULT_DURATION))
        return n if n in ALLOWED_DURATIONS else DEFAULT_DURATION
    except (TypeError, ValueError): return DEFAULT_DURATION

def save_member(user):
    db.execute('''INSERT INTO members(user_id,username,first_name,joined_at) VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name''',
    (user['id'], user.get('username',''), user.get('first_name',''), now()))
    db.commit()

def get_score(uid):
    r = db.execute('SELECT points FROM scores WHERE user_id=?', (uid,)).fetchone()
    return r['points'] if r else 0

def add_score(uid, delta, reason):
    db.execute('INSERT INTO scores(user_id,points) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET points=points+excluded.points', (uid, delta))
    db.execute('INSERT INTO score_history(user_id,points,reason,created_at) VALUES(?,?,?,?)', (uid, delta, reason, now()))
    db.commit()

def get_level(points):
    if points <= 10: return '🌱 Beginner'
    if points <= 30: return '📘 Bilimdon'
    if points <= 60: return '🧠 Zakovatchi'
    return '👑 Usta'

def is_correct(user_answer, correct_answer, variants):
    options = [correct_answer] + ([x.strip() for x in (variants or '').split(',') if x.strip()])
    return clean(user_answer) in {clean(x) for x in options}

# ================= ADMIN PANEL =================
def admin_keyboard():
    return [
      [{'text':'🧠 Savol qo‘shish','callback_data':'admin_add'},{'text':'📋 Javoblar','callback_data':'admin_answers'}],
      [{'text':'🏆 Reyting','callback_data':'admin_rating'},{'text':'👥 A’zolar','callback_data':'admin_members'}],
      [{'text':'📊 Statistika','callback_data':'admin_stats'},{'text':'📚 Savollar tarixi','callback_data':'admin_history'}],
      [{'text':'➕ Ball boshqaruvi','callback_data':'admin_points'},{'text':'📢 Xabar yuborish','callback_data':'admin_broadcast'}],
      [{'text':'⏱️ Savol vaqti','callback_data':'admin_time'},{'text':'🎁 Haftalik TOP-3','callback_data':'admin_winners'}],
      [{'text':'🏆 Turnirlar','callback_data':'tr_menu'}]
    ]

def show_admin(chat_id):
    if is_admin(chat_id): send_message(chat_id, '<b>⚙️ ADMIN PANEL</b>\n\nKerakli bo‘limni tanlang:', admin_keyboard())

# ================= ORDINARY QUESTION FLOW =================
def start_question(chat_id):
    if not is_admin(chat_id): return
    states[chat_id] = {'state':'question','duration':get_duration()}
    send_message(chat_id, '<b>🧠 Yangi savol</b>\n\nSavol matnini yuboring. Bekor qilish: /bekor')

def process_question(chat_id, text):
    s = states.get(chat_id)
    if not s: return False
    if s['state'] == 'question':
        s['question'] = text; s['state'] = 'answer'
        send_message(chat_id, 'To‘g‘ri javobni yuboring.'); return True
    if s['state'] == 'answer':
        s['answer'] = text; s['state'] = 'variants'
        send_message(chat_id, 'Javob variantlarini vergul bilan kiriting yoki variant bo‘lmasa - yuboring.'); return True
    if s['state'] == 'variants':
        s['variants'] = '' if text.strip() == '-' else text
        s['state'] = 'preview'
        send_message(chat_id, '<b>📋 SAVOL PREVYU</b>\n\n'
          f"🧠 {safe_text(s['question'])}\n\n✅ Javob: {safe_text(s['answer'])}\n"
          f"🔤 Variantlar: {safe_text(s['variants'] or 'yo‘q')}\n⏱ Vaqt: {format_duration(s['duration'])}",
          [[{'text':'📢 Kanalga chiqarish','callback_data':'question_publish'},{'text':'❌ Bekor','callback_data':'question_cancel'}]])
        return True
    return False

def publish_question(chat_id):
    s = states.get(chat_id)
    if not is_admin(chat_id) or not s or s.get('state') != 'preview': return
    start = now()
    cur = db.execute('INSERT INTO questions(question,correct_answer,variants,duration,created_at,start_time,active) VALUES(?,?,?,?,?,?,1)',
       (s['question'],s['answer'],s['variants'],s['duration'],start,start))
    db.commit(); qid = cur.lastrowid
    result = send_message(CHANNEL, '<b>🧠 ZAKOVAT SAVOLI</b>\n\n'
       f"{safe_text(s['question'])}\n\n⏱ Vaqt: {format_duration(s['duration'])}\n\nJavob berish uchun tugmani bosing.",
       [[{'text':'📝 Javob berish','callback_data':f'answer:{qid}'}]])
    if result.get('ok'):
        db.execute('UPDATE questions SET channel_message_id=? WHERE id=?',(result['result']['message_id'],qid)); db.commit()
        states.pop(chat_id,None); send_message(chat_id,'✅ Savol kanalga yuborildi.')
    else:
        db.execute('UPDATE questions SET active=0 WHERE id=?',(qid,)); db.commit()
        send_message(chat_id,'❌ Kanalga yuborilmadi. Botning kanal adminligi va post huquqini tekshiring.')

def request_answer(uid, qid):
    states[uid] = {'state':'answering','question_id':qid}
    send_message(uid, '📝 Javobingizni yozing:')

def process_user_answer(message):
    user = message['from']; uid = user['id']; s = states.get(uid)
    if not s or s.get('state') != 'answering': return False
    qid = s['question_id']; text = message.get('text','').strip()
    q = db.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone()
    if not q or not q['active'] or not q['start_time'] or now() >= q['start_time'] + q['duration']:
        send_message(uid,'⏰ Bu savol yopilgan.'); states.pop(uid,None); return True
    existing = db.execute('SELECT id FROM answers WHERE question_id=? AND user_id=?',(qid,uid)).fetchone()
    if existing:
        send_message(uid,'⚠️ Siz bu savolga allaqachon javob bergansiz.'); states.pop(uid,None); return True
    correct = is_correct(text,q['correct_answer'],q['variants']); points = 1 if correct else 0
    try:
        db.execute('INSERT INTO answers(question_id,user_id,username,first_name,answer,correct,points,created_at) VALUES(?,?,?,?,?,?,?,?)',
           (qid,uid,user.get('username',''),user.get('first_name',''),text,int(correct),points,now())); db.commit()
    except sqlite3.IntegrityError:
        send_message(uid,'⚠️ Javobingiz avval qabul qilingan.'); states.pop(uid,None); return True
    if correct: add_score(uid,1,f'Savol #{qid}')
    send_message(uid, '✅ <b>To‘g‘ri javob!</b> 🏆 +1 ball' if correct else '❌ <b>Noto‘g‘ri javob.</b> Keyingi savolda omad!')
    aid = db.execute('SELECT id FROM answers WHERE question_id=? AND user_id=?',(qid,uid)).fetchone()['id']
    send_message(ADMIN_ID, '<b>📩 Oddiy savol javobi</b>\n\n'
       f"🧠 Savol #{qid}\n👤 {safe_text(user.get('first_name','Noma’lum'))}\n"
       f"🔗 {safe_text('@'+user['username'] if user.get('username') else 'username yo‘q')}\n"
       f"🆔 <code>{uid}</code>\n📝 {safe_text(text)}\n{'✅ To‘g‘ri' if correct else '❌ Noto‘g‘ri'}\n🏆 {points} ball",
       [[{'text':'+1 ball','callback_data':f'correct:{aid}'},{'text':'Ball +1','callback_data':f'plus:{aid}'},{'text':'Ball −1','callback_data':f'minus:{aid}'}]])
    states.pop(uid,None); return True

# ================= PROFILE / RATINGS =================
def show_profile(chat_id, uid):
    member = db.execute('SELECT * FROM members WHERE user_id=?',(uid,)).fetchone()
    score = get_score(uid)
    row = db.execute('SELECT COUNT(*) AS total, SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS correct FROM answers WHERE user_id=?',(uid,)).fetchone()
    # Do not expose global rank to members.
    send_message(chat_id, '<b>👤 PROFIL</b>\n\n'
      f"👤 {safe_text(member['first_name'] if member else 'Foydalanuvchi')}\n🏆 Ball: <b>{score}</b>\n"
      f"📝 Oddiy savol javoblari: {row['total'] or 0}\n✅ To‘g‘ri: {row['correct'] or 0}\n🎖 Daraja: {get_level(score)}")

def show_rating(chat_id):
    if not is_admin(chat_id): send_message(chat_id,'🔒 Reyting faqat admin uchun ochiq.'); return
    rows = db.execute('SELECT s.user_id,s.points,m.first_name,m.username FROM scores s LEFT JOIN members m ON m.user_id=s.user_id ORDER BY s.points DESC LIMIT 50').fetchall()
    if not rows: send_message(chat_id,'Reyting hozircha bo‘sh.'); return
    text='<b>🏆 UMUMIY REYTING</b>\n\n'; medals={1:'🥇',2:'🥈',3:'🥉'}
    for i,r in enumerate(rows,1): text += f"{medals.get(i,str(i)+'.')} {safe_text(r['first_name'] or r['username'] or r['user_id'])} — <b>{r['points']}</b> ball\n"
    send_message(chat_id,text)

def show_answers(chat_id):
    if not is_admin(chat_id): return
    rows=db.execute('SELECT * FROM answers ORDER BY id DESC LIMIT 20').fetchall()
    if not rows: send_message(chat_id,'Javoblar hozircha yo‘q.'); return
    for r in rows:
        name=db.execute('SELECT first_name,username FROM members WHERE user_id=?',(r['user_id'],)).fetchone()
        nm=(name['first_name'] or name['username']) if name else str(r['user_id'])
        send_message(chat_id,f"<b>Javob #{r['id']}</b> — savol #{r['question_id']}\n👤 {safe_text(nm)} (<code>{r['user_id']}</code>)\n📝 {safe_text(r['answer'])}\n🏆 {r['points']} ball",
         [[{'text':'+1 ball','callback_data':f"correct:{r['id']}"},{'text':'Ball +1','callback_data':f"plus:{r['id']}"},{'text':'Ball −1','callback_data':f"minus:{r['id']}"}]])

def adjust_regular_answer(aid, mode):
    r=db.execute('SELECT * FROM answers WHERE id=?',(aid,)).fetchone()
    if not r: return 'Javob topilmadi.'
    old=r['points']
    if mode=='correct': new=1
    elif mode=='plus': new=old+1
    else: new=old-1
    delta=new-old
    db.execute('UPDATE answers SET points=?, correct=? WHERE id=?',(new,1 if new>=1 else r['correct'],aid)); db.commit()
    if delta: add_score(r['user_id'],delta,f'Admin {mode} javob #{aid}')
    return f'Javob #{aid}: {old} → {new} ball.'

def show_members(chat_id):
    if not is_admin(chat_id): return
    total=db.execute('SELECT COUNT(*) c FROM members').fetchone()['c']
    rows=db.execute('SELECT first_name,username,user_id FROM members ORDER BY joined_at DESC LIMIT 30').fetchall()
    text=f'<b>👥 A’ZOLAR</b>\nJami: <b>{total}</b>\n\n'
    for r in rows: text+=f"• {safe_text(r['first_name'] or r['username'] or 'Noma’lum')} <code>{r['user_id']}</code>\n"
    send_message(chat_id,text)

def show_stats(chat_id):
    if not is_admin(chat_id): return
    vals={k:db.execute(sql).fetchone()['c'] for k,sql in {
      'members':'SELECT COUNT(*) c FROM members','questions':'SELECT COUNT(*) c FROM questions','answers':'SELECT COUNT(*) c FROM answers',
      'correct':'SELECT COUNT(*) c FROM answers WHERE correct=1','active':'SELECT COUNT(*) c FROM questions WHERE active=1',
      'tournaments':'SELECT COUNT(*) c FROM tournaments'}.items()}
    send_message(chat_id,'<b>📊 STATISTIKA</b>\n\n'+f"👥 A’zolar: {vals['members']}\n🧠 Oddiy savollar: {vals['questions']}\n📝 Javoblar: {vals['answers']}\n✅ To‘g‘ri: {vals['correct']}\n❌ Noto‘g‘ri: {vals['answers']-vals['correct']}\n🟢 Faol savollar: {vals['active']}\n🏆 Turnirlar: {vals['tournaments']}")

def show_history(chat_id):
    if not is_admin(chat_id): return
    rows=db.execute('SELECT id,question,duration,active FROM questions ORDER BY id DESC LIMIT 20').fetchall()
    if not rows: send_message(chat_id,'Savollar tarixi bo‘sh.'); return
    text='<b>📚 SAVOLLAR TARIXI</b>\n\n'
    for r in rows: text+=f"{'🟢' if r['active'] else '🔴'} <b>#{r['id']}</b> {safe_text(r['question'][:140])}\n⏱ {format_duration(r['duration'])}\n\n"
    send_message(chat_id,text)

def show_time_menu(chat_id):
    if not is_admin(chat_id): return
    kb=[[{'text':'1 daqiqa','callback_data':'time:60'},{'text':'2 daqiqa','callback_data':'time:120'}],
        [{'text':'3 daqiqa','callback_data':'time:180'},{'text':'10 daqiqa','callback_data':'time:600'}],
        [{'text':'15 daqiqa','callback_data':'time:900'},{'text':'30 daqiqa','callback_data':'time:1800'}],
        [{'text':'60 daqiqa','callback_data':'time:3600'}]]
    send_message(chat_id,f"<b>⏱ SAVOL VAQTI</b>\nJoriy: {format_duration(get_duration())}",kb)

def start_broadcast(chat_id):
    if is_admin(chat_id): states[chat_id]={'state':'broadcast'}; send_message(chat_id,'Barcha a’zolarga yuboriladigan matnni yozing. Bekor qilish: /bekor')

def do_broadcast(chat_id,text):
    rows=db.execute('SELECT user_id FROM members').fetchall(); ok=fail=0
    for r in rows:
        out=send_message(r['user_id'],safe_text(text))
        if out.get('ok'): ok+=1
        else: fail+=1
        time.sleep(.06)
    send_message(chat_id,f'<b>📢 Xabar yuborildi</b>\n✅ {ok}\n❌ {fail}')

def weekly_top():
    dt=datetime.now(TZ); monday=(dt-timedelta(days=dt.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
    return db.execute('''SELECT h.user_id,SUM(h.points) points,m.first_name,m.username FROM score_history h LEFT JOIN members m ON m.user_id=h.user_id WHERE h.created_at>=? GROUP BY h.user_id ORDER BY points DESC LIMIT 3''',(int(monday.timestamp()),)).fetchall()

# ================= TOURNAMENTS =================
def tournament_menu(chat_id):
    if not is_admin(chat_id): return
    send_message(chat_id,'<b>🏆 TURNIR BOSHQARUVI</b>',[
      [{'text':'➕ Yangi turnir','callback_data':'tr_create'}],
      [{'text':'📚 Turnirlar ro‘yxati','callback_data':'tr_list'}],
      [{'text':'📊 Tugagan turnirlar','callback_data':'tr_results'}]])

def start_tournament_creation(chat_id):
    states[chat_id]={'state':'tr_name'}
    send_message(chat_id,'Turnir nomini kiriting. Bekor qilish: /bekor')

def tournament_create_question(chat_id, tid):
    states[chat_id]={'state':'tr_q_text','tournament_id':tid}
    send_message(chat_id,'Turnir savoli matnini yuboring.')

def process_tournament_creation(chat_id,text):
    s=states.get(chat_id)
    if not s or not is_admin(chat_id): return False
    st=s.get('state')
    if st=='tr_name':
        if not text: send_message(chat_id,'Turnir nomini yozing.'); return True
        cur=db.execute("INSERT INTO tournaments(name,status,created_at) VALUES(?,'draft',?)",(text,now())); db.commit()
        tid=cur.lastrowid; tournament_create_question(chat_id,tid); return True
    if st=='tr_q_text': s['question']=text; s['state']='tr_q_answer'; send_message(chat_id,'To‘g‘ri javobni yuboring.'); return True
    if st=='tr_q_answer': s['answer']=text; s['state']='tr_q_variants'; send_message(chat_id,'Qabul qilinadigan variantlarni vergul bilan yozing yoki - yuboring.'); return True
    if st=='tr_q_variants': s['variants']='' if text.strip()=='-' else text; s['state']='tr_q_duration'; send_message(chat_id,'Savol vaqtini soniyada yozing: 60, 120, 180, 600, 900, 1800 yoki 3600.'); return True
    if st=='tr_q_duration':
        try: duration=int(text)
        except ValueError: duration=0
        if duration not in ALLOWED_DURATIONS:
            send_message(chat_id,'Ruxsat etilgan vaqtni kiriting: 60, 120, 180, 600, 900, 1800 yoki 3600 soniya.'); return True
        tid=s['tournament_id']; n=db.execute('SELECT COUNT(*) c FROM tournament_questions WHERE tournament_id=?',(tid,)).fetchone()['c']+1
        db.execute('INSERT INTO tournament_questions(tournament_id,question_no,question,correct_answer,variants,duration) VALUES(?,?,?,?,?,?)',(tid,n,s['question'],s['answer'],s['variants'],duration)); db.commit()
        states[chat_id]={'state':'tr_after_question','tournament_id':tid}
        send_message(chat_id,f'✅ {n}-savol saqlandi.',[[{'text':'➕ Yana savol','callback_data':f'tr_more:{tid}'},{'text':'✅ Turnirni tayyorlash','callback_data':f'tr_ready:{tid}'}]])
        return True
    return False

def list_tournaments(chat_id, status_filter=None):
    if not is_admin(chat_id): return
    sql='SELECT t.*, (SELECT COUNT(*) FROM tournament_questions q WHERE q.tournament_id=t.id) qcount FROM tournaments t'
    args=()
    if status_filter: sql+=' WHERE t.status=?'; args=(status_filter,)
    rows=db.execute(sql+' ORDER BY t.id DESC LIMIT 25',args).fetchall()
    if not rows: send_message(chat_id,'Bunday turnirlar yo‘q.'); return
    for t in rows:
        label={'draft':'Qoralama','ready':'Tayyor','running':'Jarayonda','finished':'Tugagan'}.get(t['status'],t['status'])
        kb=[]
        if t['status']=='draft': kb=[[{'text':'➕ Savol qo‘shish','callback_data':f"tr_more:{t['id']}"},{'text':'Tayyorlash','callback_data':f"tr_ready:{t['id']}"}]]
        elif t['status']=='ready': kb=[[{'text':'🚀 Boshlash','callback_data':f"tr_start:{t['id']}"}]]
        elif t['status']=='finished': kb=[[{'text':'🏆 Natijalar','callback_data':f"tr_result:{t['id']}"}]]
        send_message(chat_id,f"<b>🏆 {safe_text(t['name'])}</b>\nID: {t['id']}\nSavollar: {t['qcount']}\nHolat: {label}",kb or None)

def mark_tournament_ready(chat_id,tid):
    row=db.execute('SELECT status FROM tournaments WHERE id=?',(tid,)).fetchone()
    count=db.execute('SELECT COUNT(*) c FROM tournament_questions WHERE tournament_id=?',(tid,)).fetchone()['c']
    if not row or row['status']!='draft': send_message(chat_id,'Turnir qoralama holatida emas.'); return
    if count<1: send_message(chat_id,'Avval kamida bitta savol qo‘shing.'); return
    db.execute("UPDATE tournaments SET status='ready' WHERE id=?",(tid,)); db.commit(); states.pop(chat_id,None)
    send_message(chat_id,'✅ Turnir tayyorlandi. Uni turnirlar ro‘yxatidan boshlashingiz mumkin.')

def start_tournament(chat_id,tid):
    if db.execute("SELECT id FROM tournaments WHERE status='running' LIMIT 1").fetchone(): send_message(chat_id,'❌ Boshqa turnir davom etmoqda.'); return
    t=db.execute('SELECT * FROM tournaments WHERE id=?',(tid,)).fetchone()
    if not t or t['status']!='ready': send_message(chat_id,'Turnir topilmadi yoki boshlashga tayyor emas.'); return
    db.execute("UPDATE tournaments SET status='running',started_at=? WHERE id=?",(now(),tid)); db.commit()
    send_message(chat_id,f"🚀 <b>{safe_text(t['name'])}</b> turniri boshlandi!")
    publish_next_tournament_question(tid)

def publish_next_tournament_question(tid):
    t=db.execute('SELECT * FROM tournaments WHERE id=?',(tid,)).fetchone()
    if not t or t['status']!='running': return
    q=db.execute('SELECT * FROM tournament_questions WHERE tournament_id=? AND start_time IS NULL ORDER BY question_no LIMIT 1',(tid,)).fetchone()
    if not q:
        db.execute("UPDATE tournaments SET status='finished',finished_at=? WHERE id=?",(now(),tid)); db.commit()
        send_message(ADMIN_ID,f"🏁 <b>{safe_text(t['name'])}</b> turniri yakunlandi.")
        show_tournament_results(ADMIN_ID,tid); return
    db.execute('UPDATE tournament_questions SET active=1,start_time=? WHERE id=?',(now(),q['id'])); db.commit()
    deep_link=f'https://t.me/{BOT_USERNAME}?start=tq_{q["id"]}'
    result=send_message(CHANNEL,f"<b>🏆 {safe_text(t['name'])}</b>\n🧠 <b>{q['question_no']}-savol</b>\n\n{safe_text(q['question'])}\n\n⏱ Vaqt: {format_duration(q['duration'])}",[[{'text':'📝 Javob berish','url':deep_link}]])
    if result.get('ok'):
        db.execute('UPDATE tournament_questions SET channel_message_id=? WHERE id=?',(result['result']['message_id'],q['id'])); db.commit()
    else:
        # Avoid a stuck tournament if the channel post fails.
        db.execute('UPDATE tournament_questions SET active=0,start_time=NULL WHERE id=?',(q['id'],)); db.commit()
        send_message(ADMIN_ID,'❌ Turnir savoli kanalga yuborilmadi. Botning kanal adminligi va post huquqini tekshiring. Turnir to‘xtatildi.')
        db.execute("UPDATE tournaments SET status='ready' WHERE id=?",(tid,)); db.commit()

def submit_tournament_answer(message,qid):
    user=message['from']; uid=user['id']; text=message.get('text','').strip()
    q=db.execute('''SELECT q.*,t.name tournament_name,t.status tournament_status FROM tournament_questions q JOIN tournaments t ON t.id=q.tournament_id WHERE q.id=?''',(qid,)).fetchone()
    if not q or q['tournament_status']!='running' or not q['active']:
        send_message(uid,'⏰ Bu turnir savoli faol emas.'); return
    if now()>=q['start_time']+q['duration']:
        close_tournament_question(qid); send_message(uid,'⏰ Savol vaqti tugagan.'); return
    try:
        cur=db.execute('''INSERT INTO tournament_answers(tournament_id,question_id,user_id,username,first_name,answer,points_awarded,reviewed,created_at) VALUES(?,?,?,?,?,?,0,0,?)''',
         (q['tournament_id'],qid,uid,user.get('username',''),user.get('first_name',''),text,now())); db.commit(); aid=cur.lastrowid
    except sqlite3.IntegrityError:
        send_message(uid,'⚠️ Siz bu turnir savoliga javob berib bo‘lgansiz.'); return
    send_message(uid,'✅ Javobingiz qabul qilindi. Natijalar turnir yakunida chiqariladi.')
    send_message(ADMIN_ID,'<b>📩 TURNIR JAVOBI</b>\n\n'
      f"🏆 {safe_text(q['tournament_name'])}\n🧠 Savol: {q['question_no']}\n👤 {safe_text(user.get('first_name','Noma’lum'))}\n"
      f"🔗 {safe_text('@'+user['username'] if user.get('username') else 'username yo‘q')}\n🆔 <code>{uid}</code>\n📝 {safe_text(text)}",
      [[{'text':'+1 ball','callback_data':f'tr_grade:{aid}:1'},{'text':'0 ball','callback_data':f'tr_grade:{aid}:0'},{'text':'−1 ball','callback_data':f'tr_grade:{aid}:-1'}]])

def grade_tournament_answer(chat_id,aid,new_points):
    r=db.execute('SELECT * FROM tournament_answers WHERE id=?',(aid,)).fetchone()
    if not r: send_message(chat_id,'Turnir javobi topilmadi.'); return
    delta=new_points-r['points_awarded']
    db.execute('UPDATE tournament_answers SET points_awarded=?,reviewed=1 WHERE id=?',(new_points,aid)); db.commit()
    if delta: add_score(r['user_id'],delta,f'Turnir #{r["tournament_id"]}, javob #{aid}')
    send_message(chat_id,f'✅ Turnir javobi #{aid}: {r["points_awarded"]} → {new_points} ball. Umumiy ball farqi: {delta:+d}.')

def close_tournament_question(qid):
    q=db.execute('SELECT * FROM tournament_questions WHERE id=?',(qid,)).fetchone()
    if not q or not q['active']: return
    db.execute('UPDATE tournament_questions SET active=0 WHERE id=?',(qid,)); db.commit()
    t=db.execute('SELECT * FROM tournaments WHERE id=?',(q['tournament_id'],)).fetchone()
    send_message(CHANNEL,f"⏰ <b>{safe_text(t['name'])}</b> — {q['question_no']}-savol yakunlandi.\n✅ To‘g‘ri javob: <b>{safe_text(q['correct_answer'])}</b>")
    publish_next_tournament_question(q['tournament_id'])

def send_long(chat_id,text,limit=3500):
    # Split by lines so Telegram message limits are not exceeded.
    chunk=''
    for line in text.splitlines(True):
        if len(chunk)+len(line)>limit and chunk:
            send_message(chat_id,chunk); chunk=''
        chunk+=line
    if chunk: send_message(chat_id,chunk)

def show_tournament_results(chat_id,tid):
    t=db.execute('SELECT * FROM tournaments WHERE id=?',(tid,)).fetchone()
    if not t: send_message(chat_id,'Turnir topilmadi.'); return
    rows=db.execute('''SELECT a.user_id,MAX(a.first_name) first_name,MAX(a.username) username,SUM(a.points_awarded) points FROM tournament_answers a WHERE a.tournament_id=? GROUP BY a.user_id ORDER BY points DESC,a.user_id''',(tid,)).fetchall()
    text=f"🏆 {t['name']} — YAKUNIY NATIJALAR\n\n"
    if not rows: text+='Ishtirokchilar javob yubormagan.\n'
    else:
        for i,r in enumerate(rows,1): text+=f"{i}. {r['first_name'] or r['username'] or r['user_id']} — {r['points'] or 0} ball\n"
    send_long(chat_id,text)
    details=db.execute('''SELECT q.question_no,q.question,a.first_name,a.username,a.user_id,a.answer,a.points_awarded FROM tournament_answers a JOIN tournament_questions q ON q.id=a.question_id WHERE a.tournament_id=? ORDER BY q.question_no,a.created_at''',(tid,)).fetchall()
    if details:
        body='📋 ISHTIROKCHILAR JAVOBLARI\n\n'
        for r in details:
            body+=f"{r['question_no']}-savol: {r['question']}\n👤 {r['first_name'] or r['username'] or r['user_id']} (ID {r['user_id']})\n📝 {r['answer']}\n🏆 {r['points_awarded']} ball\n\n"
        send_long(chat_id,body)

def check_tournament_timers():
    rows=db.execute('SELECT id,start_time,duration FROM tournament_questions WHERE active=1').fetchall()
    for r in rows:
        if r['start_time'] and now()>=r['start_time']+r['duration']: close_tournament_question(r['id'])

# ================= CALLBACK HANDLER =================
def handle_callback(query):
    user=query['from']; uid=user['id']; data=query.get('data',''); msg=query.get('message',{}); chat_id=msg.get('chat',{}).get('id',uid)
    save_member(user)
    if data=='contact_admin':
        states[uid]={'state':'contact_message'}; send_message(uid,'📩 Adminga yuboriladigan xabarni yozing. Bekor qilish: /bekor'); callback_answer(query['id']); return
    if data.startswith('contact_reply:'):
        if not is_admin(uid): callback_answer(query['id'],'Faqat admin uchun.'); return
        try: target=int(data.split(':',1)[1])
        except ValueError: callback_answer(query['id'],'ID xato.'); return
        states[ADMIN_ID]={'state':'contact_reply','target_id':target}; send_message(ADMIN_ID,'Foydalanuvchiga javob matnini yozing. Bekor qilish: /bekor'); callback_answer(query['id']); return
    # Every tournament control and all admin actions are protected here.
    if data.startswith('tr_') and not is_admin(uid): callback_answer(query['id'],'Bu amal faqat admin uchun.'); return
    admin_exact={'admin_add','admin_answers','admin_rating','admin_members','admin_stats','admin_history','admin_points','admin_broadcast','admin_time','admin_winners','question_publish','question_cancel','tr_menu','tr_create','tr_list','tr_results'}
    if (data in admin_exact or data.startswith(('correct:','plus:','minus:','time:','tr_'))) and not is_admin(uid): callback_answer(query['id'],'Bu amal faqat admin uchun.'); return
    if data=='admin_add': start_question(chat_id)
    elif data=='admin_answers': show_answers(chat_id)
    elif data=='admin_rating': show_rating(chat_id)
    elif data=='admin_members': show_members(chat_id)
    elif data=='admin_stats': show_stats(chat_id)
    elif data=='admin_history': show_history(chat_id)
    elif data=='admin_points': send_message(chat_id,'Ballni “Javoblar” bo‘limidagi tugmalar orqali boshqaring.')
    elif data=='admin_broadcast': start_broadcast(chat_id)
    elif data=='admin_time': show_time_menu(chat_id)
    elif data=='admin_winners':
        rows=weekly_top(); text='<b>🎁 HAFTALIK TOP-3</b>\n\n'
        if not rows: text='Bu hafta natijalar hali yo‘q.'
        else:
            for i,r in enumerate(rows,1): text+=f"{i}. {safe_text(r['first_name'] or r['username'] or r['user_id'])} — {r['points']} ball\n"
        send_message(chat_id,text)
    elif data.startswith('time:'):
        try: sec=int(data.split(':')[1])
        except ValueError: sec=0
        if sec not in ALLOWED_DURATIONS: callback_answer(query['id'],'Vaqt qiymati noto‘g‘ri.'); return
        set_setting('question_duration',sec); send_message(chat_id,f'✅ Keyingi savollar vaqti: {format_duration(sec)}')
    elif data=='question_publish': publish_question(chat_id)
    elif data=='question_cancel': states.pop(ADMIN_ID,None); send_message(chat_id,'Savol bekor qilindi.')
    elif data.startswith('answer:'):
        try: qid=int(data.split(':')[1])
        except ValueError: callback_answer(query['id'],'Savol ID xato.'); return
        q=db.execute('SELECT * FROM questions WHERE id=?',(qid,)).fetchone()
        if not q or not q['active'] or not q['start_time'] or now()>=q['start_time']+q['duration']:
            if q and q['active']: db.execute('UPDATE questions SET active=0 WHERE id=?',(qid,)); db.commit()
            callback_answer(query['id'],'Savol yopilgan yoki topilmadi.'); return
        request_answer(uid,qid)
    elif data=='tr_menu': tournament_menu(chat_id)
    elif data=='tr_create': start_tournament_creation(chat_id)
    elif data=='tr_list': list_tournaments(chat_id)
    elif data=='tr_results': list_tournaments(chat_id,'finished')
    elif data.startswith('tr_more:'):
        tid=int(data.split(':')[1]); t=db.execute('SELECT status FROM tournaments WHERE id=?',(tid,)).fetchone()
        if not t or t['status']!='draft': send_message(chat_id,'Bu turnirga savol qo‘shib bo‘lmaydi.')
        else: tournament_create_question(chat_id,tid)
    elif data.startswith('tr_ready:'): mark_tournament_ready(chat_id,int(data.split(':')[1]))
    elif data.startswith('tr_start:'): start_tournament(chat_id,int(data.split(':')[1]))
    elif data.startswith('tr_result:'): show_tournament_results(chat_id,int(data.split(':')[1]))
    elif data.startswith('tr_grade:'):
        try: _,aid,pts=data.split(':'); grade_tournament_answer(chat_id,int(aid),int(pts))
        except (ValueError,TypeError): send_message(chat_id,'Baholash ma’lumoti xato.')
    elif data.startswith('correct:'):
        try: send_message(chat_id,adjust_regular_answer(int(data.split(':')[1]),'correct'))
        except ValueError: send_message(chat_id,'Javob ID xato.')
    elif data.startswith('plus:'):
        try: send_message(chat_id,adjust_regular_answer(int(data.split(':')[1]),'plus'))
        except ValueError: send_message(chat_id,'Javob ID xato.')
    elif data.startswith('minus:'):
        try: send_message(chat_id,adjust_regular_answer(int(data.split(':')[1]),'minus'))
        except ValueError: send_message(chat_id,'Javob ID xato.')
    else:
        callback_answer(query['id']); return
    callback_answer(query['id'])

# ================= MESSAGE HANDLER =================
def handle_message(message):
    user=message['from']; uid=user['id']; chat_id=message['chat']['id']; text=message.get('text','').strip()
    save_member(user); s=states.get(uid)
    if text.startswith('/start'):
        payload=text.split(maxsplit=1)[1] if len(text.split(maxsplit=1))>1 else ''
        if payload.startswith('tq_'):
            try: qid=int(payload[3:])
            except ValueError: send_message(chat_id,'Turnir havolasi xato.'); return
            q=db.execute('SELECT * FROM tournament_questions WHERE id=?',(qid,)).fetchone()
            t=db.execute('SELECT status FROM tournaments WHERE id=?',(q['tournament_id'],)).fetchone() if q else None
            if not q or not t or t['status']!='running' or not q['active'] or now()>=q['start_time']+q['duration']:
                send_message(chat_id,'⏰ Bu turnir savoli yopilgan.'); return
            states[uid]={'state':'tr_answering','question_id':qid}
            send_message(chat_id,f"📝 <b>{q['question_no']}-savol</b>\nJavobingizni yozing:")
            return
        send_message(chat_id,'<b>👋 Xush kelibsiz!</b>\n\n🧠 <b>ALGORITM ZAKOVAT</b> botiga xush kelibsiz.\nBilimingizni sinang va ball to‘plang.\n\n👤 /profil — profilingiz\n🔒 Umumiy reyting faqat admin uchun ochiq.',[[{'text':'📩 Adminga murojaat','callback_data':'contact_admin'}]])
        return
    # Contact conversation
    if s and s.get('state')=='contact_message':
        if text=='/bekor': states.pop(uid,None); send_message(chat_id,'Murojaat bekor qilindi.'); return
        result=send_message(ADMIN_ID,'<b>📩 YANGI MUROJAAT</b>\n\n'
          f"👤 {safe_text(user.get('first_name','Foydalanuvchi'))}\n🔗 {safe_text('@'+user['username'] if user.get('username') else 'username yo‘q')}\n🆔 <code>{uid}</code>\n\n💬 {safe_text(text)}",
          [[{'text':'↩️ Javob berish','callback_data':f'contact_reply:{uid}'}]])
        send_message(chat_id,'✅ Murojaat adminga yuborildi.' if result.get('ok') else '❌ Yuborilmadi. Keyinroq urinib ko‘ring.')
        states.pop(uid,None); return
    if is_admin(uid) and s and s.get('state')=='contact_reply':
        if text=='/bekor': states.pop(uid,None); send_message(chat_id,'Javob bekor qilindi.'); return
        out=send_message(s['target_id'],'📩 <b>Admin javobi:</b>\n\n'+safe_text(text))
        send_message(chat_id,'✅ Yuborildi.' if out.get('ok') else '❌ Yuborilmadi.')
        states.pop(uid,None); return
    if text=='/bekor':
        if uid in states: states.pop(uid,None); send_message(chat_id,'❌ Amal bekor qilindi.')
        return
    # Answer submission states
    if s and s.get('state')=='tr_answering':
        qid=s['question_id']; states.pop(uid,None); submit_tournament_answer(message,qid); return
    if process_user_answer(message): return
    if text=='/profil': show_profile(chat_id,uid); return
    if text=='/reyting': show_rating(chat_id); return
    if text=='/admin':
        if is_admin(uid): show_admin(chat_id)
        else: send_message(chat_id,'❌ Siz admin emassiz.')
        return
    if text=='/turnir':
        if is_admin(uid): tournament_menu(chat_id)
        else: send_message(chat_id,'Bu buyruq faqat admin uchun.')
        return
    if is_admin(uid):
        if text=='/javoblar': show_answers(chat_id); return
        if text in ("/a'zolar",'/azolar'): show_members(chat_id); return
        if text=='/statistika': show_stats(chat_id); return
        if text=='/tarix': show_history(chat_id); return
        if text=='/vaqt': show_time_menu(chat_id); return
        if s and s.get('state')=='broadcast': do_broadcast(chat_id,text); states.pop(uid,None); return
        if s and s.get('state','').startswith('tr_'):
            if process_tournament_creation(chat_id,text): return
        if s and s.get('state') in ('question','answer','variants'):
            process_question(chat_id,text); return

# ================= TIMER / MAIN LOOP =================
def check_expired_questions():
    rows=db.execute('SELECT id,start_time,duration FROM questions WHERE active=1').fetchall()
    for r in rows:
        if r['start_time'] and now()>=r['start_time']+r['duration']:
            db.execute('UPDATE questions SET active=0 WHERE id=?',(r['id'],)); db.commit()
            send_message(ADMIN_ID,f"⏰ <b>#{r['id']}</b>-savol vaqti tugadi.")

def main():
    global BOT_USERNAME
    me=tg('getMe')
    if not me.get('ok'): raise RuntimeError('Bot tokeni noto‘g‘ri yoki Telegram API bilan aloqa yo‘q.')
    BOT_USERNAME=me['result']['username']
    print(f'🤖 ALGORITM ZAKOVAT ishga tushdi: @{BOT_USERNAME}')
    tg('deleteWebhook',{'drop_pending_updates':False})
    offset=0; last_check=0
    while True:
        try:
            out=tg('getUpdates',{'offset':offset,'timeout':10,'allowed_updates':['message','callback_query']})
            if not out.get('ok'): time.sleep(3); continue
            for upd in out.get('result',[]):
                offset=upd['update_id']+1
                try:
                    if 'message' in upd: handle_message(upd['message'])
                    elif 'callback_query' in upd: handle_callback(upd['callback_query'])
                except Exception as e: print('UPDATE ERROR:',repr(e))
            if now()-last_check>=2:
                check_expired_questions(); check_tournament_timers(); last_check=now()
        except KeyboardInterrupt: break
        except Exception as e: print('MAIN LOOP ERROR:',repr(e)); time.sleep(3)
            if __name__=='__main__': main()
            
