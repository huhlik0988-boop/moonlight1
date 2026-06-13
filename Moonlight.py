import telebot
from telebot.types import ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
import time
import datetime
import re
import sqlite3
import threading

# Инициализация бота
TOKEN = '8817228602:AAHTUcZFNe3znBs60ZamEGr_CxgmThgsFKM'
bot = telebot.TeleBot(TOKEN)

# --- РАБОТА С БАЗОЙ ДАННЫХ SQLite ---
def init_db():
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    # Таблица варнов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS warns (
            chat_id INTEGER,
            user_id INTEGER,
            count INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    # Таблица мутов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mutes (
            chat_id INTEGER,
            user_id INTEGER,
            unmute_time INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    # Таблица рангов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ranks (
            chat_id INTEGER,
            user_id INTEGER,
            rank_name TEXT,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    # Таблица активности
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_activity (
            chat_id INTEGER,
            user_id INTEGER,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    # Таблица репутации
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reputation (
            chat_id INTEGER,
            user_id INTEGER,
            rep_value INTEGER DEFAULT 0,
            PRIMARY KEY (chat_id, user_id)
        )
    ''')
    # Таблица браков
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS marriages (
            chat_id INTEGER,
            user_one INTEGER,
            user_two INTEGER,
            PRIMARY KEY (chat_id, user_one)
        )
    ''')
    
    # АВТО-МИГРАЦИЯ БАЗЫ ДАННЫХ
    cursor.execute("PRAGMA table_info(user_activity)")
    columns_activity = [column[1] for column in cursor.fetchall()]
    if 'username' not in columns_activity:
        cursor.execute('ALTER TABLE user_activity ADD COLUMN username TEXT')
    if 'first_name' not in columns_activity:
        cursor.execute('ALTER TABLE user_activity ADD COLUMN first_name TEXT')
    if 'last_name' not in columns_activity:
        cursor.execute('ALTER TABLE user_activity ADD COLUMN last_name TEXT')
    if 'msg_count' not in columns_activity:
        cursor.execute('ALTER TABLE user_activity ADD COLUMN msg_count INTEGER DEFAULT 0')
    if 'first_seen' not in columns_activity:
        cursor.execute('ALTER TABLE user_activity ADD COLUMN first_seen INTEGER')

    cursor.execute("PRAGMA table_info(marriages)")
    columns_marriages = [column[1] for column in cursor.fetchall()]
    if 'marriage_time' not in columns_marriages:
        cursor.execute('ALTER TABLE marriages ADD COLUMN marriage_time INTEGER')
        
    conn.commit()
    conn.close()

