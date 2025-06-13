import logging
import shutil
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaVideo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
import config
import os
from datetime import datetime
from moviepy import VideoFileClip
from pytubefix import YouTube
import instaloader
import re


# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Максимальный размер файла (10 МБ в байтах)
MAX_FILE_SIZE = 10 * 1024 * 1024

# Словарь для хранения выбранной папки для каждого пользователя
user_folders = {}

# Словарь для хранения временных файлов
temp_videos = {}

# Состояния для ConversationHandler
WAITING_FOLDER_NAME = 1
WAITING_FILENAME = 2
WAITING_TRIM_START = 3
WAITING_TRIM_END = 4
WAITING_URL = 5

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text('Привет! Я бот для работы с видео. Используйте /help для просмотра команд.')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = """
Доступные команды:
/start - Запустить бота
/help - Показать это сообщение
/list - Показать доступные видео
/folders - Доступ к видео
/create_folder - Создать новую папку (можно указать имя папки сразу или после команды)
/delete_folder - Удалить папку и все видео в ней
/delete_video - Удалить конкретное видео из папки
/clear - Очистить чат от сообщений бота
/download_from_url - Скачать видео с YouTube или Instagram

Чтобы загрузить видео, просто отправьте его мне. После загрузки вы сможете выбрать папку для сохранения.
Максимальный размер - 10 МБ.
    """
    await update.message.reply_text(help_text)

async def create_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a new folder in resources directory."""
    logger.info("Command /create_folder received")
    try:
        if context.args:
            # Если имя папки передано сразу с командой
            folder_name = context.args[0]
            logger.info(f"Creating folder with name: {folder_name}")
            folder_path = os.path.join(config.RESOURCES_DIR, folder_name)
            os.makedirs(folder_path, exist_ok=True)
            await update.message.reply_text(f"Папка '{folder_name}' успешно создана!")
        else:
            # Если имя папки нужно запросить
            logger.info("Requesting folder name from user")
            await update.message.reply_text(
                "Пожалуйста, отправьте название новой папки.\n"
                "Или отправьте /cancel для отмены."
            )
            # Сохраняем состояние ожидания имени папки
            context.user_data['waiting_for_folder_name'] = True
    except Exception as e:
        logger.error(f"Ошибка при создании папки: {e}")
        await update.message.reply_text("Извините, произошла ошибка при создании папки.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages."""
    if context.user_data.get('waiting_for_folder_name'):
        try:
            folder_name = update.message.text
            logger.info(f"Creating folder with name: {folder_name}")
            folder_path = os.path.join(config.RESOURCES_DIR, folder_name)
            os.makedirs(folder_path, exist_ok=True)
            await update.message.reply_text(f"Папка '{folder_name}' успешно создана!")
            context.user_data['waiting_for_folder_name'] = False
        except Exception as e:
            logger.error(f"Ошибка при создании папки: {e}")
            await update.message.reply_text("Извините, произошла ошибка при создании папки.")
            context.user_data['waiting_for_folder_name'] = False
    
    elif context.user_data.get('waiting_for_file_name'):
        try:
            file_name = update.message.text+".mp4"
            await save_video(update, context, file_name)
            context.user_data['waiting_for_file_name'] = False
        except Exception as e:
            logger.error(f"Ошибка при создании файла: {e}")
            await update.message.reply_text("Извините, произошла ошибка при создании файла.")
            context.user_data['waiting_for_file_name'] = False
    
    elif context.user_data.get('waiting_for_trim_start'):
        try:
            start_time = float(update.message.text)
            duration = context.user_data.get('video_duration', 0)
            
            if start_time < 0 or start_time >= duration:
                await update.message.reply_text(
                    f"Пожалуйста, введите время от 0 до {int(duration)} секунд."
                )
                return
            
            context.user_data['trim_start'] = start_time
            context.user_data['waiting_for_trim_start'] = False
            context.user_data['waiting_for_trim_end'] = True
            
            await update.message.reply_text(
                f"Введите время окончания обрезки (в секундах, от {int(start_time)} до {int(duration)}):"
            )
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите корректное число.")
    
    elif context.user_data.get('waiting_for_trim_end'):
        try:
            end_time = float(update.message.text)
            start_time = context.user_data.get('trim_start', 0)
            duration = context.user_data.get('video_duration', 0)
            
            if end_time <= start_time or end_time > duration:
                await update.message.reply_text(
                    f"Пожалуйста, введите время от {int(start_time)} до {int(duration)} секунд."
                )
                return
            
            # Обрезаем видео используя новый синтаксис
            user_id = update.effective_user.id
            if user_id in temp_videos:
                video_path = temp_videos[user_id]['path']
                try:
                    clip = (
                        VideoFileClip(video_path)
                        .subclipped(start_time, end_time)
                    )
                    temp_path = video_path.replace('.mp4', '_trimmed.mp4')
                    clip.write_videofile(temp_path)
                    clip.close()  # Закрываем клип после использования
                    
                    # Обновляем путь к видео
                    temp_videos[user_id]['path'] = temp_path
                    os.remove(video_path)  # Удаляем оригинальный файл
                    
                    # Показываем меню выбора папки
                    await show_folder_selection(update, context)
                except Exception as e:
                    logger.error(f"Ошибка при обрезке видео: {e}")
                    await update.message.reply_text("Извините, произошла ошибка при обрезке видео.")
            
            context.user_data['waiting_for_trim_end'] = False
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите корректное число.")
    elif context.user_data.get('waiting_for_url'):
        try:
            await handle_url(update, context)
        except Exception as e:
            logger.error(f"Ошибка при скачивании файла: {e}")
            await update.message.reply_text("Извините, произошла ошибка при скачивании файла.")
            context.user_data['waiting_for_url'] = False
        

