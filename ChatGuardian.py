import sqlite3
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest
import random
from functools import wraps
import logging
from datetime import datetime, timedelta, UTC

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)
logger = logging.getLogger(__name__)

TOKEN = '7680787360:AAGn3IkylYRN5xewaud-cfykEvRdz7L66oI'

def init_db():
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS warnings (user_id INTEGER, chat_id INTEGER, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, chat_id))')
        c.execute('CREATE TABLE IF NOT EXISTS rules (chat_id INTEGER PRIMARY KEY, rules_text TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS welcome (chat_id INTEGER PRIMARY KEY, message TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS nicknames (user_id INTEGER, chat_id INTEGER, nickname TEXT, PRIMARY KEY (user_id, chat_id))')
        conn.commit()

init_db()

def safe_message(func):
    @wraps(func)
    async def wrapper(update: Update, context): return await func(update, context) if update and update.message and update.message.chat else None
    return wrapper

def with_db(func):
    @wraps(func)
    async def wrapper(update: Update, context):
        with sqlite3.connect('bot.db') as conn:
            try: return await func(update, context, conn.cursor())
            except Exception as e: logger.error(f"DB error: {e}"); conn.rollback()
    return wrapper

def admin_only(func):
    @wraps(func)
    @safe_message
    async def wrapper(update: Update, context):
        chat = update.message.chat
        if chat.type in ['group', 'supergroup']:
            admins = [admin.user.id for admin in await chat.get_administrators()]
            if update.message.from_user.id not in admins: return await update.message.reply_text('❌ Доступ заборонено!')
            if context.bot.id not in admins: return await update.message.reply_text('❌ Бот не адміністратор!')
            return await func(update, context)
    return wrapper

@safe_message
async def cmd_start(update: Update, context): 
    if update.message.chat.type == 'private': await update.message.reply_text('🔹 Привіт! Я бот для чату. /help - команди')

@safe_message
async def cmd_help(update: Update, context): 
    await update.message.reply_text("📚 Команди:\n/start\n/rules\n/setrules [текст]\n/setwelcome [текст]\n/warn [причина]\n/ban [причина]\n/kick [причина]\n/mute [час] [причина]\n/unmute\n/unban\n/unwarn\n/joke\n*Усі команди керування (warn, ban тощо) потрібно використовувати у відповідь на повідомлення користувача*")

@safe_message
@with_db
async def cmd_rules(update: Update, context, cursor): 
    cursor.execute('SELECT rules_text FROM rules WHERE chat_id = ?', (update.message.chat.id,))
    await update.message.reply_text(f'📜 Правила:\n{cursor.fetchone()[0]}' if cursor.fetchone() else '❌ Правила не встановлені')

@admin_only
@with_db
async def cmd_setrules(update: Update, context, cursor): 
    if context.args: 
        cursor.execute('INSERT OR REPLACE INTO rules VALUES (?, ?)', (update.message.chat.id, ' '.join(context.args))); cursor.connection.commit()
        await update.message.reply_text('✅ Правила оновлено!')
    else: await update.message.reply_text('ℹ️ Вкажіть текст правил')

@admin_only
@with_db
async def cmd_setwelcome(update: Update, context, cursor): 
    text = update.message.text.partition(' ')[2].strip()
    if text: 
        cursor.execute('INSERT OR REPLACE INTO welcome VALUES (?, ?)', (update.message.chat.id, text)); cursor.connection.commit()
        await update.message.reply_text('✅ Привітання оновлено!')
    else: await update.message.reply_text('ℹ️ Вкажіть текст привітання')

@with_db
async def get_welcome(update: Update, context, cursor): 
    cursor.execute('SELECT message FROM welcome WHERE chat_id = ?', (update.message.chat.id,))
    result = cursor.fetchone()
    return result[0] if result else None

@safe_message
async def cmd_show_welcome(update: Update, context): 
    msg = await get_welcome(update, context)
    await update.message.reply_text(f'👋 Привітання:\n{msg}' if msg else '❌ Привітання не встановлено')

@safe_message
async def welcome_message(update: Update, context): 
    if msg := await get_welcome(update, context):
        for member in update.message.new_chat_members:
            await update.message.reply_text(msg.replace('{name}', await get_user_link(member, update.message.chat.id)), parse_mode='MarkdownV2', disable_web_page_preview=True)