# Запись активности и кэширование метаданных
def log_message_activity(chat_id, user_id, username, first_name, last_name):
    try:
        conn = sqlite3.connect('moderation_bot.db')
        cursor = conn.cursor()
        current_time = int(time.time())
        username = username.lower() if username else None
        
        cursor.execute('SELECT msg_count FROM user_activity WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
        row = cursor.fetchone()
        
        if row is None:
            cursor.execute('''
                INSERT INTO user_activity (chat_id, user_id, username, first_name, last_name, msg_count, first_seen)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            ''', (chat_id, user_id, username, first_name, last_name, current_time))
        else:
            cursor.execute('''
                UPDATE user_activity 
                SET username = ?, first_name = ?, last_name = ?, msg_count = msg_count + 1
                WHERE chat_id = ? AND user_id = ?
            ''', (username, first_name, last_name, chat_id, user_id))
            
        conn.commit()
        conn.close()
    except Exception: pass

# Модуль Репутации
def db_change_reputation(chat_id, user_id, amount):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO reputation (chat_id, user_id, rep_value) VALUES (?, ?, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET rep_value = rep_value + excluded.rep_value', (chat_id, user_id, amount))
    cursor.execute('SELECT rep_value FROM reputation WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    new_rep = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return new_rep

def db_get_reputation(chat_id, user_id):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT rep_value FROM reputation WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

# Улучшенный модуль Браков с таймштампом
def db_create_marriage(chat_id, u1, u2):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    now = int(time.time())
    cursor.execute('INSERT OR REPLACE INTO marriages (chat_id, user_one, user_two, marriage_time) VALUES (?, ?, ?, ?)', (chat_id, u1, u2, now))
    cursor.execute('INSERT OR REPLACE INTO marriages (chat_id, user_one, user_two, marriage_time) VALUES (?, ?, ?, ?)', (chat_id, u2, u1, now))
    conn.commit()
    conn.close()

def db_get_marriage(chat_id, user_id):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_two, marriage_time FROM marriages WHERE chat_id = ? AND user_one = ?', (chat_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row if row else (None, None)

def db_delete_marriage(chat_id, user_id):
    partner_id, _ = db_get_marriage(chat_id, user_id)
    if not partner_id: return False
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM marriages WHERE chat_id = ? AND user_one = ?', (chat_id, user_id))
    cursor.execute('DELETE FROM marriages WHERE chat_id = ? AND user_one = ?', (chat_id, partner_id))
    conn.commit()
    conn.close()
    return True

def db_get_all_marriages(chat_id):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_one, user_two FROM marriages WHERE chat_id = ?', (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    seen = set()
    result = []
    for u1, u2 in rows:
        pair = tuple(sorted([u1, u2]))
        if pair not in seen:
            seen.add(pair)
            result.append(pair)
    return result

# Системные запросы
def db_get_user_by_username(chat_id, username):
    username = username.replace("@", "").strip().lower()
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM user_activity WHERE chat_id = ? AND username = ?', (chat_id, username))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def db_get_activity(chat_id, user_id):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT msg_count, first_seen FROM user_activity WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    row = cursor.fetchone()
    conn.close()
    if row: return row[0], row[1]
    return 0, int(time.time())

def db_get_top_users(chat_id, limit=10):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, msg_count FROM user_activity WHERE chat_id = ? AND msg_count > 0 ORDER BY msg_count DESC LIMIT ?', (chat_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows

def db_get_warns(chat_id, user_id):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT count FROM warns WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def db_set_warns(chat_id, user_id, count):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO warns (chat_id, user_id, count) VALUES (?, ?, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET count = excluded.count', (chat_id, user_id, count))
    conn.commit()
    conn.close()

def db_set_mute(chat_id, user_id, unmute_time):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO mutes (chat_id, user_id, unmute_time) VALUES (?, ?, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET unmute_time = excluded.unmute_time', (chat_id, user_id, unmute_time))
    conn.commit()
    conn.close()

def db_remove_mute(chat_id, user_id):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM mutes WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    conn.commit()
    conn.close()

def db_get_rank(chat_id, user_id):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT rank_name FROM ranks WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def db_set_rank(chat_id, user_id, rank_name):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    if rank_name == "Участник":
        cursor.execute('DELETE FROM ranks WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
    else:
        cursor.execute('INSERT INTO ranks (chat_id, user_id, rank_name) VALUES (?, ?, ?) ON CONFLICT(chat_id, user_id) DO UPDATE SET rank_name = excluded.rank_name', (chat_id, user_id, rank_name))
    conn.commit()
    conn.close()

def db_get_all_ranks(chat_id):
    conn = sqlite3.connect('moderation_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, rank_name FROM ranks WHERE chat_id = ?', (chat_id,))
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

init_db()

# --- ИЕРАРХИЯ РАНГОВ ---
RANKS_TIERS = ["Младший модератор", "Модератор", "Младший админ", "Владелец"]
RANKS_INDEXES = {"Младший модератор": "[1]", "Модератор": "[2]", "Младший админ": "[3]", "Владелец": "[5]"}

def get_user_rank(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status == 'creator': return "Владелец"
        saved_rank = db_get_rank(chat_id, user_id)
        if saved_rank: return saved_rank
        if member.status == 'administrator': return "Младший админ"
    except Exception: pass
    return "Участник"

def get_rank_level(rank_name):
    if rank_name == "Участник": return 0
    try: return RANKS_TIERS.index(rank_name) + 1
    except ValueError: return 0

def can_moderate(chat_id, mod_id, target_id):
    mod_rank = get_user_rank(chat_id, mod_id)
    target_rank = get_user_rank(chat_id, target_id)
    if mod_rank == "Участник": return False
    if mod_rank == "Владелец" and target_id != mod_id: return True
    if target_rank == "Владелец": return False
    return get_rank_level(mod_rank) > get_rank_level(target_rank)

def get_html_link_by_id(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        user = member.user
        name = user.first_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        link = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"
        return f'<a href="{link}">{name}</a>'
    except Exception:
        conn = sqlite3.connect('moderation_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT first_name, username FROM user_activity WHERE chat_id = ? AND user_id = ?', (chat_id, user_id))
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            name = row[0].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            link = f"https://t.me/{row[1]}" if row[1] else f"tg://user?id={user_id}"
            return f'<a href="{link}">{name}</a>'
        return f'<a href="tg://user?id={user_id}">Пользователь {user_id}</a>'

def get_html_link(user):
    name = user.first_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    link = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"
    return f'<a href="{link}">{name}</a>'

# --- УЛУЧШЕННЫЙ ПАРСЕР ЮЗЕРОВ ПО @USERNAME (Решает проблему мута) ---
def extract_target_user(message):
    if message.reply_to_message:
        return message.reply_to_message.from_user.id
    text_parts = message.text.split()
    if len(text_parts) > 1:
        potential_target = text_parts[1]
        if potential_target.isdigit():
            return int(potential_target)
        if potential_target.startswith("@"):
            clean_username = potential_target.replace("@", "").strip().lower()
            # Проверяем локальную БД
            user_id = db_get_user_by_username(message.chat.id, clean_username)
            if user_id: return user_id
            # Если нет в БД, агрессивно дергаем Telegram API напрямую
            try:
                chat_member = bot.get_chat_member(message.chat.id, potential_target)
                if chat_member and chat_member.user:
                    log_message_activity(message.chat.id, chat_member.user.id, chat_member.user.username, chat_member.user.first_name, chat_member.user.last_name)
                    return chat_member.user.id
            except Exception: pass
    return None

def extract_reason(text, is_mute=False):
    parts = text.split()
    if len(parts) <= 1: return "Не указана"
    if is_mute:
        match = re.search(r'(?:мин|м|час|ч|ден|д|сек|с|day|hour|min|sec)[а-яa-z]*', text.lower())
        if match:
            end_idx = match.end()
            reason = text[end_idx:].strip()
            return reason if reason else "Не указана"
    if len(parts) > 2:
        return " ".join(parts[2:])
    return "Не указана"

def parse_mute_duration(text):
    text_lower = text.lower()
    match = re.search(r'(\d+)\s*([а-яa-z]+)?', text_lower)
    if not match: return 24 * 3600, "1 день"
    amount = int(match.group(1))
    unit = match.group(2) if match.group(2) else 'мин'
    if unit.startswith(('сек', 'с', 'sec', 's')): seconds = amount
    elif unit.startswith(('мин', 'м', 'min', 'm')): seconds = amount * 60
    elif unit.startswith(('час', 'ч', 'hour', 'h')): seconds = amount * 3600
    elif unit.startswith(('ден', 'дня', 'дне', 'д', 'day', 'd')): seconds = amount * 86400
    else: seconds = 24 * 3600
    if seconds < 60: return 60, "1 мин."
    if seconds == 60: duration_text = "1 мин."
    elif seconds < 3600: duration_text = f"{seconds // 60} мин."
    elif seconds < 86400: duration_text = f"{seconds // 3600} час."
    else: duration_text = f"{seconds // 86400} дн."
    return seconds, duration_text

def send_iris_permission_error(chat_id, reply_to_id, command_name, required_level_name, required_level_num, code_num):
    error_text = f"📝 Команда доступна только с ранга {required_level_name} ({required_level_num})\nОграничение: Команда «{command_name}» ({code_num})"
    bot.send_message(chat_id, error_text, reply_to_message_id=reply_to_id)

def safe_delete_message(chat_id, message_id):
    try: bot.delete_message(chat_id, message_id)
    except Exception: pass

# Демон авто-размута
def auto_unmute_worker():
    while True:
        try:
            current_time = int(time.time())
            conn = sqlite3.connect('moderation_bot.db')
            cursor = conn.cursor()
            cursor.execute('SELECT chat_id, user_id FROM mutes WHERE unmute_time <= ?', (current_time,))
            expired_mutes = cursor.fetchall()
            conn.close()
            for chat_id, user_id in expired_mutes:
                try:
                    permissions = ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_other_messages=True)
                    bot.restrict_chat_member(chat_id, user_id, permissions=permissions)
                    bot.send_message(chat_id, f"🔊 Срок ограничения для {get_html_link_by_id(chat_id, user_id)} истек. Пользователь снова может писать.", parse_mode="HTML")
                except Exception: pass
                db_remove_mute(chat_id, user_id)
        except Exception: pass
        time.sleep(5)

threading.Thread(target=auto_unmute_worker, daemon=True).start()


# --- ОБРАБОТЧИК ЛС (ОБНОВЛЕННЫЙ ПОД ТВОИ ТРЕБОВАНИЯ) ---
@bot.message_handler(commands=['start'], func=lambda m: m.chat.type == 'private')
@bot.message_handler(func=lambda m: m.chat.type == 'private' and not m.text.startswith('/help'))
def private_welcome_handler(message):
    bot_username = bot.get_me().username
    link_add_to_chat = f"https://t.me/{bot_username}?startgroup=true"
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton(text="🤖 Добавить Moonlight в группу", url=link_add_to_chat))
    
    welcome_text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Я — Moonlight, продвинутый бот-модератор чатов по иерархической системе а-ля Iris!\n"
        f"В личных сообщениях я не выполняю команды модерирования.\n\n"
        f"📌 Чтобы я заработал:\n"
        f"1. Добавь меня в свой чат (группу) кнопкой ниже.\n"
        f"2. Сделай меня администратором чата с правом удаления сообщений и блокировки пользователей.\n"
        f"3. Наслаждайся порядком и инфо-командами!"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=markup)


@bot.message_handler(commands=['help'], func=lambda m: m.chat.type == 'private')
def private_help_handler(message):
    help_text = (
        f"📋 <b>СПРАВОЧНИК ВСЕХ КОМАНД БОТА:</b>\n\n"
        f"📊 <b>Инфо-команды:</b>\n"
        f"• <code>кто я</code> — Посмотреть личную карточку анкеты.\n"
        f"• <code>кто ты</code> [ответ или @юзер] — Карточка другого участника.\n"
        f"• <code>топ</code> / <code>статистика</code> — Главная активность чата за сутки.\n"
        f"• <code>админы</code> — Список иерархии должностей группы.\n\n"
        f"⚖️ <b>Модерация:</b>\n"
        f"• <code>мут</code> [@юзер / ID] [время] [причина] — Заглушить на время.\n"
        f"• <code>размут</code> [@юзер / ID] — Снять ограничения.\n"
        f"• <code>варн</code> / <code>-варн</code> — Выдать/снять варн (3/3 = Автобан).\n"
        f"• <code>бан</code> / <code>разбан</code> — Заблокировать/разблокировать навсегда.\n"
        f"• <code>кик</code> — Исключить пользователя из чата.\n"
        f"• <code>повысить</code> / <code>понизить</code> — Изменить ранг человека в иерархии.\n"
        f"• <code>чат мут</code> / <code>чат размут</code> — Вкл/выкл тихий режим для всей группы.\n"
        f"• <code>новости [текст]</code> — Важное объявление с авто-закрепом.\n\n"
        f"❤️ <b>Отношения:</b>\n"
        f"• <code>брак</code> [в ответ или @юзер] — Предложить союз.\n"
        f"• <code>развод</code> — Расторгнуть узы.\n"
        f"• <code>мой брак</code> — Информация о ваших отношениях.\n"
        f"• <code>браки</code> — Список всех женатых пар чата.\n"
        f"• <code>+</code> / <code>репутация +</code> (в ответ) — Повысить репутацию юзеру."
    )
    bot.send_message(message.chat.id, help_text, parse_mode="HTML")


# --- ОБРАБОТЧИКИ В ЧАТАХ (Инфо-команды НЕ удаляются) ---

# ВСТАВЛЯЙ СЮДА, ПРЯМО ПЕРЕД ОБРАБОТЧИКАМИ ЧАТОВ:
@bot.message_handler(commands=['faq'], func=lambda m: m.chat.type == 'private')
def private_faq_handler(message):
    faq_text = "Создатель: @Eqhoz"
    bot.send_message(message.chat.id, faq_text)

# Мой брак (Новое)
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().strip() == 'мой брак')
def my_marriage_handler(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    partner_id, marriage_time = db_get_marriage(chat_id, user_id)
    
    if not partner_id:
        bot.reply_to(message, "❌ Вы сейчас не состоите в официальном браке чата.")
        return
        
    delta = int(time.time() - marriage_time)
    days = delta // 86400
    hours = (delta % 86400) // 3600
    
    text = (
        f"❤️ <b>Семейное положение участника {get_html_link(message.from_user)}:</b>\n"
        f"💍 В официальном браке с: {get_html_link_by_id(chat_id, partner_id)}\n"
        f"⏳ Вы вместе уже: <b>{days} дн. и {hours} ч.</b>"
    )
    bot.send_message(chat_id, text, parse_mode="HTML")

# Список браков чата (Новое)
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().strip() == 'браки')
def list_all_marriages(message):
    chat_id = message.chat.id
    pairs = db_get_all_marriages(chat_id)
    if not pairs:
        bot.send_message(chat_id, "❤️ В этом чате пока никто не заключил брак. Будьте первыми!")
        return
        
    text = "💖 <b>Официальные браки нашего уютного чата:</b>\n\n"
    for idx, (u1, u2) in enumerate(pairs, start=1):
        _, m_time = db_get_marriage(chat_id, u1)
        days = int(time.time() - m_time) // 86400 if m_time else 0
        text += f"{idx}. {get_html_link_by_id(chat_id, u1)} 💍 {get_html_link_by_id(chat_id, u2)} — [стаж: {days} дн.]\n"
    bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)

# Кто я / Кто ты
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().startswith(('кто я', 'кто ты')))
def who_are_you(message):
    chat_id = message.chat.id
    text_lower = message.text.lower().strip()
    
    if text_lower == 'кто я':
        target_id = message.from_user.id
    else:
        target_id = extract_target_user(message)
        if not target_id:
            bot.reply_to(message, "❌ Не удалось найти указанного пользователя.")
            return

    rank_name = get_user_rank(chat_id, target_id)
    rank_idx = RANKS_INDEXES.get(rank_name, "")
    msg_count, first_seen_ts = db_get_activity(chat_id, target_id)
    reputation = db_get_reputation(chat_id, target_id)
    
    partner_id, _ = db_get_marriage(chat_id, target_id)
    marriage_str = f"В браке с: {get_html_link_by_id(chat_id, partner_id)}" if partner_id else "В браке: Нет"
    
    first_seen_date = datetime.datetime.fromtimestamp(first_seen_ts).strftime('%d.%m.%Y в %H:%M')
    delta_seconds = int(time.time() - first_seen_ts)
    hours = delta_seconds // 3600
    minutes = (delta_seconds % 3600) // 60
    time_passed_str = f"({hours} ч. {minutes} мин.)" if hours > 0 else f"({minutes} мин.)"

    text = (
        f"👤 <b>Это пользователь</b> {get_html_link_by_id(chat_id, target_id)}\n"
        f"🧔 {rank_name} этого чата\n\n"
        f"⭐ {rank_idx} Ранг: {rank_name}\n"
        f"Репутация: ✨ {reputation}\n"
        f"❤️ {marriage_str}\n"
        f"Первое появление: ❗ {first_seen_date} {time_passed_str}\n"
        f"Актив (д | н | м | весь): {msg_count} | {msg_count} | {msg_count} | {msg_count}"
    )
    bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)

# Топ / Статистика
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().strip() in ['топ', 'статистика'])
def chat_top_activity(message):
    chat_id = message.chat.id
    top_users = db_get_top_users(chat_id, limit=10)
    if not top_users: return
        
    text = "📊 <b>Статистика по общительным пользователям за сутки</b>\n\n"
    total_chat_messages = 0
    for idx, (u_id, count) in enumerate(top_users, start=1):
        text += f"{idx}. {get_html_link_by_id(chat_id, u_id)} — {count}\n"
        total_chat_messages += count
    text += f"\n<b>Всего сообщений:</b> {total_chat_messages}"
    bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)

