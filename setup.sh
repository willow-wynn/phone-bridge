#!/bin/bash
set -euo pipefail

echo "=== Phone-to-Claude-Code Bridge Setup ==="
echo ""

# Check prerequisites
if ! command -v claude &>/dev/null; then
    echo "Error: 'claude' CLI not found. Install it first:"
    echo "  npm install -g @anthropic-ai/claude-code"
    exit 1
fi

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found."
    exit 1
fi

echo "Found claude $(claude --version 2>/dev/null || echo '(unknown version)')"
echo "Found $(python3 --version)"
echo ""

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating venv..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -q -r requirements.txt

# Check for .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "============================================"
    echo "  .env file created from .env.example"
    echo "============================================"
    echo ""
    echo "Before running, edit .env with your Telegram bot token:"
    echo ""
    echo "  1. Open Telegram, search for @BotFather"
    echo "  2. Send /newbot and follow the prompts"
    echo "  3. Copy the bot token to .env (TELEGRAM_BOT_TOKEN)"
    echo "  4. Set CLAUDE_WORKING_DIR to your project directory"
    echo "  5. Run: bash setup.sh"
    echo ""
    echo "  (ALLOWED_USERS can be set after first run —"
    echo "   send /start to the bot and it will show your user ID)"
    echo ""
    exit 0
fi

echo ""
echo "============================================"
echo "  Starting phone-bridge"
echo "============================================"
echo ""
echo "  No tunnel needed — Telegram uses polling."
echo ""
echo "  Commands you can send to the bot:"
echo "    /start  — Show your user ID"
echo "    /help   — Show available commands"
echo "    /reset  — Start a new Claude session"
echo "    /status — Show session info"
echo "    /more   — Get rest of truncated response"
echo ""
echo "Starting bot..."
echo ""

python3 app.py
