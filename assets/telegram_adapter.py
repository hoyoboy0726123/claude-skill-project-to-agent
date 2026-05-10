"""Telegram bot adapter — drop into your project as agent/telegram_adapter.py.

Requires:
    pip install python-telegram-bot>=21.0
"""

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler,
    ContextTypes, MessageHandler, filters,
)


def _parse_authorized():
    raw = os.environ.get("TELEGRAM_AUTHORIZED_USERS", "").strip()
    return {int(x) for x in raw.split(",") if x.strip().isdigit()}


class TelegramAdapter:
    """Wraps an Orchestrator and exposes it via Telegram.

    Tools that produce files should return JSON with one of:
        {"output_file": "/abs/path"}
        {"saved_path": "/abs/path"}
        {"path": "/abs/path"}
        {"output_files": ["/abs/path1", ...]}
    The adapter scans for these and sends matching files to Telegram.
    """

    FILE_KEYS = ("output_file", "saved_path", "path", "file")
    FILE_LIST_KEYS = ("output_files", "files")

    def __init__(self, orchestrator, token: str = None,
                 approval_callback: Callable = None):
        self.orch = orchestrator
        self.authorized = _parse_authorized()
        token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        self.app = ApplicationBuilder().token(token).build()
        self.app.add_handler(CommandHandler("start", self._on_start))
        self.app.add_handler(CommandHandler("reset", self._on_reset))
        self.app.add_handler(CommandHandler("help", self._on_help))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
        self.app.add_handler(CallbackQueryHandler(self._on_callback))

        # pending approval futures keyed by request_id
        self._approvals: dict[str, asyncio.Future] = {}

    # ----------------- public approval API (sync) -----------------
    def request_approval_sync(self, chat_id: int, prompt: str, timeout: int = 300) -> bool:
        """Block-wait for user to click approve/deny. Call from sync code (e.g., shell tool)."""
        loop = self.app.update_queue._loop or asyncio.get_event_loop()
        coro = self._request_approval(chat_id, prompt, timeout)
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout + 5)

    async def _request_approval(self, chat_id: int, prompt: str, timeout: int = 300) -> bool:
        rid = str(uuid.uuid4())[:8]
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._approvals[rid] = fut

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✓ Approve", callback_data=f"approve|{rid}"),
            InlineKeyboardButton("✗ Deny", callback_data=f"deny|{rid}"),
        ]])
        await self.app.bot.send_message(chat_id=chat_id, text=prompt, reply_markup=kb)

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return False
        finally:
            self._approvals.pop(rid, None)

    # ----------------- handlers -----------------
    def _ok(self, update: Update) -> bool:
        if not update.effective_user:
            return False
        if not self.authorized:
            return True  # if no allowlist configured, accept all (dev mode)
        return update.effective_user.id in self.authorized

    async def _on_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update):
            await update.message.reply_text("not authorized.")
            return
        await update.message.reply_text(
            "Agent ready. Send any message.\n"
            "/reset clears conversation. /help shows tools."
        )

    async def _on_reset(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update):
            return
        self.orch.reset()
        await update.message.reply_text("conversation reset.")

    async def _on_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update):
            return
        names = self.orch.registry.names()
        await update.message.reply_text(
            f"Available tools ({len(names)}):\n" + "\n".join(f"• {n}" for n in names)
        )

    async def _on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._ok(update):
            return
        await update.message.chat.send_action("typing")

        text = update.message.text or ""
        self.orch.add_user(text)

        # Run orchestrator on a worker thread so we don't block bot loop.
        def _run_step():
            return list(self.orch.step())

        try:
            messages = await asyncio.to_thread(_run_step)
        except Exception as e:
            await update.message.reply_text(f"agent error: {e}")
            return

        files_to_send = []
        final_text = None
        tool_lines = []

        for msg in messages:
            if msg["role"] == "assistant":
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        args = dict(getattr(tc, "args", {}))
                        tool_lines.append(f"▸ {tc.name}({args})")
                elif msg.get("content"):
                    final_text = msg["content"]
            elif msg["role"] == "tool":
                files_to_send.extend(self._extract_files(msg["content"]))

        # send tool trace + final text
        body_parts = []
        if tool_lines:
            body_parts.append("```\n" + "\n".join(tool_lines) + "\n```")
        if final_text:
            body_parts.append(final_text)
        body = "\n\n".join(body_parts) if body_parts else "(no response)"

        await self._send_long(update, body)

        for path in files_to_send:
            await self._send_file(update, path)

    async def _on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        if not q or not q.data:
            return
        if not self._ok(update):
            await q.answer("not authorized.")
            return
        try:
            action, rid = q.data.split("|", 1)
        except ValueError:
            await q.answer()
            return
        fut = self._approvals.get(rid)
        if fut and not fut.done():
            fut.set_result(action == "approve")
        await q.answer()
        try:
            await q.edit_message_text(f"{q.message.text}\n\n→ {action}")
        except Exception:
            pass

    # ----------------- helpers -----------------
    async def _send_long(self, update, text):
        for i in range(0, len(text), 4000):
            await update.message.reply_text(text[i:i+4000])

    async def _send_file(self, update, path: str):
        p = Path(path)
        if not p.exists():
            return
        try:
            if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                with p.open("rb") as f:
                    await update.message.reply_photo(f, caption=p.name)
            else:
                with p.open("rb") as f:
                    await update.message.reply_document(f, filename=p.name)
        except Exception as e:
            await update.message.reply_text(f"(failed to send {p.name}: {e})")

    def _extract_files(self, tool_result_str: str) -> list[str]:
        try:
            d = json.loads(tool_result_str) if isinstance(tool_result_str, str) else tool_result_str
            if not isinstance(d, dict):
                return []
        except Exception:
            return []
        out: list[str] = []
        for k in self.FILE_KEYS:
            v = d.get(k)
            if isinstance(v, str) and v:
                out.append(v)
        for k in self.FILE_LIST_KEYS:
            v = d.get(k)
            if isinstance(v, list):
                out.extend([x for x in v if isinstance(x, str)])
        return out

    # ----------------- run -----------------
    def run(self):
        """Block-run polling. Use this when running the bot as a script."""
        print("Telegram bot starting (polling)...")
        self.app.run_polling()