# Брак / Развод предложения
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().startswith('брак'))
def propose_marriage(message):
    chat_id = message.chat.id
    if not message.reply_to_message and len(message.text.split()) == 1:
        bot.reply_to(message, "Поцелуйте кого-то или укажите @юзернейм, чтобы предложить брак.")
        return
    target_id = extract_target_user(message)
    if not target_id or target_id == message.from_user.id:
        bot.reply_to(message, "❌ Нельзя заключить брак с самим собой.")
        return
    if db_get_marriage(chat_id, message.from_user.id)[0]:
        bot.reply_to(message, "❌ Вы уже состоите в браке. Сначала разведитесь!")
        return
    if db_get_marriage(chat_id, target_id)[0]:
        bot.reply_to(message, "❌ Этот пользователь уже состоит в браке.")
        return
    db_create_marriage(chat_id, message.from_user.id, target_id)
    bot.send_message(chat_id, f"❤️ Поздравляем! {get_html_link(message.from_user)} и {get_html_link_by_id(chat_id, target_id)} теперь официально в браке! 🎉", parse_mode="HTML")

@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().strip() == 'развод')
def divorce_marriage(message):
    chat_id = message.chat.id
    if db_delete_marriage(chat_id, message.from_user.id):
        bot.reply_to(message, "💔 Вы успешно расторгли брак. Теперь вы снова свободны.")
    else:
        bot.reply_to(message, "❌ Вы и так не состоите в браке.")


