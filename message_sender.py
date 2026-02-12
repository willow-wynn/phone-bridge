import html
import logging
import re

from telegram import Bot
from telegram.constants import MessageLimit

logger = logging.getLogger("phone-bridge.sender")

TELEGRAM_MAX = MessageLimit.MAX_TEXT_LENGTH  # 4096
TRUNCATE_THRESHOLD = 16000


def markdown_to_telegram_html(text: str) -> str:
    """Convert Claude's Markdown to Telegram-compatible HTML.

    Handles fenced code blocks, inline code, bold, italic, and strikethrough.
    Anything not inside a code block gets HTML-escaped first so raw < > & are safe.
    """
    parts: list[str] = []
    # Split on fenced code blocks (``` ... ```)
    segments = re.split(r"(```(?:\w*)\n[\s\S]*?```)", text)

    for segment in segments:
        m = re.match(r"```(\w*)\n([\s\S]*?)```", segment)
        if m:
            lang = m.group(1)
            code = html.escape(m.group(2).rstrip("\n"))
            if lang:
                parts.append(f'<pre><code class="language-{lang}">{code}</code></pre>')
            else:
                parts.append(f"<pre>{code}</pre>")
        else:
            # Escape HTML entities first
            s = html.escape(segment)
            # Inline code
            s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
            # Bold (**text** or __text__)
            s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
            s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
            # Italic (*text* or _text_) — careful not to match inside words with underscores
            s = re.sub(r"(?<!\w)\*(?!\*)(.+?)(?<!\*)\*(?!\w)", r"<i>\1</i>", s)
            s = re.sub(r"(?<!\w)_(?!_)(.+?)(?<!_)_(?!\w)", r"<i>\1</i>", s)
            # Strikethrough
            s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
            parts.append(s)

    return "".join(parts)


class MessageSender:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._overflow: dict[int, str] = {}

    async def send(self, chat_id: int, text: str):
        """Send a message, splitting or truncating if needed.

        Converts Markdown to Telegram HTML. Falls back to plain text if
        Telegram rejects the markup.
        """
        chunks = self._prepare_chunks(chat_id, text)
        for chunk in chunks:
            html_chunk = markdown_to_telegram_html(chunk)
            try:
                await self.bot.send_message(
                    chat_id=chat_id, text=html_chunk, parse_mode="HTML",
                )
            except Exception:
                # Fallback: send as plain text if HTML parsing fails
                await self.bot.send_message(chat_id=chat_id, text=chunk)

    async def send_more(self, chat_id: int) -> bool:
        """Send the next batch of overflow text."""
        overflow = self._overflow.pop(chat_id, None)
        if not overflow:
            return False
        await self.send(chat_id, overflow)
        return True

    def has_overflow(self, chat_id: int) -> bool:
        return chat_id in self._overflow

    def _prepare_chunks(self, chat_id: int, text: str) -> list[str]:
        if len(text) <= TELEGRAM_MAX:
            return [text]

        if len(text) > TRUNCATE_THRESHOLD:
            cut = self._find_break(text, TRUNCATE_THRESHOLD)
            self._overflow[chat_id] = text[cut:]
            text = text[:cut].rstrip() + "\n\n[Truncated — send /more for the rest]"

        return self._split(text)

    def _split(self, text: str) -> list[str]:
        if len(text) <= TELEGRAM_MAX:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= TELEGRAM_MAX:
                chunks.append(remaining)
                break

            cut = self._find_break(remaining, TELEGRAM_MAX)
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()

        if len(chunks) > 1:
            total = len(chunks)
            chunks = [f"[{i + 1}/{total}] {chunk}" for i, chunk in enumerate(chunks)]

        return chunks

    def _find_break(self, text: str, max_pos: int) -> int:
        for delimiter in ["\n\n", "\n", ". ", " "]:
            pos = text.rfind(delimiter, 0, max_pos)
            if pos > max_pos // 2:
                return pos + len(delimiter)
        return max_pos
