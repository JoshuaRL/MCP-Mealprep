# Client connections and optional OpenAPI bridge

**Evidence boundary:** the local smoke tests exercise real gateway/mcpo containers
with synthetic keys, HTTP/MCP requests and tool results. They do **not** launch
Open WebUI, n8n, Claude, Cursor or OpenCode, call a model, or prove those apps work
end-to-end. The examples below follow the primary documentation checked 2026-11-03.
Review/merge them manually; none is automatically loaded or installed by this repo.

## Endpoints and keys

Default gateway transport is now **stateful Streamable HTTP** at `/mcp`. The former
default `/sse` endpoint is not simultaneously enabled. Set `MCP_TRANSPORT=sse` for
the legacy `/sse` + `/message` pair. Unknown transports fail closed. This is a
deliberate configuration change; existing SSE clients need an explicit setting.

| Connection | Same-host URL (Everything example) | Credential |
| --- | --- | --- |
| Native MCP | `http://127.0.0.1:8081/mcp` | gateway key |
| Explicit legacy SSE | `http://127.0.0.1:8081/sse` | gateway key on GET and every POST |
| Optional OpenAPI | `http://127.0.0.1:8000` | **distinct mcpo key** |
| OpenAPI schema / example tool | `/openapi.json`, `POST /echo` on port 8000 | mcpo key |

Use `Authorization: Bearer <key>`. Do not supply keys in URLs or command arguments.
Port 8081 is the Everything test server, not all services or a useful production
toolkit; select the intended integration and its port. The samples are key-only,
not OAuth services. “Streamable HTTP” is the transport; our verified handshake is
MCP **2025-11-25**, not a guarantee of `2026-07-28` support.

All host bindings stay on loopback. `localhost` means the machine/container running
the client, not necessarily your browser or Docker host. For a client container,
deliberately join a reviewed private network and use service DNS (e.g.
`http://mcp-mealprep-everything:8081/mcp` or `http://mcp-mealprep-mcpo:8000`). A
host loopback binding is not normally reachable via `host.docker.internal` on Linux.
No existing client networks are modified here. Remote clients need separately
reviewed HTTPS/network access; do not broaden ports to fix a connection error.

## Optional mcpo service

Prepare **two distinct randomly generated key files**, `gateway_api_key` and
`mcpo_api_key`, under your private `MEALPREP_SECRET_DIR` (or ignored `./secrets`).
Follow [deployment permissions](DEPLOYMENT.md): UID 1000 must read them; real keys
must not be world-readable. The bridge refuses missing/invalid/reused keys.

```sh
docker compose -f docker-compose.yml -f docker-compose.mcpo.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.mcpo.yml \
  up --build -d mcp-mealprep-mcpo
```

This starts the selected Everything gateway and a separate bridge on port 8000,
not the whole catalog. The overlay waits for a bounded authenticated HTTP listener
probe; that probe is **not** tool health. mcpo must still initialize and discover
tools before serving its schema. Upstream authentication errors must not be
treated as readiness or worked around by disabling auth.

The optional `mcpo` Docker target pins mcpo 0.0.20, MCP Python SDK 1.26.0,
FastAPI 0.135.0 and Starlette 1.10.0. FastAPI 0.162.0 rejected mcpo's constructor
arguments in the first real-image test; the compatible version is deliberate.
Other transitive dependencies remain mutable; these pins are not a CVE clearance
or hermetic build. The default image does not include this optional dependency set.

`mcpo_bridge.py` calls the pinned mcpo API with in-memory credentials because its
CLI lacks file-key options. It does not generate a credential-bearing config or
pass secrets in argv. `strict_auth` protects schema, docs and tool routes. Logs are
fixed to warning level. Keys/files remain accessible within this trusted container;
mcpo's middleware also supports Basic auth on protected routes, but use Bearer.

The bridge proxies the existing `/mcp` gateway; it does not spawn another backend
command. Its MCP session is separate from a native client's session, which can
mean separate backend processes/state. **This is not a shared Memory session or
safe multi-writer design.** Do not point simultaneous Memory writers at the same
JSONL file. Changing the upstream requires deliberately editing the URL, dependency,
probe and key mounts; no automatic catalog aggregation is supplied.

## Open WebUI (OpenAPI)

For a personal **User Tool Server**, upstream docs use **Settings → Integrations →
Tools → Add**. Direct Integrations/permissions may need admin approval. Set the
server URL to `http://127.0.0.1:8000`, schema path `/openapi.json`, auth **Bearer**
with the **mcpo key**, not your Open WebUI session token or the gateway key. Enable
the tool for the current chat and choose a tool-capable model yourself. No model
run is performed by this change.

User-tool requests originate in the **browser**. The default allowed browser origin
is exactly `http://localhost:3000`; set `MCPO_ALLOWED_ORIGIN` to the actual trusted
Open WebUI origin (scheme, host, port; no trailing slash). Wildcards are rejected.
Strict auth means opening `/docs` in a bare browser tab without a header gets 401;
that is expected, not a reason to make documentation public. Authenticated protocol
checks below work without a browser. HTTPS/mixed-content/private-network browser
rules can still block a direct local connection; actual browser testing is deferred.

