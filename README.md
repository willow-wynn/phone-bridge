# phone-bridge

Text your phone and talk to [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) running on your laptop.

```
Phone (WhatsApp) → Twilio → Cloudflare Tunnel → Flask → claude -p → reply
```

Messages you send are piped to `claude -p` with session continuity, so Claude remembers the full conversation. Responses are sent back to your phone via WhatsApp.

## Setup

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) installed and authenticated
- Python 3.10+
- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (`brew install cloudflared`) or [ngrok](https://ngrok.com/)
- A free [Twilio](https://www.twilio.com/) account

### 1. Install

```bash
cd ~/projects/phone-bridge
bash setup.sh
```

This creates a virtualenv, installs dependencies, and generates a `.env` file from the template.

### 2. Configure Twilio

1. Sign up at [twilio.com](https://www.twilio.com/) (free trial includes $15 credit)
2. Go to **Messaging → Try it out → Send a WhatsApp message**
3. Follow the sandbox setup — send the join code from your phone
4. Copy your **Account SID** and **Auth Token** into `.env`
5. Set `ALLOWED_PHONES` to your phone number (e.g., `+15551234567`)
6. Set `CLAUDE_WORKING_DIR` to the project directory you want Claude to work in

### 3. Start the server

```bash
bash setup.sh
```

### 4. Start a tunnel (separate terminal)

```bash
cloudflared tunnel --url http://localhost:5000
```

### 5. Set the webhook in Twilio

Copy the tunnel URL and go to your Twilio WhatsApp sandbox settings. Set **"When a message comes in"** to:

```
https://YOUR-TUNNEL-URL/webhook
```

### 6. Text your Twilio sandbox number

You're in. Send any message and Claude Code will respond.

## Commands

| Command   | Description                          |
|-----------|--------------------------------------|
| `/help`   | Show available commands              |
| `/reset`  | Start a new Claude session           |
| `/status` | Show current session info            |
| `/more`   | Get the rest of a truncated response |

Anything else is sent directly to Claude Code.

## Configuration

All config is in `.env`:

| Variable                   | Default                        | Description                                    |
|----------------------------|--------------------------------|------------------------------------------------|
| `TWILIO_ACCOUNT_SID`      | —                              | From Twilio console                            |
| `TWILIO_AUTH_TOKEN`        | —                              | From Twilio console                            |
| `TWILIO_PHONE_NUMBER`     | `whatsapp:+14155238886`        | Twilio sandbox number                          |
| `ALLOWED_PHONES`           | —                              | Comma-separated phone numbers that can interact|
| `CLAUDE_WORKING_DIR`      | `~`                            | Directory Claude Code operates in              |
| `CLAUDE_ALLOWED_TOOLS`    | `Read,Glob,Grep`               | Tools Claude can use (read-only by default)    |
| `CLAUDE_MAX_TIMEOUT`      | `120`                          | Max seconds per Claude invocation              |
| `CLAUDE_MAX_BUDGET_USD`   | `1.00`                         | Max cost per turn                              |
| `FLASK_PORT`               | `5000`                         | Server port                                    |
| `VALIDATE_TWILIO_SIGNATURE`| `true`                        | Verify webhook authenticity                    |

## How it works

1. You text the Twilio WhatsApp sandbox number
2. Twilio POSTs the message to your tunnel URL → Flask server
3. Server validates the request (Twilio signature + phone allowlist)
4. Runs `claude -p "your message" --output-format json --resume <session_id>`
5. Parses the response, saves the session ID for continuity
6. Sends the reply back via Twilio REST API
7. Long responses are split into multiple messages; very long ones are truncated with `/more` pagination

## Security

- **Twilio signature validation** on every request
- **Phone allowlist** — only your number(s) can interact
- **Read-only tools by default** — opt into `Edit`, `Write`, `Bash` explicitly
- **Budget cap** per turn
- **Tunnel URL is random** and not discoverable
