# Phase 6 — Telegram bot adapter

## Goal

Let the user chat with the agent from anywhere via Telegram. Outputs (.docx, .png, etc.) come back as Telegram documents/photos.

## Get a bot token

1. Open Telegram, search for **@BotFather**
2. `/newbot` → pick a name → pick a `_bot`-suffixed username
3. BotFather gives you a token like `1234567890:AAH...`
4. Save in `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=1234567890:AAH...your_token...
```

5. Find your **own** Telegram user ID:
   - Search for `@userinfobot`, `/start`
   - Copy the number ID
6. Save in `.env` as the **only** authorized user (you don't want randoms talking to your agent):

```dotenv
TELEGRAM_AUTHORIZED_USERS=123456789
```

(Comma-separate if multiple users.)

## Install

```bash
pip install python-telegram-bot>=21.0
```

## Adapter pattern

```python
# agent/telegram_adapter.py
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters

AUTHORIZED = {int(x) for x in os.environ.get("TELEGRAM_AUTHORIZED_USERS", "").split(",") if x.strip()}

class TelegramAdapter:
    def __init__(self, orchestrator, token=None):
        self.orch = orchestrator
        token = token or os.environ["TELEGRAM_BOT_TOKEN"]
        self.app = ApplicationBuilder().token(token).build()
        self.app.add_handler(CommandHandler("start", self._on_start))
        self.app.add_handler(CommandHandler("reset", self._on_reset))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

    async def _on_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            await update.message.reply_text("not authorized.")
            return
        await update.message.reply_text("agent ready. send any message.")

    async def _on_reset(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        self.orch.messages = []
        await update.message.reply_text("conversation reset.")

    async def _on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._authorized(update):
            return
        user_text = update.message.text
        await update.message.chat.send_action("typing")
        self.orch.add_user(user_text)
        files_to_send = []
        try:
            for msg in self.orch.step():
                if msg["role"] == "assistant" and not msg.get("tool_calls"):
                    if msg["content"]:
                        await self._send_long(update, msg["content"])
                elif msg["role"] == "tool":
                    # if tool returned a file path, queue for sending
                    files_to_send.extend(self._extract_files(msg["content"]))
        except Exception as e:
            await update.message.reply_text(f"agent error: {e}")
            return
        for path in files_to_send:
            await self._send_file(update, path)

    def _authorized(self, update):
        return update.effective_user and update.effective_user.id in AUTHORIZED

    async def _send_long(self, update, text):
        # Telegram caps at 4096 chars per message
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i+4000])

    async def _send_file(self, update, path):
        from pathlib import Path
        p = Path(path)
        if not p.exists():
            return
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
            await update.message.reply_photo(p.open("rb"), caption=p.name)
        else:
            await update.message.reply_document(p.open("rb"), filename=p.name)

    def _extract_files(self, tool_result_json):
        """Look for output_file / saved_path / etc. keys in the JSON."""
        import json
        try:
            d = json.loads(tool_result_json) if isinstance(tool_result_json, str) else tool_result_json
        except Exception:
            return []
        out = []
        for key in ("output_file", "saved_path", "path", "file"):
            if key in d and isinstance(d[key], str):
                out.append(d[key])
        return out

    def run(self):
        self.app.run_polling()
```

## Run it

```python
# scripts/run_telegram.py
from dotenv import load_dotenv; load_dotenv()
from agent.gemini_client import GeminiClient
from agent.tool_registry import ToolRegistry
from agent.orchestrator import Orchestrator
from agent.tools import register_all
from agent.telegram_adapter import TelegramAdapter

registry = ToolRegistry()
register_all(registry)
orch = Orchestrator(GeminiClient(), registry, system_prompt="...")
TelegramAdapter(orch).run()
```

`python scripts/run_telegram.py` → bot is live as long as the script runs. For 24/7, run on a small VPS or as a background service (`pm2`, `systemd`, `tmux`).

## File delivery convention

Establish a contract: tools that produce files return JSON with one of:
- `"output_file": "/abs/path/to/file"` (single file)
- `"saved_path": "/abs/path"` (alternative)
- `"path": "/abs/path"` (alternative)

The adapter scans for these keys and sends matching files via Telegram.

For multiple files, use `"output_files": [path1, path2, ...]` and update `_extract_files` accordingly.

## Concurrency note

`python-telegram-bot` 21+ uses asyncio. The orchestrator and tools are sync. If a tool blocks for a long time (e.g., generating a 50-page report), wrap the orchestrator call in `asyncio.to_thread` to avoid blocking the bot's event loop:

```python
import asyncio
result_msgs = []
def _run():
    return list(self.orch.step())
async def _on_text(self, update, ctx):
    ...
    self.orch.add_user(user_text)
    for msg in await asyncio.to_thread(_run):
        ...
```

For small projects, the simple sync version is fine — Telegram users tolerate a few seconds of "typing".

## Common issues

- **Bot doesn't reply**: check `TELEGRAM_AUTHORIZED_USERS` includes your numeric user ID (not username). Send `/start` to your bot to verify.
- **"Conflict: terminated by other getUpdates request"**: another instance of the bot is running somewhere. Kill it (only one polling client per token).
- **Files don't deliver**: confirm the tool actually returned `{"output_file": "..."}` in its result; the adapter only knows about that convention.
- **Markdown in replies**: Telegram has its own MarkdownV2 syntax which is picky. By default the adapter sends plain text — fine for 95% of agent replies. If you want bold/italic, use `parse_mode="MarkdownV2"` and escape special characters.
