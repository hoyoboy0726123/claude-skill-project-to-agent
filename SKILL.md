---
name: project-to-agent
description: |
  Transform any existing software project (Python script, CLI tool, automation, web app, library, etc.) into a self-evolving conversational agent. Wraps existing functions as Gemini/Gemma tools, sets up a Telegram bot front-end so the user can chat & trigger operations remotely, requests folder permissions, optionally adds shell-bash tools (so the agent can write code & even modify itself), and Tavily web search. Make sure to use this skill whenever the user mentions: turning a project into an agent, "agentify", building a Telegram bot for an existing tool, exposing a Python script as a chat-driven assistant, self-improving / self-evolving agent, adding LLM control to an existing app, packaging functions as tools for an LLM, or making any tool remote-controllable through chat. Trigger even when the user only says "make my X chat-controllable" or "turn this into a bot" — those are calls for this skill.
---

# project-to-agent

Turn an existing project into a Telegram-controllable agent that can call its own functions, write code, search the web, and grow new capabilities over time.

## What this skill produces

By the end, the user's project has:

- An **agent core** (orchestrator + tool registry) that can converse and call tools
- **Existing project functions wrapped as tools** the agent can invoke
- **Gemma-4-31B** (Google AI Studio free tier) as the brain
- **Telegram bot adapter** so user can chat to the agent on the go and receive output files
- **Folder permission boundaries** — agent only touches what user explicitly allowed
- **Shell tool (optional)** with confirmation — agent can write code & even patch itself
- **Tavily web search (optional)** for fact-finding & research

The result is a project that **users keep teaching new tricks** through natural conversation — every new tool the agent gains is one fewer manual task for them.

## Core philosophy

1. **Existing project is the seed.** Whatever the project already does, that's what the agent should be able to drive on day 1. Don't start from scratch — wrap.
2. **Permissions are explicit, never assumed.** The agent only writes to folders the user said yes to. Shell access is opt-in. Self-modify is opt-in.
3. **Self-evolution = adding tools.** New capability = new tool = small, scoped function. The agent can suggest & write new tools; user approves before they become live.
4. **The user owns the keys.** API keys go in `.env`, gitignored. Telegram bot token, Gemini key, Tavily key — all user's.

## When the skill triggers

- User has a project (any language, any size) and says "make this an agent" / "I want to chat with this" / "turn this into a Telegram bot"
- User wants to talk to a remote machine running their project
- User says they want to "automate" their project further
- User asks how to give an LLM control over their existing tool

## Phased workflow

The skill walks the user through 9 phases. Don't dump them all at once — work phase-by-phase, checking in after each.

| # | Phase | Reference |
|---|---|---|
| 1 | **Analyze the project** — understand what it does | `references/phase1-analyze.md` |
| 2 | **Identify tool candidates** — pick functions worth exposing | `references/phase2-tools.md` |
| 3 | **LLM setup (Gemma-4-31B + Google AI Studio)** | `references/phase3-llm.md` |
| 4 | **Build agent core (orchestrator + registry)** | `references/phase4-core.md` |
| 5 | **Permission boundaries** — folder ACL | `references/phase5-permissions.md` |
| 6 | **Telegram bot adapter** | `references/phase6-telegram.md` |
| 7 | **Shell tool (opt-in)** — let agent run bash & write code | `references/phase7-shell.md` |
| 8 | **Tavily web search (opt-in)** | `references/phase8-tavily.md` |
| 9 | **Self-evolution loop** — agent proposes new tools | `references/phase9-evolve.md` |

## Phase-by-phase summary

### Phase 1 — Analyze the project

Read the codebase to understand: language, entry points, existing CLI / functions / API endpoints, dependencies, what data flows where. Produce a one-paragraph summary the user can confirm or correct. **Don't move on until the user agrees on what the project does.** Detail in `references/phase1-analyze.md`.

### Phase 2 — Identify tool candidates

From the analysis, propose 5–15 functions that could become agent tools. Each tool should: do one thing, have clear input/output, be safe to call repeatedly. Skip functions that are pure-helpers, take-no-args setup, or destructive without confirmation. Show the list to the user, let them edit. Detail in `references/phase2-tools.md`.

### Phase 3 — LLM setup

