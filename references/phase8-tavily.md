# Phase 8 — Tavily web search (opt-in)

## Why Tavily

Free tier 1000 searches/month. Returns LLM-friendly results (already cleaned of nav cruft, with relevance scores). Single API key, single function. Good fit for adding "look it up online" to an agent without writing a scraper.

## Get the key

1. Sign up at https://tavily.com (Google login works)
2. Dashboard → copy API key (`tvly-...`)
3. Save in `.env`:

```dotenv
TAVILY_API_KEY=tvly-...your_key...
```

## Install

```bash
pip install tavily-python>=0.3
```

## Tool wrapper

```python
# agent/tavily_tool.py
import os
from tavily import TavilyClient

_client = None
def _get():
    global _client
    if _client is None:
        _client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    return _client


def web_search(query: str, max_results: int = 5, search_depth: str = "basic") -> dict:
    """Search the web via Tavily. Returns top results with title, url, content snippet."""
    try:
        r = _get().search(query=query, max_results=max_results, search_depth=search_depth)
    except Exception as e:
        return {"error": str(e)}
    return {
        "query": query,
        "answer": r.get("answer", ""),  # Tavily's quick AI summary
        "results": [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": (item.get("content", "") or "")[:500],  # cap snippet
                "score": item.get("score", 0),
            }
            for item in r.get("results", [])
        ],
    }


def web_search_schema():
    return {
        "name": "web_search",
        "description": (
            "Search the web for current information. Returns up to N results with title, "
            "URL, and content snippet, plus an AI-generated summary in 'answer'. "
            "Use for: current events, library docs, recent news, or any fact you don't know. "
            "search_depth='basic' is fast & cheap; 'advanced' is more thorough but slower."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "max_results": {"type": "integer", "description": "Number of results (1-10). Default 5."},
                "search_depth": {"type": "string", "description": "'basic' (default) or 'advanced'."},
            },
            "required": ["query"],
        },
    }
```

Register in `tools.py`:

```python
from agent.tavily_tool import web_search, web_search_schema
from agent.tool_registry import Tool

def register_all(registry):
    ...existing tools...
    if os.environ.get("TAVILY_API_KEY"):
        registry.register(Tool(
            name="web_search",
            description=web_search_schema()["description"],
            parameters=web_search_schema()["parameters"],
            func=web_search,
        ))
```

The `if os.environ.get(...)` guard means: if the user hasn't set up Tavily yet, the tool simply doesn't get registered. The agent won't try to use it. No errors, no confusion.

## Combining with shell

The agent can chain tools naturally:

> User: "What's the latest version of pandas? Then upgrade my project."

→ `web_search("pandas latest version PyPI")` → answer: 2.4.x  
→ `shell("pip install --upgrade pandas")` → asks user to approve  
→ user clicks ✓ on Telegram  
→ shell runs, returns success  
→ agent: "Done — pandas upgraded to 2.4.1."

This is a small example of why the combo is powerful. With permissions and approval, it's also safe.

## Cost watch

Tavily free tier = 1000 searches/mo. Aggressive agents (especially on auto-loops) burn through this fast. Tips:
- Cache common queries — wrap the tool in a 1-hour TTL cache for the same query
- Rate-limit per chat — e.g., max 20 searches per 24h per user
- Tell the agent in the system prompt: "Use web_search sparingly — for things that change often (news, library versions). For static knowledge, answer from your training."

## Alternatives

- **Brave Search API** (similar shape, 2000/mo free)
- **Serper** (Google results, $50/mo for ~2500/day)
- **DuckDuckGo (`duckduckgo-search` lib)** — unofficial, no key, brittle

If the user is privacy-conscious or doesn't want a Tavily account, suggest DuckDuckGo with the disclaimer that it's less reliable.
