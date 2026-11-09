# Example secrets (dummy placeholders)

These files make `docker compose up` start out of the box with obviously
fake values. **Replace every value before real use.** Generate real ones:

- `gateway_api_key` → `openssl rand -hex 32`
- `mcp.json` token → `openssl rand -hex 32`
- `baserow.json` token → mint a table-scoped read-only token in Baserow
  (see `examples/baserow/README.md`); `url` = your Baserow origin.

All three are loopback-only inside Compose, but treat the gateway key
as a real credential anyway: anyone who reaches the published port
with it gets your MCP tools.