For an admin **Global Tool Server**, requests originate in the **Open WebUI backend**.
Use its deliberately reachable bridge DNS URL, not that container's localhost.
Keep cookie/user-header forwarding off unless separately justified. This single
upstream bridge serves its schema at the root: do not add `/everything` (mcpo's
multi-server config subpaths are not used). Native MCP-capable Open WebUI versions
can alternatively connect directly to `/mcp` with the gateway key and skip mcpo.

## OpenCode V2

Merge [examples/opencode-v2.json](../examples/opencode-v2.json) into the desired
project `opencode.json(c)` only after review; preserve unrelated settings. Native
V2 nests named entries under **`mcp.servers`**. It uses environment substitution
`{env:MEALPREP_GATEWAY_KEY}`, `oauth: false` for this exclusively key-based server,
and `protocol: legacy` for the tested initialize handshake. Here `legacy` refers
to the **protocol revision**, not the HTTP transport: the URL is still `/mcp`.

Make `MEALPREP_GATEWAY_KEY` available to the OpenCode service process via your own
secret workflow. Never paste its value into the config or CLI `--header`. Check
`opencode mcp list` and `/mcps` for actual connected status before claiming success.
No OpenCode config, service or permissions are changed here; no sign-in is needed
for this key-only gateway. OpenCode V2 watches saved config changes automatically.

## Claude Code and Cursor

- **Claude Code:** merge [examples/claude-code.json](../examples/claude-code.json)
  into the intended `.mcp.json` or personal MCP settings, preserving existing
  entries. Its explicit `type: http` and `${MEALPREP_GATEWAY_KEY}` header expansion
  follow Claude Code's docs. Approve project servers through Claude's own trust
  flow and check `/mcp` / `claude mcp get mealprep` for connection status.
- **Cursor:** merge [examples/cursor.json](../examples/cursor.json) into the intended
  `.cursor/mcp.json` or personal MCP configuration. Its interpolation syntax is
  `${env:MEALPREP_GATEWAY_KEY}`, **not** OpenCode's `{env:...}`. Check Customize/MCP
  connection status and keep tool approvals enabled for the initial call.

Both require the gateway key to be available to their actual process. CLI and GUI
launch environments may differ. These are docs-derived examples, not app-tested
compatibility claims. Claude **Desktop/web connectors** are not Claude Code; this
repo does not provide a verified Desktop adapter or the public HTTPS/OAuth connector
deployment some versions require. Do not assume the same configuration applies.

## n8n

The checked MCP Client Tool docs expose **SSE Endpoint**, authentication and tool
selection. For a version with that interface, use the explicit legacy override:

```sh
docker compose -f docker-compose.yml -f examples/compose.sse.yml \
  up --build -d mcp-mealprep-everything
```

In n8n's MCP Client Tool, set **SSE Endpoint** to the gateway's reachable `/sse`
URL, **Authentication** to **Bearer**, and use a credential containing the gateway
key. Restrict **Tools to Include** to the intended tool (e.g. `echo` for the test
server). n8n's process/worker must reach the URL; in a separate container, its
localhost does not mean Mealprep. Do not combine this SSE override with the HTTP
mcpo overlay for the same gateway. If your installed n8n version explicitly offers
Streamable HTTP, use `/mcp` without the SSE override and test that version first;
the doc's “SSE Endpoint” label alone does not prove HTTP compatibility.

## Exact protocol examples (no model or app required)

These examples run **from this checkout on the Docker host**. Point the file-path
environment variables at private key files; they contain paths, not key values.
Start only the gateway/bridge described above, using Streamable HTTP for the first
example. The helper is a bounded smoke client, not a production SDK.

```sh
export MEALPREP_GATEWAY_KEY_FILE=/private/mealprep/gateway_api_key
python3 - <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, 'tests')
from integration_optional import HttpClient
from integration_smoke import text, tool
client = HttpClient(8081, key=Path(os.environ['MEALPREP_GATEWAY_KEY_FILE']).read_text().strip())
try:
    print(client.initialize()['protocolVersion'])
    print([t['name'] for t in client.rpc('tools/list')['tools']])
    print(text(tool(client, 'echo', {'message': 'synthetic-client-check'})))
finally:
    client.close()
PY
```

```sh
export MEALPREP_MCPO_KEY_FILE=/private/mealprep/mcpo_api_key
python3 - <<'PY'
import json, os, urllib.request
from pathlib import Path
key = Path(os.environ['MEALPREP_MCPO_KEY_FILE']).read_text().strip()
for path, body in [('/openapi.json', None), ('/echo', {'message': 'synthetic-client-check'})]:
    request = urllib.request.Request('http://127.0.0.1:8000' + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        print(json.load(response))
PY
```

Protocol/full smoke commands and evidence boundaries are in [INTEGRATION.md](INTEGRATION.md).
Wrong keys must fail; schema fetch alone is not proof of tool execution. Use synthetic
data while validating a client and inspect the returned tool value, not the model's
claim that a call succeeded. Never enable unsafe tools just to test connection.

## Primary references

- [Supergateway](https://github.com/supercorp-ai/supergateway) (installed 4.2.1 source inspected)
- [mcpo](https://github.com/open-webui/mcpo) (0.0.20 wheel/API inspected)
- [Open WebUI OpenAPI integration](https://docs.openwebui.com/features/extensibility/plugin/tools/openapi-servers/open-webui/)
- [OpenCode V2 MCP](https://opencode.ai/v2/docs/mcp-servers)
- [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- [Cursor MCP](https://cursor.com/docs/context/mcp)
- [n8n MCP Client Tool](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolmcp/)
