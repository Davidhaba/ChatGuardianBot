import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest
import random
from functools import wraps
import logging
from datetime import datetime, timedelta, UTC
from flask import Flask, render_template
import threading
import os

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)
logger = logging.getLogger(__name__)
TOKEN = '7697842873:AAEIhT22Ho6sTbsWIiiItg3tR6DqYR2tpzY' # '7424478954:AAEnWzgyf9wrDHjVWeBCqZqnMS0MiRuhlQQ'
app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

def init_db():
    with sqlite3.connect('bot.db') as conn:
        c = conn.cursor()
        c.execute('CREATE TABLE IF NOT EXISTS warnings (user_id INTEGER, chat_id INTEGER, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, chat_id))')
        c.execute('CREATE TABLE IF NOT EXISTS rules (chat_id INTEGER PRIMARY KEY, rules_text TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS welcome (chat_id INTEGER PRIMARY KEY, message TEXT)')
        c.execute('CREATE TABLE IF NOT EXISTS nicknames (user_id INTEGER, chat_id INTEGER, nickname TEXT, PRIMARY KEY (user_id, chat_id))')
        c.execute('''CREATE TABLE IF NOT EXISTS cikirkas 
                     (user_id INTEGER PRIMARY KEY, cikirkas INTEGER DEFAULT 0, last_try TIMESTAMP, 
                      cooldown_reduction INTEGER DEFAULT 0, success_boost INTEGER DEFAULT 0, bonus INTEGER DEFAULT 0)''')
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
    if update.message.chat.type == 'private': await update.message.reply_text('🔹 Привіт! Я бот для чату. /help - допомога')

@safe_message
async def cmd_help(update: Update, context): 
    support_link = await get_user_link(await context.bot.get_chat("5046805682"))
    bot_link = await get_user_link(await context.bot.get_chat("7424478954"))
    help_url = "https://teletype.in/@cikir_bot/commands"
    help_text = (
        f"📖 Допомога з функціоналу бота {bot_link}\n\n"
        f"👨‍💻 Агент підтримки\\: {support_link}\n\n"
        f"🗂 Список усіх команд [з їх описом]({help_url})\\."
    )
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("📖 Команди", url=help_url)]])
    await update.message.reply_text(help_text, parse_mode='MarkdownV2', reply_markup=reply_markup, disable_web_page_preview=True)

async def cmd_bot(update: Update, context):
    received_time = update.message.date
    response_time = datetime.now(UTC)
    delay = (response_time - received_time).total_seconds()
    await update.message.reply_text(f"🧑‍💻 Бот онлайн!\n🏓 Затримка: {delay:.2f}с.")

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

