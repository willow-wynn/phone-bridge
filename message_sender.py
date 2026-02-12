import logging
import time

from twilio.rest import Client

logger = logging.getLogger("phone-bridge.sender")

WHATSAPP_MAX = 4000  # WhatsApp limit is 4096, leave margin
TRUNCATE_THRESHOLD = 16000  # Beyond this, truncate and offer /more
SEND_DELAY = 0.5  # Seconds between multi-part messages


class MessageSender:
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        self.client = Client(account_sid, auth_token)
        self.from_number = from_number
        # Store truncated remainders keyed by phone number
        self._overflow: dict[str, str] = {}

    def send(self, to_number: str, text: str):
        """Send a message, splitting or truncating if needed."""
        to_number = self._normalize_to(to_number)
        chunks = self._prepare_chunks(to_number, text)

        for i, chunk in enumerate(chunks):
            if i > 0:
                time.sleep(SEND_DELAY)
            self._send_one(to_number, chunk)

    def send_more(self, to_number: str) -> bool:
        """Send the next batch of overflow text. Returns True if there was overflow to send."""
        to_number = self._normalize_to(to_number)
        overflow = self._overflow.pop(to_number, None)
        if not overflow:
            return False
        self.send(to_number, overflow)
        return True

    def has_overflow(self, to_number: str) -> bool:
        to_number = self._normalize_to(to_number)
        return to_number in self._overflow

    def _prepare_chunks(self, to_number: str, text: str) -> list[str]:
        # If short enough, send as-is
        if len(text) <= WHATSAPP_MAX:
            return [text]

        # If very long, truncate and store overflow
        if len(text) > TRUNCATE_THRESHOLD:
            # Find a clean break point near the threshold
            cut = self._find_break(text, TRUNCATE_THRESHOLD)
            self._overflow[to_number] = text[cut:]
            text = text[:cut].rstrip() + "\n\n[Truncated — send /more for the rest]"

        # Split into WhatsApp-sized chunks
        return self._split(text)

    def _split(self, text: str) -> list[str]:
        if len(text) <= WHATSAPP_MAX:
            return [text]

        chunks: list[str] = []
        remaining = text

        while remaining:
            if len(remaining) <= WHATSAPP_MAX:
                chunks.append(remaining)
                break

            cut = self._find_break(remaining, WHATSAPP_MAX)
            chunks.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()

        if len(chunks) > 1:
            total = len(chunks)
            chunks = [f"[{i + 1}/{total}] {chunk}" for i, chunk in enumerate(chunks)]

        return chunks

    def _find_break(self, text: str, max_pos: int) -> int:
        """Find the best position to split text at or before max_pos."""
        for delimiter in ["\n\n", "\n", ". ", " "]:
            pos = text.rfind(delimiter, 0, max_pos)
            if pos > max_pos // 2:
                return pos + len(delimiter)
        # No good break found, hard cut
        return max_pos

    def _send_one(self, to_number: str, body: str):
        logger.info(f"Sending {len(body)} chars to {to_number}")
        self.client.messages.create(
            body=body,
            from_=self.from_number,
            to=to_number,
        )

    def _normalize_to(self, to_number: str) -> str:
        """Ensure WhatsApp prefix matches from_number format."""
        if self.from_number.startswith("whatsapp:") and not to_number.startswith("whatsapp:"):
            return f"whatsapp:{to_number}"
        return to_number