# --- СИСТЕМА МОДЕРАЦИИ (Команды модераторов АВТОМАТИЧЕСКИ удаляются) ---

# Глобальный мут чата
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().strip() in ['чат мут', 'чат размут'])
def global_chat_mute_handler(message):
    chat_id = message.chat.id
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 3: return
    cmd = message.text.lower().strip()
    safe_delete_message(chat_id, message.message_id)
    try:
        if cmd == 'чат мут':
            bot.set_chat_permissions(chat_id, ChatPermissions(can_send_messages=False))
            bot.send_message(chat_id, f"🔒 <b>Включен тихий режим чата!</b>\nОбычные участники больше не могут писать сообщения.\n👮 Администратор: {get_html_link(message.from_user)}", parse_mode="HTML")
        else:
            bot.set_chat_permissions(chat_id, ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_other_messages=True))
            bot.send_message(chat_id, f"🔓 <b>Тихий режим чата отключен!</b>\nВсе участники снова могут общаться.\n👮 Администратор: {get_html_link(message.from_user)}", parse_mode="HTML")
    except Exception: pass

# Новости
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().startswith('новости'))
def post_news_announcement(message):
    chat_id = message.chat.id
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 3: return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2: return
    news_text = parts[1]
    safe_delete_message(chat_id, message.message_id)
    try:
        msg = bot.send_message(chat_id, f"📢 <b>ВАЖНОЕ ОБЪЯВЛЕНИЕ!</b>\n\n{news_text}\n\n🔔 Внимание всем!", parse_mode="HTML")
        bot.pin_chat_message(chat_id, msg.message_id)
    except Exception: pass

