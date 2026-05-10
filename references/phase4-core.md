# Phase 4 — Build agent core

## Goal

Wire up: `Tool` registry + `GeminiClient` + `Orchestrator` (planner loop). After Phase 4, the user can drive their tools by chatting in a Python REPL — Telegram comes later.

## Three files

```
agent/
├── tool_registry.py   # Tool dataclass + ToolRegistry
├── gemini_client.py   # from Phase 3
├── orchestrator.py    # the planner loop
└── tools.py           # from Phase 2 — wrappers + schemas
```

## Tool registry

```python
# agent/tool_registry.py
from dataclasses import dataclass
from typing import Any, Callable

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict   # JSON-schema dict (see Phase 2)
    func: Callable

    def schema(self):
        return {"name": self.name, "description": self.description, "parameters": self.parameters}

    def run(self, args: dict) -> Any:
        try:
            return self.func(**(args or {}))
        except TypeError as e:
            return {"error": f"bad args: {e}"}
        except Exception as e:
            return {"error": str(e)}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def run(self, name, args):
        t = self._tools.get(name)
        if t is None:
            return {"error": f"unknown tool: {name}"}
        return t.run(args)
```

Why: tools are pluggable, schemas auto-built, errors land as dicts (LLM-readable) instead of crashing the loop.

## Orchestrator (planner loop)

The loop: send messages → LLM → if it asked for tool calls, run them, append results → repeat until LLM gives final text.

```python
# agent/orchestrator.py
import json

class Orchestrator:
    def __init__(self, llm, registry, model=None, max_iters=10, system_prompt=""):
        self.llm = llm
        self.registry = registry
        self.model = model
        self.max_iters = max_iters
        self.messages = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

    def add_user(self, text):
        self.messages.append({"role": "user", "content": text})

    def step(self):
        """Yield each message produced (assistant tool-calls + tool results + final text)."""
        for _ in range(self.max_iters):
            resp = self.llm.chat(self.messages, tools=self.registry.schemas(), model=self.model)
            text = getattr(resp, "text", "") or ""
            tool_calls = list(getattr(resp, "function_calls", []) or [])

            asst_msg = {"role": "assistant", "content": text, "tool_calls": tool_calls}
            self.messages.append(asst_msg)
            yield asst_msg

            if not tool_calls:
                return  # final answer

            for tc in tool_calls:
                result = self.registry.run(tc.name, dict(tc.args or {}))
                tool_msg = {
                    "role": "tool",
                    "tool_name": tc.name,
                    "content": json.dumps(result, default=str, ensure_ascii=False),
                }
                self.messages.append(tool_msg)
                yield tool_msg

        yield {"role": "assistant", "content": f"[max_iters={self.max_iters} hit]", "tool_calls": []}
```

The loop:
1. Send full history to LLM
2. LLM responds with text + maybe tool calls
3. If tool calls, run each, append result, loop
4. If no tool calls, that's the final answer; return

## System prompt

Give the LLM context about its tools and the user's project. A simple template:

```
You are an automation assistant for the {project_name} project.

Tools you can call: see below.

Behaviors to follow:
- Before destructive operations (delete / overwrite / send), confirm with the user.
- If a tool returns {"error": ...}, explain the problem to the user; don't loop indefinitely.
- When the user asks for status / overview, prefer read tools first to gather facts before answering.
- Reply concisely; use markdown lists / tables when helpful.
```

Tune over time as you watch how the agent handles real requests.

## Wire it up + smoke test

```python
# scripts/agent_repl.py
from dotenv import load_dotenv; load_dotenv()
from agent.gemini_client import GeminiClient
from agent.tool_registry import ToolRegistry
from agent.orchestrator import Orchestrator
from agent.tools import register_all  # you write this in tools.py

registry = ToolRegistry()
register_all(registry)
orch = Orchestrator(GeminiClient(), registry, system_prompt="You help with X project. ...")

while True:
    user = input("you> ").strip()
    if not user:
        break
    orch.add_user(user)
    for msg in orch.step():
        if msg["role"] == "assistant" and not msg.get("tool_calls"):
            print(f"agent> {msg['content']}")
        elif msg["role"] == "assistant":
            for tc in msg["tool_calls"]:
                print(f"  [tool] {tc.name}({dict(tc.args)})")
        elif msg["role"] == "tool":
            preview = msg["content"][:200]
            print(f"     ↳ {preview}")
```

Run it. If you can chat with the agent and it correctly calls a tool from Phase 2, Phase 4 is done.

## Common mistakes

- **`messages` shape mismatch with the SDK** — the wrappers in `assets/gemini_client.py` already convert to Gemini's native `Content`/`Part` types. Don't reinvent.
- **Forgetting to register tools** — the registry has 0 tools and the agent can only chat, never act. Make the smoke test prompt require a tool call.
- **Missing system prompt** — without one, Gemma sometimes wanders or under-uses tools. A 10-line system prompt explaining the agent's role pays off immediately.
