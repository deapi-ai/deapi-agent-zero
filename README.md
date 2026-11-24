# deAPI for Agent Zero

Gives [Agent Zero](https://github.com/agent0ai/agent-zero) image, video, speech and music generation, transcription of files and links (YouTube, TikTok, X, Twitch, Kick), video description and OCR through [deAPI](https://deapi.ai).

The plugin connects to deAPI's hosted MCP server (`https://mcp.deapi.ai/mcp`) and adds two tools:

| Tool | What it does |
| --- | --- |
| `deapi_tools` | Lists deAPI tools and their arguments, optionally filtered (`{"query": "video"}`). |
| `deapi` | Runs one deAPI tool: `{"tool": "text_to_image", "arguments": {"prompt": "a lighthouse at dusk"}}`. |

The tool list comes from the server, so new models and tools show up without a plugin update. Every generation tool has a `*_price` twin that returns the cost without running the job.

## Setup

1. Create an API key at [app.deapi.ai/settings/api-keys](https://app.deapi.ai/settings/api-keys).
2. Set `DEAPI_API_KEY` in the Agent Zero runtime environment (for Docker: `-e DEAPI_API_KEY=...` or the `.env` file that your container reads), then restart Agent Zero.
3. Install the plugin from the Plugin Hub, or clone this repository into `/a0/usr/plugins/deapi`.

Then ask, for example: *"Transcribe https://www.youtube.com/watch?v=... and summarise it"* or *"Make a 16:9 image of a lighthouse at dusk"*.

## Notes

- Jobs are paid from your deAPI balance. Check it with the `get_balance` tool.
- deAPI filters NSFW content. A rejected prompt comes back as an error message, not as a broken tool.
- The key is sent only to `mcp.deapi.ai`, without environment proxies or redirects, and is removed from tool output. Requests carry the `deapi-agent-zero` user agent so deAPI can see traffic from this plugin; nothing about you or your prompts is added.
- To remove the plugin, delete `/a0/usr/plugins/deapi` or turn it off in the Plugin Hub.

## Development

```bash
uv run --no-project --with "mcp==1.27.0" --with "httpx==0.28.1" --with pytest pytest -q tests
```

## License

MIT
