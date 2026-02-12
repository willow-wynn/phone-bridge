import logging

from telegram import Bot
from telegram.constants import MessageLimit

logger = logging.getLogger("phone-bridge.sender")

TELEGRAM_MAX = MessageLimit.MAX_TEXT_LENGTH  # 4096
TRUNCATE_THRESHOLD = 16000


class MessageSender:
    def __init__(self, bot: Bot):
        self.bot = bot
        self._overflow: dict[int, str] = {}

    async def send(self, chat_id: int, text: str):
        """Send a message, splitting or truncating if needed."""
        chunks = self._prepare_chunks(chat_id, text)
        for chunk in chunks:
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