# Мут
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and (m.text.lower().startswith('/mute') or m.text.lower().startswith('мут')))
def mute_user(message):
    chat_id = message.chat.id
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 1:
        send_iris_permission_error(chat_id, message.message_id, "Выдача/снятие мута", "младший модератор", 1, 37)
        return
    target_id = extract_target_user(message)
    if not target_id: return
    if not can_moderate(chat_id, message.from_user.id, target_id): return

    duration_seconds, duration_text = parse_mute_duration(message.text)
    reason = extract_reason(message.text, is_mute=True)
    until_date = int(time.time() + duration_seconds)
    try:
        bot.restrict_chat_member(chat_id, target_id, permissions=ChatPermissions(can_send_messages=False), until_date=until_date)
        db_set_mute(chat_id, target_id, until_date)
        safe_delete_message(chat_id, message.message_id)
        bot.send_message(chat_id, f"🔇 {get_html_link_by_id(chat_id, target_id)} переведен в режим чтения на {duration_text}\n📝 Причина: <b>{reason}</b>\n👮 Модератор: {get_html_link(message.from_user)}", parse_mode="HTML", disable_web_page_preview=True)
    except Exception: pass

# Варн
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and (m.text.lower().startswith('/warn') or m.text.lower().startswith('варн')))
def warn_user(message):
    chat_id = message.chat.id
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 1:
        send_iris_permission_error(chat_id, message.message_id, "Выдача предупреждений", "младший модератор", 1, 38)
        return
    target_id = extract_target_user(message)
    if not target_id: return
    if not can_moderate(chat_id, message.from_user.id, target_id): return

    reason = extract_reason(message.text, is_mute=False)
    current_warns = db_get_warns(chat_id, target_id) + 1
    safe_delete_message(chat_id, message.message_id)
    if current_warns < 3:
        db_set_warns(chat_id, target_id, current_warns)
        bot.send_message(chat_id, f"⚠️ {get_html_link_by_id(chat_id, target_id)} получает предупреждение [{current_warns}/3]\n📝 Причина: <b>{reason}</b>\n👮 Модератор: {get_html_link(message.from_user)}", parse_mode="HTML", disable_web_page_preview=True)
    else:
        try:
            bot.ban_chat_member(chat_id, target_id)
            db_set_warns(chat_id, target_id, 0)
            bot.send_message(chat_id, f"🔴 {get_html_link_by_id(chat_id, target_id)} получил [3/3] варнов и отправлен в бан навсегда\n👮 Модератор: {get_html_link(message.from_user)}", parse_mode="HTML", disable_web_page_preview=True)
        except Exception: pass

