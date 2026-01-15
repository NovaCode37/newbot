import logging
import time
import os
import re
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Set, Tuple
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, ConversationHandler, CallbackQueryHandler

load_dotenv(dotenv_path='.env')
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    print("ОШИБКА: BOT_TOKEN не найден в .env файле!")
    exit(1)

if not re.match(r'^\d+:[A-Za-z0-9_-]+$', BOT_TOKEN):
    print("ОШИБКА: Неверный формат токена!")
    exit(1)

MODERATION_GROUP_ID = int(os.getenv('MODERATION_GROUP_ID', '-1003481535857'))
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '-1003697286219'))
ADMIN_USER_IDS = set(map(int, os.getenv('ADMIN_USER_IDS', '8555103088,1976311091,1449145485').split(',')))
print(f"Админы: {ADMIN_USER_IDS}")
MAX_NEWS_LENGTH = int(os.getenv('MAX_NEWS_LENGTH', '4000'))
MAX_TITLE_LENGTH = int(os.getenv('MAX_TITLE_LENGTH', '200'))
BLACKLISTED_WORDS = os.getenv('BLACKLISTED_WORDS', '').split(',') if os.getenv('BLACKLISTED_WORDS') else []
MAX_URLS = int(os.getenv('MAX_URLS', '3'))

user_cooldowns = {}
blocked_users = set()
flood_detection = {}
scheduled_posts = {}
edit_mode = {}
delay_mode = {}

BLACKLISTED_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in BLACKLISTED_WORDS if pattern]

TITLE, TEXT, PHOTO = range(3)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
news_storage = {}


class SecurityManager:
    @staticmethod
    def check_rate_limit(user_id: int) -> bool:
        now = time.time()
        if user_id in user_cooldowns:
            if now - user_cooldowns[user_id] < 60:
                return False
        user_cooldowns[user_id] = now
        return True

    @staticmethod
    def check_flood(user_id: int) -> bool:
        now = time.time()
        if user_id not in flood_detection:
            flood_detection[user_id] = []
        flood_detection[user_id] = [ts for ts in flood_detection[user_id] if now - ts < 10]
        flood_detection[user_id].append(now)
        if len(flood_detection[user_id]) > 5:
            blocked_users.add(user_id)
            return True
        return False

    @staticmethod
    def check_content(text: str) -> Tuple[bool, str]:
        for pattern in BLACKLISTED_PATTERNS:
            if pattern.search(text):
                return False, f"Запрещенное слово: {pattern.pattern}"
        if re.search(r'(.)\1{10,}', text):
            return False, "Подозрительный паттерн"
        if len(text) > MAX_NEWS_LENGTH:
            return False, f"Текст слишком длинный (макс {MAX_NEWS_LENGTH})"
        if len(re.findall(r'https?://\S+|www\.\S+', text)) > MAX_URLS:
            return False, f"Много ссылок (макс {MAX_URLS})"
        return True, ""

    @staticmethod
    def is_user_blocked(user_id: int) -> bool:
        return user_id in blocked_users