@safe_message
@with_db
async def cmd_try(update: Update, context, cursor):
    user_id = update.message.from_user.id
    now = datetime.now(UTC)

    cursor.execute("SELECT cikirkas, last_try, cooldown_reduction, success_boost, bonus FROM cikirkas WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    base_cooldown = 3600
    min_cooldown = 1800
    cooldown = max(min_cooldown, base_cooldown - (result[2] * 60 if result else 0))

    if result and result[1]:
        last_try = datetime.strptime(result[1], '%Y-%m-%d %H:%M:%S').replace(tzinfo=UTC)
        if (now - last_try).total_seconds() < cooldown:
            remaining = int(cooldown - (now - last_try).total_seconds())
            await update.message.reply_text(f"⏳ Зачекайте ще {remaining // 60} хв {remaining % 60} сек!")
            return

    success_boost = min(80, result[3] if result else 0)
    bonus = result[4] if result else 0
    chance = random.random() * 100
    base_chance = 50
    if chance < base_chance + success_boost:
        if chance < 20 + success_boost / 2:
            reward = random.randint(1, 5)
        elif chance < 40 + success_boost:
            reward = random.randint(6, 10)
        else:
            reward = 20
        reward += bonus
    else:
        reward = random.randint(0, 5)

    current_cikirkas = result[0] if result else 0
    if result:
        cursor.execute("UPDATE cikirkas SET cikirkas = ?, last_try = ? WHERE user_id = ?",
                       (current_cikirkas + reward, now.strftime('%Y-%m-%d %H:%M:%S'), user_id))
    else:
        cursor.execute("INSERT INTO cikirkas (user_id, cikirkas, last_try) VALUES (?, ?, ?)",
                       (user_id, reward, now.strftime('%Y-%m-%d %H:%M:%S')))
    cursor.connection.commit()

    if reward > 0:
        await update.message.reply_text(f"🎉 Ви отримали {reward} цикирок! Ваш баланс: {current_cikirkas + reward} цикирок.")
    else:
        await update.message.reply_text("😔 Нічого не випало. Спробуйте ще раз пізніше!")

@safe_message
@with_db
async def cmd_cikirkas(update: Update, context, cursor):
    user_id = update.message.from_user.id
    cursor.execute("SELECT cikirkas, cooldown_reduction, success_boost, bonus FROM cikirkas WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    cooldown_reduction = result[1] if result else 0
    success_boost = result[2] if result else 0
    bonus = result[3] if result else 0
    await update.message.reply_text(
        f"💰 Ваш баланс: {balance} цикирок\n"
        f"⏱ Скорочення часу: {cooldown_reduction} хв\n"
        f"🍀 Шанс успіху: {50 + success_boost}%\n"
        f"🎁 Бонус: +{bonus} цикирок за успіх"
    )

@safe_message
@with_db
async def cmd_shop(update: Update, context, cursor):
    user_id = update.message.from_user.id
    cursor.execute("SELECT cooldown_reduction, success_boost, bonus FROM cikirkas WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    cooldown_reduction, success_boost, bonus = result if result else (0, 0, 0)
    current_cooldown = max(1800, 3600 - cooldown_reduction * 60)
    shop_text = (
        "🏪 Магазин покращень:\n\n"
        f"1. Скорочення часу (50 цикирок) - Зменшує очікування на 1 хв (зараз: {current_cooldown // 60} хв, мін. 30)\n"
        f"2. Шанс успіху (75 цикирок) - +2% до шансу нагороди (зараз: {50 + success_boost}%, макс. 80%)\n"
        f"3. Бонус (100 цикирок) - +1 цикирка за успіх (зараз: +{bonus})\n\n"
        "Використовуйте /buy [назва] для покупки."
    )
    await update.message.reply_text(shop_text)

@safe_message
@with_db
async def cmd_buy(update: Update, context, cursor):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("ℹ️ Вкажіть назву покращення: /buy [назва]")
        return

    item = context.args[0].lower()
    cursor.execute("SELECT cikirkas, cooldown_reduction, success_boost, bonus FROM cikirkas WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    cooldown_reduction, success_boost, bonus = result[1:] if result else (0, 0, 0)

    upgrades = {
        "скорочення": {"cost": 50, "field": "cooldown_reduction", "max": (3600 - 1800) // 60, "current": cooldown_reduction},
        "шанс": {"cost": 75, "field": "success_boost", "max": 30, "current": success_boost},
        "бонус": {"cost": 100, "field": "bonus", "max": None, "current": bonus}
    }

    if item not in upgrades:
        await update.message.reply_text("❌ Такого покращення немає. Перегляньте /shop.")
        return

    upgrade = upgrades[item]
    if upgrade["max"] is not None and upgrade["current"] >= upgrade["max"]:
        await update.message.reply_text(f"❌ Ви досягли максимуму для '{item}'!")
        return

    if balance < upgrade["cost"]:
        await update.message.reply_text(f"❌ Недостатньо цикирок! Потрібно: {upgrade['cost']}, у вас: {balance}")
        return

    cursor.execute(f"UPDATE cikirkas SET cikirkas = cikirkas - ?, {upgrade['field']} = {upgrade['field']} + 1 WHERE user_id = ?",
                   (upgrade["cost"], user_id))
    if not result:
        cursor.execute(f"INSERT INTO cikirkas (user_id, cikirkas, {upgrade['field']}) VALUES (?, ?, 1)",
                       (user_id, -upgrade["cost"]))
    cursor.connection.commit()
    await update.message.reply_text(f"✅ Ви придбали '{item}' за {upgrade['cost']} цикирок! Новий баланс: {balance - upgrade['cost']} цикирок.")

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
    tg_er = "⚠️ Помилка телеграм: "
    errors = {
        "not enough rights": "❌ Боту бракує прав!\nНадайте мені необхідні права.",
        "user not found": "❌ Користувача не знайдено!",
        "chat_admin_required": "❌ Бот не адмін!\nНадайте мені права адміністратора.",
        "user is an administrator": "❌ Користувач є адміністратором чату, і його не можна заблокувати/обмежити.",
        "can't restrict self": "❌ Я не можу обмежувати самого себе!",
        "user is not a member": "❌ Користувач не є учасником чату!",
        "too many requests": "❌ Занадто багато запитів! Зачекайте трохи.",
        "can't parse entities": "❌ Помилка форматування тексту!",
        "chat not found": "❌ Чат не знайдено!",
        "bot was kicked": "❌ Бота було видалено з чату!"
    }
    for key, msg in errors.items():
        if key in error_msg: return await update.message.reply_text(f"{tg_er}\n\n{msg}")
    await update.message.reply_text(f"{tg_er}\n\n{error}")

command_map = {
    'бот': cmd_bot, 'вітання': cmd_show_welcome, 'привітайся': cmd_show_welcome, '+привітання': cmd_setwelcome, '-привітання': cmd_remove_welcome, 'бан': cmd_ban, '-бан': cmd_ban,
    'унбан': cmd_unban, 'анбан': cmd_unban, 'варн': cmd_warn, '-варн': cmd_warn, 'унварн': cmd_unwarn, 'анварн': cmd_unwarn, 'допомога': cmd_help, 'правила': cmd_rules,
    '+правила': cmd_setrules, 'кік': cmd_kick, 'мут': cmd_mute, 'анмут': cmd_unmute, 'унмут': cmd_unmute,
    '+нік': cmd_set_nickname, '-нік': cmd_remove_nickname, 'нік': cmd_show_nickname,
    'спроба': cmd_try, 'цикирки': cmd_cikirkas, 'магазин': cmd_shop, 'купити': cmd_buy
}

async def handle_text(update: Update, context):
    words = update.message.text.strip().split()
    if words and words[0] in command_map: 
        context.args = words[1:]
        await command_map[words[0]](update, context)

async def error_handler(update: object, context): 
    logger.error("Exception:", exc_info=context.error)
    if update and hasattr(update, 'message'): await update.message.reply_text('⚠️ Помилка')

def run_bot():
    bot_app = Application.builder().token(TOKEN).build()
    bot_app.add_handlers([
        CommandHandler('start', cmd_start), CommandHandler('help', cmd_help), CommandHandler('rules', cmd_rules),
        CommandHandler('setrules', cmd_setrules), CommandHandler('setwelcome', cmd_setwelcome),
        CommandHandler('warn', cmd_warn), CommandHandler('ban', cmd_ban), CommandHandler('kick', cmd_kick), CommandHandler('mute', cmd_mute),
        CommandHandler('unmute', cmd_unmute), CommandHandler('unban', cmd_unban), CommandHandler('unwarn', cmd_unwarn),
        CommandHandler('try', cmd_try), CommandHandler('cikirkas', cmd_cikirkas), CommandHandler('shop', cmd_shop), CommandHandler('buy', cmd_buy),
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_message), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    ])
    bot_app.add_error_handler(error_handler)
    bot_app.run_polling()

def run_flask():
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    run_bot()