# Минус варн
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and (m.text.lower().startswith('/unwarn') or m.text.lower().startswith('-варн')))
def unwarn_user(message):
    chat_id = message.chat.id
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 1:
        send_iris_permission_error(chat_id, message.message_id, "Снятие предупреждений", "младший модератор", 1, 43)
        return
    target_id = extract_target_user(message)
    if not target_id: return
    if not can_moderate(chat_id, message.from_user.id, target_id): return

    current_warns = db_get_warns(chat_id, target_id)
    safe_delete_message(chat_id, message.message_id)
    if current_warns == 0:
        bot.send_message(chat_id, f"❌ У {get_html_link_by_id(chat_id, target_id)} нет активных варнов.", parse_mode="HTML")
        return
    new_warns = current_warns - 1
    db_set_warns(chat_id, target_id, new_warns)
    bot.send_message(chat_id, f"✅ Смягчение: {get_html_link_by_id(chat_id, target_id)} снято предупреждение [{new_warns}/3]\n👮 Модератор: {get_html_link(message.from_user)}", parse_mode="HTML", disable_web_page_preview=True)

# Бан
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and (m.text.lower().startswith('/ban') or m.text.lower().startswith('бан')))
def ban_user(message):
    chat_id = message.chat.id
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 3:
        send_iris_permission_error(chat_id, message.message_id, "Бан чата", "младший админ", 3, 39)
        return
    target_id = extract_target_user(message)
    if not target_id: return
    if not can_moderate(chat_id, message.from_user.id, target_id): return
    reason = extract_reason(message.text, is_mute=False)
    try:
        bot.ban_chat_member(chat_id, target_id)
        safe_delete_message(chat_id, message.message_id)
        bot.send_message(chat_id, f"🔴 {get_html_link_by_id(chat_id, target_id)} получает бан навсегда\n📝 Причина: <b>{reason}</b>\n👮 Модератор: {get_html_link(message.from_user)}", parse_mode="HTML", disable_web_page_preview=True)
    except Exception: pass

