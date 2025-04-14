import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import BadRequest
from pyrogram import Client
from pyrogram.enums import ParseMode
import random
from functools import wraps
import logging
from datetime import datetime, timedelta, UTC
from flask import Flask, render_template
import threading
import os
import re

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.ERROR)
logger = logging.getLogger(__name__)
TOKEN = os.getenv("BOT_TOKEN")
app = Flask(__name__)

SUPPORTED_COMMANDS = ["warn", "ban", "kick", "mute", "unmute", "unban", "unwarn"]

RANK_NAMES = {
    1: 'Молодший модератор',
    2: 'Старший модератор',
    3: 'Молодший адміністратор',
    4: 'Старший адміністратор',
    5: 'Творець'
}

ERROR_MESSAGES = {
    "not enough rights": "❌ Боту бракує прав!\nНадайте мені необхідні права.",
    "user not found": "❌ Користувача не знайдено!",
    "chat_admin_required": "❌ Бот не адмін!\nНадайте мені права адміністратора.",
    "user is an administrator": "❌ Користувач є адміністратором чату, і його не можна заблокувати/обмежити.",
    "can't restrict self": "❌ Я не можу обмежувати самого себе!",
    "user is not a member": "❌ Користувач не є учасником чату!",
    "too many requests": "❌ Занадто багато запитів! Зачекайте трохи.",
    "can't parse entities": "❌ Помилка форматування тексту!",
    "chat not found": "❌ Чат не знайдено!",
    "bot was kicked": "❌ Бота було видалено з чату!",
}

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
        c.execute('''CREATE TABLE IF NOT EXISTS messages 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER, timestamp TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS moderators 
                     (user_id INTEGER, chat_id INTEGER, rank INTEGER, appointed_by INTEGER, PRIMARY KEY (user_id, chat_id))''')
        c.execute('''CREATE TABLE IF NOT EXISTS chat_settings 
                     (chat_id INTEGER PRIMARY KEY, min_rank_to_add INTEGER DEFAULT 3, 
                      min_rank_warn INTEGER DEFAULT 1, min_rank_ban INTEGER DEFAULT 3, min_rank_kick INTEGER DEFAULT 3,
                      min_rank_mute INTEGER DEFAULT 2, min_rank_unmute INTEGER DEFAULT 2, min_rank_unban INTEGER DEFAULT 3,
                      min_rank_unwarn INTEGER DEFAULT 1)''')
        conn.commit()

init_db()

def safe_message(func):
    @wraps(func)
    async def wrapper(update: Update, context):
        if update and update.message and update.message.chat:
            return await func(update, context)
        return None
    return wrapper

def with_db(func):
    @wraps(func)
    async def wrapper(update: Update, context):
        with sqlite3.connect('bot.db') as conn:
            try:
                return await func(update, context, conn.cursor())
            except Exception as e:
                logger.error(f"DB error: {e}")
                conn.rollback()
    return wrapper

def moderator_only(command):
    def decorator(func):
        @wraps(func)
        @safe_message
        async def wrapper(update: Update, context):
            chat_id = update.message.chat.id
            user_id = update.message.from_user.id
            min_rank = await get_min_rank_for_command(chat_id, command)
            user_rank = await get_user_rank(user_id, chat_id)
            if user_rank < min_rank:
                await update.message.reply_text(f'❌ Недостатній ранг для команди {command}!')
                return
            return await func(update, context)
        return wrapper
    return decorator

