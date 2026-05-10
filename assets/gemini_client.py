"""Gemini SDK wrapper with retry. Drop into your project as agent/gemini_client.py.

Requires:
    pip install google-genai>=2.0.0 python-dotenv>=1.0
"""

import json
import os
import time

try:
    from google import genai
    from google.genai import types as genai_types
    AVAILABLE = True
except ImportError:
    AVAILABLE = False
    genai = None
    genai_types = None


# Gemma 4 transient retry config
_RETRY_STATUS = (500, 502, 503, 504)
_BACKOFF = (1.0, 3.0, 7.0, 15.0)  # accumulate ~26s


def _is_retryable(exc):
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code in _RETRY_STATUS:
        return True
    msg = str(exc)
    return any(f"{c} " in msg or f"code\": {c}" in msg or f"code': {c}" in msg
               for c in _RETRY_STATUS)


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
    def __init__(self, api_key: str = None, default_model: str = "gemma-4-31b-it"):
        if not AVAILABLE:
            raise RuntimeError("google-genai not installed. pip install google-genai>=2.0")
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or ""
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY not set in env")
        self.client = genai.Client(api_key=self.api_key)
        self.default_model = default_model

    def chat(self, messages: list[dict], tools: list[dict] = None, model: str = None):
        """messages: [{role, content, tool_name?}]; tools: list of tool schemas."""
        contents, system = self._convert_messages(messages)

        gemini_tools = None
        if tools:
            decls = [
                genai_types.FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters_json_schema=t.get("parameters", {"type": "object"}),
                )
                for t in tools
            ]
            gemini_tools = [genai_types.Tool(function_declarations=decls)]

        config = genai_types.GenerateContentConfig(
            tools=gemini_tools,
            system_instruction=system or None,
        )

        return _retry(lambda: self.client.models.generate_content(
            model=model or self.default_model,
            contents=contents,
            config=config,
        ))

    def vision_complete(self, system: str, user_text: str, images: list,
                        model: str = "gemma-4-31b-it"):
        """Single-turn vision call. images: list of file paths or bytes."""
        # Gemma 4 quirk: image Parts MUST come before text + system non-empty
        parts = []
        for img in images or []:
            if isinstance(img, (bytes, bytearray)):
                data, mime = bytes(img), "image/png"
            else:
                with open(img, "rb") as f:
                    data = f.read()
                ext = str(img).lower().rsplit(".", 1)[-1]
                mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "png": "image/png", "gif": "image/gif",
                        "webp": "image/webp"}.get(ext, "image/png")
            parts.append(genai_types.Part.from_bytes(data=data, mime_type=mime))
        parts.append(genai_types.Part(text=user_text or ""))

        contents = [genai_types.Content(role="user", parts=parts)]

        is_gemma = "gemma" in (model or "").lower()
        sys_text = system or ("You are a vision assistant." if is_gemma else None)
        config = genai_types.GenerateContentConfig(system_instruction=sys_text)

        resp = _retry(lambda: self.client.models.generate_content(
            model=model, contents=contents, config=config,
        ))
        return getattr(resp, "text", "") or ""

    def list_models(self) -> list[str]:
        try:
            return sorted({
                getattr(m, "name", "").replace("models/", "")
                for m in self.client.models.list()
                if "generateContent" in (
                    getattr(m, "supported_actions", None)
                    or getattr(m, "supported_generation_methods", None)
                    or []
                )
            })
        except Exception:
            return []

    def _convert_messages(self, messages: list[dict]):
        contents = []
        system_parts = []
        for msg in messages:
            role = msg.get("role")
            text = msg.get("content", "") or ""
            if role == "system":
                if text:
                    system_parts.append(text)
                continue
            if role == "user":
                contents.append(genai_types.Content(
                    role="user", parts=[genai_types.Part(text=text)],
                ))
            elif role == "assistant":
                parts = []
                if text:
                    parts.append(genai_types.Part(text=text))
                for tc in msg.get("tool_calls", []):
                    name = getattr(tc, "name", None) or tc.get("name") if isinstance(tc, dict) else tc.name
                    args = getattr(tc, "args", None) or (tc.get("args") if isinstance(tc, dict) else {})
                    parts.append(genai_types.Part(
                        function_call=genai_types.FunctionCall(name=name, args=dict(args or {})),
                    ))
                if parts:
                    contents.append(genai_types.Content(role="model", parts=parts))
            elif role == "tool":
                # function_response needs a dict
                obj = self._coerce_to_dict(text)
                contents.append(genai_types.Content(
                    role="tool",
                    parts=[genai_types.Part.from_function_response(
                        name=msg.get("tool_name", ""), response=obj,
                    )],
                ))
        return contents, "\n\n".join(system_parts)

    @staticmethod
    def _coerce_to_dict(text):
        if not text:
            return {"result": ""}
        try:
            v = json.loads(text)
            return v if isinstance(v, dict) else {"result": v}
        except (json.JSONDecodeError, TypeError):
            return {"result": text}
