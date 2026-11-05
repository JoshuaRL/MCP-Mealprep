# Startup contract

`startup.sh` validates its inputs, constructs a backend command and replaces itself
with the foreground Supergateway process. The gateway launches its own stdio MCP
child. There is no independent backend prelaunch, `eval`, background job supervisor
or post-exit scanner/second server.

These are local source/runtime changes, not a published image update. See
[integration checks](docs/INTEGRATION.md) for the narrow real-image test scope and
README.md for remaining deployment limitations.

## Configuration

| Variable | Meaning |
| --- | --- |
| `MCP_SERVER_TYPE` | Optional log label; defaults to `custom`. Does not choose a package. |
| `MCP_COMMAND_TYPE` | Required: `npx`, `uvx`, `uv` or `python3`. |
| `MCP_PACKAGE` | Required npm/Python package or, for `python3`, Python module name. No fallback. |
| `MCP_ARGS` | Optional trusted shell argument fragment. See the trust warning below. |
| `MCP_PORT` | Decimal port 1..65535; defaults to 8081. Leading zeroes normalize to decimal. |
| `MCP_TRANSPORT` | `streamable-http` (default, stateful `/mcp`) or explicit legacy `sse` (`/sse` and `/message`). |
| `MCP_API_KEY_FILE` | Required readable file containing one printable ASCII key of at least 16 characters. Use a cryptographically random key. |
| `USE_MCPO` | Retired in-process mode. Defaults to false; true fails. Use the separate mcpo Compose overlay. |
| `USE_SUPERARGS` | Deprecated. True prints a warning and has no effect. |

Empty or missing required values, unsupported runners, invalid ports or a requested
broken mcpo mode fail before invoking npx/uv or starting a gateway. Unknown
USE_MCPO values are rejected rather than silently enabling/disabling a feature.

`SUPERGATEWAY_API_KEY` and `SUPERGATEWAY_API_KEY_FILE` are rejected to prevent
unreviewed additional authentication sources. Only the key file path is passed via
`--apiKeyFile`; gateway logging is fixed to `none`. Streamable HTTP requests (or
both legacy SSE and message POST) require client authentication. Supported provider `_FILE` mappings, file permissions,
non-root behavior and trust limits are documented in [deployment](docs/DEPLOYMENT.md).
Providers still receive values in their process environment. The backend can read
the container's mounted files: this is not isolation from backend packages.

## Runner mapping

| Type | Backend command |
| --- | --- |
| `npx` | `npx -y PACKAGE` |
| `uvx` | `uvx PACKAGE` |
| `uv` | `uv tool run PACKAGE` (not the invalid `uv PACKAGE`) |
| `python3` | `python3 -m MODULE` |

For example, `MCP_COMMAND_TYPE=npx` and
`MCP_PACKAGE=@modelcontextprotocol/server-memory` select Memory. A label of
`MCP_SERVER_TYPE=memory` alone is insufficient. For Python, the module must already
be available in the runtime; this mode does not pip-install it. Older custom Python
configurations that used an entire command in MCP_PACKAGE must migrate to a module
name and put its options in MCP_ARGS.

Fixed executable/package/module arguments are single-quoted for Supergateway's
shell-command interface. A package value cannot splice another shell command into
that fixed prefix. **MCP_ARGS remains a trusted shell fragment for compatibility:**
quoted words are preserved, but shell substitutions/operators are executable by
the gateway. Do not populate it from untrusted input or use it to carry secrets.
Removing the launcher's eval does not make the gateway command a sandbox.

## Process ownership and optional features

The launcher uses `exec supergateway --stdio ...`; the pinned binary is installed
when building the image. There is no npm gateway wrapper or second Bash launch
phase. Errors and exit status are not hidden by later scanner commands. Offline
tests use a stub; the explicit integration smoke separately stops real containers
while MCP connections remain open. A clean container exit is not proof that every
possible backend safely completes in-flight work.

The previous mcpo block was behind a long-running foreground gateway, reused its
port and conflated server arguments with an API key. It is deliberately refused,
not silently repaired or run concurrently. The new optional overlay builds a
separate mcpo service/port with its own file credential and a remote authenticated
HTTP upstream. See [client setup and tested boundaries](docs/CLIENTS.md).

The previous mcp-shield command was also after the long-running gateway, so it was
not a functioning startup scan. Run any reviewed scanner separately with explicit
targets and scope. Startup does not assert that tools are safe or scanned.

## Verification

```sh
bash -n startup.sh
docker compose --env-file /dev/null -f docker-compose.yml config --quiet
python3 -m unittest discover -s tests -v
```

The Python suite uses only the standard library and local executable stubs. It
checks fail-closed configuration, runner argv, quoting, no prelaunch/scanner,
foreground PID/exit status/signals and all 14 Compose package/runner selections.
Compose is required for configuration tests but never starts containers. Real
MCP requests/container shutdown are checked separately by the explicit integration
smoke, not this suite. Real Supabase/provider credentials, TLS and the rest
of the catalog remain unverified.