@with_db
async def get_user_rank(user_id, chat_id, cursor):
    cursor.execute('SELECT rank FROM moderators WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    result = cursor.fetchone()
    return result[0] if result else 0

async def get_min_rank_for_command(chat_id, command):
    with sqlite3.connect('bot.db') as conn:
        cursor = conn.cursor()
        field = f'min_rank_{command}'
        cursor.execute(f'SELECT {field} FROM chat_settings WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            defaults = {
                'warn': 1,
                'ban': 3,
                'kick': 3,
                'mute': 2,
                'unmute': 2,
                'unban': 3,
                'unwarn': 1
            }
            return defaults.get(command, 1)

@safe_message
async def cmd_start(update: Update, context):
    if update.message.chat.type == 'private':
        await update.message.reply_text('🔹 Привіт! Я бот для чату. /help - допомога')

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

@with_db
async def cmd_rules(update: Update, context, cursor):
    cursor.execute('SELECT rules_text FROM rules WHERE chat_id = ?', (update.message.chat.id,))
    result = cursor.fetchone()
    await update.message.reply_text(f'📜 Правила:\n{result[0]}' if result else '❌ Правила не встановлені')

@with_db
async def cmd_setrules(update: Update, context, cursor):
    if context.args:
        cursor.execute('INSERT OR REPLACE INTO rules VALUES (?, ?)', (update.message.chat.id, ' '.join(context.args)))
        cursor.connection.commit()
        await update.message.reply_text('✅ Правила оновлено!')
    else:
        await update.message.reply_text('ℹ️ Вкажіть текст правил')

@with_db
async def cmd_setwelcome(update: Update, context, cursor):
    text = update.message.text.partition(' ')[2].strip()
    if text:
        cursor.execute('INSERT OR REPLACE INTO welcome VALUES (?, ?)', (update.message.chat.id, text))
        cursor.connection.commit()
        await update.message.reply_text('✅ Привітання оновлено!')
    else:
        await update.message.reply_text('ℹ️ Вкажіть текст привітання')

@with_db
async def get_welcome(update: Update, context, cursor):
    cursor.execute('SELECT message FROM welcome WHERE chat_id = ?', (update.message.chat.id,))
    result = cursor.fetchone()
    return result[0] if result else None

async def cmd_show_welcome(update: Update, context):
    msg = await get_welcome(update, context)
    await update.message.reply_text(f'👋 Привітання:\n{msg}' if msg else '❌ Привітання не встановлено')

@with_db
async def assign_creator_rank(chat_id, creator_id, cursor):
    cursor.execute('SELECT rank FROM moderators WHERE user_id = ? AND chat_id = ?', (creator_id, chat_id))
    if not cursor.fetchone():
        cursor.execute('INSERT INTO moderators (user_id, chat_id, rank, appointed_by) VALUES (?, ?, ?, ?)',
                       (creator_id, chat_id, 5, creator_id))
        cursor.connection.commit()

async def welcome_message(update: Update, context):
    chat_id = update.message.chat.id
    new_members = update.message.new_chat_members
    bot_id = context.bot.id
    if any(member.id == bot_id for member in new_members):
        try:
            administrators = await context.bot.get_chat_administrators(chat_id)
            creator = next((admin for admin in administrators if admin.status == 'creator'), None)
            if creator:
                await assign_creator_rank(chat_id, creator.user.id)
                await context.bot.send_message(
                    chat_id,
                    f"👑 Творцю чату {creator.user.first_name} автоматично призначено ранг 5!",
                )
        except Exception as e:
            print(f"Помилка: {e}")

    if msg := await get_welcome(update, context):
        for member in new_members:
            user_link = await get_user_link(member, chat_id)
            text = escape_markdown_text(msg).replace('\\{name\\}', user_link)
            await update.message.reply_text(text, parse_mode='MarkdownV2', disable_web_page_preview=True)

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

@with_db
async def cmd_remove_nickname(update: Update, context, cursor):
    user_id = update.message.from_user.id
    chat_id = update.message.chat.id
    cursor.execute('DELETE FROM nicknames WHERE user_id = ? AND chat_id = ?', (user_id, chat_id))
    cursor.connection.commit()
    await update.message.reply_text('✅ Нікнейм видалено!' if cursor.rowcount > 0 else 'ℹ️ Нікнейм не був встановлений')

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
    name = escape_markdown_text(name)
    return f"[{name}](https://t.me/{member.username})" if member.username else f"[{name}](tg://user?id={member.id})"

def escape_markdown_text(text):
    return ''.join(f'\\{c}' if c in '_*[]()~`>#+-=|{{}}.!' else c for c in text)

@with_db
async def cmd_remove_welcome(update: Update, context, cursor):
    cursor.execute('DELETE FROM welcome WHERE chat_id = ?', (update.message.chat.id,))
    cursor.connection.commit()
    await update.message.reply_text('✅ Привітання видалено!' if cursor.rowcount > 0 else 'ℹ️ Привітання не було встановлено.')

@moderator_only('warn')
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

@moderator_only('ban')
async def cmd_ban(update: Update, context):
    target_id, reason = await parse_target(update, context)
    if target_id:
        try:
            target = await context.bot.get_chat(target_id); target_link = await get_user_link(target, update.message.chat.id); mod_link = await get_user_link(update.message.from_user, update.message.chat.id)
            await context.bot.ban_chat_member(update.message.chat.id, target_id)
            await update.message.reply_text(f"🚫 {target_link} заблоковано\\!\nПричина: {reason}\nМодератор: {mod_link}", parse_mode='MarkdownV2', disable_web_page_preview=True)
        except BadRequest as e: await handle_errors(update, e)

@moderator_only('kick')
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

@moderator_only('mute')
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

@moderator_only('unmute')
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

@moderator_only('unban')
async def cmd_unban(update: Update, context):
    target_id, reason = await parse_target(update, context)
    if target_id:
        chat_id = update.message.chat.id
        try:
            target = await context.bot.get_chat(target_id); target_link = await get_user_link(target, chat_id); mod_link = await get_user_link(update.message.from_user, chat_id)
            await context.bot.unban_chat_member(chat_id, target_id)
            await update.message.reply_text(f"✅ {target_link} розблоковано\\!\nМодератор: {mod_link}", parse_mode='MarkdownV2', disable_web_page_preview=True)
        except BadRequest as e: await handle_errors(update, e)

@moderator_only('unwarn')
@with_db
async def cmd_unwarn(update: Update, context, cursor):
    target_id, reason = await parse_target(update, context)
    if target_id:
        chat_id = update.message.chat.id
        cursor.execute('UPDATE warnings SET count = count - 1 WHERE user_id = ? AND chat_id = ? AND count > 0', (target_id, chat_id))
        cursor.connection.commit()
        count = cursor.execute('SELECT count FROM warnings WHERE user_id = ? AND chat_id = ?', (target_id, chat_id)).fetchone()[0] if cursor.rowcount > 0 else 0
        await update.message.reply_text(f"✅ Попередження знято з {target_id}\nЗагалом: {count}/3" if cursor.rowcount > 0 else "ℹ️ Немає попереджень")

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
        "Оберіть покращення:"
    )
    keyboard = [
        [InlineKeyboardButton("Скорочення часу", callback_data="buy_cooldown")],
        [InlineKeyboardButton("Шанс успіху", callback_data="buy_success")],
        [InlineKeyboardButton("Бонус", callback_data="buy_bonus")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(shop_text, reply_markup=reply_markup)

async def buy_upgrade(user_id, item, cursor, context, chat_id, message_id=None):
    cursor.execute("SELECT cikirkas, cooldown_reduction, success_boost, bonus FROM cikirkas WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    cooldown_reduction, success_boost, bonus = result[1:] if result else (0, 0, 0)
    upgrades = {
        "скорочення": {"cost": 50, "field": "cooldown_reduction", "max": (3600 - 1800) // 60, "current": cooldown_reduction, "name": "скорочення"},
        "шанс": {"cost": 75, "field": "success_boost", "max": 30, "current": success_boost, "name": "шанс"},
        "бонус": {"cost": 100, "field": "bonus", "max": None, "current": bonus, "name": "бонус"},
        "buy_cooldown": {"cost": 50, "field": "cooldown_reduction", "max": (3600 - 1800) // 60, "current": cooldown_reduction, "name": "скорочення"},
        "buy_success": {"cost": 75, "field": "success_boost", "max": 30, "current": success_boost, "name": "шанс"},
        "buy_bonus": {"cost": 100, "field": "bonus", "max": None, "current": bonus, "name": "бонус"}
    }
    if item not in upgrades:
        response = "❌ Такого покращення немає. Перегляньте /shop."
    else:
        upgrade = upgrades[item]
        if upgrade["max"] is not None and upgrade["current"] >= upgrade["max"]:
            response = f"❌ Ви досягли максимуму для '{upgrade['name']}'!"
        elif balance < upgrade["cost"]:
            response = f"❌ Недостатньо цикирок! Потрібно: {upgrade['cost']}, у вас: {balance}"
        else:
            cursor.execute(f"UPDATE cikirkas SET cikirkas = cikirkas - ?, {upgrade['field']} = {upgrade['field']} + 1 WHERE user_id = ?",
                           (upgrade["cost"], user_id))
            if not result:
                cursor.execute(f"INSERT INTO cikirkas (user_id, cikirkas, {upgrade['field']}) VALUES (?, ?, 1)",
                               (user_id, -upgrade["cost"]))
            cursor.connection.commit()
            response = f"✅ Ви придбали '{upgrade['name']}' за {upgrade['cost']} цикирок!\nНовий баланс: {balance - upgrade['cost']} цикирок."
    if message_id:
        await context.bot.edit_message_text(response, chat_id=chat_id, message_id=message_id)
    else:
        await context.bot.send_message(chat_id=chat_id, text=response)

@with_db
async def cmd_buy(update: Update, context, cursor):
    user_id = update.message.from_user.id
    if not context.args:
        await update.message.reply_text("ℹ️ Вкажіть назву покращення: /buy [назва]")
        return
    item = context.args[0].lower()
    await buy_upgrade(user_id, item, cursor, context, update.message.chat.id)

@with_db
async def cmd_leaderboard(update: Update, context, cursor):
    cursor.execute("SELECT user_id, cikirkas FROM cikirkas ORDER BY cikirkas DESC LIMIT 10")
    results = cursor.fetchall()
    if not results:
        await update.message.reply_text("🏆 Рейтинг порожній!")
        return
    leaderboard = "🏆 Рейтинг цикирок\\:\n\n"
    for i, (user_id, cikirkas) in enumerate(results, 1):
        try:
            user = await context.bot.get_chat(user_id)
            user_link = await get_user_link(user, update.message.chat.id)
            leaderboard += f"{i}\\. {user_link} — \\{cikirkas} цикирок\n"
        except BadRequest:
            leaderboard += f"{i}\\. \\[Користувач видалений\\] — {cikirkas} цикирок\n"
    await update.message.reply_text(leaderboard, parse_mode='MarkdownV2', disable_web_page_preview=True)

@with_db
async def cmd_stats(update: Update, context, cursor):
    chat_id = update.message.chat.id
    show_all = context.args and context.args[0].lower() == 'вся'
    title = "📊 Статистика по товариським користувачам за весь час" if show_all else "📊 Статистика по товариським користувачам за добу"
    if show_all:
        cursor.execute("""
            SELECT user_id, COUNT(*) as count 
            FROM messages 
            WHERE chat_id = ? 
            GROUP BY user_id 
            ORDER BY count DESC 
            LIMIT 10
        """, (chat_id,))
        results = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ?", (chat_id,))
    else:
        since = (datetime.now(UTC) - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("""
            SELECT user_id, COUNT(*) as count 
            FROM messages 
            WHERE chat_id = ? AND timestamp >= ? 
            GROUP BY user_id 
            ORDER BY count DESC 
            LIMIT 10
        """, (chat_id, since))
        results = cursor.fetchall()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE chat_id = ? AND timestamp >= ?", (chat_id, since))
    total_result = cursor.fetchone()
    total_messages = total_result[0] if total_result else 0
    if not results:
        await update.message.reply_text(f"{title}\n\nНемає повідомлень\\!", parse_mode='MarkdownV2')
        return
    stats = f"*{title}*\n\n"
    for i, (user_id, count) in enumerate(results, 1):
        try:
            user = await context.bot.get_chat(user_id)
            user_link = await get_user_link(user, chat_id)
            stats += f"{i}\\. {user_link} — \\{count}\n"
        except BadRequest:
            stats += f"{i}\\. \\[Користувач видалений\\] — \\{count} повідомлень\n"
    stats += f"\nВсього повідомлень\\: \\{total_messages}"
    await update.message.reply_text(stats, parse_mode='MarkdownV2', disable_web_page_preview=True)

@with_db
async def track_messages(update: Update, context, cursor):
    if update.message.chat.type in ['group', 'supergroup']:
        user_id = update.message.from_user.id
        chat_id = update.message.chat.id
        timestamp = datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('INSERT INTO messages (user_id, chat_id, timestamp) VALUES (?, ?, ?)', (user_id, chat_id, timestamp))
        cursor.connection.commit()

@with_db
async def button_handler(update: Update, context, cursor):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    choice = query.data
    await buy_upgrade(user_id, choice, cursor, context, query.message.chat.id, query.message.message_id)

async def parse_target(update: Update, context, return_args=False):
    args = context.args
    reason = "Без причини"
    target_id = None
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    elif args:
        target_arg = args[0]
        if target_arg.isdigit():
            target_id = int(target_arg)
        elif target_arg.startswith('@'):
            try:
                user = await context.bot.get_chat(target_arg)
                target_id = user.id
            except BadRequest:
                await update.message.reply_text('❌ Користувача не знайдено!')
                return None, args if return_args else reason
        else:
            match = re.search(r'tg://user\?id=(\d+)', target_arg)
            if not match:
                match = re.search(r'id=(\d+)', target_arg)
            if match:
                target_id = int(match.group(1))
            else:
                for entity in update.message.entities:
                    if entity.type == 'text_mention':
                        target_id = entity.user.id
                        break
                if not target_id:
                    await update.message.reply_text('❌ Невірний формат аргументу! Вкажіть ID, @username або посилання на профіль.')
                    return None, args if return_args else reason
    if not target_id:
        await update.message.reply_text('ℹ️ Вкажіть користувача через ID, @username, посилання на профіль або відповівши на його повідомлення!')
        return None, args if return_args else reason
    if target_id == update.message.from_user.id:
        await update.message.reply_text('❌ Не можна використовувати команду на собі!')
        return None, args if return_args else reason
    if return_args:
        return target_id, args[1:] if len(args) > 1 else []
    else:
        reason = ' '.join(args[1:]) if len(args) > 1 else reason
        return target_id, reason

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
    for key, msg in ERROR_MESSAGES.items():
        if key in error_msg: return await update.message.reply_text(f"{tg_er}\n\n{msg}")
    await update.message.reply_text(f"{tg_er}\n\n{error}")

@with_db
async def cmd_list_moderators(update: Update, context, cursor):
    chat_id = update.message.chat.id
    cursor.execute('SELECT user_id, rank FROM moderators WHERE chat_id = ? ORDER BY rank DESC', (chat_id,))
    moderators = cursor.fetchall()
    if not moderators:
        return await update.message.reply_text('ℹ️ Немає модераторів!')
    list_text = '📋 Список модераторів:\n\n'
    for user_id, rank in moderators:
        try:
            user = await context.bot.get_chat(user_id)
            user_link = await get_user_link(user, chat_id)
            list_text += f"{user_link} — {RANK_NAMES[rank]}\n"
        except BadRequest:
            list_text += f"[Користувач видалений] — {RANK_NAMES[rank]}\n"
    await update.message.reply_text(list_text, parse_mode='MarkdownV2')

@with_db
async def cmd_who_appointed(update: Update, context, cursor):
    chat_id = update.message.chat.id
    if not context.args:
        return await update.message.reply_text('ℹ️ Вкажіть користувача: Кто назначил [ссылка]')
    target_id = await parse_target_id(context.args[0], context)
    if not target_id:
        return await update.message.reply_text('❌ Не вдалося знайти користувача!')
    cursor.execute('SELECT appointed_by FROM moderators WHERE user_id = ? AND chat_id = ?', (target_id, chat_id))
    result = cursor.fetchone()
    if not result:
        return await update.message.reply_text('❌ Користувач не є модератором!')
    appointed_by = result[0]
    try:
        appointer = await context.bot.get_chat(appointed_by)
        appointer_link = await get_user_link(appointer, chat_id)
        target = await context.bot.get_chat(target_id)
        target_link = await get_user_link(target, chat_id)
        await update.message.reply_text(f'ℹ️ {target_link} був призначений модератором користувачем {appointer_link}!', parse_mode='MarkdownV2')
    except BadRequest:
        await update.message.reply_text('❌ Не вдалося знайти призначаючого!')

async def add_moderator(update: Update, context, rank_to_add):
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    min_rank_to_add = await get_min_rank_to_add(chat_id)
    user_rank = await get_user_rank(user_id, chat_id)
    if user_rank < min_rank_to_add:
        return await update.message.reply_text('❌ Ви не можете призначати модераторів! Недостатній ранг.')
    if not context.args:
        return await update.message.reply_text(f'ℹ️ Вкажіть користувача: +Модер{rank_to_add} [ссылка]')
    target_id = await parse_target_id(context.args[0], context)
    if not target_id:
        return await update.message.reply_text('❌ Не вдалося знайти користувача!')
    target_rank = await get_user_rank(target_id, chat_id)
    if target_rank > 0:
        return await update.message.reply_text('❌ Користувач вже є модератором!')
    if rank_to_add >= user_rank:
        return await update.message.reply_text('❌ Ви не можете призначити ранг, вищий або рівний вашому!')
    with sqlite3.connect('bot.db') as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO moderators (user_id, chat_id, rank, appointed_by) VALUES (?, ?, ?, ?)', 
                       (target_id, chat_id, rank_to_add, user_id))
        conn.commit()
    target = await context.bot.get_chat(target_id)
    target_link = await get_user_link(target, chat_id)
    await update.message.reply_text(f'✅ {target_link} призначено {RANK_NAMES[rank_to_add].lower()}!', parse_mode='MarkdownV2')

@with_db
async def cmd_promote_moderator(update: Update, context, cursor):
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    user_rank = await get_user_rank(user_id, chat_id)
    if user_rank < 3:
        return await update.message.reply_text('❌ Ви не можете підвищувати модераторів! Недостатній ранг.')
    if not context.args:
        return await update.message.reply_text('ℹ️ Вкажіть користувача: !повысить [ссылка]')
    target_id = await parse_target_id(context.args[0], context)
    if not target_id:
        return await update.message.reply_text('❌ Не вдалося знайти користувача!')
    target_rank = await get_user_rank(target_id, chat_id)
    if target_rank == 0:
        return await update.message.reply_text('❌ Користувач не є модератором!')
    if target_rank >= user_rank:
        return await update.message.reply_text('❌ Ви не можете підвищувати користувачів з рангом, вищим або рівним вашому!')
    new_rank = min(target_rank + 1, 5)
    cursor.execute('UPDATE moderators SET rank = ? WHERE user_id = ? AND chat_id = ?', (new_rank, target_id, chat_id))
    cursor.connection.commit()
    target = await context.bot.get_chat(target_id)
    target_link = await get_user_link(target, chat_id)
    await update.message.reply_text(f'✅ {target_link} підвищено до {RANK_NAMES[new_rank].lower()}!', parse_mode='MarkdownV2')

@with_db
async def cmd_demote_moderator(update: Update, context, cursor):
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    user_rank = await get_user_rank(user_id, chat_id)
    if user_rank < 3:
        return await update.message.reply_text('❌ Ви не можете понижувати модераторів! Недостатній ранг.')
    if not context.args:
        return await update.message.reply_text('ℹ️ Вкажіть користувача: !понизить [ссылка]')
    target_id = await parse_target_id(context.args[0], context)
    if not target_id:
        return await update.message.reply_text('❌ Не вдалося знайти користувача!')
    target_rank = await get_user_rank(target_id, chat_id)
    if target_rank == 0:
        return await update.message.reply_text('❌ Користувач не є модератором!')
    if target_rank >= user_rank:
        return await update.message.reply_text('❌ Ви не можете понижувати користувачів з рангом, вищим або рівним вашому!')
    new_rank = max(target_rank - 1, 1)
    cursor.execute('UPDATE moderators SET rank = ? WHERE user_id = ? AND chat_id = ?', (new_rank, target_id, chat_id))
    cursor.connection.commit()
    target = await context.bot.get_chat(target_id)
    target_link = await get_user_link(target, chat_id)
    await update.message.reply_text(f'✅ {target_link} понижено до {RANK_NAMES[new_rank].lower()}!', parse_mode='MarkdownV2')

@with_db
async def cmd_remove_moderator(update: Update, context, cursor):
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    user_rank = await get_user_rank(user_id, chat_id)
    if user_rank < 3:
        return await update.message.reply_text('❌ Ви не можете знімати модераторів! Недостатній ранг.')
    if not context.args:
        return await update.message.reply_text('ℹ️ Вкажіть користувача: !снять [ссылка]')
    target_id = await parse_target_id(context.args[0], context)
    if not target_id:
        return await update.message.reply_text('❌ Не вдалося знайти користувача!')
    target_rank = await get_user_rank(target_id, chat_id)
    if target_rank == 0:
        return await update.message.reply_text('❌ Користувач не є модератором!')
    if target_rank >= user_rank:
        return await update.message.reply_text('❌ Ви не можете знімати користувачів з рангом, вищим або рівним вашому!')
    cursor.execute('DELETE FROM moderators WHERE user_id = ? AND chat_id = ?', (target_id, chat_id))
    cursor.connection.commit()
    target = await context.bot.get_chat(target_id)
    target_link = await get_user_link(target, chat_id)
    await update.message.reply_text(f'✅ {target_link} більше не є модератором!', parse_mode='MarkdownV2')

@with_db
async def cmd_remove_left_moderators(update: Update, context, cursor):
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    user_rank = await get_user_rank(user_id, chat_id)
    if user_rank < 3:
        return await update.message.reply_text('❌ Ви не можете знімати модераторів! Недостатній ранг.')
    cursor.execute('SELECT user_id FROM moderators WHERE chat_id = ?', (chat_id,))
    moderators = cursor.fetchall()
    left_mods = []
    for mod in moderators:
        try:
            member = await context.bot.get_chat_member(chat_id, mod[0])
            if member.status in ['left', 'kicked']:
                left_mods.append(mod[0])
        except BadRequest:
            left_mods.append(mod[0])
    if not left_mods:
        return await update.message.reply_text('ℹ️ Немає вишедших модераторів!')
    for mod_id in left_mods:
        cursor.execute('DELETE FROM moderators WHERE user_id = ? AND chat_id = ?', (mod_id, chat_id))
    cursor.connection.commit()
    await update.message.reply_text(f'✅ Знято статус з {len(left_mods)} вишедших модераторів!')

@with_db
async def cmd_remove_all_moderators(update: Update, context, cursor):
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    user_rank = await get_user_rank(user_id, chat_id)
    if user_rank < 5:
        return await update.message.reply_text('❌ Лише творець може зняти всіх модераторів!')
    cursor.execute('DELETE FROM moderators WHERE chat_id = ?', (chat_id,))
    cursor.connection.commit()
    await update.message.reply_text('✅ Всі модератори зняті!')

@with_db
async def cmd_set_min_rank(update: Update, context, cursor):
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    user_rank = await get_user_rank(user_id, chat_id)
    if user_rank < 5:
        return await update.message.reply_text('❌ Лише творець може змінювати мінімальний ранг!')
    if not context.args or not context.args[0].isdigit():
        return await update.message.reply_text('ℹ️ Вкажіть числовий ранг: set_min_rank [ранг]')
    new_min_rank = int(context.args[0])
    if new_min_rank < 1 or new_min_rank > 5:
        return await update.message.reply_text('❌ Ранг має бути від 1 до 5!')
    cursor.execute('INSERT OR REPLACE INTO chat_settings (chat_id, min_rank_to_add) VALUES (?, ?)', (chat_id, new_min_rank))
    cursor.connection.commit()
    await update.message.reply_text(f'✅ Мінімальний ранг для призначення модераторів встановлено на {new_min_rank}!')

@with_db
async def cmd_set_min_rank_command(update: Update, context, cursor):
    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    user_rank = await get_user_rank(user_id, chat_id)
    if user_rank < 5:
        return await update.message.reply_text('❌ Лише творець може змінювати мінімальні ранги!')
    if len(context.args) != 2 or not context.args[1].isdigit():
        return await update.message.reply_text('ℹ️ Використання: set_min_rank_command [команда] [ранг]')
    command = context.args[0].lower()
    new_min_rank = int(context.args[1])
    if new_min_rank < 1 or new_min_rank > 5:
        return await update.message.reply_text('❌ Ранг має бути від 1 до 5!')
    field = f'min_rank_{command}'
    cursor.execute(f'PRAGMA table_info(chat_settings)')
    columns = [col[1] for col in cursor.fetchall()]
    if field not in columns:
        supported_commands_list = ", ".join(SUPPORTED_COMMANDS)
        return await update.message.reply_text(f'❌ Команда "{command}" не підтримується!\n\nПідтримувані команди: {supported_commands_list}')
    cursor.execute(f'INSERT OR REPLACE INTO chat_settings (chat_id, {field}) VALUES (?, ?)', (chat_id, new_min_rank))
    cursor.connection.commit()
    await update.message.reply_text(f'✅ Мінімальний ранг для {command} встановлено на {new_min_rank}!')

async def get_user_by_username(username: str):
    async with get_user_by_username_bot as bot:
        try:
            user = await bot.get_users(username)
            return user
        except Exception as err:
            return None

async def parse_target_id(arg, context):
    if arg.isdigit():
        return int(arg)
    elif arg.startswith('@'):
        try:
            user = await get_user_by_username(arg)
            return user.id
        except BadRequest:
            return None
    else:
        match = re.search(r'tg://user\?id=(\d+)', arg)
        if match:
            return int(match.group(1))
    return None

async def get_min_rank_to_add(chat_id):
    with sqlite3.connect('bot.db') as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT min_rank_to_add FROM chat_settings WHERE chat_id = ?', (chat_id,))
        result = cursor.fetchone()
        return result[0] if result else 3

async def cmd_add_moderator(update: Update, context):
    if not context.args or len(context.args) < 2 or not context.args[1].isdigit():
        return await update.message.reply_text('ℹ️ Використання: +модер [ссылка] [ранг]')
    rank_to_add = int(context.args[1])
    if rank_to_add < 1 or rank_to_add > 5:
        return await update.message.reply_text('❌ Ранг має бути від 1 до 5!')
    await add_moderator(update, context, rank_to_add)

command_map = {
    'бот': cmd_bot, 'вітання': cmd_show_welcome, 'привітайся': cmd_show_welcome, '+привітання': cmd_setwelcome, '-привітання': cmd_remove_welcome, 'бан': cmd_ban, '-бан': cmd_ban,
    'унбан': cmd_unban, 'анбан': cmd_unban, 'варн': cmd_warn, '-варн': cmd_warn, 'унварн': cmd_unwarn, 'анварн': cmd_unwarn, 'допомога': cmd_help, 'правила': cmd_rules,
    '+правила': cmd_setrules, 'кік': cmd_kick, 'мут': cmd_mute, 'анмут': cmd_unmute, 'унмут': cmd_unmute,
    '+нік': cmd_set_nickname, '-нік': cmd_remove_nickname, 'нік': cmd_show_nickname,
    'спроба': cmd_try, 'цикирки': cmd_cikirkas, 'магазин': cmd_shop, 'купити': cmd_buy, 'рейтинг': cmd_leaderboard,
    'стата': cmd_stats, 'хто адмін': cmd_list_moderators, 'хто назначив': cmd_who_appointed,
    '+модер': cmd_add_moderator, '!повисити': cmd_promote_moderator,
    '!понизити': cmd_demote_moderator, '!зняти': cmd_remove_moderator,
    '!зняти вибулих': cmd_remove_left_moderators, '!зняти всіх': cmd_remove_all_moderators
}

async def handle_text(update: Update, context):
    await track_messages(update, context)
    words = update.message.text.strip().split()
    if words and words[0] in command_map:
        context.args = words[1:]
        await command_map[words[0]](update, context)

async def error_handler(update: object, context):
    logger.error("Exception:", exc_info=context.error)
    if update and hasattr(update, 'message'):
        await update.message.reply_text('⚠️ Помилка')

def run_bot():
    bot_app = Application.builder().token(TOKEN).build()
    bot_app.add_handlers([
        CommandHandler('start', cmd_start), CommandHandler('help', cmd_help), CommandHandler('rules', cmd_rules),
        CommandHandler('setrules', cmd_setrules), CommandHandler('setwelcome', cmd_setwelcome),
        CommandHandler('warn', cmd_warn), CommandHandler('ban', cmd_ban), CommandHandler('kick', cmd_kick), CommandHandler('mute', cmd_mute),
        CommandHandler('unmute', cmd_unmute), CommandHandler('unban', cmd_unban), CommandHandler('unwarn', cmd_unwarn),
        CommandHandler('try', cmd_try), CommandHandler('cikirkas', cmd_cikirkas), CommandHandler('shop', cmd_shop), CommandHandler('buy', cmd_buy), CommandHandler('leaderboard', cmd_leaderboard), CommandHandler('stats', cmd_stats),
        CommandHandler('set_min_rank_command', cmd_set_min_rank_command), CommandHandler('set_min_rank', cmd_set_min_rank),
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_message), MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
        CallbackQueryHandler(button_handler)
    ])
    bot_app.add_error_handler(error_handler)
    bot_app.run_polling()

def run_flask():
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    get_user_by_username_bot = Client(name="get_user_by_username_bot", api_id=25122036, api_hash="3e906c8d3c372af56e273f46f505730f", bot_token=TOKEN, parse_mode=ParseMode.HTML)
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.start()
    run_bot()
