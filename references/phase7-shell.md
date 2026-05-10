# Phase 7 — Shell tool (opt-in)

## Why this is opt-in

Adding a `shell` tool gives the agent the ability to run arbitrary commands on the user's machine. This unlocks self-evolution (Phase 9) but also creates real risk if not scoped.

**Don't add this without:**
- Phase 5 permissions in place (folders are scoped)
- Per-call user approval (no auto-execute)
- A clear conversation with the user about the risks

If the user is unsure, skip Phase 7 and ship the agent without it. They can come back to it.

## The pattern

```python
# agent/shell_tool.py
import subprocess, os
from pathlib import Path

class ShellApprovalRequired(Exception):
    pass

class ShellTool:
    def __init__(self, permissions, approval_callback):
        """
        permissions: agent/permissions.py instance (Phase 5)
        approval_callback: callable(command: str) -> bool
                          (Telegram inline-button prompt; blocks until user clicks)
        """
        self.perm = permissions
        self.approve = approval_callback
        # commands that don't need approval — keep this list TINY and read-only
        self.allowlist_prefixes = (
            "ls ", "cat ", "head ", "tail ", "wc ", "grep ", "find ",
            "git status", "git log", "git diff", "git branch",
            "python --version", "pip list", "node --version",
        )

    def run(self, command: str, cwd: str = None) -> dict:
        cwd = cwd or os.getcwd()
        # path-scope check: cwd must be inside an allowed write folder
        try:
            self.perm.check(cwd, "write")
        except Exception as e:
            return {"error": f"cwd not in write-allowed folders: {e}"}

        # auto-approve only the allowlist
        if not any(command.strip().startswith(p) for p in self.allowlist_prefixes):
            ok = self.approve(command)
            if not ok:
                return {"error": "user denied", "command": command}

        try:
            r = subprocess.run(
                command, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=120,
            )
            return {
                "ok": r.returncode == 0,
                "exit_code": r.returncode,
                "stdout": r.stdout[-4000:] if r.stdout else "",
                "stderr": r.stderr[-2000:] if r.stderr else "",
                "command": command,
                "cwd": cwd,
            }
        except subprocess.TimeoutExpired:
            return {"error": "timeout (>120s)", "command": command}
        except Exception as e:
            return {"error": str(e), "command": command}


def shell_schema():
    return {
        "name": "shell",
        "description": (
            "Run a shell command. Read-only commands (ls, cat, git status, etc.) execute immediately; "
            "anything else requires user approval via Telegram inline button. "
            "cwd must be inside a write-permitted folder. "
            "Use this when you need to run scripts, install packages, or modify code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command, e.g. 'pip install requests' or 'python scripts/build.py'"},
                "cwd": {"type": "string", "description": "Working directory (absolute). Must be inside a write-permitted folder."},
            },
            "required": ["command"],
        },
    }
```

## Approval callback (Telegram inline buttons)

```python
# in TelegramAdapter (Phase 6)
import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class TelegramAdapter:
    def __init__(self, ...):
        ...
        self._pending_approvals = {}  # request_id -> asyncio.Future

    async def _request_approval(self, chat_id, command):
        request_id = str(uuid.uuid4())
        fut = asyncio.get_event_loop().create_future()
        self._pending_approvals[request_id] = fut

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✓ Run", callback_data=f"approve|{request_id}"),
            InlineKeyboardButton("✗ Deny", callback_data=f"deny|{request_id}"),
        ]])
        await self.app.bot.send_message(
            chat_id=chat_id,
            text=f"Run shell command?\n\n```\n{command}\n```",
            parse_mode="MarkdownV2",
            reply_markup=kb,
        )
        try:
            return await asyncio.wait_for(fut, timeout=300)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_approvals.pop(request_id, None)

    # CallbackQueryHandler:
    async def _on_callback(self, update, ctx):
        q = update.callback_query
        action, request_id = q.data.split("|", 1)
        fut = self._pending_approvals.get(request_id)
        if fut and not fut.done():
            fut.set_result(action == "approve")
        await q.answer()
        await q.edit_message_text(q.message.text + f"\n\n→ {action}d")
```

The shell tool's `approve` callback then becomes a sync wrapper:

```python
def approve_callback(command):
    chat_id = ...  # the user's chat
    return asyncio.run_coroutine_threadsafe(
        adapter._request_approval(chat_id, command), adapter.app.loop,
    ).result(timeout=320)
```

## Output truncation

Long stdout/stderr (e.g., `pip install` with verbose) eats LLM context fast. The pattern above already truncates to last 4000 / 2000 chars. The "tail" is more useful than "head" for build/install logs (errors appear at the end).

## What shell unlocks

- **Code writing**: agent can `pip install <pkg>` then write a new tool file in `agent/tools/` and ask the user to reload
- **Git operations**: agent can branch / commit / show diff (push/force-push should be denied always)
- **Testing**: agent can run `pytest -x -k test_foo` to verify changes
- **Inspection**: agent can `tail -f logs/app.log` to debug issues

This is the foundation of Phase 9 (self-evolution).

## Hard guardrails

Even with approval, **never let the agent**:
- Set new `permissions.json` entries via shell (must go through code review)
- `chmod +s`, install login shells, modify `~/.ssh/`
- Run `rm -rf /` / `format /` / etc. — block these prefixes outright

A simple deny-list at the top of `ShellTool.run`:

```python
DENY_PATTERNS = [
    r"\brm\s+-rf\s+/", r"\bsudo\b", r"\bchmod\s+\+s",
    r"\.ssh\b", r"\bcrontab\b -",
]
import re
for pat in DENY_PATTERNS:
    if re.search(pat, command):
        return {"error": f"denied by hard guardrail: matches {pat}"}
```

This belt-and-suspenders alongside permission scoping.
