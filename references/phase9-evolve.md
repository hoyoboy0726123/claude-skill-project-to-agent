# Phase 9 — Self-evolution loop

## What this means

The user asks the agent to do something it can't (no tool exists). With shell + permissions in place, the agent **proposes a new tool**, shows the user the diff, and the user merges it. Each accepted proposal makes the project compound — the agent gets more capable over time.

## The loop

1. **User asks for something unsupported**:
   > "Can you also count rows in the latest CSV in /downloads?"
2. **Agent recognizes the gap** (the system prompt teaches this — see below)
3. **Agent drafts a new tool** in `agent/tools_proposed/<name>.py`:
   ```python
   # agent/tools_proposed/count_csv_rows.py
   from pathlib import Path
   import csv

   def count_csv_rows(path: str) -> dict:
       """Count rows in a CSV file (excluding header)."""
       p = Path(path)
       try:
           with p.open(newline="", encoding="utf-8") as f:
               return {"path": str(p), "rows": sum(1 for _ in csv.reader(f)) - 1}
       except Exception as e:
           return {"error": str(e)}

   COUNT_CSV_ROWS_SCHEMA = {
       "name": "count_csv_rows",
       "description": "Count data rows (excluding header) in a CSV file.",
       "parameters": {
           "type": "object",
           "properties": {
               "path": {"type": "string", "description": "Absolute path to CSV file. Must be in a read-permitted folder."},
           },
           "required": ["path"],
       },
   }
   ```
4. **Agent shows diff and asks for approval** (Telegram inline buttons):
   - ✓ Approve & merge → agent moves file from `tools_proposed/` to `tools/`, registers it on next reload
   - ✗ Deny → file deleted, conversation continues without the tool
5. **Agent restarts itself** (or hot-reloads — see below) and now uses the new tool to answer the original question

## System prompt addition

```
When the user asks for something you don't have a tool for:

1. Briefly explain what's missing.
2. Draft a new tool in agent/tools_proposed/<snake_name>.py with:
   - The function (with type hints + docstring).
   - A schema dict named <UPPER_SNAKE>_SCHEMA.
   - Use existing patterns: return {"error": "..."} on failure, cap large outputs.
3. Show the file content to the user and ask: "Approve this new tool?"
4. If approved, use the shell tool to:
   a. mv agent/tools_proposed/<name>.py agent/tools/<name>.py
   b. Add registration to agent/tools.py
   c. (re-import or restart — see project's reload mechanism)
5. Then use the new tool to answer the user's original question.

Do not bypass the approval step. Do not modify other files unrelated to the new tool.
```

## Hot reload (so the agent doesn't need restart)

Add a tool that re-imports tool modules after a new tool is merged:

```python
# in agent/tools.py
import importlib, pkgutil
from agent.tool_registry import Tool

def reload_tools(registry: ToolRegistry) -> dict:
    """Re-discover and register all tools in agent/tools/. Returns count."""
    import agent.tools as tools_pkg
    importlib.reload(tools_pkg)
    # walk submodules:
    n = 0
    for _, name, _ in pkgutil.iter_modules(tools_pkg.__path__):
        mod = importlib.import_module(f"agent.tools.{name}")
        if hasattr(mod, "register"):
            mod.register(registry)
            n += 1
    return {"reloaded": n}
```

Convention: each tool file in `agent/tools/<name>.py` exports `register(registry)` that calls `registry.register(Tool(...))`. The `reload_tools` walker calls each. After merge + reload, the agent sees the new tool and uses it.

## Diff preview

Before approving, the user wants to see what they're agreeing to. Use the shell tool to show the new file:

```
shell: cat agent/tools_proposed/count_csv_rows.py
```

The output (capped to 4000 chars by the shell wrapper) goes into the agent's context, and the agent forwards it to the user via Telegram before asking for approval. Reading 30 lines of code on a phone is fast.

For longer or multi-file changes, use:

```
shell: git diff --stat agent/tools_proposed
```

Then per-file:

```
shell: cat agent/tools_proposed/<filename>
```

Whatever feels natural. The agent's system prompt should already tell it to "show before asking".

## Quality discipline

The agent is going to write some bad tool drafts. Make the user a critical reviewer by including these checks in the system prompt:

```
When proposing a new tool, ensure:
- Function has type hints and a one-line docstring.
- Returns dict (not raises) on errors.
- Caps output if it might exceed 4KB.
- Calls permissions.check() if it touches files.
- Schema description starts with a verb and mentions return shape.
- No global side effects beyond the documented operation.
```

These rules become the auto-checklist the agent applies before showing the user.

## Anti-patterns

- ❌ **Auto-merge new tools without approval.** Even with shell approval, the *file content* deserves a separate look. Each new tool is new attack surface.
- ❌ **Tools that wrap shell commands as a thin layer.** If the agent has shell, it doesn't need a `git_status` tool — it can `shell("git status")`. New tools should add real value (parsing, abstraction, type safety), not duplicate raw shell.
- ❌ **Letting the agent edit `tool_registry.py` / `orchestrator.py` / `permissions.py`** through self-evolution. Those are the trust boundary; never auto-merge changes there. Only `tools/` should be auto-mergeable.
- ❌ **Drafting tools the user will never approve.** When the user keeps saying no to similar tools, the system prompt is missing a rule. Update it (manually) to teach the agent about the user's preferences.

## What this enables long-term

After a month of regular use, the agent ends up with 30-100 tools tailored to exactly what the user does. Each one is small, reviewed, and earned through real interaction. The project stops being "a tool you maintain" and starts being "a tool that grows alongside you."

That's the goal of this skill.