async def list_folders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available folders."""
    try:
        folders = [f for f in os.listdir(config.RESOURCES_DIR) 
                  if os.path.isdir(os.path.join(config.RESOURCES_DIR, f))]
        
        if not folders:
            message = "Нет доступных папок."
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
            return

        keyboard = []
        for folder in folders:
            # Подсчет видео в папке
            videos = [f for f in os.listdir(os.path.join(config.RESOURCES_DIR, folder)) 
                     if f.endswith(('.mp4', '.avi', '.mov'))]
            keyboard.append([
                InlineKeyboardButton(
                    f"📁 {folder} ({len(videos)} видео)", 
                    callback_data=f"view_{folder}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = "Выберите папку для просмотра видео:"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Ошибка при показе списка папок: {e}")
        message = "Извините, произошла ошибка при получении списка папок."
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming video files."""
    try:
        video = update.message.video
        user_id = update.effective_user.id
        
        # Проверка размера файла
        if video.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(
                f"Извините, файл слишком большой. Максимальный размер - 10 МБ."
            )
            return

        # Получаем файл
        file = await context.bot.get_file(video.file_id)
        
        # Создаем временное имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_filename = f"temp_{timestamp}.mp4"
        temp_path = os.path.join(config.RESOURCES_DIR, temp_filename)
        
        # Скачиваем файл во временную папку
        await file.download_to_drive(temp_path)
        
        # Сохраняем информацию о временном файле
        temp_videos[user_id] = {
            'path': temp_path,
            'size': video.file_size,
            'timestamp': timestamp
        }
        
        # Показываем меню выбора режима загрузки
        keyboard = [
            [InlineKeyboardButton("📤 Загрузить видео полностью", callback_data="upload_full")],
            [InlineKeyboardButton("✂️ Обрезать видео", callback_data="upload_trim")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите режим загрузки видео:",
            reply_markup=reply_markup
        )
        
    except Exception as e:
        logger.error(f"Ошибка при загрузке видео: {e}")
        await update.message.reply_text("Извините, произошла ошибка при загрузке видео.")

async def show_folder_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show folder selection keyboard for video saving."""
    try:
        folders = [f for f in os.listdir(config.RESOURCES_DIR) 
                  if os.path.isdir(os.path.join(config.RESOURCES_DIR, f))]
        
        if not folders:
            message = "Нет доступных папок. Создайте папку командой /create_folder"
            if update.callback_query:
                await update.callback_query.edit_message_text(message)
            else:
                await update.message.reply_text(message)
            return

        keyboard = []
        for folder in folders:
            keyboard.append([InlineKeyboardButton(folder, callback_data=f"save_{folder}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        message = "Выберите папку для сохранения видео:"
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                message,
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                message,
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Ошибка при выборе папки: {e}")
        error_message = "Извините, произошла ошибка при выборе папки."
        if update.callback_query:
            await update.callback_query.edit_message_text(error_message)
        else:
            await update.message.reply_text(error_message)

async def show_filename_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, folder_name: str):
    """Show filename selection keyboard."""
    query = update.callback_query
    user_id = update.effective_user.id
    
    # Сохраняем выбранную папку
    temp_videos[user_id]['selected_folder'] = folder_name
    
    keyboard = [
        [InlineKeyboardButton("Использовать случайное имя", callback_data="random_name")],
        [InlineKeyboardButton("Ввести своё имя", callback_data="custom_name")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        "Выберите способ задания имени файла:",
        reply_markup=reply_markup
    )

async def handle_filename_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle custom filename input."""
    user_id = update.effective_user.id
    filename = update.message.text
    
    if not filename.endswith('.mp4'):
        filename += '.mp4'
    
    await save_video(update, context, filename)
    return ConversationHandler.END

async def save_video(update: Update, context: ContextTypes.DEFAULT_TYPE, filename: str = None):
    """Save video to selected folder with given filename."""
    user_id = update.effective_user.id
    
    if user_id not in temp_videos:
        if update.callback_query:
            await update.callback_query.edit_message_text("Ошибка: видео не найдено. Пожалуйста, загрузите видео снова.")
        else:
            await update.message.reply_text("Ошибка: видео не найдено. Пожалуйста, загрузите видео снова.")
        return
    
    temp_video = temp_videos[user_id]
    folder_name = temp_video['selected_folder']
    
    # Если имя файла не указано, генерируем случайное
    if not filename:
        filename = f"video_{temp_video['timestamp']}.mp4"
    
    final_path = os.path.join(config.RESOURCES_DIR, folder_name, filename)
    
    try:
        # Перемещаем файл в выбранную папку
        os.rename(temp_video['path'], final_path)
        
        message = (
            f"Видео успешно сохранено в папку '{folder_name}'!\n"
            f"Имя файла: {filename}\n"
            f"Размер: {round(temp_video['size'] / (1024 * 1024), 2)} МБ"
        )
        
        if update.callback_query:
            await update.callback_query.edit_message_text(message)
        else:
            await update.message.reply_text(message)
        
        # Удаляем информацию о временном файле
        del temp_videos[user_id]
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении видео: {e}")
        error_message = "Извините, произошла ошибка при сохранении видео."
        
        if update.callback_query:
            await update.callback_query.edit_message_text(error_message)
        else:
            await update.message.reply_text(error_message)
        
        # Удаляем временный файл в случае ошибки
        if os.path.exists(temp_video['path']):
            os.remove(temp_video['path'])
        del temp_videos[user_id]

async def delete_folder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show folder deletion keyboard."""
    try:
        folders = [f for f in os.listdir(config.RESOURCES_DIR) 
                  if os.path.isdir(os.path.join(config.RESOURCES_DIR, f))]
        
        if not folders:
            await update.message.reply_text("Нет доступных папок для удаления.")
            return

        keyboard = []
        for folder in folders:
            # Подсчет видео в папке
            videos = [f for f in os.listdir(os.path.join(config.RESOURCES_DIR, folder)) 
                     if f.endswith(('.mp4', '.avi', '.mov'))]
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑 {folder} ({len(videos)} видео)", 
                    callback_data=f"delete_{folder}"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите папку для удаления (вместе со всеми видео):",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка при показе списка папок для удаления: {e}")
        await update.message.reply_text("Извините, произошла ошибка при получении списка папок.")

async def clear_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show confirmation for chat clearing."""
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, очистить", callback_data="clear_confirm"),
            InlineKeyboardButton("❌ Нет, отмена", callback_data="clear_cancel")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚠️ Вы уверены, что хотите очистить чат от всех сообщений бота?\n"
        "Это действие нельзя отменить!",
        reply_markup=reply_markup
    )

