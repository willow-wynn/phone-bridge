# phone-bridge

Text your phone and talk to [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) running on your laptop.

```
Phone (Telegram) → Bot API (polling) → claude -p → reply
```

Messages you send are piped to `claude -p` with session continuity, so Claude remembers the full conversation. Responses are sent back via Telegram. Completely free, no tunnel required.

## Setup

### Prerequisites

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview) installed and authenticated
- Python 3.10+
- A [Telegram](https://telegram.org/) account

### 1. Install

```bash
cd ~/projects/phone-bridge
bash setup.sh
```

This creates a virtualenv, installs dependencies, and generates a `.env` file from the template.

### 2. Create a Telegram bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts (pick any name/username)
3. Copy the bot token into `.env` (`TELEGRAM_BOT_TOKEN`)
4. Set `CLAUDE_WORKING_DIR` to the project directory you want Claude to work in

### 3. Start the bot

```bash
bash setup.sh
```

No tunnel needed — the bot uses polling.

### 4. Lock down access

1. Open your bot in Telegram and send `/start`
2. It will reply with your user ID
3. Add that ID to `ALLOWED_USERS` in `.env` and restart

## Commands

| Command   | Description                          |
|-----------|--------------------------------------|
| `/start`  | Show your user ID                    |
| `/help`   | Show available commands              |
| `/reset`  | Start a new Claude session           |
| `/status` | Show current session info            |
| `/more`   | Get the rest of a truncated response |

Anything else is sent directly to Claude Code.

## Configuration

All config is in `.env`:

| Variable               | Default        | Description                                 |
|------------------------|----------------|---------------------------------------------|
| `TELEGRAM_BOT_TOKEN`  | —              | From @BotFather                             |
| `ALLOWED_USERS`        | —              | Comma-separated Telegram user IDs           |
| `CLAUDE_WORKING_DIR`  | `~`            | Directory Claude Code operates in           |
| `CLAUDE_ALLOWED_TOOLS`| `Read,Glob,Grep` | Tools Claude can use (read-only by default) |
| `CLAUDE_MAX_TIMEOUT`  | `120`          | Max seconds per Claude invocation           |
| `CLAUDE_MAX_BUDGET_USD`| `1.00`        | Max cost per turn                           |

## How it works

1. You message the Telegram bot from your phone
2. Bot receives it via long polling (no webhook/tunnel needed)
3. Checks your user ID against the allowlist
4. Runs `claude -p "your message" --output-format json --resume <session_id>`
5. Parses the response, saves the session ID for continuity
6. Sends the reply back to your Telegram chat
7. Long responses are split into multiple messages; very long ones are truncated with `/more` pagination

## Security

- **User ID allowlist** — only your account can interact
- **Read-only tools by default** — opt into `Edit`, `Write`, `Bash` explicitly
- **Budget cap** per turn
- **No public endpoint** — polling means nothing is exposed to the internet
