"""Discord glue: a gateway connection in a background thread. Starts when DISCORD_BOT_TOKEN is set.

Anyone can DM a bot, so it is the same deal as Telegram: direct messages only (server channels are ignored),
`!link CODE` (from the app's Settings) ties a Discord account to a tracker account, and every other message is
answered only for a linked account, as that account. DISCORD_ALLOWED_USER_IDS, when set, makes the bot ignore
everyone else entirely."""
import asyncio
import logging
import threading

import discord

from app.bot import logic
from app.config import settings
from app.db import SessionLocal
from app.notify.factory import allowed_discord_ids
from app.services.records import MAX_UPLOAD

log = logging.getLogger("bot.discord")
CHANNEL = "discord"
PREFIXES = ("!", "/")


def _view(reply: logic.Reply) -> discord.ui.View | None:
    if not reply.buttons:
        return None
    # The clicks are handled in on_interaction (the same callback strings as on Telegram), so the view only
    # draws the buttons; a short timeout drops it from discord.py's memory, the buttons keep working.
    view = discord.ui.View(timeout=1)
    for label, cb in reply.buttons[:25]:
        view.add_item(discord.ui.Button(label=label[:80], custom_id=cb, style=discord.ButtonStyle.secondary))
    return view


async def _send(channel: discord.abc.Messageable, reply: logic.Reply) -> None:
    view = _view(reply)
    if view:
        await channel.send(reply.text[:2000], view=view)
    else:
        await channel.send(reply.text[:2000])


def parse_command(text: str) -> tuple[str, list[str]] | None:
    """'!link abc' -> ('link', ['abc']). None for plain text such as a km reading."""
    text = text.strip()
    if not text.startswith(PREFIXES):
        return None
    parts = text[1:].split()
    if not parts:
        return "", []
    return parts[0].lower(), parts[1:]


def allowed(user_id: int) -> bool:
    ids = allowed_discord_ids()
    return not ids or user_id in ids


def reply_for_message(db, user_id: int, text: str) -> logic.Reply | None:
    """Everything except attachments, without any Discord objects (so it can be tested)."""
    cmd = parse_command(text)
    if cmd and cmd[0] == "link":
        if not cmd[1]:
            return logic.Reply("Send !link followed by the code from the app's Settings → Chat apps.")
        if not logic.link_allowed(f"{CHANNEL}:{user_id}"):
            return logic.Reply("Too many tries. Wait a few minutes and get a fresh code.")
        return logic.cmd_link(db, user_id, cmd[1][0], CHANNEL)
    user = logic.user_for(db, CHANNEL, user_id)
    if not user:
        return logic.Reply(logic.NOT_LINKED.replace("the link command", "the !link command"))
    if cmd:
        if cmd[0] in ("help", "start"):
            return logic.Reply(logic.help_text(CHANNEL))
        if cmd[0] == "due":
            return logic.cmd_due(db, user)
        if cmd[0] == "vehicles":
            return logic.cmd_vehicles(db, user)
        return logic.Reply(f"I don't know that command.\n\n{logic.help_text(CHANNEL)}")
    return logic.handle_text(db, user, text, channel=CHANNEL)


def build_client() -> discord.Client:
    intents = discord.Intents.none()
    intents.dm_messages = True  # DM text arrives without the privileged message-content intent
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log.info("Discord bot connected as %s", client.user)

    @client.event
    async def on_message(msg: discord.Message):
        if msg.author.bot or msg.guild is not None or not allowed(msg.author.id):
            return
        try:
            if msg.attachments:
                reply = await _attachment_reply(msg)
            else:
                with SessionLocal() as db:
                    reply = reply_for_message(db, msg.author.id, msg.content or "")
        except Exception:  # noqa: BLE001 - one bad message must not take the bot down
            log.exception("Discord message failed")
            reply = logic.Reply("Something went wrong with that. Try again, or use the app.")
        if reply:
            await _send(msg.channel, reply)

    @client.event
    async def on_interaction(interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component or interaction.guild is not None:
            return
        if not allowed(interaction.user.id):
            return
        data = (interaction.data or {}).get("custom_id", "")
        try:
            with SessionLocal() as db:
                user = logic.user_for(db, CHANNEL, interaction.user.id)
                reply = (logic.handle_callback(db, user, data, channel=CHANNEL) if user
                         else logic.Reply(logic.NOT_LINKED.replace("the link command", "the !link command")))
        except Exception:  # noqa: BLE001
            log.exception("Discord button failed")
            reply = logic.Reply("That didn't work. Try again, or use the app.")
        await interaction.response.edit_message(view=None)  # a button works once, as on Telegram
        view = _view(reply)
        if view:
            await interaction.followup.send(reply.text[:2000], view=view)
        else:
            await interaction.followup.send(reply.text[:2000])

    return client


async def _attachment_reply(msg: discord.Message) -> logic.Reply:
    """Download first, then open the database, so no transaction is held during a 20 MB download."""
    with SessionLocal() as db:
        linked = logic.user_for(db, CHANNEL, msg.author.id) is not None
    if not linked:
        return logic.Reply(logic.NOT_LINKED.replace("the link command", "the !link command"))
    att = msg.attachments[0]
    if att.size > MAX_UPLOAD:
        return logic.Reply("That file is over 20 MB.")
    data = await att.read()
    with SessionLocal() as db:
        user = logic.user_for(db, CHANNEL, msg.author.id)
        if not user:
            return logic.Reply(logic.NOT_LINKED)
        return logic.handle_attachment(db, user, att.filename or "receipt", data, channel=CHANNEL)


class DiscordThread(threading.Thread):
    def __init__(self, token: str) -> None:
        super().__init__(daemon=True, name="discord-bot")
        self.token = token
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client: discord.Client | None = None

    def run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.client = build_client()
        try:
            # discord.py reconnects on its own after network drops
            self.loop.run_until_complete(self.client.start(self.token))
        except Exception:  # noqa: BLE001
            log.exception("Discord bot stopped")

    def stop(self) -> None:
        if self.loop and self.client and not self.client.is_closed():
            asyncio.run_coroutine_threadsafe(self.client.close(), self.loop)


def start() -> DiscordThread | None:
    if not settings.live_notifications or not settings.discord_bot_token:
        log.info("Discord bot disabled")
        return None
    t = DiscordThread(settings.discord_bot_token)
    t.start()
    return t
