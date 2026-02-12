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
    echo "Before running, edit .env with your Twilio credentials:"
    echo ""
    echo "  1. Sign up at https://console.twilio.com (free trial)"
    echo "  2. Go to: Messaging > Try it out > Send a WhatsApp message"
    echo "     Follow the sandbox setup (send the join code from your phone)"
    echo "  3. Copy your Account SID and Auth Token to .env"
    echo "  4. Set ALLOWED_PHONES to your phone number (e.g., +15551234567)"
    echo "  5. Set CLAUDE_WORKING_DIR to your project directory"
    echo ""
    echo "Then run: bash setup.sh"
    exit 0
fi

echo ""
echo "============================================"
echo "  Starting phone-bridge server"
echo "============================================"
echo ""
echo "Next steps (in another terminal):"
echo ""
echo "  1. Start a tunnel to expose localhost:"
echo "     cloudflared tunnel --url http://localhost:${FLASK_PORT:-5000}"
echo "     (install: brew install cloudflared)"
echo ""
echo "  2. Copy the tunnel URL and set it in Twilio:"
echo "     https://console.twilio.com > Messaging > Try it out > WhatsApp sandbox"
echo "     Set 'When a message comes in' to: https://YOUR-TUNNEL-URL/webhook"
echo ""
echo "  3. Text your Twilio WhatsApp sandbox number from your phone!"
echo ""
echo "  Commands you can send:"
echo "    /help   — Show available commands"
echo "    /reset  — Start a new Claude session"
echo "    /status — Show session info"
echo "    /more   — Get rest of truncated response"
echo ""
echo "Starting server..."
echo ""

python3 app.py
