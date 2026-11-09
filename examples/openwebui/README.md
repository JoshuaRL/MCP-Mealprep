# Open WebUI example — our stack as the tool provider

Open WebUI is the **client** side: it registers this project's MCP
servers as tools, and supplies the model. Two pieces:

## 1. Register our MCP servers in Open WebUI

In Open WebUI **Admin → External Connections → MCP**, add each gateway
URL with the bearer key from your gateway secret file, e.g.:

| Name | URL | Auth |
|---|---|---|
| mealprep-everything | `http://127.0.0.1:8081/mcp` | Bearer `<gateway key>` |
| mealprep-memory | `http://127.0.0.1:8086/mcp` | Bearer `<gateway key>` |
| mealprep-fetch | `http://127.0.0.1:8082/mcp` | Bearer `<gateway key>` |

Full runnable layout: see `openwebui-mcp-connection.json` (placeholders
only — put the real key in your secret file, never in this file).
Verify in the chat UI that the tool list shows the expected tools
before attaching them to a chat.

## 2. Model backend — pick your provider

Open WebUI accepts local **and** cloud models. Examples:

- **Local:** Ollama (`http://127.0.0.1:11434`) — free, private, slower
  on small hardware. (Our validation used local Qwen via Ollama.)
- **Cloud — OpenRouter:** enable the OpenRouter connection in Admin →
  External Connections, paste your API key, pull a model id (e.g.
  `openai/gpt-4o-mini`). No local GPU needed.
- **Cloud — Hugging Face:** enable the Hugging Face connection, paste
  your HF token, pull e.g. `meta-llama/Llama-3.1-8B-Instruct`.
- **Cloud — Ollama Cloud:** enable the Ollama connection pointed at
  `https://ollama.com` (hosted Ollama models, no local download).

Trade-off, stated plainly: local models keep everything private but
smaller ones are weak at tool use (our 1.5B didn't call tools; 3B
called them but answered poorly). Cloud models generally use tools
better but send prompt text to the provider. For public-documentation
queries we validated with Microsoft Learn MCP, prompt text is
non-sensitive either way.

## What this example does NOT do

- Doesn't ship Open WebUI or a model — they're your infra.
- Doesn't grant tools to unrelated users — connection visibility and
  per-user tool access are Open WebUI settings; verify them yourself
  after registering (we confirmed isolation by observation: unrelated
  accounts don't see these connections, per 2026-11-06 owner note).
