"""Owner-only dev backup commands. No archive download or in-place restore via chat."""
import asyncio

from telegram.ext import CommandHandler

from storage import dev_backups


class PostgresBackupHandlers:
    def __init__(self, app_config):
        self.app_config = app_config

    def get_handlers(self):
        return [CommandHandler(command, self.dispatch) for command in ('backup', 'backups', 'restore', 'deletebackup', 'backupstats')]

    async def dispatch(self, update, context):
        if not update.effective_message or not update.effective_user:
            return
        owner = self.app_config.global_settings.get('developer_notifications', {}).get('developer_user_id')
        if update.effective_user.id != owner:
            await update.effective_message.reply_text('Управление копиями доступно только владельцу бота или через закрытую локальную панель.', parse_mode=None)
            return
        storage = getattr(context.bot_data.get('data_manager'), 'postgres_storage', None)
        if not storage:
            return
        command = (update.effective_message.text or '').split()[0].split('@')[0]
        args = context.args or []
        try:
            await asyncio.to_thread(dev_backups.guard, storage.database)
            if command == '/backup':
                snapshot = await dev_backups.create(storage.database)
                text = f"Dev-копия создана: {snapshot['id']}. Проверка: /restore {snapshot['id']}. Сам архив доступен только в локальной панели."
            elif command in {'/backups', '/backupstats'}:
                items = await asyncio.to_thread(dev_backups.listing)
                text = f"Dev-копий: {len(items)}; размер: {sum(i.get('bytes', 0) for i in items) / 1048576:.2f} МиБ."
                if command == '/backups':
                    text += '\n' + '\n'.join(f"{i['id']} · {i.get('created_at', 'повреждён')}" for i in items[:20])
            elif command == '/restore':
                if len(args) != 1:
                    text = 'Использование: /restore ID — проверка восстановления в отдельную временную БД. Рабочая dev-БД не меняется; полное восстановление доступно только через PowerShell.'
                else:
                    result = await dev_backups.verify_restore(storage.database, args[0])
                    text = f"Проверено восстановление {result['tables']} таблиц. Рабочая dev-БД не менялась."
            else:
                if len(args) != 2 or args[1] != 'подтверждаю':
                    text = 'Использование: /deletebackup ID подтверждаю. Только выбранный dev-архив будет перемещён в корзину.'
                else:
                    await asyncio.to_thread(dev_backups.trash, args[0])
                    text = 'Выбранный архив перенесён в .local/dev-backups/trash. Его можно вернуть.'
        except (ValueError, LookupError) as error:
            text = str(error)
        except Exception:
            text = 'Операция локальной dev-копии не завершена. Подробную проверку выполните в закрытой панели; JSON fallback не запускается.'
        await update.effective_message.reply_text(text, parse_mode=None)
