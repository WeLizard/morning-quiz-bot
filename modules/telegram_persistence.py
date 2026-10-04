"""Keep Telegram conversation UI state separate from PostgreSQL domain state."""

from telegram.ext import DictPersistence, PersistenceInput, PicklePersistence


def build_telegram_persistence(filepath, *, postgres=False):
    if not postgres:
        return PicklePersistence(filepath=filepath)
    # PostgreSQL owns every durable user/game value. Telegram ConversationHandler
    # state is merely a resumable menu cursor, so losing it on restart only sends
    # the user back to the menu; it must not create another mutable file store.
    return DictPersistence(store_data=PersistenceInput(bot_data=False))
