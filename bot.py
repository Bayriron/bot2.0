import os
import json
import pandas as pd
import aiofiles  # Асинхронная работа с файлами
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler
import telegram.ext.filters as filters
import logging

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Токен вашего бота
TOKEN = '7627934679:AAENgIwsEZgLGNGNwuq1Ud9foRo6nufbK5o'

# Директория для хранения статистики
STATS_DIR = 'C:\\Users\\User\\Desktop\\python\\stats'
ANSWER_FILE = os.path.join(STATS_DIR, 'answers.json')
STATS_FILE = os.path.join(STATS_DIR, 'stats.json')
EXCEL_FILE = os.path.join(STATS_DIR, 'student_stats.xlsx')

# Создание директории для статистики, если она не существует
if not os.path.exists(STATS_DIR):
    os.makedirs(STATS_DIR)

# Словарь для отслеживания состояния пользователей
user_states = {}
user_data = {}  # Словарь для хранения данных пользователя
cached_stats = None  # Кэш для статистики

# Кэш для ключей ответов
ANSWER_KEY = None

async def load_answer_key():
    """Асинхронно загружает ключи ответов из файла answers.json."""
    global ANSWER_KEY
    if ANSWER_KEY is None:  # Используем кэширование
        try:
            async with aiofiles.open(ANSWER_FILE, 'r', encoding='utf-8') as file:
                data = json.loads(await file.read())
                ANSWER_KEY = data.get('answers', [])
                if not ANSWER_KEY:
                    logger.error("Ответы не найдены в файле answers.json. Проверьте содержимое.")
                else:
                    logger.info(f"Ключи ответов успешно загружены: {ANSWER_KEY}")
        except FileNotFoundError:
            logger.error("Файл answers.json не найден.")
            ANSWER_KEY = []
        except json.JSONDecodeError:
            logger.error("Ошибка декодирования JSON. Проверьте формат файла answers.json.")
            ANSWER_KEY = []
    return ANSWER_KEY

def normalize_answer(answer):
    """Нормализует ответ, удаляя все пробелы и приводя к нижнему регистру."""
    return ''.join(answer.split()).lower()

async def load_stats_async():
    """Асинхронно загружает статистику из файла stats.json с кэшированием."""
    global cached_stats
    if cached_stats is None:
        if os.path.exists(STATS_FILE):
            try:
                async with aiofiles.open(STATS_FILE, 'r', encoding='utf-8') as file:
                    cached_stats = json.loads(await file.read()).get('users', {})
            except json.JSONDecodeError:
                logger.error("Ошибка декодирования JSON. Проверьте формат файла stats.json.")
                cached_stats = {}
        else:
            cached_stats = {}
    return cached_stats


async def save_stats_async(stats):
    """Асинхронно сохраняет статистику в файл stats.json."""
    global cached_stats
    if stats != cached_stats:
        cached_stats = stats  # Обновляем кэш
        data = {"users": stats}
        try:
            async with aiofiles.open(STATS_FILE, 'w', encoding='utf-8') as file:
                await file.write(json.dumps(data, ensure_ascii=False))
        except IOError as e:
            logger.error(f"Ошибка записи в файл {STATS_FILE}: {e}")