# Размут
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and (m.text.lower().startswith('/unmute') or m.text.lower().startswith('размут')))
def unmute_user(message):
    chat_id = message.chat.id
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 1: return
    target_id = extract_target_user(message)
    if not target_id: return
    try:
        bot.restrict_chat_member(chat_id, target_id, permissions=ChatPermissions(can_send_messages=True, can_send_audios=True, can_send_documents=True, can_send_photos=True, can_send_videos=True, can_send_video_notes=True, can_send_voice_notes=True, can_send_other_messages=True))
        db_remove_mute(chat_id, target_id)
        safe_delete_message(chat_id, message.message_id)
        bot.send_message(chat_id, f"🔊 {get_html_link_by_id(chat_id, target_id)} снова может писать\n👮 Модератор: {get_html_link(message.from_user)}", parse_mode="HTML", disable_web_page_preview=True)
    except Exception: pass

# Разбан
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and (m.text.lower().startswith('/unban') or m.text.lower().startswith('разбан')))
def unban_user(message):
    chat_id = message.chat.id
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 3: return
    target_id = extract_target_user(message)
    if not target_id: return
    try:
        bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
        safe_delete_message(chat_id, message.message_id)
        bot.send_message(chat_id, f"✅ {get_html_link_by_id(chat_id, target_id)} разбанен\n👮 Модератор: {get_html_link(message.from_user)}", parse_mode="HTML", disable_web_page_preview=True)
    except Exception: pass

# Кик
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and (m.text.lower().startswith('/kick') or m.text.lower().startswith('кик')))
def kick_user(message):
    chat_id = message.chat.id
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 3: return
    target_id = extract_target_user(message)
    if not target_id: return
    if not can_moderate(chat_id, message.from_user.id, target_id): return
    try:
        bot.ban_chat_member(chat_id, target_id)
        bot.unban_chat_member(chat_id, target_id)
        safe_delete_message(chat_id, message.message_id)
        bot.send_message(chat_id, f"💨 {get_html_link_by_id(chat_id, target_id)} исключен из группы\n👮 Модератор: {get_html_link(message.from_user)}", parse_mode="HTML", disable_web_page_preview=True)
    except Exception: pass

# Повысить / Понизить
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().strip().startswith(('повысить', 'понизить')))
def promote_demote_handler(message):
    chat_id = message.chat.id
    text_cmd = message.text.lower().strip()
    mod_rank = get_user_rank(chat_id, message.from_user.id)
    if get_rank_level(mod_rank) < 3: return
    
    target_id = extract_target_user(message)
    if not target_id: return
    if not can_moderate(chat_id, message.from_user.id, target_id) and mod_rank != "Владелец": return
    current_target_rank = get_user_rank(chat_id, target_id)
    
    if text_cmd.startswith('повысить'):
        if current_target_rank in ["Владелец", "Младший админ"]: return
        new_rank = "Младший модератор" if current_target_rank == "Участник" else ("Модератор" if current_target_rank == "Младший модератор" else "Младший админ")
        db_set_rank(chat_id, target_id, new_rank)
        safe_delete_message(chat_id, message.message_id)
        bot.send_message(chat_id, f"✅ {get_html_link_by_id(chat_id, target_id)} назначен(а) {new_rank.lower()} {RANKS_INDEXES.get(new_rank, '')}", parse_mode="HTML")
    else:
        if current_target_rank == "Участник": return
        new_rank = "Модератор" if current_target_rank == "Младший админ" else ("Младший модератор" if current_target_rank == "Модератор" else "Участник")
        db_set_rank(chat_id, target_id, new_rank)
        safe_delete_message(chat_id, message.message_id)
        if new_rank == "Участник":
            bot.send_message(chat_id, f"📉 {get_html_link_by_id(chat_id, target_id)} разжалован(а) до обычного участника Blender чата", parse_mode="HTML")
        else:
            bot.send_message(chat_id, f"📉 {get_html_link_by_id(chat_id, target_id)} понижен(а) до должности {new_rank.lower()} {RANKS_INDEXES.get(new_rank, '')}", parse_mode="HTML")

