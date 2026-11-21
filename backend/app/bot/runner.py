"""Telegram glue: long polling in a background thread. Only starts when NOTIFIER=telegram.

Anyone can message a Telegram bot, so: private chats only, `/link CODE` (from the app's Settings) ties a
chat to an account, and every other message is answered only for a linked chat, as that account."""
import asyncio
import logging
import threading

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.bot import logic
from app.config import settings
from app.db import SessionLocal
from app.services.records import MAX_UPLOAD

log = logging.getLogger("bot")
LINK_ATTEMPTS, LINK_WINDOW, link_allowed = logic.LINK_ATTEMPTS, logic.LINK_WINDOW, logic.link_allowed


def _markup(reply: logic.Reply) -> InlineKeyboardMarkup | None:
    if not reply.buttons:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=cb)] for label, cb in reply.buttons])


async def _send(update: Update, reply: logic.Reply) -> None:
    await update.effective_message.reply_text(reply.text, reply_markup=_markup(reply))


def build_application(token: str) -> Application:
    # private chats only: in a group, every member would be able to drive the bot
    private = filters.ChatType.PRIVATE
    app = Application.builder().token(token).build()

    def as_user(fn):
        """Run fn(db, user, update) for a linked chat; tell unlinked chats how to link."""
        async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            with SessionLocal() as db:
                user = logic.user_for_chat(db, update.effective_chat.id)
                if not user:
                    await _send(update, logic.Reply(logic.NOT_LINKED))
                    return
                reply = await fn(db, user, update)
            if reply:
                await _send(update, reply)
        return handler

    async def on_text(db, user, update: Update):
        return logic.handle_text(db, user, update.effective_message.text or "")

    async def on_file(db, user, update: Update):
        msg = update.effective_message
        if msg.photo:
            tg_file, name = await msg.photo[-1].get_file(), "photo.jpg"
        else:
            if (msg.document.file_size or 0) > MAX_UPLOAD:
                return logic.Reply("That file is over 20 MB.")
            tg_file, name = await msg.document.get_file(), msg.document.file_name or "receipt"
        data = bytes(await tg_file.download_as_bytearray())
        return logic.handle_attachment(db, user, name, data)

    def command(fn):
        async def run(db, user, update: Update):
            return fn(db, user)
        return as_user(run)

    async def on_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if not ctx.args:
            await _send(update, logic.Reply("Send /link followed by the code from the app's Settings → Chat apps."))
            return
        if not link_allowed(chat_id):
            await _send(update, logic.Reply("Too many tries. Wait a few minutes and get a fresh code."))
            return
        with SessionLocal() as db:
            await _send(update, logic.cmd_link(db, chat_id, ctx.args[0]))

    async def on_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        with SessionLocal() as db:
            user = logic.user_for_chat(db, update.effective_chat.id)
            await _send(update, logic.cmd_help(db, user) if user else logic.Reply(logic.NOT_LINKED))

    async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if q.message.chat.type != "private":
            return
        with SessionLocal() as db:
            user = logic.user_for_chat(db, q.message.chat.id)
            if not user:
                return
            reply = logic.handle_callback(db, user, q.data or "")
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(reply.text, reply_markup=_markup(reply))

    app.add_handler(CommandHandler("link", on_link, filters=private))
    app.add_handler(CommandHandler(["help", "start"], on_start, filters=private))
    app.add_handler(CommandHandler("due", command(logic.cmd_due), filters=private))
    app.add_handler(CommandHandler("vehicles", command(logic.cmd_vehicles), filters=private))
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, as_user(on_text)))
    app.add_handler(MessageHandler(private & (filters.PHOTO | filters.Document.ALL), as_user(on_file)))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app


class BotThread(threading.Thread):
    def __init__(self, token: str) -> None:
        super().__init__(daemon=True, name="telegram-bot")
        self.token = token
        self.loop: asyncio.AbstractEventLoop | None = None
        self.app: Application | None = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.app = build_application(self.token)
        try:
            self.app.run_polling(stop_signals=None, close_loop=False, bootstrap_retries=-1)
        except Exception:  # noqa: BLE001
            log.exception("Telegram bot stopped")

    def stop(self) -> None:
        if self.loop and self.app and self.app.running:
            self.loop.call_soon_threadsafe(self.app.stop_running)


def start() -> BotThread | None:
    if not settings.live_notifications or not settings.telegram_bot_token:
        log.info("Telegram bot disabled (NOTIFIER=%s)", settings.notifier)
        return None
    t = BotThread(settings.telegram_bot_token)
    t.start()
    return t
