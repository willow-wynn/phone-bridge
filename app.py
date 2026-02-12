import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import Config
from session_store import SessionStore
from claude_runner import ClaudeRunner
from message_sender import MessageSender

Config.validate()

logger = logging.getLogger("phone-bridge")

store = SessionStore(Config.DB_PATH)
runner = ClaudeRunner(
    working_dir=Config.CLAUDE_WORKING_DIR,
    allowed_tools=Config.CLAUDE_ALLOWED_TOOLS,
    max_timeout=Config.CLAUDE_MAX_TIMEOUT,
    max_budget_usd=Config.CLAUDE_MAX_BUDGET_USD,
)

# Per-user locks to serialize concurrent messages
_user_locks: dict[int, asyncio.Lock] = {}


def _get_user_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _user_locks:
        _user_locks[user_id] = asyncio.Lock()
    return _user_locks[user_id]


def _is_allowed(user_id: int) -> bool:
    # If no allowlist configured, allow anyone (but log a warning)
    if not Config.ALLOWED_USERS:
        return True
    return user_id in Config.ALLOWED_USERS


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    logger.info(f"/start from user {user.id} ({user.username})")
    await update.message.reply_text(
        f"Phone Bridge is running.\n\n"
        f"Your user ID: {user.id}\n"
        f"Add this to ALLOWED_USERS in .env to lock down access.\n\n"
        f"Send any message to talk to Claude Code.\n"
        f"Commands: /reset /status /more /help"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "Commands:\n"
        "/reset — Start a new session\n"
        "/status — Show current session info\n"
        "/more — Get truncated content\n"
        "/help — Show this message\n\n"
        "Anything else is sent to Claude Code."
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return
    store.reset_session(str(user_id))
    await update.message.reply_text("Session reset. Next message starts a fresh conversation.")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return
    session_id = store.get_session(str(user_id))
    info = store.list_sessions()
    entry = next((s for s in info if s["phone_number"] == str(user_id)), None)
    lines = [
        f"Session: {session_id or 'none'}",
        f"Dir: {Config.CLAUDE_WORKING_DIR}",
        f"Tools: {Config.CLAUDE_ALLOWED_TOOLS}",
    ]
    if entry:
        lines.append(f"Messages: {entry['message_count']}")
        lines.append(f"Last used: {entry['last_used_at']}")
    await update.message.reply_text("\n".join(lines))


async def cmd_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return
    sender: MessageSender = context.bot_data["sender"]
    if sender.has_overflow(user_id):
        await sender.send_more(user_id)
    else:
        await update.message.reply_text("No more content to send.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    body = update.message.text.strip()

    if not _is_allowed(user_id):
        logger.warning(f"Blocked message from user {user_id}")
        return

    logger.info(f"Message from {user_id}: {body[:80]!r}")
    sender: MessageSender = context.bot_data["sender"]

    lock = _get_user_lock(user_id)
    async with lock:
        try:
            session_id = store.get_session(str(user_id))

            # Run Claude in a thread to avoid blocking the event loop
            result = await asyncio.to_thread(runner.run, prompt=body, session_id=session_id)

            store.save_session(str(user_id), result.session_id, Config.CLAUDE_WORKING_DIR)

            text = result.text
            if result.cost_usd > 0:
                text += f"\n\n[${result.cost_usd:.4f} | {result.duration_ms / 1000:.1f}s]"

            await sender.send(user_id, text)

        except Exception:
            logger.exception(f"Error processing message from {user_id}")
            try:
                await update.message.reply_text(
                    "Something went wrong processing your message. Check server logs."
                )
            except Exception:
                logger.exception("Failed to send error reply")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info(f"Claude working dir: {Config.CLAUDE_WORKING_DIR}")
    logger.info(f"Allowed tools: {Config.CLAUDE_ALLOWED_TOOLS}")
    if Config.ALLOWED_USERS:
        logger.info(f"Allowed users: {Config.ALLOWED_USERS}")
    else:
        logger.warning("No ALLOWED_USERS set — anyone can message the bot!")

    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()

    # Store sender in bot_data so handlers can access it
    sender = MessageSender(app.bot)
    app.bot_data["sender"] = sender

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("more", cmd_more))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting Telegram bot (polling)...")
    app.run_polling()


if __name__ == "__main__":
    main()