async def start(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if SecurityManager.is_user_blocked(user_id):
        await update.message.reply_text("Вы заблокированы.")
        return
    if not SecurityManager.check_rate_limit(user_id):
        await update.message.reply_text("Подождите немного.")
        return
    if SecurityManager.check_flood(user_id):
        await update.message.reply_text("Вы заблокированы за флуд.")
        return
    keyboard = [[InlineKeyboardButton("Предложить новость", callback_data='start_post')]]
    await update.message.reply_text('Бот для новостей. Нажмите кнопку.', reply_markup=InlineKeyboardMarkup(keyboard))


async def start_post(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Напишите заголовок для вашей новости:")
    return TITLE


async def get_title(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    user_text = update.message.text.strip()
    if SecurityManager.is_user_blocked(user_id):
        await update.message.reply_text("Вы заблокированы.")
        return ConversationHandler.END
    if len(user_text) > MAX_TITLE_LENGTH:
        await update.message.reply_text(f"Заголовок слишком длинный (макс {MAX_TITLE_LENGTH}).\nПопробуйте снова:")
        return TITLE
    is_valid, message = SecurityManager.check_content(user_text)
    if not is_valid:
        await update.message.reply_text(f"{message}\nПопробуйте снова:")
        return TITLE
    context.user_data['news_title'] = user_text
    await update.message.reply_text("Теперь отправьте текст новости:")
    return TEXT


async def get_text(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    news_text = update.message.text.strip()
    if SecurityManager.is_user_blocked(user_id):
        await update.message.reply_text("Вы заблокированы.")
        return ConversationHandler.END
    is_valid, message = SecurityManager.check_content(news_text)
    if not is_valid:
        await update.message.reply_text(f"{message}\nПопробуйте снова:")
        return TEXT
    context.user_data['news_text'] = news_text
    keyboard = [
        [InlineKeyboardButton("Пропустить фото", callback_data='skip_photo')]
    ]
    await update.message.reply_text("Отправьте фото (или нажмите кнопку чтобы пропустить):", reply_markup=InlineKeyboardMarkup(keyboard))
    return PHOTO


async def get_photo(update: Update, context: CallbackContext) -> int:
    user = update.effective_user
    if update.message.photo:
        photo = update.message.photo[-1]
        context.user_data['news_photo'] = photo.file_id
    await send_to_moderation(update, context, user)
    return ConversationHandler.END


async def skip_photo(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    context.user_data['news_photo'] = None
    await query.edit_message_text("Фото пропущено.")
    await send_to_moderation_from_callback(context, user)
    return ConversationHandler.END


async def send_to_moderation(update: Update, context: CallbackContext, user) -> None:
    news_title = context.user_data.get('news_title', 'НЕТ ЗАГОЛОВКА')
    news_text = context.user_data.get('news_text', '')
    news_photo = context.user_data.get('news_photo')
    unique_key = f"{user.id}_{int(time.time())}"
    news_storage[unique_key] = {
        'title': news_title,
        'text': news_text,
        'photo': news_photo,
        'user_id': user.id,
        'username': user.username or user.first_name
    }
    keyboard = [
        [
            InlineKeyboardButton("Опубликовать", callback_data=f'publish_{unique_key}'),
            InlineKeyboardButton("Отклонить", callback_data=f'reject_{unique_key}')
        ],
        [
            InlineKeyboardButton("Редактировать", callback_data=f'edit_{unique_key}'),
            InlineKeyboardButton("СПАМ", callback_data=f'spam_{unique_key}')
        ],
        [
            InlineKeyboardButton("1ч", callback_data=f'delay1_{unique_key}'),
            InlineKeyboardButton("3ч", callback_data=f'delay3_{unique_key}'),
            InlineKeyboardButton("Свое время", callback_data=f'delaycustom_{unique_key}')
        ]
    ]
    mod_text = f"*Новая новость*\n\n*От:* {user.username or user.first_name} (ID: {user.id})\n*Заголовок:* {news_title}\n*Текст:* {news_text}\n*Фото:* {'Да' if news_photo else 'Нет'}\n*ID:* `{unique_key}`"
    if news_photo:
        await context.bot.send_photo(chat_id=MODERATION_GROUP_ID, photo=news_photo, caption=mod_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(chat_id=MODERATION_GROUP_ID, text=mod_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    await update.message.reply_text("Новость отправлена на модерацию.")
    context.user_data.clear()


async def send_to_moderation_from_callback(context: CallbackContext, user) -> None:
    news_title = context.user_data.get('news_title', 'НЕТ ЗАГОЛОВКА')
    news_text = context.user_data.get('news_text', '')
    news_photo = context.user_data.get('news_photo')
    unique_key = f"{user.id}_{int(time.time())}"
    news_storage[unique_key] = {
        'title': news_title,
        'text': news_text,
        'photo': news_photo,
        'user_id': user.id,
        'username': user.username or user.first_name
    }
    keyboard = [
        [
            InlineKeyboardButton("Опубликовать", callback_data=f'publish_{unique_key}'),
            InlineKeyboardButton("Отклонить", callback_data=f'reject_{unique_key}')
        ],
        [
            InlineKeyboardButton("Редактировать", callback_data=f'edit_{unique_key}'),
            InlineKeyboardButton("СПАМ", callback_data=f'spam_{unique_key}')
        ],
        [
            InlineKeyboardButton("1ч", callback_data=f'delay1_{unique_key}'),
            InlineKeyboardButton("3ч", callback_data=f'delay3_{unique_key}'),
            InlineKeyboardButton("Свое время", callback_data=f'delaycustom_{unique_key}')
        ]
    ]
    mod_text = f"*Новая новость*\n\n*От:* {user.username or user.first_name} (ID: {user.id})\n*Заголовок:* {news_title}\n*Текст:* {news_text}\n*Фото:* {'Да' if news_photo else 'Нет'}\n*ID:* `{unique_key}`"
    if news_photo:
        await context.bot.send_photo(chat_id=MODERATION_GROUP_ID, photo=news_photo, caption=mod_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await context.bot.send_message(chat_id=MODERATION_GROUP_ID, text=mod_text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    await context.bot.send_message(chat_id=user.id, text="Новость отправлена на модерацию.")
    context.user_data.clear()


async def button_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_USER_IDS:
        await query.answer("Требуются права администратора.", show_alert=True)
        return
    data = query.data
    if data.startswith('edit_'):
        unique_key = data.split('_', 1)[1]
        if unique_key in news_storage:
            edit_mode[query.from_user.id] = unique_key
            await query.message.reply_text(f"Отправьте новый текст для новости {unique_key}:")
        return
    action, unique_key = data.split('_', 1)
    if unique_key not in news_storage:
        try:
            await query.edit_message_text("Новость не найдена")
        except:
            await query.edit_message_caption(caption="Новость не найдена")
        return
    news = news_storage[unique_key]
    has_photo = news.get('photo') is not None
    if action == 'publish':
        await publish_news(context, news, unique_key)
        result_text = f"ОПУБЛИКОВАНО\n\nЗаголовок: {news['title']}\nАвтор: {news['username']}"
        if has_photo:
            await query.edit_message_caption(caption=result_text)
        else:
            await query.edit_message_text(result_text)
        del news_storage[unique_key]
    elif action == 'reject':
        try:
            await context.bot.send_message(chat_id=news['user_id'], text=f"Ваша новость отклонена.\n\n{news['title']}")
        except:
            pass
        result_text = f"ОТКЛОНЕНО\n\nЗаголовок: {news['title']}\nАвтор: {news['username']}"
        if has_photo:
            await query.edit_message_caption(caption=result_text)
        else:
            await query.edit_message_text(result_text)
        del news_storage[unique_key]
    elif action == 'spam':
        blocked_users.add(news['user_id'])
        logger.warning(f"Пользователь {news['user_id']} заблокирован за спам")
        try:
            await context.bot.send_message(chat_id=news['user_id'], text="Вы заблокированы за спам.")
        except:
            pass
        result_text = f"СПАМ - ЗАБЛОКИРОВАН\n\nЗаголовок: {news['title']}\nАвтор: {news['username']} (ID: {news['user_id']})"
        if has_photo:
            await query.edit_message_caption(caption=result_text)
        else:
            await query.edit_message_text(result_text)
        del news_storage[unique_key]
    elif action == 'delay1':
        publish_time = datetime.now() + timedelta(hours=1)
        scheduled_posts[unique_key] = {'news': news, 'time': publish_time}
        result_text = f"ОТЛОЖЕНО на 1 час\n\nЗаголовок: {news['title']}\nПубликация: {publish_time.strftime('%H:%M')}"
        if has_photo:
            await query.edit_message_caption(caption=result_text)
        else:
            await query.edit_message_text(result_text)
        del news_storage[unique_key]
        asyncio.create_task(delayed_publish(context, unique_key, 3600))
    elif action == 'delay3':
        publish_time = datetime.now() + timedelta(hours=3)
        scheduled_posts[unique_key] = {'news': news, 'time': publish_time}
        result_text = f"ОТЛОЖЕНО на 3 часа\n\nЗаголовок: {news['title']}\nПубликация: {publish_time.strftime('%H:%M')}"
        if has_photo:
            await query.edit_message_caption(caption=result_text)
        else:
            await query.edit_message_text(result_text)
        del news_storage[unique_key]
        asyncio.create_task(delayed_publish(context, unique_key, 10800))
    elif action == 'delaycustom':
        delay_mode[query.from_user.id] = unique_key
        await query.message.reply_text("Введите время публикации в формате ЧЧ:ММ (например 14:30):")


async def publish_news(context: CallbackContext, news: dict, unique_key: str) -> None:
    if news.get('photo'):
        await context.bot.send_photo(chat_id=CHANNEL_ID, photo=news['photo'], caption=f"*{news['title']}*\n\n{news['text']}", parse_mode='Markdown')
    else:
        await context.bot.send_message(chat_id=CHANNEL_ID, text=f"*{news['title']}*\n\n{news['text']}", parse_mode='Markdown')
    try:
        await context.bot.send_message(chat_id=news['user_id'], text=f"Ваша новость опубликована!\n\n{news['title']}")
    except:
        pass


async def delayed_publish(context: CallbackContext, unique_key: str, delay: int) -> None:
    await asyncio.sleep(delay)
    if unique_key in scheduled_posts:
        news = scheduled_posts[unique_key]['news']
        await publish_news(context, news, unique_key)
        del scheduled_posts[unique_key]
        logger.info(f"Отложенная публикация: {unique_key}")


async def handle_admin_input(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if user_id in delay_mode:
        unique_key = delay_mode[user_id]
        if unique_key in news_storage:
            time_match = re.match(r'^(\d{1,2}):(\d{2})$', text)
            if time_match:
                hours, minutes = int(time_match.group(1)), int(time_match.group(2))
                if 0 <= hours <= 23 and 0 <= minutes <= 59:
                    now = datetime.now()
                    publish_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
                    if publish_time <= now:
                        publish_time += timedelta(days=1)
                    delay_seconds = (publish_time - now).total_seconds()
                    news = news_storage[unique_key]
                    scheduled_posts[unique_key] = {'news': news, 'time': publish_time}
                    del news_storage[unique_key]
                    await update.message.reply_text(f"Новость отложена до {publish_time.strftime('%d.%m %H:%M')}")
                    asyncio.create_task(delayed_publish(context, unique_key, int(delay_seconds)))
                else:
                    await update.message.reply_text("Неверное время. Используйте формат ЧЧ:ММ (00-23:00-59)")
                    return
            else:
                await update.message.reply_text("Неверный формат. Введите время как ЧЧ:ММ (например 14:30):")
                return
        del delay_mode[user_id]
        return
    if user_id in edit_mode:
        unique_key = edit_mode[user_id]
        if unique_key in news_storage:
            new_text = update.message.text.strip()
            news_storage[unique_key]['text'] = new_text
            await update.message.reply_text(f"Текст новости обновлен:\n\n{new_text}")
            keyboard = [
                [
                    InlineKeyboardButton("Опубликовать", callback_data=f'publish_{unique_key}'),
                    InlineKeyboardButton("Отклонить", callback_data=f'reject_{unique_key}')
                ]
            ]
            news = news_storage[unique_key]
            await context.bot.send_message(
                chat_id=MODERATION_GROUP_ID,
                text=f"*ОТРЕДАКТИРОВАНО*\n\n*Заголовок:* {news['title']}\n*Текст:* {new_text}",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        del edit_mode[user_id]


async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text('Отменено.')
    context.user_data.clear()
    return ConversationHandler.END


async def admin_block(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id not in ADMIN_USER_IDS:
        return
    if not context.args:
        await update.message.reply_text("Использование: /block <user_id>")
        return
    try:
        target_id = int(context.args[0])
        blocked_users.add(target_id)
        await update.message.reply_text(f"Пользователь {target_id} заблокирован.")
    except ValueError:
        await update.message.reply_text("Неверный ID.")


async def admin_unblock(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id not in ADMIN_USER_IDS:
        return
    if not context.args:
        await update.message.reply_text("Использование: /unblock <user_id>")
        return
    try:
        target_id = int(context.args[0])
        if target_id in blocked_users:
            blocked_users.remove(target_id)
            await update.message.reply_text(f"Пользователь {target_id} разблокирован.")
        else:
            await update.message.reply_text(f"Пользователь не заблокирован.")
    except ValueError:
        await update.message.reply_text("Неверный ID.")


async def admin_stats(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id not in ADMIN_USER_IDS:
        return
    stats = f"*Статистика*\n\nВ очереди: {len(news_storage)}\nОтложено: {len(scheduled_posts)}\nЗаблокировано: {len(blocked_users)}"
    await update.message.reply_text(stats, parse_mode='Markdown')


async def admin_help(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id not in ADMIN_USER_IDS:
        return
    help_text = "*Команды*\n\n/block <id> - Заблокировать\n/unblock <id> - Разблокировать\n/stats - Статистика\n/scheduled - Отложенные\n\n*Кнопки модерации:*\nОпубликовать/Отклонить\nРедактировать/СПАМ\nОтложить 1ч/3ч"
    await update.message.reply_text(help_text, parse_mode='Markdown')


async def admin_scheduled(update: Update, context: CallbackContext) -> None:
    if update.effective_user.id not in ADMIN_USER_IDS:
        return
    if not scheduled_posts:
        await update.message.reply_text("Нет отложенных публикаций.")
        return
    text = "*Отложенные публикации:*\n\n"
    for key, data in scheduled_posts.items():
        text += f"- {data['news']['title']} в {data['time'].strftime('%H:%M')}\n"
    await update.message.reply_text(text, parse_mode='Markdown')


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_post, pattern='^start_post$')],
        states={
            TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_title)],
            TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_text)],
            PHOTO: [
                MessageHandler(filters.PHOTO, get_photo),
                CallbackQueryHandler(skip_photo, pattern='^skip_photo$')
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        name="news_conversation",
        per_message=False
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("block", admin_block))
    application.add_handler(CommandHandler("unblock", admin_unblock))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("adminhelp", admin_help))
    application.add_handler(CommandHandler("scheduled", admin_scheduled))
    application.add_handler(CallbackQueryHandler(button_callback, pattern='^(publish|reject|spam|edit|delay1|delay3|delaycustom)_'))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_input))
    logger.info("Бот запускается...")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