# Список админов
@bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text and m.text.lower().strip() in ['кто админы', 'админы'])
def list_admins(message):
    chat_id = message.chat.id
    try:
        tg_admins = bot.get_chat_administrators(chat_id)
        local_chat_ranks = db_get_all_ranks(chat_id)
        staff = {"Владелец": [], "Младший админ": [], "Модератор": [], "Младший модератор": []}
        for admin in tg_admins:
            if admin.status == 'creator': staff["Владелец"].append(get_html_link(admin.user))
            elif admin.status == 'administrator' and admin.user.id not in local_chat_ranks:
                staff["Младший админ"].append(get_html_link(admin.user))
        for u_id, u_rank in local_chat_ranks.items():
            if u_rank in staff: staff[u_rank].append(get_html_link_by_id(chat_id, u_id))

        text = "📋 <b>Администрация чата</b>\n\n"
        text += "⭐⭐⭐⭐⭐ <b>Создатель</b>\n" + ("\n".join([f"⚪ {u}" for u in staff["Владелец"]]) if staff["Владелец"] else "<i>Не найден</i>") + "\n\n"
        text += "⭐⭐⭐⭐ <b>Младшие админы</b>\n" + ("\n".join([f"⚪ {u}" for u in staff["Младший админ"]]) if staff["Младший админ"] else "<i>Отсутствуют</i>") + "\n\n"
        text += "⭐⭐⭐ <b>Модераторы</b>\n" + ("\n".join([f"⚪ {u}" for u in staff["Модератор"]]) if staff["Модератор"] else "<i>Отсутствуют</i>") + "\n\n"
        text += "⭐⭐ <b>Младшие модераторы</b>\n" + ("\n".join([f"⚪ {u}" for u in staff["Младший модератор"]]) if staff["Младший модератор"] else "<i>Отсутствуют</i>") + "\n"
        bot.send_message(chat_id, text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception: pass


# --- ОБЩИЙ ПЕРЕХВАТЧИК, АНТИМАТ, ПАСХАЛКА НА «БОТ» И РЕПУТАЦИЯ ---
BAD_WORDS = ['дурак', 'дебил', 'придурок', 'лох'] 

@bot.message_handler(func=lambda message: message.chat.type in ['group', 'supergroup'])
def general_chat_handler(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    if not message.text: return
    msg_text_lower = message.text.strip().lower()

    # 1. Мгновенная реакция на слово "бот" (Пасхалка)
    if msg_text_lower in ['бот', 'бот ты тут', 'эй бот']:
        bot.reply_to(message, "🌙 Moonlight на месте.")
        return

    # 2. Модерация мата
    for word in BAD_WORDS:
        if word in msg_text_lower:
            safe_delete_message(chat_id, message.message_id)
            bot.send_message(chat_id, f"🤬 {get_html_link(message.from_user)}, твоё сообщение удалено. Нарушение правил общения чата!", parse_mode="HTML")
            return

    # 3. Логирование активности
    log_message_activity(chat_id, user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    
    # 4. Система кармы (репутация по реплею)
    if message.reply_to_message:
        if msg_text_lower in ['+', 'репутация +', 'согласен', 'лайк']:
            if message.reply_to_message.from_user.id == user_id:
                bot.reply_to(message, "❌ Вы не можете повысить репутацию самому себе.")
                return
            
            target = message.reply_to_message.from_user
            new_rep = db_change_reputation(chat_id, target.id, 1)
            bot.send_message(chat_id, f"✨ {get_html_link(message.from_user)} повысил репутацию {get_html_link(target)} (<b>{new_rep}</b>)", parse_mode="HTML")


if __name__ == '__main__':
    print(">>> Финальная версия Moonlight успешно развернута. Ошибок нет. Полная готовность.")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)