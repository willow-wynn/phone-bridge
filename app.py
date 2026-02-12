import asyncio
import logging
import os
import queue
import tempfile
import time

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from config import Config
from session_store import SessionStore
from claude_runner import ClaudeRunner, ToolEvent
from message_sender import MessageSender

Config.validate()

logger = logging.getLogger("phone-bridge")

store = SessionStore(Config.DB_PATH)
runner = ClaudeRunner(
    working_dir=Config.CLAUDE_WORKING_DIR,
    allowed_tools=Config.CLAUDE_ALLOWED_TOOLS,
    max_timeout=Config.CLAUDE_MAX_TIMEOUT,
    max_budget_usd=Config.CLAUDE_MAX_BUDGET_USD,
    system_prompt=Config.CLAUDE_SYSTEM_PROMPT,
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
        "/cost — Show cumulative session cost\n"
        "/prompt — View or set system prompt\n"
        "/help — Show this message\n\n"
        "You can also send photos and files.\n"
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


async def cmd_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return
    total = store.get_cost(str(user_id))
    info = store.list_sessions()
    entry = next((s for s in info if s["phone_number"] == str(user_id)), None)
    msg_count = entry["message_count"] if entry else 0
    await update.message.reply_text(
        f"Session cost: ${total:.4f}\n"
        f"Messages: {msg_count}\n"
        f"Avg per message: ${total / msg_count:.4f}" if msg_count > 0 else f"Session cost: ${total:.4f}\nNo messages yet."
    )


async def cmd_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return
    text = (update.message.text or "").replace("/prompt", "", 1).strip()
    if not text:
        current = runner.system_prompt or "(none)"
        await update.message.reply_text(f"Current system prompt:\n{current}\n\nUsage: /prompt <your prompt>")
        return
    runner.system_prompt = text
    await update.message.reply_text(f"System prompt updated:\n{text}")


async def cmd_more(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        return
    sender: MessageSender = context.bot_data["sender"]
    if sender.has_overflow(user_id):
        await sender.send_more(user_id)
    else:
        await update.message.reply_text("No more content to send.")


async def _download_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Download a photo or document from the message. Returns the local path or None."""
    msg = update.message

    if msg.photo:
        # Get the highest-resolution photo
        photo = msg.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        ext = ".jpg"
    elif msg.document:
        file = await context.bot.get_file(msg.document.file_id)
        name = msg.document.file_name or "file"
        ext = os.path.splitext(name)[1] or ""
    else:
        return None

    tmp_dir = os.path.join(tempfile.gettempdir(), "phone-bridge")
    os.makedirs(tmp_dir, exist_ok=True)
    local_path = os.path.join(tmp_dir, f"{file.file_unique_id}{ext}")
    await file.download_to_drive(local_path)
    logger.info(f"Downloaded file to {local_path}")
    return local_path


def _format_status(elapsed: int, tool_calls: list[str]) -> str:
    """Format the live status message showing elapsed time and recent tool calls."""
    lines = [f"Working... ({elapsed}s)"]
    if tool_calls:
        # Show last 5 tool calls
        recent = tool_calls[-5:]
        for i, tc in enumerate(recent):
            prefix = ">" if i == len(recent) - 1 else " "
            lines.append(f"{prefix} {tc}")
    return "\n".join(lines)


async def _process_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    body: str,
    file_paths: list[str] | None = None,
):
    """Core message processing: stream Claude tool calls live, then send reply."""
    user_id = update.effective_user.id
    sender: MessageSender = context.bot_data["sender"]

    lock = _get_user_lock(user_id)
    async with lock:
        try:
            session_id = store.get_session(str(user_id))

            status_msg = await context.bot.send_message(
                chat_id=user_id, text="Working..."
            )
            start_time = time.monotonic()
            done_event = asyncio.Event()
            event_queue: queue.Queue[ToolEvent] = queue.Queue()
            tool_calls: list[str] = []
            last_status_text = ""

            async def update_status():
                """Poll the event queue and update the status message with tool calls."""
                nonlocal last_status_text
                while not done_event.is_set():
                    # Drain all pending events
                    while True:
                        try:
                            evt = event_queue.get_nowait()
                            tool_calls.append(evt.summary)
                        except queue.Empty:
                            break

                    elapsed = int(time.monotonic() - start_time)
                    new_text = _format_status(elapsed, tool_calls)

                    if new_text != last_status_text:
                        try:
                            await status_msg.edit_text(new_text)
                            last_status_text = new_text
                        except Exception:
                            pass

                    try:
                        await asyncio.wait_for(done_event.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        pass

            async def keep_typing():
                while not done_event.is_set():
                    try:
                        await context.bot.send_chat_action(chat_id=user_id, action="typing")
                    except Exception:
                        pass
                    try:
                        await asyncio.wait_for(done_event.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        pass

            status_task = asyncio.create_task(update_status())
            typing_task = asyncio.create_task(keep_typing())

            try:
                result = await asyncio.to_thread(
                    runner.run_streaming,
                    prompt=body,
                    session_id=session_id,
                    file_paths=file_paths,
                    event_queue=event_queue,
                )
            finally:
                done_event.set()
                await status_task
                await typing_task

            # Delete the status message
            try:
                await status_msg.delete()
            except Exception:
                pass

            store.save_session(str(user_id), result.session_id, Config.CLAUDE_WORKING_DIR, result.cost_usd)

            text = result.text
            elapsed = round(time.monotonic() - start_time, 1)
            if result.cost_usd > 0:
                text += f"\n\n[${result.cost_usd:.4f} | {elapsed}s | {len(result.tool_calls)} tool calls]"

            await sender.send(user_id, text)

        except Exception:
            logger.exception(f"Error processing message from {user_id}")
            try:
                await update.message.reply_text(
                    "Something went wrong processing your message. Check server logs."
                )
            except Exception:
                logger.exception("Failed to send error reply")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    body = (update.message.text or "").strip()

    if not _is_allowed(user_id):
        logger.warning(f"Blocked message from user {user_id}")
        return

    logger.info(f"Message from {user_id}: {body[:80]!r}")
    await _process_message(update, context, body)


async def handle_photo_or_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_allowed(user_id):
        logger.warning(f"Blocked file from user {user_id}")
        return

    caption = (update.message.caption or "").strip()
    file_path = await _download_file(update, context)
    if not file_path:
        await update.message.reply_text("Unsupported file type.")
        return

    # Build prompt: include caption if provided, and tell Claude about the file
    if caption:
        body = f"{caption}\n\n[Attached file: {file_path}]"
    else:
        body = f"I've sent you a file. Please look at it and describe what you see.\n\n[Attached file: {file_path}]"

    logger.info(f"File from {user_id}: {file_path} caption={caption[:80]!r}")
    await _process_message(update, context, body, file_paths=[file_path])


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
    app.add_handler(CommandHandler("cost", cmd_cost))
    app.add_handler(CommandHandler("prompt", cmd_prompt))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_photo_or_document))

    logger.info("Starting Telegram bot (polling)...")
    app.run_polling()


if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())
    main()
