import os
import asyncio
from datetime import datetime, timedelta, timezone

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==========================================
# SOZLAMALAR
# ==========================================

# BOT_TOKEN GitHub kodiga yozilmaydi.
# Keyin hostingda BOT_TOKEN sifatida beramiz.
TOKEN = os.getenv("BOT_TOKEN")

CHANNEL = "@zakalgoritm"

# Sizning Telegram ID'ingiz
ADMIN_ID = 5607350126

active_question = None


# ==========================================
# MATNNI NORMALIZATSIYA QILISH
# ==========================================

def normalize(text):
    text = text.lower().strip()

    replacements = {
        "’": "'",
        "‘": "'",
        "ʻ": "'",
        "`": "'",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    return text


# ==========================================
# /START
# ==========================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🧠 Assalomu alaykum!\n\n"
        "Algoritm Zakovat botiga xush kelibsiz!\n\n"
        "📚 Har kuni yangi Zakovat savoli beriladi.\n"
        "📩 Savolga javobingizni shu botga yuboring."
    )


# ==========================================
# /SAVOL
# ==========================================

async def savol(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "⛔ Bu buyruq faqat admin uchun."
        )

        return

    if active_question is not None:

        await update.message.reply_text(
            "⚠️ Hozir boshqa savol faol.\n\n"
            "Avval 6 soatlik muddat tugashi kerak."
        )

        return

    context.user_data["creating_question"] = True
    context.user_data["waiting_answer"] = False

    await update.message.reply_text(
        "📝 Yangi Zakovat savolini yuboring:"
    )


# ==========================================
# MATNLARNI QABUL QILISH
# ==========================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    global active_question

    if not update.message:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ======================================
    # ADMIN
    # ======================================

    if user_id == ADMIN_ID:

        # SAVOL
        if context.user_data.get("creating_question"):

            context.user_data["question"] = text

            context.user_data["creating_question"] = False
            context.user_data["waiting_answer"] = True

            await update.message.reply_text(
                "✅ Savol qabul qilindi.\n\n"
                "🎯 Endi to‘g‘ri javobni yuboring:"
            )

            return

        # JAVOB
        if context.user_data.get("waiting_answer"):

            question = context.user_data["question"]
            answer = text

            context.user_data["waiting_answer"] = False
            context.user_data["question"] = None

            now = datetime.now(timezone.utc)

            active_question = {

                "question": question,

                "answer": answer,

                "start": now,

                "end": now + timedelta(hours=6),

                "users": {}
            }

            # ==================================
            # SAVOLNI KANALGA YUBORISH
            # ==================================

            await context.bot.send_message(

                chat_id=CHANNEL,

                text=(
                    "🧠 KUNLIK ZAKOVAT SAVOLI\n\n"

                    f"{question}\n\n"

                    "⏳ Javob berish uchun 6 soat vaqt bor.\n\n"

                    "📩 Javobingizni botga yuboring."
                )
            )

            await update.message.reply_text(

                "🚀 Savol @zakalgoritm kanaliga yuborildi!\n\n"

                "⏳ 6 soatlik javob berish vaqti boshlandi."
            )

            # 6 soatlik timer
            asyncio.create_task(
                finish_question(
                    context.application
                )
            )

            return

    # ======================================
    # FOYDALANUVCHI JAVOBI
    # ======================================

    if active_question is None:

        await update.message.reply_text(
            "⏳ Hozir faol Zakovat savoli yo‘q."
        )

        return

    # Muddat tugaganini tekshirish

    now = datetime.now(timezone.utc)

    if now >= active_question["end"]:

        await update.message.reply_text(
            "⛔ Bu savolga javob berish vaqti tugagan."
        )

        return

    # Bir foydalanuvchi bir marta javob beradi

    if user_id in active_question["users"]:

        await update.message.reply_text(
            "⚠️ Siz bu savolga allaqachon javob bergansiz."
        )

        return

    # Javobni saqlash

    active_question["users"][user_id] = {

        "name": update.effective_user.full_name,

        "answer": text,

        "time": now
    }

    await update.message.reply_text(

        "✅ Javobingiz qabul qilindi!\n\n"

        "⏳ 6 soat tugagach natija e’lon qilinadi."
    )


# ==========================================
# 6 SOATDAN KEYIN
# ==========================================

async def finish_question(application):

    global active_question

    if active_question is None:
        return

    # Qolgan vaqt

    seconds = (

        active_question["end"]

        - datetime.now(timezone.utc)

    ).total_seconds()

    if seconds > 0:

        await asyncio.sleep(seconds)

    if active_question is None:
        return

    # Ma'lumotlarni olish

    question = active_question["question"]

    correct_answer = active_question["answer"]

    users = active_question["users"]

    correct_users = []

    # Javoblarni tekshirish

    for user in users.values():

        if normalize(user["answer"]) == normalize(
            correct_answer
        ):

            correct_users.append(
                user["name"]
            )

    # ======================================
    # NATIJA
    # ======================================

    result = (

        "✅ SAVOL JAVOBI\n\n"

        f"🧠 Savol:\n"
        f"{question}\n\n"

        f"🎯 Javobi: {correct_answer}\n\n"

        f"👥 Javob berganlar: "
        f"{len(users)} ta\n"

        f"🏆 To‘g‘ri javoblar: "
        f"{len(correct_users)} ta"
    )

    # To‘g‘ri javob berganlar

    if correct_users:

        result += (
            "\n\n🥇 To‘g‘ri javob berganlar:\n"
        )

        result += "\n".join(

            f"• {name}"

            for name in correct_users
        )

    # Kanalga javobni yuborish

    await application.bot.send_message(

        chat_id=CHANNEL,

        text=result
    )

    # Savolni yopish

    active_question = None


# ==========================================
# BOTNI ISHGA TUSHIRISH
# ==========================================

def main():

    if not TOKEN:

        raise ValueError(
            "BOT_TOKEN topilmadi! "
            "Hostingdagi Secret/Environment "
            "Variables bo‘limiga BOT_TOKEN qo‘ying."
        )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # Buyruqlar

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "savol",
            savol
        )
    )

    # Oddiy matnlar

    app.add_handler(

        MessageHandler(

            filters.TEXT
            & ~filters.COMMAND,

            text_handler
        )
    )

    print(
        "🧠 Algoritm Zakovat bot ishga tushdi!"
    )

    app.run_polling()


# ==========================================
# START
# ==========================================

if __name__ == "__main__":

    main()
