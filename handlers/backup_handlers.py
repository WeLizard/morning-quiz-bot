#handlers/backup_handlers.py
import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from telegram.constants import ParseMode
from utils import escape_markdown_v2, is_user_admin_in_update
from backup_manager import BackupManager
from pathlib import Path

logger = logging.getLogger(__name__)

class BackupHandlers:
    def __init__(self, app_config, backup_manager: BackupManager):
        self.app_config = app_config
        self.backup_manager = backup_manager
    
    def get_handlers(self):
        """Возвращает список обработчиков команд для бекапов"""
        if getattr(self.app_config, 'storage_backend', 'json') == 'postgres':
            from handlers.postgres_backup_handlers import PostgresBackupHandlers
            return PostgresBackupHandlers(self.app_config).get_handlers()
        return [
            CommandHandler("backup", self.backup_command),
            CommandHandler("backups", self.list_backups_command),
            CommandHandler("restore", self.restore_backup_command),
            CommandHandler("deletebackup", self.delete_backup_command),
            CommandHandler("backupstats", self.backup_stats_command),
        ]
    
    async def backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда для создания бекапа системы"""
        if not update.message or not update.effective_chat:
            return
        
        # Проверяем права администратора
        if not await is_user_admin_in_update(update, context):
            await update.message.reply_text(
                escape_markdown_v2("❌ У вас нет прав для выполнения этой команды. Требуются права администратора.")
            )
            return
        
        chat_id = update.effective_chat.id
        user = update.effective_user
        
        # Получаем описание из аргументов
        description = " ".join(context.args) if context.args else "Ручной бекап"
        
        logger.info(f"Создание бекапа запрошено пользователем {user.id} ({user.full_name}) в чате {chat_id}")
        
        # Отправляем сообщение о начале процесса
        status_msg = await update.message.reply_text(
            escape_markdown_v2("🔄 Создание бекапа системы...\n\nПожалуйста, подождите.")
        )
        
        try:
            # Создаем бекап
            success, result = self.backup_manager.create_backup(description=description)
            
            if success:
                # Получаем статистику бекапа
                stats = self.backup_manager.get_backup_stats()
                
                response_text = "✅ *Бекап успешно создан!*\n\n"
                response_text += f"📁 *Описание:* {escape_markdown_v2(description)}\n"
                response_text += f"📊 *Размер:* {stats.get('total_size_bytes', 0):,} байт\n"
                response_text += f"📈 *Всего бекапов:* {stats.get('total_backups', 0)}\n"
                response_text += f"🗂️ *Файлов в бекапе:* {stats.get('total_files_backed_up', 0)}\n\n"
                response_text += f"💾 *Путь:* `{escape_markdown_v2(result)}`"
                
                await status_msg.edit_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await status_msg.edit_text(
                    escape_markdown_v2(f"❌ *Ошибка при создании бекапа:*\n\n{result}"),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                
        except Exception as e:
            logger.error(f"Ошибка при создании бекапа: {e}", exc_info=True)
            await status_msg.edit_text(
                escape_markdown_v2(f"❌ *Критическая ошибка при создании бекапа:*\n\n{str(e)}"),
                parse_mode=ParseMode.MARKDOWN_V2
            )
    
    async def list_backups_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда для просмотра списка доступных бекапов"""
        if not update.message or not update.effective_chat:
            return
        
        # Проверяем права администратора
        if not await is_user_admin_in_update(update, context):
            await update.message.reply_text(
                escape_markdown_v2("❌ У вас нет прав для выполнения этой команды. Требуются права администратора.")
            )
            return
        
        chat_id = update.effective_chat.id
        user = update.effective_user
        
        logger.info(f"Просмотр бекапов запрошен пользователем {user.id} ({user.full_name}) в чате {chat_id}")
        
        try:
            # Получаем список бекапов
            backups = self.backup_manager.list_backups()
            
            if not backups:
                await update.message.reply_text(
                    escape_markdown_v2("📭 Бекапы не найдены.\n\nИспользуйте `/backup` для создания первого бекапа.")
                )
                return
            
            # Формируем ответ
            response_text = "📋 *Доступные бекапы:*\n\n"
            
            for i, backup in enumerate(backups[:10], 1):  # Показываем только первые 10
                # Форматируем время
                from datetime import datetime
                created_time = datetime.fromisoformat(backup["created_at"])
                time_str = created_time.strftime("%d.%m.%Y %H:%M")
                
                # Форматируем размер
                size_mb = backup["size_bytes"] / (1024 * 1024)
                size_str = f"{size_mb:.1f} МБ"
                
                response_text += f"{i}\\. *{escape_markdown_v2(backup['name'])}*\n"
                response_text += f"   📅 {time_str}\n"
                response_text += f"   📊 {size_str} \\(файлов: {backup['files_count']}\\)\n"
                
                if backup["description"]:
                    response_text += f"   📝 {escape_markdown_v2(backup['description'])}\n"
                
                response_text += "\n"
            
            if len(backups) > 10:
                response_text += f"\\+ еще {len(backups) - 10} бекапов\\.\\.\\."
            
            response_text += "\n💡 *Команды:*\n"
            response_text += "• `/restore <имя>` \\- восстановить бекап\n"
            response_text += "• `/deletebackup <имя>` \\- удалить бекап\n"
            response_text += "• `/backupstats` \\- статистика бекапов"
            
            await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
            
        except Exception as e:
            logger.error(f"Ошибка при получении списка бекапов: {e}", exc_info=True)
            await update.message.reply_text(
                escape_markdown_v2(f"❌ Ошибка при получении списка бекапов: {str(e)}")
            )
    
    async def restore_backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда для восстановления системы из бекапа - ТОЛЬКО ДЛЯ СОЗДАТЕЛЯ!"""
        if not update.message or not update.effective_chat:
            return

        # КРИТИЧЕСКАЯ КОМАНДА: Только для создателя бота!
        user_id = update.effective_user.id if update.effective_user else None
        developer_id = self.app_config.global_settings.get("developer_notifications", {}).get("developer_user_id")

        if user_id != developer_id:
            await update.message.reply_text(
                escape_markdown_v2("❌ У вас нет прав для выполнения этой команды. Требуются права администратора.")
            )
            return
        
        if not context.args:
            await update.message.reply_text(
                escape_markdown_v2("❌ *Использование:* `/restore <имя_бекапа>`\n\n"
                                "Пример: `/restore auto_backup_20241201_143022`")
            )
            return
        
        chat_id = update.effective_chat.id
        user = update.effective_user
        backup_name = context.args[0]
        
        logger.info(f"Восстановление из бекапа {backup_name} запрошено пользователем {user.id} ({user.full_name}) в чате {chat_id}")
        
        # Отправляем сообщение о начале процесса
        status_msg = await update.message.reply_text(
            escape_markdown_v2(f"🔄 Восстановление из бекапа `{escape_markdown_v2(backup_name)}`...\n\n"
                            "⚠️ *ВНИМАНИЕ:* Это действие перезапишет текущие файлы!\\n"
                            "Пожалуйста, подождите.")
        )
        
        try:
            # Восстанавливаем из бекапа
            success, result = self.backup_manager.restore_backup(backup_name)
            
            if success:
                response_text = f"✅ *Восстановление успешно завершено!*\n\n"
                response_text += f"📁 *Бекап:* `{escape_markdown_v2(backup_name)}`\n"
                response_text += f"📊 *Результат:* {escape_markdown_v2(result)}\n\n"
                response_text += "🔄 *Рекомендуется перезапустить бота для применения изменений\\!*"
                
                await status_msg.edit_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await status_msg.edit_text(
                    escape_markdown_v2(f"❌ *Ошибка при восстановлении:*\n\n{result}"),
                    parse_mode=ParseMode.MARKDOWN_V2
                )
                
        except Exception as e:
            logger.error(f"Ошибка при восстановлении из бекапа: {e}", exc_info=True)
            await status_msg.edit_text(
                escape_markdown_v2(f"❌ *Критическая ошибка при восстановлении:*\n\n{str(e)}"),
                parse_mode=ParseMode.MARKDOWN_V2
            )
    
    async def delete_backup_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда для удаления бекапа - ТОЛЬКО ДЛЯ СОЗДАТЕЛЯ!"""
        if not update.message or not update.effective_chat:
            return

        # КРИТИЧЕСКАЯ КОМАНДА: Только для создателя бота!
        user_id = update.effective_user.id if update.effective_user else None
        developer_id = self.app_config.global_settings.get("developer_notifications", {}).get("developer_user_id")

        if user_id != developer_id:
            await update.message.reply_text(
                escape_markdown_v2("❌ У вас нет прав для выполнения этой команды. Требуются права администратора.")
            )
            return
        
        if not context.args:
            await update.message.reply_text(
                escape_markdown_v2("❌ *Использование:* `/deletebackup <имя_бекапа>`\n\n"
                                "Пример: `/deletebackup auto_backup_20241201_143022`")
            )
            return
        
        chat_id = update.effective_chat.id
        user = update.effective_user
        backup_name = context.args[0]
        
        logger.info(f"Удаление бекапа {backup_name} запрошено пользователем {user.id} ({user.full_name}) в чате {chat_id}")
        
        try:
            # Удаляем бекап
            success, result = self.backup_manager.delete_backup(backup_name)
            
            if success:
                await update.message.reply_text(
                    escape_markdown_v2(f"✅ {result}")
                )
            else:
                await update.message.reply_text(
                    escape_markdown_v2(f"❌ {result}")
                )
                
        except Exception as e:
            logger.error(f"Ошибка при удалении бекапа: {e}", exc_info=True)
            await update.message.reply_text(
                escape_markdown_v2(f"❌ Критическая ошибка при удалении бекапа: {str(e)}")
            )
    
    async def backup_stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Команда для просмотра статистики бекапов"""
        if not update.message or not update.effective_chat:
            return
        
        # Проверяем права администратора
        if not await is_user_admin_in_update(update, context):
            await update.message.reply_text(
                escape_markdown_v2("❌ У вас нет прав для выполнения этой команды. Требуются права администратора.")
            )
            return
        
        chat_id = update.effective_chat.id
        user = update.effective_user
        
        logger.info(f"Статистика бекапов запрошена пользователем {user.id} ({user.full_name}) в чате {chat_id}")
        
        try:
            # Получаем статистику
            stats = self.backup_manager.get_backup_stats()
            
            if not stats:
                await update.message.reply_text(
                    escape_markdown_v2("📊 Статистика бекапов недоступна.")
                )
                return
            
            # Форматируем размеры
            total_size_mb = stats.get('total_size_bytes', 0) / (1024 * 1024)
            dir_size_mb = stats.get('backup_dir_size_bytes', 0) / (1024 * 1024)
            
            response_text = "📊 *Статистика бекапов:*\n\n"
            response_text += f"📁 *Всего бекапов:* {stats.get('total_backups', 0)}\n"
            response_text += f"💾 *Общий размер данных:* {total_size_mb:.1f} МБ\n"
            response_text += f"🗂️ *Размер директории:* {dir_size_mb:.1f} МБ\n"
            response_text += f"📄 *Всего файлов:* {stats.get('total_files_backed_up', 0)}\n"
            response_text += f"🔢 *Максимум бекапов:* {stats.get('max_backups', 10)}\n\n"
            
            if stats.get('oldest_backup'):
                from datetime import datetime
                oldest = datetime.fromisoformat(stats['oldest_backup'])
                oldest_str = oldest.strftime("%d.%m.%Y %H:%M")
                response_text += f"📅 *Самый старый:* {oldest_str}\n"
            
            if stats.get('newest_backup'):
                newest = datetime.fromisoformat(stats['newest_backup'])
                newest_str = newest.strftime("%d.%m.%Y %H:%M")
                response_text += f"📅 *Самый новый:* {newest_str}\n"
            
            response_text += "\n💡 *Команды:*\n"
            response_text += "• `/backup` \\- создать бекап\n"
            response_text += "• `/backups` \\- список бекапов\n"
            response_text += "• `/restore <имя>` \\- восстановить\n"
            response_text += "• `/deletebackup <имя>` \\- удалить"
            
            await update.message.reply_text(response_text, parse_mode=ParseMode.MARKDOWN_V2)
            
        except Exception as e:
            logger.error(f"Ошибка при получении статистики бекапов: {e}", exc_info=True)
            await update.message.reply_text(
                escape_markdown_v2(f"❌ Ошибка при получении статистики бекапов: {str(e)}")
            )
