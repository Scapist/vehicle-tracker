"""Telegram glue: long polling in a background thread. Only starts when NOTIFIER=telegram."""
import asyncio
import logging
import threading

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.bot import logic
from app.config import settings
from app.db import SessionLocal
from app.notify.factory import allowed_chat_ids

log = logging.getLogger("bot")


def _markup(reply: logic.Reply) -> InlineKeyboardMarkup | None:
    if not reply.buttons:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=cb)] for label, cb in reply.buttons])


async def _send(update: Update, reply: logic.Reply) -> None:
    await update.effective_message.reply_text(reply.text, reply_markup=_markup(reply))


def build_application(token: str, chat_ids: list[int]) -> Application:
    only_me = filters.Chat(chat_id=chat_ids)
    app = Application.builder().token(token).build()

    async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        with SessionLocal() as db:
            await _send(update, logic.handle_text(db, update.effective_message.text or ""))

    async def on_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        if msg.photo:
            tg_file, name = await msg.photo[-1].get_file(), "photo.jpg"
        else:
            tg_file, name = await msg.document.get_file(), msg.document.file_name or "receipt"
        data = bytes(await tg_file.download_as_bytearray())
        with SessionLocal() as db:
            await _send(update, logic.handle_attachment(db, name, data))

    async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if q.message.chat.id not in chat_ids:
            return
        with SessionLocal() as db:
            reply = logic.handle_callback(db, q.data or "")
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(reply.text, reply_markup=_markup(reply))

    def command(fn):
        async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            with SessionLocal() as db:
                await _send(update, fn(db))
        return handler

    app.add_handler(CommandHandler("due", command(logic.cmd_due), filters=only_me))
    app.add_handler(CommandHandler("vehicles", command(logic.cmd_vehicles), filters=only_me))
    app.add_handler(CommandHandler(["help", "start"], command(logic.cmd_help), filters=only_me))
    app.add_handler(MessageHandler(only_me & filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(MessageHandler(only_me & (filters.PHOTO | filters.Document.ALL), on_file))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app


class BotThread(threading.Thread):
    def __init__(self, token: str, chat_ids: list[int]) -> None:
        super().__init__(daemon=True, name="telegram-bot")
        self.token, self.chat_ids = token, chat_ids
        self.loop: asyncio.AbstractEventLoop | None = None
        self.app: Application | None = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.app = build_application(self.token, self.chat_ids)
        try:
            self.app.run_polling(stop_signals=None, close_loop=False, bootstrap_retries=-1)
        except Exception:  # noqa: BLE001
            log.exception("Telegram bot stopped")

    def stop(self) -> None:
        if self.loop and self.app and self.app.running:
            self.loop.call_soon_threadsafe(self.app.stop_running)


def start() -> BotThread | None:
    ids = allowed_chat_ids()
    if settings.notifier != "telegram" or not settings.telegram_bot_token or not ids:
        log.info("Telegram bot disabled (NOTIFIER=%s)", settings.notifier)
        return None
    t = BotThread(settings.telegram_bot_token, ids)
    t.start()
    return t