@safe_message
@with_db
async def cmd_set_nickname(update: Update, context, cursor):
    if not context.args:
        await update.message.reply_text('ℹ️ Вкажіть нікнейм: +нік [нікнейм]')
        return
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    nickname = ' '.join(context.args)
    cursor.execute('INSERT OR REPLACE INTO nicknames VALUES (?, ?, ?)', (user_id, chat_id, nickname))
    cursor.connection.commit()
    await update.message.reply_text(f'✅ Нікнейм встановлено!')

@safe_message
@with_db
async def cmd_remove_nickname(update: Update, context, cursor):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    cursor.execute('DELETE FROM nicknames WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    cursor.connection.commit()
    await update.message.reply_text('✅ Нікнейм видалено!' if cursor.rowcount > 0 else 'ℹ️ Нікнейм не був встановлений')

@safe_message
@with_db
async def cmd_show_nickname(update: Update, context, cursor):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    nickname = await get_nickname(user_id, chat_id)
    await update.message.reply_text(f'👤 Ваш нікнейм: {nickname}' if nickname else 'ℹ️ Нікнейм не встановлено')

@with_db
async def get_nickname(user_id, chat_id, cursor):
    cursor.execute('SELECT nickname FROM nicknames WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    result = cursor.fetchone()
    return result[0] if result else None

async def get_user_link(member, chat_id=None):
    if chat_id:
        nickname = await get_nickname(member.id, chat_id)
        name = nickname if nickname else member.full_name
    else:
        name = member.full_name
    name = ''.join(f'\\{c}' if c in '_*[]()~`>#+-=|{{}}.!' else c for c in name)
    return f"[{name}](https://t.me/{member.username})" if member.username else f"[{name}](tg://user?id={member.id})"

@admin_only
@with_db
async def cmd_remove_welcome(update: Update, context, cursor): 
    cursor.execute('DELETE FROM welcome WHERE chat_id = ?', (update.message.chat.id,)); cursor.connection.commit()
    await update.message.reply_text('✅ Привітання видалено!' if cursor.rowcount > 0 else 'ℹ️ Привітання не було встановлено.')

@safe_message
async def cmd_joke(update: Update, context): 
    await update.message.reply_text(random.choice(['Чому програміст пішов у ліс? — Бо там немає багів!', 'Код боту: "Працюй або падай!"']))

@admin_only
@with_db
async def cmd_warn(update: Update, context, cursor):
    target_id, reason = await parse_target(update, context)
    if target_id:
        chat_id = update.message.chat.id
        cursor.execute('INSERT INTO warnings VALUES (?, ?, 1) ON CONFLICT(user_id, chat_id) DO UPDATE SET count = count + 1', (target_id, chat_id))
        cursor.execute('SELECT count FROM warnings WHERE user_id = ? AND chat_id = ?', (target_id, chat_id))
        count = cursor.fetchone()[0]; cursor.connection.commit()
        target = await context.bot.get_chat(target_id); target_link = await get_user_link(target, chat_id); mod_link = await get_user_link(update.message.from_user, chat_id)
        await update.message.reply_text(f"⚠️ {target_link} отримує попередження \\({count}/3\\)\nПричина: {reason}\nМодератор: {mod_link}", parse_mode='MarkdownV2', disable_web_page_preview=True)
        if count >= 3:
            try:
                await context.bot.ban_chat_member(chat_id, target_id)
                await update.message.reply_text(f"🚫 {target_link} заблоковано\\!\nПричина: ліміт попереджень \\(3/3\\)\nМодератор: {mod_link}\nПопередження скинуто", parse_mode='MarkdownV2', disable_web_page_preview=True)
                cursor.execute('UPDATE warnings SET count = 0 WHERE user_id = ? AND chat_id = ?', (target_id, chat_id)); cursor.connection.commit()
            except BadRequest as e: await handle_errors(update, e)

@admin_only
async def cmd_ban(update: Update, context):
    target_id, reason = await parse_target(update, context)
    if target_id:
        try:
            target = await context.bot.get_chat(target_id); target_link = await get_user_link(target, update.message.chat.id); mod_link = await get_user_link(update.message.from_user, update.message.chat.id)
            await context.bot.ban_chat_member(update.message.chat.id, target_id)
            await update.message.reply_text(f"🚫 {target_link} заблоковано\\!\nПричина: {reason}\nМодератор: {mod_link}", parse_mode='MarkdownV2', disable_web_page_preview=True)
        except BadRequest as e: await handle_errors(update, e)

@admin_only
async def cmd_kick(update: Update, context):
    target_id, reason = await parse_target(update, context)
    if target_id:
        chat_id = update.message.chat.id
        try:
            target = await context.bot.get_chat(target_id); target_link = await get_user_link(target, chat_id); mod_link = await get_user_link(update.message.from_user, chat_id)
            await context.bot.ban_chat_member(chat_id, target_id); await context.bot.unban_chat_member(chat_id, target_id)
            await update.message.reply_text(f"👢 {target_link} видалено\\!\nПричина: {reason}\nМодератор: {mod_link}", parse_mode='MarkdownV2', disable_web_page_preview=True)
        except BadRequest as e: await handle_errors(update, e)

async def unmute_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id, user_id = job.data
    target = await context.bot.get_chat(user_id)
    target_link = await get_user_link(target, chat_id)
    await context.bot.restrict_chat_member(chat_id=chat_id, user_id=user_id, permissions={"can_send_messages": True})
    await context.bot.send_message(chat_id=chat_id, text=f"🔊 {target_link} знову може писати\\!", parse_mode='MarkdownV2', disable_web_page_preview=True)

@admin_only
async def cmd_mute(update: Update, context):
    target_id, args = await parse_target(update, context, True)
    if target_id:
        chat_id = update.message.chat.id
        try:
            duration, reason = parse_duration_and_reason(args) if args else (3600, "Без причини")
            target = await context.bot.get_chat(target_id); target_link = await get_user_link(target, chat_id); mod_link = await get_user_link(update.message.from_user, chat_id)
            until_date = datetime.now(UTC) + timedelta(seconds=duration)
            await context.bot.restrict_chat_member(chat_id, target_id, permissions={"can_send_messages": False}, until_date=until_date)
            await update.message.reply_text(f"🔇 {target_link} замучено на {format_duration(duration)}\\!\nПричина: {reason}\nМодератор: {mod_link}", parse_mode='MarkdownV2', disable_web_page_preview=True)
            context.job_queue.run_once(unmute_callback, duration, data=(chat_id, target_id), name=f"unmute_{chat_id}_{target_id}")
        except BadRequest as e: await handle_errors(update, e)

@admin_only
async def cmd_unmute(update: Update, context):
    target_id, reason = await parse_target(update, context)
    if target_id:
        chat_id = update.message.chat.id
        try:
            target = await context.bot.get_chat(target_id); target_link = await get_user_link(target, chat_id); mod_link = await get_user_link(update.message.from_user, chat_id)
            await context.bot.restrict_chat_member(chat_id, target_id, permissions={"can_send_messages": True})
            await update.message.reply_text(f"🔊 {target_link} розмучено\\!\nМодератор: {mod_link}", parse_mode='MarkdownV2', disable_web_page_preview=True)
            current_jobs = context.job_queue.get_jobs_by_name(f"unmute_{chat_id}_{target_id}")
            for job in current_jobs:
                job.schedule_removal()
        except BadRequest as e: await handle_errors(update, e)

@admin_only
async def cmd_unban(update: Update, context):
    target_id, reason = await parse_target(update, context)
    if target_id:
        chat_id = update.message.chat.id
        try:
            target = await context.bot.get_chat(target_id); target_link = await get_user_link(target, chat_id); mod_link = await get_user_link(update.message.from_user, chat_id)
            await context.bot.unban_chat_member(chat_id, target_id)
            await update.message.reply_text(f"✅ {target_link} розблоковано\\!\nМодератор: {mod_link}", parse_mode='MarkdownV2', disable_web_page_preview=True)
        except BadRequest as e: await handle_errors(update, e)

@admin_only
@with_db
async def cmd_unwarn(update: Update, context, cursor):
    target_id, reason = await parse_target(update, context)
    if target_id:
        chat_id = update.message.chat.id
        cursor.execute('UPDATE warnings SET count = count - 1 WHERE user_id = ? AND chat_id = ? AND count > 0', (target_id, chat_id)); cursor.connection.commit()
        count = cursor.execute('SELECT count FROM warnings WHERE user_id = ? AND chat_id = ?', (target_id, chat_id)).fetchone()[0] if cursor.rowcount > 0 else 0
        await update.message.reply_text(f"✅ Попередження знято з {target_id}\nЗагалом: {count}/3" if cursor.rowcount > 0 else "ℹ️ Немає попереджень")

async def parse_target(update: Update, context, return_args=False):
    args = context.args; reason = "Без причини"; target = update.message.reply_to_message.from_user.id if update.message.reply_to_message else None
    if not target:
        await update.message.reply_text("ℹ️ Відповідайте на повідомлення користувача для виконання команди!")
        return None, args if return_args else reason
    if target == update.message.from_user.id:
        await update.message.reply_text("❌ Не можна використовувати на собі!")
        return None, args if return_args else reason
    reason = ' '.join(args) or reason
    return target, args if return_args else reason

def parse_duration_and_reason(args):
    if not args: return 3600, "Без причини"
    time_str = args[0].lower(); reason = ' '.join(args[1:]) or "Без причини"
    units = {'с': 1, 'сек': 1, 'хв': 60, 'год': 3600, 'д': 86400, 'днів': 86400, 'р': 31536000, 'років': 31536000}
    for unit, seconds in units.items():
        if time_str.endswith(unit):
            try: return int(time_str[:-len(unit)]) * seconds, reason
            except ValueError: break
    return 3600, ' '.join(args)

def format_duration(seconds):
    if seconds < 60: return f"{seconds} сек"
    elif seconds < 3600: return f"{seconds // 60} хв"
    elif seconds < 86400: return f"{seconds // 3600} год"
    elif seconds < 31536000: return f"{seconds // 86400} днів"
    return f"{seconds // 31536000} років"

async def handle_errors(update: Update, error: BadRequest):
    error_msg = str(error).lower()
    errors = {
        "not enough rights": "❌ Боту бракує прав!\nНадайте мені права.",
        "user not found": "❌ Користувача не знайдено!",
        "chat_admin_required": "❌ Бот не адмін!\nДодайте мене як адміністратора.",
        "user is an administrator": "❌ Користувач - адмін!",
        "can't restrict self": "❌ Не можу замутити себе!",
        "user is not a member": "❌ Користувач не в чаті!",
        "too many requests": "❌ Занадто багато запитів! Зачекайте.",
        "can't parse entities": "❌ Помилка форматування тексту!",
        "chat not found": "❌ Чат не знайдено!",
        "bot was kicked": "❌ Бота видалено з чату!"
    }
    for key, msg in errors.items():
        if key in error_msg: return await update.message.reply_text(msg)
    await update.message.reply_text(f"❗ Помилка: {error}")

command_map = {
    'привітайся': cmd_show_welcome, '+привітання': cmd_setwelcome, '-привітання': cmd_remove_welcome, 'бан': cmd_ban, '-бан': cmd_ban,
    'унбан': cmd_unban, 'варн': cmd_warn, '-варн': cmd_warn, 'унварн': cmd_unwarn, 'допомога': cmd_help, 'правила': cmd_rules,
    '+правила': cmd_setrules, 'жарт': cmd_joke, 'кік': cmd_kick, 'мут': cmd_mute, 'анмут': cmd_unmute, 'унмут': cmd_unmute,
    '+нік': cmd_set_nickname, '-нік': cmd_remove_nickname, 'нік': cmd_show_nickname
}

async def handle_text(update: Update, context):
    words = update.message.text.strip().split()
    if words and words[0] in command_map: context.args = words[1:]; await command_map[words[0]](update, context)

async def error_handler(update: object, context): 
    logger.error("Exception:", exc_info=context.error)
    if update and hasattr(update, 'message'): await update.message.reply_text('⚠️ Помилка')

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handlers([
        CommandHandler('start', cmd_start), CommandHandler('help', cmd_help), CommandHandler('rules', cmd_rules),
        CommandHandler('setrules', cmd_setrules), CommandHandler('setwelcome', cmd_setwelcome), CommandHandler('joke', cmd_joke),
        CommandHandler('warn', cmd_warn), CommandHandler('ban', cmd_ban), CommandHandler('kick', cmd_kick), CommandHandler('mute', cmd_mute),
        CommandHandler('unmute', cmd_unmute), CommandHandler('unban', cmd_unban), CommandHandler('unwarn', cmd_unwarn),
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_message), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    ])
    app.add_error_handler(error_handler)
    app.run_polling()

if __name__ == '__main__':
    main()