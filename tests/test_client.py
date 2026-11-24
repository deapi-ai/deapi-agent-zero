import asyncio
import importlib.util
import pathlib
from types import SimpleNamespace

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("deapi_client", ROOT / "helpers" / "client.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def tool(name, description, props, required=()):
    return SimpleNamespace(
        name=name,
        description=description,
        inputSchema={"properties": props, "required": list(required)},
    )


TOOLS = [
    tool(
        "video_url_transcription",
        "Transcribe a video from a URL.\nMore text.",
        {
            "video_url": {"type": "string", "description": "Video link"},
            "include_ts": {"type": "boolean", "description": "Timestamps"},
            "lang": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        },
        required=("video_url", "include_ts"),
    ),
    tool("text_to_image", "Generate an image.", {"prompt": {"type": "string", "enum": None}}),
]


def test_format_lists_every_tool_with_required_args():
    out = client.format_tools(TOOLS)
    assert "video_url_transcription: Transcribe a video from a URL." in out
    assert "More text" not in out
    assert "video_url: string (required)" in out
    assert "lang: string." in out
    assert "text_to_image" in out


def test_format_filters_by_all_words():
    out = client.format_tools(TOOLS, "video transcribe")
    assert "video_url_transcription" in out and "text_to_image" not in out
    assert "No deAPI tool matches" in client.format_tools(TOOLS, "nothing-like-this")


def test_missing_key_is_a_safe_error(monkeypatch):
    monkeypatch.delenv("DEAPI_API_KEY", raising=False)
    with pytest.raises(client.DeapiError, match="Set DEAPI_API_KEY"):
        asyncio.run(client.list_tools())


@pytest.mark.parametrize("arguments", ["[1]", "not json", 5])
def test_arguments_must_be_an_object(monkeypatch, arguments):
    monkeypatch.setenv("DEAPI_API_KEY", "sk-dp-test")
    with pytest.raises(client.DeapiError, match="JSON object"):
        asyncio.run(client.call_tool("text_to_image", arguments))


def test_call_returns_text_and_redacts_key(monkeypatch):
    monkeypatch.setenv("DEAPI_API_KEY", "sk-dp-secret")
    seen = {}

    async def fake(key, timeout, action):
        session = SimpleNamespace()

        async def call_tool(name, args):
            seen["call"] = (name, args)
            return SimpleNamespace(
                isError=False,
                content=[SimpleNamespace(type="text", text="url https://x/y.png sk-dp-secret")],
            )

        session.call_tool = call_tool
        seen["key"] = key
        return await action(session)

    monkeypatch.setattr(client, "_session_call", fake)
    out = asyncio.run(client.call_tool("text_to_image", '{"prompt": "a cat"}'))
    assert seen["call"] == ("text_to_image", {"prompt": "a cat"})
    assert seen["key"] == "sk-dp-secret"
    assert "https://x/y.png" in out and "sk-dp-secret" not in out


def test_tool_error_is_reported(monkeypatch):
    monkeypatch.setenv("DEAPI_API_KEY", "sk-dp-secret")

    async def fake(key, timeout, action):
        return SimpleNamespace(isError=True, content=[SimpleNamespace(type="text", text="Insufficient balance")])

    monkeypatch.setattr(client, "_session_call", fake)
    with pytest.raises(client.DeapiError, match="Insufficient balance"):
        asyncio.run(client.call_tool("text_to_video", {}))


def test_transport_errors_do_not_leak(monkeypatch):
    monkeypatch.setenv("DEAPI_API_KEY", "sk-dp-secret")

    async def fake(key, timeout, action):
        raise RuntimeError("401 Authorization: Bearer sk-dp-secret")

    monkeypatch.setattr(client, "_session_call", fake)
    with pytest.raises(client.DeapiError) as err:
        asyncio.run(client.list_tools())
    assert "sk-dp-secret" not in str(err.value)


KEY = "sk-dp-26669-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdef"
RAW_KEY = "26669|AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdef"
SECRET = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcdef"


def fragments(secret, size=8):
    return {secret[i : i + size] for i in range(len(secret) - size + 1)}


def leaks(text, secret=SECRET):
    return [f for f in fragments(secret) if f in text]


def fake_result(text, is_error=False):
    async def fake(key, timeout, action):
        return SimpleNamespace(isError=is_error, content=[SimpleNamespace(type="text", text=text)])

    return fake


@pytest.mark.parametrize("offset", range(-len(KEY), 2))
def test_key_cut_by_the_output_limit_does_not_leak(monkeypatch, offset):
    # Put the key at every position around the cut, including straddling it.
    monkeypatch.setenv("DEAPI_API_KEY", KEY)
    text = "a" * (client.MAX_OUTPUT_CHARS + offset) + KEY + "b" * 500
    monkeypatch.setattr(client, "_session_call", fake_result(text))
    out = asyncio.run(client.call_tool("text_to_image", {}))
    assert "[truncated," in out
    assert not leaks(out)


def test_key_cut_in_an_error_message_does_not_leak(monkeypatch):
    monkeypatch.setenv("DEAPI_API_KEY", KEY)
    text = "x" * (client.MAX_OUTPUT_CHARS - 10) + KEY
    monkeypatch.setattr(client, "_session_call", fake_result(text, is_error=True))
    with pytest.raises(client.DeapiError) as err:
        asyncio.run(client.call_tool("text_to_image", {}))
    assert not leaks(str(err.value))


@pytest.mark.parametrize(
    "key, echoed",
    [
        (KEY, KEY),
        (KEY, "Bearer " + KEY),
        (KEY, SECRET),  # secret part alone
        (RAW_KEY, RAW_KEY),
        (RAW_KEY, "26669%7C" + SECRET),  # URL-encoded raw key
        ("dpn-sk-" + RAW_KEY, "dpn-sk-" + RAW_KEY),
    ],
)
def test_every_form_of_the_key_is_redacted(monkeypatch, key, echoed):
    monkeypatch.setenv("DEAPI_API_KEY", key)
    monkeypatch.setattr(client, "_session_call", fake_result(f"before {echoed} after"))
    out = asyncio.run(client.call_tool("text_to_image", {}))
    assert out.startswith("before ") and out.endswith(" after")
    assert "[REDACTED]" in out
    assert not leaks(out)


def test_short_key_parts_are_not_redacted_from_normal_text():
    # Only the full key and a long secret part are replaced, so ids and words stay readable.
    assert client._redact("job 26669 done, see sk-dp docs", KEY) == "job 26669 done, see sk-dp docs"


def test_tool_list_is_redacted_and_limited(monkeypatch):
    monkeypatch.setenv("DEAPI_API_KEY", KEY)
    long_tool = tool("echo", "Echo " + KEY, {"x": {"type": "string", "description": "y" * 30000}})

    async def fake(key, timeout, action):
        return SimpleNamespace(tools=[long_tool])

    monkeypatch.setattr(client, "_session_call", fake)
    out = asyncio.run(client.list_tools())
    assert not leaks(out)
    assert len(out) <= client.MAX_OUTPUT_CHARS + 60