async def save_stats_to_excel_async(stats):
    """Асинхронно сохраняет статистику в Excel файл."""
    data = [
        {
            'Имя': user_data['first_name'],
            'Фамилия': user_data['last_name'],
            'Правильных ответов': sum(user_data['scores'])
        }
        for user_id, user_data in stats.items()
    ]
    df = pd.DataFrame(data)
    try:
        df.to_excel(EXCEL_FILE, index=False)
    except IOError as e:
        logger.error(f"Ошибка записи в файл {EXCEL_FILE}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /start, запрашивает имя и фамилию пользователя."""
    try:
        user = update.message.from_user
        logger.info("Команда /start вызвана пользователем %s", user.username)
        user_id = user.id

        user_states[user_id] = 'waiting_for_first_name'
        await update.message.reply_text('Привет! Пожалуйста, введите ваше имя:')
    except Exception as e:
        logger.error("Ошибка в команде /start: %s", e)
        await update.message.reply_text('Произошла ошибка. Пожалуйста, попробуйте позже.')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает текстовые сообщения пользователей для ввода имени и фамилии."""
    try:
        user_id = update.message.from_user.id
        user_text = update.message.text.strip()

        if user_states.get(user_id) == 'waiting_for_first_name':
            user_states[user_id] = 'waiting_for_last_name'
            user_data[user_id] = {'first_name': user_text, 'last_name': ''}
            await update.message.reply_text('Спасибо! Теперь введите вашу фамилию:')
        elif user_states.get(user_id) == 'waiting_for_last_name':
            user_data[user_id]['last_name'] = user_text
            user_states[user_id] = 'registered'
            keyboard = [
                [InlineKeyboardButton("Получить тест", callback_data='get_test')],
                [InlineKeyboardButton("Показать статистику", callback_data='show_stats')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f'Спасибо, {user_data[user_id]["first_name"]} {user_data[user_id]["last_name"]}!\n'
                'Вы можете выбрать, что делать дальше:', 
                reply_markup=reply_markup
            )
        elif user_states.get(user_id) == 'answers_submitted':
            await update.message.reply_text('Вы уже отправили свои ответы. Пожалуйста, используйте команды.')
        else:
            await submit_answers(update, context)
    except Exception as e:
        logger.error("Ошибка в обработке сообщения: %s", e)
        await update.message.reply_text('❌ Произошла ошибка. Пожалуйста, попробуйте позже.')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает нажатия инлайн-кнопок."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id  # Получаем chat_id из query.message

    if query.data == 'get_test':
        await send_test(chat_id, context)
    elif query.data == 'show_stats':
        await show_stats(query.message, context)

async def send_test(chat_id, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет тестовые изображения пользователю."""
    try:
        logger.info("Отправка теста в чат %s", chat_id)
        user_id = chat_id  # Используем chat_id как user_id

        # Проверка, получил ли пользователь уже тест
        if user_states.get(user_id) in ['test_sent', 'answers_submitted']:
            await context.bot.send_message(chat_id, 'Вы уже получили тест. Пожалуйста, отправьте свои ответы.')
            return

        user_states[user_id] = 'test_sent'  # Обновляем состояние пользователя
        file_paths = [
            "C:\\Users\\User\\Desktop\\phyton\\test n2.png"  
     ]
        for file_path in file_paths:
            try:
                async with aiofiles.open(file_path, 'rb') as image:
                    image_data = await image.read()  # Здесь нужно явно вызвать read
                    await context.bot.send_photo(chat_id=chat_id, photo=image_data)
            except FileNotFoundError:
                await context.bot.send_message(chat_id, f"Файл {file_path} не найден. Пожалуйста, проверьте путь к файлу.")
        
        recommendations = (
            "Для решения тестов советуется отводить время 1 час.\n"
            "Отправляйте ответы в нижнем регистре без пробелов.\n"
            "Пример: abcdeabcdeabcdeabcdeabcdeabcde"
        )
        await context.bot.send_message(chat_id, recommendations)
    except Exception as e:
        logger.error("Ошибка в команде /get_test: %s", e)
        await context.bot.send_message(chat_id, 'Произошла ошибка. Пожалуйста, попробуйте позже.')
async def show_stats(message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет пользователю статистику в виде списка."""
    try:
        stats = await load_stats_async()
        if stats:
            sorted_stats = sorted(
                [(user_data['first_name'], user_data['last_name'], sum(user_data['scores'])) for user_data in stats.values()],
                key=lambda x: x[2],
                reverse=True
            )
            stats_message = "Статистика📊:\n"
            for idx, (first_name, last_name, total_correct) in enumerate(sorted_stats, 1):
                stats_message += f"{idx}. {first_name} {last_name} - {total_correct} правильных ответов\n"
        else:
            stats_message = "Статистика не найдена."
        await message.reply_text(stats_message)
    except Exception as e:
        logger.error("Ошибка в команде /show_stats: %s", e)
        await message.reply_text('Произошла ошибка. Пожалуйста, попробуйте позже.')

def format_results(user_answers, correct_answers):
    """Форматирует результаты теста с зелеными галочками и красными крестиками."""
    results = []
    for i, (user_answer, correct_answer) in enumerate(zip(user_answers, correct_answers), 1):
        if normalize_answer(user_answer) == normalize_answer(correct_answer):
            results.append(f"{i}. {user_answer} ✅")
        else:
            results.append(f"{i}. {user_answer} ❌")
    return "\n".join(results)

async def submit_answers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает отправленные ответы от пользователя и сохраняет их."""
    try:
        user_id = update.message.from_user.id
        answers = update.message.text.strip()

        # Проверка состояния пользователя
        if user_states.get(user_id) != 'test_sent':
            await update.message.reply_text('Вы еще не получили тест. Пожалуйста, выберите тест из меню.')
            return

        # Загружаем правильные ответы
        correct_answers = await load_answer_key()

        # Проверка на совпадение количества ответов
        if len(answers) != len(correct_answers):
            await update.message.reply_text(
                f'Количество ответов ({len(answers)}) не совпадает с количеством вопросов ({len(correct_answers)}). Попробуйте снова.'
            )
            return

        # Форматируем результаты
        results = format_results(answers, correct_answers)
        await update.message.reply_text(f"Результаты:\n{results}")

        # Обновляем состояние пользователя
        user_states[user_id] = 'answers_submitted'

        # Загружаем текущую статистику
        stats = await load_stats_async()

        # Проверка на пустой словарь
        if stats is None:
            stats = {}
        
        # Логируем текущее состояние статистики
        logger.info(f"Текущая статистика: {stats}")

        # Проверяем наличие данных пользователя
        if str(user_id) not in stats:
            # Если пользователя нет в статистике, добавляем его
            logger.info(f"Добавляем нового пользователя {user_id} в статистику.")
            if user_id in user_data:
                stats[str(user_id)] = {
                    'first_name': user_data[user_id].get('first_name', 'Неизвестно'),
                    'last_name': user_data[user_id].get('last_name', 'Неизвестно'),
                    'scores': [1 if normalize_answer(a) == normalize_answer(c) else 0 for a, c in zip(answers, correct_answers)]
                }
            else:
                logger.error(f"Данные пользователя с ID {user_id} не найдены в user_data.")
                await update.message.reply_text('Произошла ошибка. Ваши данные не найдены.')
                return
        else:
            # Если пользователь уже есть, обновляем его статистику
            logger.info(f"Обновляем статистику для пользователя {user_id}.")
            stats[str(user_id)]['scores'].extend(
                [1 if normalize_answer(a) == normalize_answer(c) else 0 for a, c in zip(answers, correct_answers)]
            )

        # Логируем обновленную статистику
        logger.info(f"Обновленная статистика для пользователя {user_id}: {stats[str(user_id)]}")

        # Сохраняем статистику
        await save_stats_async(stats)
        await save_stats_to_excel_async(stats)

    except Exception as e:
        logger.error("Ошибка при отправке ответов: %s", e)
        await update.message.reply_text('Произошла ошибка. Пожалуйста, попробуйте позже.')


def main():
    """Запускает бота."""
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()

if __name__ == '__main__':
    main()
