import os
import sys

from dotenv import load_dotenv

load_dotenv()


class Config:
    # Twilio
    TWILIO_ACCOUNT_SID: str = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN: str = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_PHONE_NUMBER: str = os.environ.get("TWILIO_PHONE_NUMBER", "whatsapp:+14155238886")

    # Security
    ALLOWED_PHONES: list[str] = [
        p.strip() for p in os.environ.get("ALLOWED_PHONES", "").split(",") if p.strip()
    ]

    # Claude
    CLAUDE_WORKING_DIR: str = os.environ.get("CLAUDE_WORKING_DIR", os.path.expanduser("~"))
    CLAUDE_ALLOWED_TOOLS: str = os.environ.get("CLAUDE_ALLOWED_TOOLS", "Read,Glob,Grep")
    CLAUDE_MAX_TIMEOUT: int = int(os.environ.get("CLAUDE_MAX_TIMEOUT", "120"))
    CLAUDE_MAX_BUDGET_USD: float = float(os.environ.get("CLAUDE_MAX_BUDGET_USD", "1.00"))

    # Server
    FLASK_PORT: int = int(os.environ.get("FLASK_PORT", "5000"))
    VALIDATE_TWILIO_SIGNATURE: bool = os.environ.get("VALIDATE_TWILIO_SIGNATURE", "true").lower() == "true"

    # Derived
    DB_PATH: str = os.path.join(os.path.expanduser("~"), ".phone-bridge", "sessions.db")

    @classmethod
    def validate(cls):
        """Check required fields are set. Exit with a clear message if not."""
        missing = []
        if not cls.TWILIO_ACCOUNT_SID or cls.TWILIO_ACCOUNT_SID.startswith("ACxxxx"):
            missing.append("TWILIO_ACCOUNT_SID")
        if not cls.TWILIO_AUTH_TOKEN or cls.TWILIO_AUTH_TOKEN == "your_auth_token_here":
            missing.append("TWILIO_AUTH_TOKEN")
        if not cls.ALLOWED_PHONES:
            missing.append("ALLOWED_PHONES")

        if missing:
            print(f"Error: Missing required config in .env: {', '.join(missing)}")
            print("Copy .env.example to .env and fill in your credentials.")
            sys.exit(1)

        os.makedirs(os.path.dirname(cls.DB_PATH), exist_ok=True)
        os.makedirs(cls.CLAUDE_WORKING_DIR, exist_ok=True)
