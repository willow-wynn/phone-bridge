import os
import sys

from dotenv import load_dotenv

load_dotenv()


class Config:
    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    # Security: allowed Telegram user IDs
    ALLOWED_USERS: list[int] = [
        int(u.strip()) for u in os.environ.get("ALLOWED_USERS", "").split(",") if u.strip()
    ]

    # Claude
    CLAUDE_WORKING_DIR: str = os.environ.get("CLAUDE_WORKING_DIR", os.path.expanduser("~"))
    CLAUDE_ALLOWED_TOOLS: str = os.environ.get("CLAUDE_ALLOWED_TOOLS", "Read,Write,Edit,Bash,Glob,Grep,WebSearch,WebFetch,NotebookEdit")
    CLAUDE_MAX_TIMEOUT: int = int(os.environ.get("CLAUDE_MAX_TIMEOUT", "1800"))
    CLAUDE_MAX_BUDGET_USD: float = float(os.environ.get("CLAUDE_MAX_BUDGET_USD", "5.00"))
    CLAUDE_SYSTEM_PROMPT: str = os.environ.get("CLAUDE_SYSTEM_PROMPT", "")

    # Derived
    DB_PATH: str = os.path.join(os.path.expanduser("~"), ".phone-bridge", "sessions.db")

    @classmethod
    def validate(cls):
        """Check required fields are set. Exit with a clear message if not."""
        missing = []
        if not cls.TELEGRAM_BOT_TOKEN or cls.TELEGRAM_BOT_TOKEN == "your_bot_token_here":
            missing.append("TELEGRAM_BOT_TOKEN")

        if missing:
            print(f"Error: Missing required config in .env: {', '.join(missing)}")
            print("Copy .env.example to .env and fill in your credentials.")
            sys.exit(1)

        os.makedirs(os.path.dirname(cls.DB_PATH), exist_ok=True)
        os.makedirs(cls.CLAUDE_WORKING_DIR, exist_ok=True)
