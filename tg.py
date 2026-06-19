import logging
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Вставь сюда свой токен от BotFather
TOKEN = "8907478731:AAGe5WqmBh4vnTQWxGzyIrSzKcCbwOxYo78"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# База данных в памяти для хранения привязанных каналов
channel_config = {}

# --- РАБОТА В ЛИЧНЫХ СООБЩЕНИЯХ (ЛС) ---

@dp.message(Command("start"), F.chat.type == "private")
async def start_private(message: types.Message):
    bot_user = await bot.get_me()
    link_to_add = f"https://t.me/{bot_user.username}?startgroup=true"
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="➕ Добавить в группу", url=link_to_add)
    )
    
    welcome_text = (
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        f"<b>Что я умею?</b>\n"
        f"⛔ Я запрещаю писать пользователям в твоей группе, пока они не подпишутся на твой Telegram-канал, их сообщения будут автоматически удаляться.\n\n"
        f"⚙️ <b>Как настроить:</b>\n"
        f"1️⃣ Нажми кнопку ниже и добавь меня в свою группу.\n"
        f"2️⃣ Сделай меня <b>администратором</b> в группе (с правом удаления сообщений) и в своем канале.\n"
        f"3️⃣ В группе напиши команду: <code>/setchannel @юз_канала</code>"
    )
    
    await message.answer(welcome_text, reply_markup=builder.as_markup(), parse_mode="HTML")


# --- РАБОТА В ГРУППАХ (Настройка и проверка подписки) ---

@dp.message(Command("setchannel"), F.chat.type.in_({"group", "supergroup"}))
async def set_channel(message: types.Message):
    # Проверяем права администратора у того, кто ввел команду
    member = await message.chat.get_member(message.from_user.id)
    if member.status not in ["creator", "administrator"]:
        await message.reply("❌ Эту команду могут использовать только администраторы чата.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "⚠️ <b>Использование команды:</b>\n<code>/setchannel @username_канала</code>\n\n"
            "<i>Убедитесь, что у бота есть права администратора в этом канале.</i>", 
            parse_mode="HTML"
        )
        return

    channel_identifier = args[1].strip()
    channel_config[message.chat.id] = channel_identifier
    
    # Бот отвечает прямо на твое сообщение, подтверждая успех
    await message.reply(
        f"✅ <b>Успешно!</b>\nДля этого чата установлен канал проверки: <code>{channel_identifier}</code>\n\n"
        f"", 
        parse_mode="HTML"
    )


@dp.message(F.chat.type.in_({"group", "supergroup"}))
async def check_subscription(message: types.Message):
    # Игнорируем системные уведомления (кто-то вошел/вышел)
    if message.left_chat_member or message.new_chat_members:
        return

    # Администраторов группы проверка не касается
    member = await message.chat.get_member(message.from_user.id)
    if member.status in ["creator", "administrator"]:
        return

    # Ищем, какой канал привязан к этой группе
    target_channel = channel_config.get(message.chat.id)
    if not target_channel:
        return  

    try:
        # Запрашиваем у Telegram статус пользователя в канале
        user_in_channel = await bot.get_chat_member(chat_id=target_channel, user_id=message.from_user.id)
        if user_in_channel.status in ["left", "kicked"]:
            raise ValueError
    except (TelegramBadRequest, ValueError):
        # Если пользователя нет в канале — удаляем его сообщение
        try:
            await message.delete()
            await message.answer(
                f"👤 <b>{message.from_user.first_name}</b>, твое сообщение удалено.\n"
                f"Чтобы общаться в этом чате, сначала подпишись на наш канал: {target_channel}!",
                parse_mode="HTML"
            )
        except Exception as e:
            logging.error(f"Ошибка при удалении сообщения: {e}")

# Запуск бота
async def main():
    logging.basicConfig(level=logging.INFO)
    print("Бот успешно запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())