Walk the user through getting a Gemini API key from Google AI Studio (https://aistudio.google.com/apikey — free tier, no payment required). Save in `.env` as `GEMINI_API_KEY`. Confirm `.env` is gitignored. Default model: `gemma-4-31b-it`. Detail (incl. the chat / vision quirks of Gemma 4 + retry pattern) in `references/phase3-llm.md`.

### Phase 4 — Build agent core

Create `agent/` directory in the project with:
- `tool_registry.py` (Tool + ToolRegistry classes)
- `gemini_client.py` (Gemini SDK wrapper with retry)
- `orchestrator.py` (planner loop: chat → tool calls → tool results → loop until final text)
- Wrap the Phase 2 tools in `tools.py`

The orchestrator does: send user message → LLM → if tool calls, run them, append results, loop → final text. See `assets/agent_template.py` for a copy-pasteable starting point. Detail in `references/phase4-core.md`.

### Phase 5 — Permission boundaries

Before letting the agent touch the filesystem, **explicitly ask the user**:
- Which folders may the agent **read** from?
- Which folders may it **write** to?
- Which folders may it **delete** files in?

Save as `agent/permissions.json`. Every file-touching tool must call `check_permission(path, op)` before acting. Detail in `references/phase5-permissions.md`.

### Phase 6 — Telegram bot adapter

User creates a bot via @BotFather, gets the token, saves it as `TELEGRAM_BOT_TOKEN` in `.env`. The adapter in `agent/telegram_adapter.py` listens for messages, forwards to orchestrator, sends back assistant replies. **Output files** (e.g., generated docx, plot.png) get sent as Telegram documents/photos. Detail in `references/phase6-telegram.md`.

### Phase 7 — Shell tool (opt-in)

If the user wants the agent to write code / modify itself / run arbitrary commands, add a `shell` tool. **It must require user approval per call** (Telegram inline button) — never auto-execute. Sandbox to allowed folders from Phase 5. This is what enables self-evolution. Detail in `references/phase7-shell.md`.

### Phase 8 — Tavily web search (opt-in)

If the user wants the agent to search the web, add Tavily integration. Free tier 1000 searches/mo; key from https://tavily.com. Wrapped as a `web_search` tool. Detail in `references/phase8-tavily.md`.

### Phase 9 — Self-evolution loop

With shell + permissions in place, teach the user the `agent_propose_tool` flow: when the user asks the agent to do something it can't, the agent drafts a new tool, shows the diff, asks for approval, and the user merges it on Telegram. Detail in `references/phase9-evolve.md`.

## Order of operations

You don't have to do all 9 phases in one session. The minimum viable agent is **Phases 1–6** (analyze → tools → LLM → core → permissions → Telegram). Phases 7–9 unlock self-evolution but each is a clear opt-in moment for the user.

After each phase, **commit to git**. This makes rollback trivial if a phase goes wrong.

## What to NOT do

- Don't write tools that take no arguments and rely on global state — they're hard for the LLM to reason about
- Don't hardcode API keys in code — `.env` only
- Don't add shell access without phase 5 permissions in place — too dangerous
- Don't auto-execute shell commands sent from Telegram — always require explicit user approval
- Don't expose tools that touch the filesystem without going through the permission check
- Don't use `gemini-2.5-pro` etc. by default — Gemma-4-31B is free and supports tools/vision; the user can upgrade later
- Don't try to wrap *every* function — focus on the ones the user does manually & repeatedly. The tools list grows organically through Phase 9.

## Tone with the user

You're working *with* the user, not *for* them. They know their project; you know agent design. After each phase, **show them what you did, ask if it's right, then proceed**. If the project is in a language you don't recognize well, say so and ask the user to confirm your interpretation.

When recommending the optional pieces (shell, Tavily, self-evolution), explain the trade-offs honestly:
- Shell: huge power, real risk if folders not scoped right
- Tavily: 1000/mo free tier ample for personal use, paid for high-volume
- Self-evolution: makes the project compound; but every new tool is new code the user needs to skim

## See also

- `references/phase*.md` — detailed how-tos per phase (read when working on that phase)
- `assets/agent_template.py` — drop-in agent core for Python projects
- `assets/telegram_adapter.py` — Telegram bot starter
- `assets/permissions.json.example` — permission file template
- `assets/.env.example` — environment variable template
- `assets/requirements.txt` — Python deps for the agent layer