async def delete_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show folder selection for video deletion."""
    try:
        folders = [f for f in os.listdir(config.RESOURCES_DIR) 
                  if os.path.isdir(os.path.join(config.RESOURCES_DIR, f))]
        
        if not folders:
            await update.message.reply_text("Нет доступных папок для удаления видео.")
            return

        keyboard = []
        for folder in folders:
            # Подсчет видео в папке
            videos = [f for f in os.listdir(os.path.join(config.RESOURCES_DIR, folder)) 
                     if f.endswith(('.mp4', '.avi', '.mov'))]
            keyboard.append([
                InlineKeyboardButton(
                    f"📁 {folder} ({len(videos)} видео)", 
                    callback_data=f"select_delete_folder_{folder}"
                )
            ])
        
        # Добавляем кнопку отмены
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete_video")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Выберите папку для удаления видео:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Ошибка при показе списка папок для удаления видео: {e}")
        await update.message.reply_text("Извините, произошла ошибка при получении списка папок.")

async def folder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle folder selection callback."""
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    
    if callback_data == "upload_full":
        # Показываем меню выбора папки
        await show_folder_selection(update, context)
    elif callback_data == "upload_trim":
        # Запрашиваем время начала обрезки
        user_id = update.effective_user.id
        if user_id in temp_videos:
            video_path = temp_videos[user_id]['path']
            try:
                with VideoFileClip(video_path) as clip:
                    duration = clip.duration
                    await query.edit_message_text(
                        f"Длительность видео: {int(duration)} секунд\n"
                        f"Введите время начала обрезки (в секундах, от 0 до {int(duration)}):"
                    )
                    context.user_data['video_duration'] = duration
                    context.user_data['waiting_for_trim_start'] = True
            except Exception as e:
                logger.error(f"Ошибка при получении длительности видео: {e}")
                await query.edit_message_text("Извините, произошла ошибка при обработке видео.")
    elif callback_data == "clear_confirm":
        # Очистка чата
        try:
            # Получаем ID чата
            chat_id = query.message.chat_id
            
            # Отправляем сообщение о начале очистки
            status_message = await query.message.reply_text("🔄 Начинаю очистку чата...")
            
            deleted_count = 0
            message_id = query.message.message_id
            count_errors = 0
            
            # Удаляем сообщения, начиная с текущего
            while message_id > 0 and count_errors < 10:
                try:
                    # Пытаемся удалить сообщение
                    await context.bot.delete_message(
                        chat_id=chat_id,
                        message_id=message_id
                    )
                    deleted_count += 1
                    count_errors = 0
                    
                    # Обновляем статус каждые 5 сообщений
                    if deleted_count % 5 == 0:
                        await status_message.edit_text(
                            f"🔄 Удалено сообщений: {deleted_count}..."
                        )
                    
                    # Уменьшаем ID для следующего сообщения
                    message_id -= 1
                    # Добавляем задержку
                    await asyncio.sleep(0.01)
                    
                except Exception as e:
                    # Если сообщение не найдено или не может быть удалено, пропускаем его
                    message_id -= 1
                    count_errors += 1
                    continue
                
                # Если удалено более 100 сообщений, останавливаемся
                if deleted_count >= 100:
                    break
            
            # Финальное сообщение
            await status_message.edit_text(
                f"✅ Чат успешно очищен!\nУдалено сообщений: {deleted_count}"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при очистке чата: {e}")
            await query.edit_message_text("Извините, произошла ошибка при очистке чата.")
    elif callback_data == "clear_cancel":
        await query.edit_message_text("❌ Очистка чата отменена.")
    elif callback_data == "cancel_delete_video":
        await query.edit_message_text("❌ Удаление видео отменено.")
    elif callback_data.startswith("select_delete_folder_"):
        # Показываем список видео в выбранной папке
        folder_name = callback_data.replace("select_delete_folder_", "")
        folder_path = os.path.join(config.RESOURCES_DIR, folder_name)
        
        try:
            videos = [f for f in os.listdir(folder_path) 
                     if f.endswith(('.mp4', '.avi', '.mov'))]
            
            if not videos:
                await query.edit_message_text(f"❌ В папке '{folder_name}' нет видео.")
                return
            
            keyboard = []
            for video in videos:
                keyboard.append([
                    InlineKeyboardButton(
                        f"🗑 {video}", 
                        callback_data=f"delete_video;{folder_name};{video}"
                    )
                ])
            
            # Добавляем кнопки управления
            keyboard.append([
                InlineKeyboardButton("✅ Завершить удаление", callback_data="finish_delete_video"),
                InlineKeyboardButton("◀️ Назад к папкам", callback_data="back_to_folders_delete")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"Выберите видео для удаления из папки '{folder_name}':",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка при получении списка видео: {e}")
            await query.edit_message_text("Извините, произошла ошибка при получении списка видео.")
    elif callback_data.startswith("delete_video"):
        # Удаляем выбранное видео
        _, folder_name, video_name = callback_data.split(";", 2)
        video_path = os.path.join(config.RESOURCES_DIR, folder_name, video_name)
        
        try:
            logger.info(f"Attempting to delete video at path: {video_path}")
            if os.path.exists(video_path):
                os.remove(video_path)
                await query.answer(f"✅ Видео '{video_name}' удалено")
                
                # Обновляем список видео
                videos = [f for f in os.listdir(os.path.join(config.RESOURCES_DIR, folder_name)) 
                         if f.endswith(('.mp4', '.avi', '.mov'))]
                
                if not videos:
                    await query.edit_message_text(f"✅ Все видео из папки '{folder_name}' удалены.")
                    return
                
                keyboard = []
                for video in videos:
                    keyboard.append([
                        InlineKeyboardButton(
                            f"🗑 {video}", 
                            callback_data=f"delete_video;{folder_name};{video}"
                        )
                    ])
                
                keyboard.append([
                    InlineKeyboardButton("✅ Завершить удаление", callback_data="finish_delete_video"),
                    InlineKeyboardButton("◀️ Назад к папкам", callback_data="back_to_folders_delete")
                ])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    f"Выберите видео для удаления из папки '{folder_name}':",
                    reply_markup=reply_markup
                )
            else:
                logger.error(f"Video file not found at path: {video_path}")
                await query.answer("❌ Видео не найдено")
        except Exception as e:
            logger.error(f"Ошибка при удалении видео: {e}")
            await query.answer("❌ Ошибка при удалении видео")
    elif callback_data == "finish_delete_video":
        await query.edit_message_text("✅ Удаление видео завершено.")
    elif callback_data == "back_to_folders_delete":
        # Показываем список папок снова
        try:
            folders = [f for f in os.listdir(config.RESOURCES_DIR) 
                      if os.path.isdir(os.path.join(config.RESOURCES_DIR, f))]
            
            if not folders:
                await query.edit_message_text("Нет доступных папок для удаления видео.")
                return

            keyboard = []
            for folder in folders:
                videos = [f for f in os.listdir(os.path.join(config.RESOURCES_DIR, folder)) 
                         if f.endswith(('.mp4', '.avi', '.mov'))]
                keyboard.append([
                    InlineKeyboardButton(
                        f"📁 {folder} ({len(videos)} видео)", 
                        callback_data=f"select_delete_folder_{folder}"
                    )
                ])
            
            keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete_video")])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "Выберите папку для удаления видео:",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка при показе списка папок: {e}")
            await query.edit_message_text("Извините, произошла ошибка при получении списка папок.")
    elif callback_data.startswith("save_"):
        # Обработка выбора папки
        folder_name = callback_data.replace("save_", "")
        await show_filename_selection(update, context, folder_name)
    elif callback_data == "random_name":
        # Использовать случайное имя
        await save_video(update, context)
    elif callback_data == "custom_name":
        # Запросить пользовательское имя
        await query.edit_message_text(
            "Пожалуйста, отправьте желаемое имя файла (без расширения .mp4):\n"
            "Или отправьте /cancel для отмены."
        )
        context.user_data['waiting_for_file_name'] = True
        return WAITING_FILENAME
    elif callback_data.startswith("delete_"):
        # Обработка удаления папки
        folder_name = callback_data.replace("delete_", "")
        folder_path = os.path.join(config.RESOURCES_DIR, folder_name)
        
        try:
            # Подсчет видео перед удалением
            videos = [f for f in os.listdir(folder_path) 
                     if f.endswith(('.mp4', '.avi', '.mov'))]
            
            # Удаляем папку со всем содержимым
            shutil.rmtree(folder_path)
            
            await query.edit_message_text(
                f"Папка '{folder_name}' успешно удалена!\n"
                f"Удалено видео: {len(videos)}"
            )
        except Exception as e:
            logger.error(f"Ошибка при удалении папки: {e}")
            await query.edit_message_text(
                "Извините, произошла ошибка при удалении папки."
            )
    elif callback_data.startswith("view_"):
        # Просмотр видео в папке
        folder_name = callback_data.replace("view_", "")
        folder_path = os.path.join(config.RESOURCES_DIR, folder_name)
        
        try:
            videos = [f for f in os.listdir(folder_path) 
                     if f.endswith(('.mp4', '.avi', '.mov'))]
            
            if not videos:
                await query.edit_message_text(f"В папке '{folder_name}' нет видео.")
                return
            
            # Создаем клавиатуру с видео
            keyboard = []
            for video in videos:
                keyboard.append([
                    InlineKeyboardButton(
                        f"🎥 {video}", 
                        callback_data=f"play_{folder_name}_{video}"
                    )
                ])
            
            # Добавляем кнопки управления
            keyboard.append([
                InlineKeyboardButton("📤 Отправить все видео", callback_data=f"send_all_{folder_name}"),
                InlineKeyboardButton("◀️ Назад к папкам", callback_data="back_to_folders")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                f"Видео в папке '{folder_name}':",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка при просмотре видео в папке: {e}")
            await query.edit_message_text(
                "Извините, произошла ошибка при получении списка видео."
            )
    elif callback_data.startswith("play_"):
        # Воспроизведение выбранного видео
        _, folder_name, video_name = callback_data.split("_", 2)
        video_path = os.path.join(config.RESOURCES_DIR, folder_name, video_name)
        
        try:
            with open(video_path, 'rb') as video_file:
                await query.message.reply_video(
                    video=video_file,
                    caption=f"🎥 {video_name}"
                )
        except Exception as e:
            logger.error(f"Ошибка при отправке видео: {e}")
            await query.edit_message_text(
                "Извините, произошла ошибка при отправке видео."
            )
    elif callback_data.startswith("send_all_"):
        # Отправка всех видео из папки
        folder_name = callback_data.replace("send_all_", "")
        folder_path = os.path.join(config.RESOURCES_DIR, folder_name)
        
        try:
            videos = [f for f in os.listdir(folder_path) 
                     if f.endswith(('.mp4', '.avi', '.mov'))]
            
            if not videos:
                await query.edit_message_text(f"В папке '{folder_name}' нет видео.")
                return
            
            # Отправляем сообщение о начале отправки
            status_message = await query.message.reply_text(
                f"Начинаю отправку {len(videos)} видео из папки '{folder_name}'..."
            )
            
            # Отправляем видео по одному
            for i, video in enumerate(videos, 1):
                try:
                    video_path = os.path.join(folder_path, video)
                    with open(video_path, 'rb') as video_file:
                        await query.message.reply_video(
                            video=video_file,
                            caption=f"🎥 {video} ({i}/{len(videos)})"
                        )
                    
                    # Обновляем статус
                    await status_message.edit_text(
                        f"Отправлено {i} из {len(videos)} видео..."
                    )
                except Exception as e:
                    logger.error(f"Ошибка при отправке видео {video}: {e}")
                    await status_message.edit_text(
                        f"Ошибка при отправке видео {video}. Продолжаю отправку..."
                    )
                    continue
            
            # Финальное сообщение
            await status_message.edit_text(
                f"✅ Все видео из папки '{folder_name}' успешно отправлены!"
            )
            
        except Exception as e:
            logger.error(f"Ошибка при отправке всех видео: {e}")
            await query.edit_message_text(
                "Извините, произошла ошибка при отправке видео."
            )
    elif callback_data == "back_to_folders":
        # Возврат к списку папок
        await list_folders(update, context)

async def list_resources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all available video resources."""
    try:
        folders = [f for f in os.listdir(config.RESOURCES_DIR) 
                  if os.path.isdir(os.path.join(config.RESOURCES_DIR, f))]
        
        if not folders:
            await update.message.reply_text("Нет доступных папок с видео.")
            return
        
        message = "Доступные видео по папкам:\n\n"
        for folder in folders:
            folder_path = os.path.join(config.RESOURCES_DIR, folder)
            files = [f for f in os.listdir(folder_path) if f.endswith(('.mp4', '.avi', '.mov'))]
            
            if files:
                message += f"📁 {folder}:\n"
                for i, file in enumerate(files, 1):
                    file_size = os.path.getsize(os.path.join(folder_path, file))
                    size_mb = round(file_size / (1024 * 1024), 2)
                    message += f"  {i}. {file} ({size_mb} МБ)\n"
                message += "\n"
        
        await update.message.reply_text(message)
    except Exception as e:
        logger.error(f"Ошибка при получении списка ресурсов: {e}")
        await update.message.reply_text("Извините, произошла ошибка при получении списка видео.")

async def download_from_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /download_from_url command."""
    await update.message.reply_text(
        "Отправьте ссылку на видео с YouTube или Instagram.\n"
        "Или отправьте /cancel для отмены."
    )
    context.user_data['waiting_for_url'] = True
    return WAITING_URL

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    user_id = update.effective_user.id
    
    try:
        # Проверяем, что это валидный URL
        if not (url.startswith('http://') or url.startswith('https://')):
            await update.message.reply_text("Пожалуйста, отправьте корректную ссылку.")
            return
        
        # Отправляем сообщение о начале загрузки
        status_message = await update.message.reply_text("⏳ Начинаю загрузку видео...")
        
        # Создаем временное имя файла
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_filename = f"temp_{timestamp}.mp4"
        temp_path = os.path.join(config.RESOURCES_DIR, temp_filename)
        
        # Определяем тип URL и скачиваем видео
        if 'youtube.com' in url or 'youtu.be' in url:
            # YouTube
            await status_message.edit_text("⏳ Загружаю видео с YouTube...")
            try:
                yt = YouTube(url)
                stream = None
                # Пробуем получить поток с максимальным качеством
                try:
                    stream = yt.streams.get_highest_resolution()
                except Exception as e:
                    logger.error(f"Ошибка при выборе качества видео: {e}")
                    
                if stream == None:
                    # Если не получилось, пробуем получить любой MP4 поток
                    stream = yt.streams.filter(file_extension='mp4').first()
                if not stream:
                    await status_message.edit_text("❌ Не удалось найти подходящий формат видео.")
                    return
                
                # Скачиваем видео
                await status_message.edit_text("⏳ Скачиваю видео...")
                downloaded_path = stream.download(output_path=config.RESOURCES_DIR, filename=temp_filename)
                
                # Проверяем, что файл существует
                if not os.path.exists(downloaded_path):
                    await status_message.edit_text("❌ Ошибка при сохранении видео.")
                    return
                
                # Обновляем путь к файлу
                temp_path = downloaded_path
                
            except Exception as e:
                logger.error(f"Ошибка при скачивании с YouTube: {e}")
                await status_message.edit_text("❌ Ошибка при скачивании видео с YouTube. Попробуйте другую ссылку.")
                return
            
        elif 'instagram.com' in url:
            # Instagram
            await status_message.edit_text("⏳ Загружаю видео с Instagram...")
            L = instaloader.Instaloader()
            post = instaloader.Post.from_shortcode(L.context, url.split('/')[-2])
            if not post.is_video:
                await status_message.edit_text("❌ Это не видео.")
                return
            L.download_post(post, target=config.RESOURCES_DIR)
            # Переименовываем скачанный файл
            downloaded_file = [f for f in os.listdir(config.RESOURCES_DIR) if f.endswith('.mp4')][-1]
            os.rename(os.path.join(config.RESOURCES_DIR, downloaded_file), temp_path)
            
        else:
            await status_message.edit_text("❌ Поддерживаются только ссылки на YouTube и Instagram.")
            return
        
        # Проверяем размер файла
        file_size = os.path.getsize(temp_path)
        if file_size > MAX_FILE_SIZE:
            os.remove(temp_path)
            await status_message.edit_text("❌ Видео слишком большое. Максимальный размер - 10 МБ.")
            return
        
        # Сохраняем информацию о временном файле
        temp_videos[user_id] = {
            'path': temp_path,
            'size': file_size,
            'timestamp': timestamp
        }
        
        # Показываем меню выбора режима загрузки
        keyboard = [
            [InlineKeyboardButton("📤 Загрузить видео полностью", callback_data="upload_full")],
            [InlineKeyboardButton("✂️ Обрезать видео", callback_data="upload_trim")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await status_message.edit_text(
            "✅ Видео успешно загружено!\nВыберите режим загрузки видео:",
            reply_markup=reply_markup
        )
        
        context.user_data['waiting_for_url'] = False
        
    except Exception as e:
        logger.error(f"Ошибка при загрузке видео: {e}")
        await update.message.reply_text("❌ Произошла ошибка при загрузке видео. Проверьте ссылку и попробуйте снова.")
        context.user_data['waiting_for_url'] = False

def main():
    """Start the bot."""
    # Create the Application with increased connection pool size and timeout
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .connection_pool_size(16)  # Увеличиваем размер пула соединений
        .connect_timeout(30.0)     # Увеличиваем таймаут соединения
        .read_timeout(30.0)        # Увеличиваем таймаут чтения
        .write_timeout(30.0)       # Увеличиваем таймаут записи
        .pool_timeout(30.0)        # Увеличиваем таймаут пула
        .build()
    )

    # Add command handlers first
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("list", list_resources))
    application.add_handler(CommandHandler("folders", list_folders))
    application.add_handler(CommandHandler("create_folder", create_folder))
    application.add_handler(CommandHandler("delete_folder", delete_folder))
    application.add_handler(CommandHandler("delete_video", delete_video))
    application.add_handler(CommandHandler("clear", clear_chat))
    application.add_handler(CommandHandler("download_from_url", download_from_url))
    
    # Add video handler
    application.add_handler(MessageHandler(filters.VIDEO, handle_video))
    
    # Add text handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Add callback handler for folder selection
    application.add_handler(CallbackQueryHandler(folder_callback, pattern="^(save_|random_name|delete_|view_|play_|send_all_|back_to_folders|clear_confirm|clear_cancel|select_delete_folder_|delete_video_|cancel_delete_video|finish_delete_video|back_to_folders_delete|custom_name|upload_full|upload_trim)"))

    # Start the Bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main() 