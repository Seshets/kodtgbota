import sqlite3
import logging
import os
import qrcode
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler, ConversationHandler
)

# --- НАСТРОЙКИ ---
TOKEN = "8623152070:AAGDDpVRSgvx2Vew743seJQ0uPb0q-N9UhY"
MY_ID = 1670506364

# Состояния для диалогов
NEW_CAT_NAME, SET_TIMER, ADD_EMPTY_CAT = 1, 2, 3

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)


# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ---
def init_db():
    with sqlite3.connect("storage.db") as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS storage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                content TEXT,
                caption TEXT,
                category TEXT DEFAULT 'Общее',
                created_at TEXT
            )
        """)
        # Исправляем базу под новые версии (добавляем колонки, если их нет)
        cursor = conn.execute("PRAGMA table_info(storage)")
        cols = [column[1] for column in cursor.fetchall()]
        if 'category' not in cols:
            conn.execute("ALTER TABLE storage ADD COLUMN category TEXT DEFAULT 'Общее'")
        if 'created_at' not in cols:
            conn.execute("ALTER TABLE storage ADD COLUMN created_at TEXT")
    print("✅ База данных Матео готова (совместима с Python 3.12+)")


# --- ГЛАВНОЕ МЕНЮ ---
def main_menu():
    return ReplyKeyboardMarkup([
        ["📚 Библиотека", "🔍 Поиск"],
        ["📊 Статистика", "🖼 Сделать QR"],
        ["❓ Помощь"]
    ], resize_keyboard=True)


async def check_user(update: Update):
    if update.effective_user.id != MY_ID:
        await update.message.reply_text("⛔ Доступ запрещен.")
        return False
    return True


# --- КОМАНДЫ МЕНЮ ---
async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *Справка для Матео:*\n\n"
        "1️⃣ *Сохранение:* Пришли текст, фото или файл. Я предложу выбрать или создать папку.\n"
        "2️⃣ *Библиотека:* Просмотр записей по категориям и создание новых пустых разделов.\n"
        "3️⃣ *Поиск:* Команда `/search слово` найдет заметки.\n"
        "4️⃣ *QR-коды:* Команда `/qr текст` сделает картинку с кодом.\n"
        "5️⃣ *Напоминания:* При сохранении нажми ⏰ и введи минуты.\n"
        "6️⃣ *Статистика:* Покажет количество файлов в каждой папке."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect("storage.db") as conn:
        res = conn.execute("SELECT category, COUNT(*) FROM storage GROUP BY category").fetchall()
    if not res:
        return await update.message.reply_text("📊 Твое хранилище пока пусто.")
    msg = "📊 *Твоя статистика:*\n\n" + "\n".join([f"📁 {cat}: {count} шт." for cat, count in res])
    await update.message.reply_text(msg, parse_mode="Markdown")


# --- СОХРАНЕНИЕ КОНТЕНТА ---
async def save_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update): return
    msg = update.message

    # Реакция на кнопки главного меню
    if msg.text == "📚 Библиотека": return await show_library_menu(update, context)
    if msg.text == "📊 Статистика": return await show_stats(update, context)
    if msg.text == "❓ Помощь": return await show_help(update, context)
    if msg.text == "🖼 Сделать QR": return await update.message.reply_text("Напиши: `/qr ссылка`")
    if msg.text == "🔍 Поиск": return await update.message.reply_text("Напиши: `/search слово` для поиска.")

    c_type, c_val, cap = None, None, msg.caption or ""
    if msg.text:
        c_type, c_val = "text", msg.text
    elif msg.photo:
        c_type, c_val = "photo", msg.photo[-1].file_id
    elif msg.document:
        c_type, c_val = "doc", msg.document.file_id
    elif msg.video:
        c_type, c_val = "video", msg.video.file_id

    if c_type:
        with sqlite3.connect("storage.db") as conn:
            # Используем .isoformat() для фикса ошибки Python 3.12
            cursor = conn.execute(
                "INSERT INTO storage (user_id, type, content, caption, created_at) VALUES (?, ?, ?, ?, ?)",
                (MY_ID, c_type, c_val, cap, datetime.now().isoformat())
            )
            row_id = cursor.lastrowid

        with sqlite3.connect("storage.db") as conn:
            cats = conn.execute("SELECT DISTINCT category FROM storage WHERE user_id = ?", (MY_ID,)).fetchall()

        kb = [[InlineKeyboardButton(f"📁 {c[0]}", callback_data=f"cat_{row_id}_{c[0]}")] for c in cats[:3]]
        kb.append([InlineKeyboardButton("➕ Своя папка", callback_data=f"newcat_{row_id}"),
                   InlineKeyboardButton("⏰ Напомнить", callback_data=f"rem_{row_id}")])
        kb.append([InlineKeyboardButton("🗑 Удалить", callback_data=f"del_{row_id}")])

        await update.message.reply_text(f"✅ Сохранено (#{row_id})", reply_markup=InlineKeyboardMarkup(kb))


# --- ЛОГИКА БИБЛИОТЕКИ И ПАПОК ---
async def show_library_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with sqlite3.connect("storage.db") as conn:
        cats = conn.execute("SELECT DISTINCT category FROM storage WHERE user_id = ?", (MY_ID,)).fetchall()
    kb = [[InlineKeyboardButton(f"📁 {c[0]}", callback_data=f"lib_{c[0]}")] for c in cats]
    kb.append([InlineKeyboardButton("➕ Создать новый раздел", callback_data="add_empty_cat")])
    await update.message.reply_text("📚 Выбери раздел библиотеки:", reply_markup=InlineKeyboardMarkup(kb))


async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("cat_"):
        _, r_id, name = data.split("_")
        with sqlite3.connect("storage.db") as conn:
            conn.execute("UPDATE storage SET category=? WHERE id=?", (name, r_id))
        await query.edit_message_text(f"📂 Запись #{r_id} теперь в папке '{name}'")

    elif data.startswith("lib_"):
        cat = data.split("_")[1]
        with sqlite3.connect("storage.db") as conn:
            rows = conn.execute("SELECT id, type, content, caption FROM storage WHERE category=?", (cat,)).fetchall()
        if not rows: return await query.message.reply_text(f"Папка {cat} пуста.")
        for r_id, t, c, cap in rows:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("🗑 Удалить", callback_data=f"del_{r_id}")]])
            if t == 'text':
                await query.message.reply_text(f"📝 {c}", reply_markup=kb)
            elif t == 'photo':
                await query.message.reply_photo(c, caption=cap, reply_markup=kb)
            elif t == 'doc':
                await query.message.reply_document(c, caption=cap, reply_markup=kb)

    elif data.startswith("del_"):
        r_id = data.split("_")[1]
        with sqlite3.connect("storage.db") as conn:
            conn.execute("DELETE FROM storage WHERE id=?", (r_id,))
        await query.edit_message_text("🗑 Удалено.")


# --- QR-КОДЫ И ПОИСК ---
async def make_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text: return await update.message.reply_text("Пример: `/qr привет`")
    img = qrcode.make(text);
    img.save("qr.png")
    await update.message.reply_photo(photo=open("qr.png", "rb"), caption=f"QR для: {text}");
    os.remove("qr.png")


async def search_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_user(update): return
    if not context.args: return await update.message.reply_text("Использование: `/search слово`")
    word = f"%{' '.join(context.args)}%"
    with sqlite3.connect("storage.db") as conn:
        rows = conn.execute("SELECT type, content, caption FROM storage WHERE content LIKE ? OR caption LIKE ?",
                            (word, word)).fetchall()
    if not rows: return await update.message.reply_text("🔍 Ничего не нашел.")
    for t, c, cap in rows:
        if t == 'text':
            await update.message.reply_text(f"📝 Найдено: {c}")
        elif t == 'photo':
            await update.message.reply_photo(c, caption=f"Найдено: {cap}")


# --- ДИАЛОГИ (НОВЫЕ ПАПКИ И ТАЙМЕРЫ) ---
async def start_new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['tmp_id'] = update.callback_query.data.split("_")[1]
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Напиши название новой папки:")
    return NEW_CAT_NAME


async def finish_new_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name, r_id = update.message.text, context.user_data['tmp_id']
    with sqlite3.connect("storage.db") as conn:
        conn.execute("UPDATE storage SET category=? WHERE id=?", (name, r_id))
    await update.message.reply_text(f"📁 Запись #{r_id} сохранена в '{name}'", reply_markup=main_menu())
    return ConversationHandler.END


async def start_empty_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Название для нового раздела библиотеки:")
    return ADD_EMPTY_CAT


async def finish_empty_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat_name = update.message.text
    # Фиктивная запись для создания категории
    with sqlite3.connect("storage.db") as conn:
        conn.execute("INSERT INTO storage (user_id, type, content, category) VALUES (?, ?, ?, ?)",
                     (MY_ID, 'text', 'Инициализация папки', cat_name))
    await update.message.reply_text(f"✅ Раздел '{cat_name}' теперь доступен!", reply_markup=main_menu())
    return ConversationHandler.END


if __name__ == "__main__":
    init_db()
    app = Application.builder().token(TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_new_cat, pattern="^newcat_"),
            CallbackQueryHandler(start_empty_cat, pattern="add_empty_cat")
        ],
        states={
            NEW_CAT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_new_cat)],
            ADD_EMPTY_CAT: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_empty_cat)]
        },
        fallbacks=[]
    )

    app.add_handler(
        CommandHandler("start", lambda u, c: u.message.reply_text("Готов к работе, Матео!", reply_markup=main_menu())))
    app.add_handler(CommandHandler("qr", make_qr))
    app.add_handler(CommandHandler("search", search_content))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, save_content))

    print("🚀 Проект запущен. Матео, всё работает!")
    app.run_polling()
