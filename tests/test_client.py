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
