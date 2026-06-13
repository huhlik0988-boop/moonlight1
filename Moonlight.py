import telebot
from telebot.types import ChatPermissions
import time
import re

# Инициализация бота
TOKEN = '8817228602:AAHTUcZFNe3znBs60ZamEGr_CxgmThgsFKM'
bot = telebot.TeleBot(TOKEN)

# Словарь для хранения варнов: {chat_id: {user_id: количество_варнов}}
warns_storage = {}

# Функция проверки прав администратора
def check_admin(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except Exception:
        return False

# Функция для создания скрытых гиперссылок (стиль Iris)
def get_html_link(user):
    name = user.first_name
    name = name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    link = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"
    return f'<a href="{link}">{name}</a>'

# Функция определения времени мута
def parse_duration(text):
    parts = text.lower().split()
    remaining_text = " ".join(parts[1:])
    
    match = re.search(r'(\d+)\s*([а-яa-z]+)?', remaining_text)
    if not match:
        return 24 * 3600, "1 день"
        
    amount = int(match.group(1))
    unit = match.group(2) if match.group(2) else 'мин'
    
    if unit.startswith(('сек', 'с', 'sec', 's')):
        return amount, f"{amount} сек."
    elif unit.startswith(('мин', 'м', 'min', 'm')):
        return amount * 60, f"{amount} мин."
    elif unit.startswith(('час', 'ч', 'hour', 'h')):
        return amount * 3600, f"{amount} час."
    elif unit.startswith(('ден', 'дня', 'дне', 'д', 'day', 'd')):
        return amount * 86400, f"{amount} дн."
        
    return 24 * 3600, "1 день"

# Базовая команда /start и /help
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    help_text = (
        "🛡 **Бот-модератор для чата**\n\n"
        "Доступные команды:\n"
        "• `/mute` или `мут` (можно указать время, например: `мут 5 мин`)\n"
        "• `/unmute` или `размут`\n"
        "• `/warn` или `варн` (3 варна = бан)\n"
        "• `/ban` или `бан`\n"
        "• `/unban` или `разбан`\n"
        "• `/kick` или `кик`\n\n"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")

# Команда ВАРН (/warn или слово "варн")
@bot.message_handler(func=lambda m: m.text and (m.text.lower().startswith('/warn') or m.text.lower().strip() == 'варн'))
def warn_user(message):
    if not check_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав для использования этой команды.")
        return

    if not message.reply_to_message:
        bot.reply_to(message, "⚠ Ошибка! Ответьте этой командой на сообщение.")
        return

    chat_id = message.chat.id
    target_user = message.reply_to_message.from_user
    moderator = message.from_user

    # Инициализируем структуру данных для чата и юзера, если их еще нет
    if chat_id not in warns_storage:
        warns_storage[chat_id] = {}
    if target_user.id not in warns_storage[chat_id]:
        warns_storage[chat_id][target_user.id] = 0

    # Добавляем 1 варн
    warns_storage[chat_id][target_user.id] += 1
    current_warns = warns_storage[chat_id][target_user.id]

    target_html = get_html_link(target_user)
    mod_html = get_html_link(moderator)

    if current_warns < 3:
        # Обычный варн (1-й или 2-й)
        warn_text = (
            f"⚠️ {target_html} получает предупреждение [{current_warns}/3]\n"
            f"👮 Модератор: {mod_html}"
        )
        bot.send_message(chat_id, warn_text, parse_mode="HTML", disable_web_page_preview=True)
    else:
        # 3-й варн -> Автоматический БАН
        try:
            bot.ban_chat_member(chat_id, target_user.id)
            warns_storage[chat_id][target_user.id] = 0  # Сбрасываем счетчик после бана
            
            ban_text = (
                f"🔴 {target_html} получил [3/3] предупреждений и отправляется в бан навсегда\n"
                f"👮 Модератор: {mod_html}"
            )
            bot.send_message(chat_id, ban_text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            bot.reply_to(message, f"❌ Не удалось забанить за превышение лимита варнов. Проверьте права бота.")

# Команда МУТ (/mute или слово "мут" с поддержкой времени)
@bot.message_handler(func=lambda m: m.text and (m.text.lower().startswith('/mute') or m.text.lower().startswith('мут')))
def mute_user(message):
    if not check_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ У вас нет прав для использования этой команды.")
        return

    if not message.reply_to_message:
        bot.reply_to(message, "⚠ Ошибка! Ответьте этой командой на сообщение.")
        return

    target_user = message.reply_to_message.from_user
    moderator = message.from_user
    
    duration_seconds, duration_text = parse_duration(message.text)
    until_date = int(time.time() + duration_seconds)
    
    try:
        permissions = ChatPermissions(can_send_messages=False)
        bot.restrict_chat_member(message.chat.id, target_user.id, permissions=permissions, until_date=until_date)
        
        target_html = get_html_link(target_user)
        mod_html = get_html_link(moderator)
        
        mute_text = (
            f"🔇 {target_html} переведен в режим чтения на {duration_text}\n"
            f"👮 Модератор: {mod_html}"
        )
        bot.send_message(message.chat.id, mute_text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        bot.reply_to(message, f"❌ Не удалось применить мут. Проверьте права бота.")

# Команда РАЗМУТ (/unmute или слово "размут")
@bot.message_handler(func=lambda m: m.text and (m.text.lower().startswith('/unmute') or m.text.lower().startswith('размут')))
def unmute_user(message):
    if not check_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ Доступно только администраторам.")
        return

    if not message.reply_to_message:
        bot.reply_to(message, "⚠ Ответьте на сообщение пользователя для снятия мута.")
        return

    target_user = message.reply_to_message.from_user
    moderator = message.from_user
    
    try:
        permissions = ChatPermissions(
            can_send_messages=True, can_send_audios=True, can_send_documents=True,
            can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
            can_send_voice_notes=True, can_send_other_messages=True
        )
        bot.restrict_chat_member(message.chat.id, target_user.id, permissions=permissions)
        
        target_html = get_html_link(target_user)
        mod_html = get_html_link(moderator)
        
        unmute_text = (
            f"🔊 {target_html} снова может писать\n"
            f"👮 Модератор: {mod_html}"
        )
        bot.send_message(message.chat.id, unmute_text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при снятии мута.")

# Команда БАН (/ban или слово "бан")
@bot.message_handler(func=lambda m: m.text and (m.text.lower().startswith('/ban') or m.text.lower().startswith('бан')))
def ban_user(message):
    if not check_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ Доступно только администраторам.")
        return

    if not message.reply_to_message:
        bot.reply_to(message, "⚠ Ответьте на сообщение для блокировки.")
        return

    target_user = message.reply_to_message.from_user
    moderator = message.from_user
    
    try:
        bot.ban_chat_member(message.chat.id, target_user.id)
        
        target_html = get_html_link(target_user)
        mod_html = get_html_link(moderator)
        
        ban_text = (
            f"🔴 {target_html} получает бан навсегда\n"
            f"👮 Модератор: {mod_html}"
        )
        bot.send_message(message.chat.id, ban_text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        bot.reply_to(message, f"❌ Не удалось забанить. Проверьте права бота.")

# Команда РАЗБАН (/unban или слово "разбан")
@bot.message_handler(func=lambda m: m.text and (m.text.lower().startswith('/unban') or m.text.lower().startswith('разбан')))
def unban_user(message):
    if not check_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ Доступно только администраторам.")
        return

    if not message.reply_to_message:
        bot.reply_to(message, "⚠ Ответьте на сообщение для разблокировки.")
        return

    target_user = message.reply_to_message.from_user
    moderator = message.from_user
    
    try:
        bot.unban_chat_member(message.chat.id, target_user.id, only_if_banned=True)
        
        target_html = get_html_link(target_user)
        mod_html = get_html_link(moderator)
        
        unban_text = (
            f"✅ {target_html} разбанен\n"
            f"👮 Модератор: {mod_html}"
        )
        bot.send_message(message.chat.id, unban_text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка разбана.")

# Команда КИК (/kick или слово "кик")
@bot.message_handler(func=lambda m: m.text and (m.text.lower().startswith('/kick') or m.text.lower().startswith('кик')))
def kick_user(message):
    if not check_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "❌ Доступно только администраторам.")
        return

    if not message.reply_to_message:
        bot.reply_to(message, "⚠ Ответьте на сообщение, чтобы кикнуть.")
        return

    target_user = message.reply_to_message.from_user
    moderator = message.from_user
    
    try:
        bot.ban_chat_member(message.chat.id, target_user.id)
        bot.unban_chat_member(message.chat.id, target_user.id)
        
        target_html = get_html_link(target_user)
        mod_html = get_html_link(moderator)
        
        kick_text = (
            f"💨 {target_html} исключен из группы\n"
            f"👮 Модератор: {mod_html}"
        )
        bot.send_message(message.chat.id, kick_text, parse_mode="HTML", disable_web_page_preview=True)
    except Exception as e:
        bot.reply_to(message, f"❌ Ошибка при исключении.")

# Безопасный запуск бота
if __name__ == '__main__':
    print(">>> Бот-модератор успешно запущен в работу!")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)