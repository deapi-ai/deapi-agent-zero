"""Client for the hosted deAPI MCP server (https://mcp.deapi.ai/mcp).

The plugin does not copy deAPI's tool list. It asks the server for it, so new
models and tools appear without a plugin update.
"""

import asyncio
import json
import os
from urllib.parse import quote

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

ENDPOINT = "https://mcp.deapi.ai/mcp?source=agent-zero"
VERSION = "0.1.1"
# Tells deAPI which integration a request came from. No user data.
SOURCE_HEADERS = {"User-Agent": f"deapi-agent-zero/{VERSION}", "X-Deapi-Source": "agent-zero"}
LIST_TIMEOUT_SECONDS = 60
# Video generation and long transcriptions wait for the job to finish.
CALL_TIMEOUT_SECONDS = 900
MAX_OUTPUT_CHARS = 20000


class DeapiError(Exception):
    """Holds only messages that are safe to show in the agent history."""


def _api_key() -> str:
    key = os.environ.get("DEAPI_API_KEY", "").strip()
    if not key:
        raise DeapiError(
            "Set DEAPI_API_KEY in the Agent Zero runtime environment, then retry. "
            "Get a key at https://app.deapi.ai/settings/api-keys."
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in key):
        raise DeapiError("DEAPI_API_KEY contains invalid header characters.")
    return key


def _http_client(headers=None, timeout=None, auth=None):
    # Never forward the key through environment proxies or redirects.
    return httpx.AsyncClient(
        headers=headers, timeout=timeout, auth=auth, follow_redirects=False, trust_env=False
    )


REDACTED = "[REDACTED]"
# The secret part of a key is long; a shorter tail would match ordinary text.
MIN_SECRET_TAIL = 16


def _secret_forms(key: str) -> list[str]:
    """The key as it may appear in a response: as is, URL-encoded, JSON-escaped,
    and its secret part alone (after the last '-' of sk-dp-<id>-<secret> or the
    '|' of a raw <id>|<secret> key). Longest first, so no form is left half-replaced."""
    forms = {key, quote(key, safe=""), json.dumps(key)[1:-1]}
    for separator in ("|", "-"):
        tail = key.rsplit(separator, 1)[-1]
        if len(tail) >= MIN_SECRET_TAIL:
            forms.add(tail)
            forms.add(quote(tail, safe=""))
    return sorted((form for form in forms if form), key=len, reverse=True)


def _redact(text: str, key: str) -> str:
    if not key:
        return text
    for form in _secret_forms(key):
        text = text.replace(form, REDACTED)
    return text


def _limit(text: str) -> str:
    """Trim long output. Call only on text that is already redacted: trimming
    first could cut the key in two and leave a fragment that redaction misses."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n[truncated, {len(text)} characters in total]"


async def _session_call(key: str, timeout: float, action):
    headers = {"Authorization": f"Bearer {key}", **SOURCE_HEADERS}
    async with asyncio.timeout(timeout):
        async with streamablehttp_client(
            ENDPOINT,
            headers=headers,
            timeout=30,
            sse_read_timeout=timeout,
            httpx_client_factory=_http_client,
        ) as (reader, writer, _), ClientSession(reader, writer) as session:
            await session.initialize()
            return await action(session)


def format_tools(tools, query: str = "") -> str:
    """One block per tool: name, description and argument schema."""
    words = [w for w in query.lower().split() if w]
    blocks = []
    for tool in tools:
        haystack = f"{tool.name} {tool.description or ''}".lower()
        if words and not all(w in haystack for w in words):
            continue
        schema = tool.inputSchema or {}
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        args = []
        for name, spec in props.items():
            kind = spec.get("type") or "/".join(
                s.get("type", "?") for s in spec.get("anyOf", []) if s.get("type") != "null"
            )
            mark = " (required)" if name in required else ""
            desc = (spec.get("description") or "").strip()
            enum = spec.get("enum")
            if enum:
                desc += f" One of: {', '.join(map(str, enum))}."
            default = spec.get("default")
            if default not in (None, ""):
                desc += f" Default: {default}."
            args.append(f"  - {name}: {kind}{mark}. {desc}".rstrip())
        first_line = (tool.description or "").strip().splitlines()[0] if tool.description else ""
        blocks.append(f"{tool.name}: {first_line}\n" + "\n".join(args))
    if not blocks:
        return f"No deAPI tool matches '{query}'. Call deapi_tools with no query to see all tools."
    return "\n\n".join(blocks)


async def list_tools(query: str = "") -> str:
    if not isinstance(query, str) or len(query) > 200:
        raise DeapiError("query must be a string of at most 200 characters.")
    key = _api_key()
    try:
        result = await _session_call(key, LIST_TIMEOUT_SECONDS, lambda s: s.list_tools())
        return _limit(_redact(format_tools(result.tools, query), key))
    except DeapiError:
        raise
    except TimeoutError:
        raise DeapiError("deAPI did not answer in time. Retry later.") from None
    except Exception:  # noqa: BLE001 -- SDK errors can carry headers; never echo them
        raise DeapiError(
            "Could not reach deAPI. Check DEAPI_API_KEY, the connection and https://status.deapi.ai."
        ) from None


async def call_tool(name: str, arguments) -> str:
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise DeapiError("tool must be the name of a deAPI tool from deapi_tools.")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            raise DeapiError("arguments must be a JSON object.") from None
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise DeapiError("arguments must be a JSON object.")
    key = _api_key()
    try:
        result = await _session_call(
            key, CALL_TIMEOUT_SECONDS, lambda s: s.call_tool(name.strip(), arguments)
        )
    except DeapiError:
        raise
    except TimeoutError:
        raise DeapiError(
            "The deAPI job is taking longer than 15 minutes. Check it later with the "
            "check_job_status tool and its request id."
        ) from None
    except Exception:  # noqa: BLE001
        raise DeapiError(
            "The deAPI call failed. Check the tool name, DEAPI_API_KEY and the connection."
        ) from None
    texts = [block.text for block in result.content if getattr(block, "type", "") == "text"]
    text = "\n".join(texts).strip() or "deAPI returned no text."
    # Redact before trimming, never after: see _limit.
    text = _limit(_redact(text, key))
    if result.isError:
        raise DeapiError(f"deAPI rejected the call: {text}")
    return text
