# Phase 5 — Permission boundaries

## Why

The agent will read and write files. Without explicit boundaries, a single bad tool call (or worse, a malicious prompt) could read `~/.ssh/id_rsa` or wipe `~/Documents`. **Always add permissions before any filesystem-touching tool, and definitely before Phase 7 (shell)**.

## The model

Three permission levels per folder:

- `read` — the agent can list / open files inside
- `write` — the agent can create / overwrite files (no delete)
- `delete` — the agent can remove files

`agent/permissions.json` (gitignored):

```json
{
  "read": [
    "C:/Users/me/projects/myapp/data",
    "C:/Users/me/projects/myapp/templates"
  ],
  "write": [
    "C:/Users/me/projects/myapp/output"
  ],
  "delete": []
}
```

`delete` defaults to empty — the user must explicitly grant. Be conservative.

## Setup flow (do this with the user)

When wiring Phase 5:

1. List the folders the project already touches (from Phase 1 analysis)
2. Ask the user: "Should the agent be able to **read** these? [y/N for each]"
3. Ask: "Should it **write** to ___ ?" (probably the output folder only)
4. Ask: "Should it **delete** anywhere? Most users say no — only enable if you have a clear use case." [y/N]
5. Save to `permissions.json`. Print the summary back.

Path normalization matters: store absolute paths, normalize separators (`/` on all platforms in JSON, convert when checking).

## The permission check

Every filesystem tool calls this before acting:

```python
# agent/permissions.py
import json, os
from pathlib import Path

class PermissionDenied(Exception):
    pass

class Permissions:
    def __init__(self, path="agent/permissions.json"):
        with open(path, "r", encoding="utf-8") as f:
            self.acl = json.load(f)
        # normalize stored paths
        for k in ("read", "write", "delete"):
            self.acl[k] = [str(Path(p).resolve()) for p in self.acl.get(k, [])]

    def check(self, target_path: str, op: str):
        if op not in ("read", "write", "delete"):
            raise ValueError(f"unknown op: {op}")
        target = str(Path(target_path).resolve())
        for allowed in self.acl[op]:
            try:
                Path(target).relative_to(allowed)
                return  # OK — target is inside an allowed folder
            except ValueError:
                continue
        raise PermissionDenied(
            f"agent has no '{op}' permission for {target}. "
            f"Allowed {op} folders: {self.acl[op]}"
        )
```

Wrap it in tools:

```python
def write_report(filename: str, content: str) -> dict:
    target = OUTPUT_DIR / filename
    try:
        permissions.check(str(target), "write")
    except PermissionDenied as e:
        return {"error": str(e)}
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target)}
```

## Surface permission errors clearly

When the agent hits a permission error, it should tell the user *why*, not just "couldn't do it". The orchestrator's tool result handling already passes `{"error": ...}` back to the LLM, which then explains it in chat. That's enough.

## Re-prompting for permission

When the agent wants to do something a current permission set doesn't allow, **the agent should ask the user for permission via Telegram** (or chat) — don't auto-grant, don't fail silently. A pattern:

```python
def _request_permission(self, path: str, op: str):
    """Ask user via Telegram to add a permission. Returns True if granted."""
    # send Telegram message with inline buttons:
    #   [Grant {op} on {path}]  [Deny]
    # block or short-poll for response, then update permissions.json on grant
    ...
```

This makes the agent feel collaborative — it's asking for capability, not silently failing.

## Anti-patterns

- ❌ A single `"all": ["~"]` permission. Defeats the point.
- ❌ Reading the user's home dir or git history. Even read-only this leaks credentials, browser cookies, etc.
- ❌ Symlink traversal. Resolve paths to canonical form (`Path.resolve()`) before checking — otherwise a symlink inside an allowed folder could escape.
- ❌ Storing permissions in code. `permissions.json` (gitignored) is the source of truth — the user can edit it without a code change.
