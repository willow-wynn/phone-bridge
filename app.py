import logging
import threading

from flask import Flask, Response, request
from twilio.request_validator import RequestValidator
from twilio.twiml.messaging_response import MessagingResponse
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from session_store import SessionStore
from claude_runner import ClaudeRunner
from message_sender import MessageSender

Config.validate()

app = Flask(__name__)
# Trust X-Forwarded-* headers from the tunnel so request.url matches
# what Twilio signed against (the public HTTPS URL, not localhost)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
logger = logging.getLogger("phone-bridge")

store = SessionStore(Config.DB_PATH)
runner = ClaudeRunner(
    working_dir=Config.CLAUDE_WORKING_DIR,
    allowed_tools=Config.CLAUDE_ALLOWED_TOOLS,
    max_timeout=Config.CLAUDE_MAX_TIMEOUT,
    max_budget_usd=Config.CLAUDE_MAX_BUDGET_USD,
)
sender = MessageSender(
    Config.TWILIO_ACCOUNT_SID,
    Config.TWILIO_AUTH_TOKEN,
    Config.TWILIO_PHONE_NUMBER,
)
validator = RequestValidator(Config.TWILIO_AUTH_TOKEN)

# Per-phone locks to serialize concurrent messages from the same user
_phone_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _get_phone_lock(phone: str) -> threading.Lock:
    with _locks_lock:
        if phone not in _phone_locks:
            _phone_locks[phone] = threading.Lock()
        return _phone_locks[phone]


def _empty_twiml() -> Response:
    resp = MessagingResponse()
    return Response(str(resp), content_type="application/xml")


@app.route("/webhook", methods=["POST"])
def webhook():
    # Validate Twilio signature
    if Config.VALIDATE_TWILIO_SIGNATURE:
        sig = request.headers.get("X-Twilio-Signature", "")
        if not validator.validate(request.url, request.form.to_dict(), sig):
            logger.warning("Invalid Twilio signature — rejecting request")
            return Response("Forbidden", status=403)

    from_number = request.form.get("From", "")
    body = request.form.get("Body", "").strip()

    logger.info(f"Message from {from_number}: {body[:80]!r}")

    # Check allowlist
    bare_number = from_number.replace("whatsapp:", "")
    if bare_number not in Config.ALLOWED_PHONES:
        logger.warning(f"Blocked message from unlisted number: {from_number}")
        return _empty_twiml()

    # Handle special commands
    if body.lower() == "/reset":
        store.reset_session(from_number)
        sender.send(from_number, "Session reset. Next message starts a fresh conversation.")
        return _empty_twiml()

    if body.lower() == "/status":
        session_id = store.get_session(from_number)
        info = store.list_sessions()
        entry = next((s for s in info if s["phone_number"] == from_number), None)
        lines = [
            f"Session: {session_id or 'none'}",
            f"Dir: {Config.CLAUDE_WORKING_DIR}",
            f"Tools: {Config.CLAUDE_ALLOWED_TOOLS}",
        ]
        if entry:
            lines.append(f"Messages: {entry['message_count']}")
            lines.append(f"Last used: {entry['last_used_at']}")
        sender.send(from_number, "\n".join(lines))
        return _empty_twiml()

    if body.lower() == "/more":
        if sender.has_overflow(from_number):
            threading.Thread(
                target=sender.send_more,
                args=(from_number,),
                daemon=True,
            ).start()
        else:
            sender.send(from_number, "No more content to send.")
        return _empty_twiml()

    if body.lower() == "/help":
        sender.send(from_number, (
            "Commands:\n"
            "/reset — Start a new session\n"
            "/status — Show current session info\n"
            "/more — Get truncated content\n"
            "/help — Show this message\n\n"
            "Anything else is sent to Claude Code."
        ))
        return _empty_twiml()

    # Process in background thread
    thread = threading.Thread(
        target=_process_message,
        args=(from_number, body),
        daemon=True,
    )
    thread.start()

    return _empty_twiml()


def _process_message(from_number: str, body: str):
    lock = _get_phone_lock(from_number)
    with lock:
        try:
            session_id = store.get_session(from_number)
            result = runner.run(prompt=body, session_id=session_id)

            # Persist session
            store.save_session(from_number, result.session_id, Config.CLAUDE_WORKING_DIR)

            # Build response
            text = result.text
            if result.cost_usd > 0:
                text += f"\n\n[${result.cost_usd:.4f} | {result.duration_ms / 1000:.1f}s]"

            sender.send(from_number, text)

        except Exception:
            logger.exception(f"Error processing message from {from_number}")
            try:
                sender.send(from_number, "Something went wrong processing your message. Check server logs.")
            except Exception:
                logger.exception("Failed to send error reply")


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(f"Starting phone-bridge on port {Config.FLASK_PORT}")
    logger.info(f"Claude working dir: {Config.CLAUDE_WORKING_DIR}")
    logger.info(f"Allowed phones: {Config.ALLOWED_PHONES}")
    logger.info(f"WhatsApp mode: {Config.TWILIO_PHONE_NUMBER.startswith('whatsapp:')}")
    app.run(host="127.0.0.1", port=Config.FLASK_PORT, debug=False)
