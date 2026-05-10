# Phase 3 — LLM setup (Gemma-4-31B + Google AI Studio)

## Why Gemma-4-31B

Free tier on Google AI Studio supports it for both **chat with tools** AND **vision** (image input). The user gets a real agent without paying anything until they outgrow free tier limits. It's the right default.

If the user later needs a stronger model, they can just change one string (`gemma-4-31b-it` → `gemini-2.5-flash` / `gemini-3-pro-preview` / etc.). Same SDK, same code path.

## Get the API key

1. Open https://aistudio.google.com/apikey
2. Sign in with Google
3. "Create API key" → copy the `AIza...` string
4. Save in the project's `.env`:

```dotenv
GEMINI_API_KEY=AIza...your_key...
```

5. Confirm `.env` is in `.gitignore` — if not, add it BEFORE committing anything.

## Install the SDK

The new Google GenAI SDK (NOT the old `google-generativeai`):

```bash
pip install google-genai>=2.0.0 python-dotenv>=1.0
```

The old `google-generativeai` package was deprecated in 2025. Don't use it.

## Minimal client (with retry)

Gemma-4-31B on Gemini API hits transient `500 INTERNAL` / `503 UNAVAILABLE` more often than paid Gemini models. Wrap calls with retry:

```python
# agent/gemini_client.py
import os, time
from google import genai
from google.genai import types as genai_types

_RETRYABLE = (500, 502, 503, 504)
_BACKOFF = (1, 3, 7, 15)  # 4 retries, total wait ~26s

def _is_retryable(e):
    code = getattr(e, "code", None) or getattr(e, "status_code", None)
    if code in _RETRYABLE:
        return True
    msg = str(e)
    return any(f"{c} " in msg for c in _RETRYABLE)

def _retry(fn):
    last = None
    for i in range(len(_BACKOFF) + 1):
        try:
            return fn()
        except Exception as e:
            last = e
            if i >= len(_BACKOFF) or not _is_retryable(e):
                raise
            time.sleep(_BACKOFF[i])
    if last:
        raise last


class GeminiClient:
    def __init__(self, api_key=None, default_model="gemma-4-31b-it"):
        self.api_key = api_key or os.environ["GEMINI_API_KEY"]
        self.client = genai.Client(api_key=self.api_key)
        self.default_model = default_model

    def chat(self, messages, tools=None, model=None):
        """messages: list of {'role': 'user'|'assistant'|'tool', 'content': ..., 'tool_name'?: ...}"""
        contents, system = self._convert(messages)
        gemini_tools = self._convert_tools(tools) if tools else None
        config = genai_types.GenerateContentConfig(
            tools=gemini_tools,
            system_instruction=system or None,
        )
        return _retry(lambda: self.client.models.generate_content(
            model=model or self.default_model,
            contents=contents,
            config=config,
        ))
```

The full `_convert` and `_convert_tools` helpers are in `assets/gemini_client.py` (working copy you can drop into the project).

## Gemma 4 vision quirk (only matters if you use vision)

Gemma-4-31B vision works on Gemini API **only if**:
1. Image `Part`s come **before** the text `Part` in the user message
2. `system_instruction` is non-empty (don't pass `None` / `""`)

For Gemini-2.x and 3.x, neither matters — they're forgiving. The fix in `vision_complete` is small but essential for Gemma:

```python
def vision_complete(self, system, user_text, images, model):
    parts = []
    for img in images:
        with open(img, "rb") as f:
            data = f.read()
        parts.append(genai_types.Part.from_bytes(data=data, mime_type="image/png"))
    parts.append(genai_types.Part(text=user_text))  # text LAST
    contents = [genai_types.Content(role="user", parts=parts)]
    sys_text = system or "你是視覺助理。"  # MUST be non-empty for Gemma
    config = genai_types.GenerateContentConfig(system_instruction=sys_text)
    return _retry(lambda: self.client.models.generate_content(
        model=model, contents=contents, config=config,
    ))
```

## Test the connection

Before wiring up the orchestrator, make sure the key works:

```python
from agent.gemini_client import GeminiClient
c = GeminiClient()
r = c.chat([{"role": "user", "content": "say hi in one word"}])
print(r.text)
```

If this prints "Hi" (or similar), Phase 3 is done. If it errors, common causes:
- Wrong key (regenerate, the key starts with `AIza`)
- Region restriction (some countries can't access free tier; user may need a VPN to a supported region for setup)
- Quota burst (rare — wait 60s and retry)

## Save model defaults to .env

Let the user override defaults without editing code:

```dotenv
GEMINI_API_KEY=AIza...
PLANNER_MODEL=gemma-4-31b-it
REVIEWER_MODEL=gemma-4-31b-it
```

Read with `os.environ.get("PLANNER_MODEL", "gemma-4-31b-it")` so defaults still work if the var is missing.
