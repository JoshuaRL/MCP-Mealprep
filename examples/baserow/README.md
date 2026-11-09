# Baserow example — read-only MCP access to a Baserow database

A pinned third-party server (`bitingwaxen/baserow-streamable-mcp@dcbbd3d`)
behind a read-only wrapper (`wrapper/server.mjs`): exactly 7 read tools
exposed, mutations disabled, no redirects, bounded responses, sanitized
errors, bearer-authenticated, loopback-only. Live-validated 2026-11-05
(see `docs/ADDING-A-SERVICE.md`).

## Hosted vs self-hosted

Baserow has a **free cloud-hosted tier** (baserow.io) and a **self-hosted**
install. Both work identically here — the wrapper only needs the origin
and a database token. Nothing in this example bakes in a host.

| Option | `url` in `baserow.json` | Token source |
|---|---|---|
| Baserow Cloud (free tier) | `https://baserow.io` | Your cloud account → workspace → database tokens |
| Self-hosted | `https://<your-baserow-origin>` | Your instance's admin/user |

## Use (pull, don't build)

This example deploys from the published image. The `Dockerfile` lives in
this repo so the GHCR workflow can rebuild the image — you never need it
to deploy.

```sh
# 1. Write secrets (0600, owned by UID 1000) — see below

# 2. Pull + start (private bind)
BASEROW_SECRETS_DIR=/path/to/secrets docker compose up -d
# 3. Verify
curl -s http://127.0.0.1:7317/health   # {"status":"ok",...}
```

## Secrets (create on the host, never in git)

`/abs/path/to/secrets/baserow.json`:
```json
{"token": "<read-only database token>", "url": "https://baserow.io"}
```

`/abs/path/to/secrets/mcp.json`:
```json
{"token": "mealprep-mcp-<long-random>"}
```

## Seed + token steps

1. Create a dedicated workspace → database → table (text fields).
2. Insert a few synthetic rows (label them `TEST-…`).
3. Mint a database token, then PATCH permissions to read-only for
   exactly that table:
   `{"create": false, "read": [["table", <id>]], "update": false, "delete": false}`.
4. Write the secret files above. The token can never write (server
   returns 401), so keep seeded data synthetic.

## Register in a client

Attach `http://127.0.0.1:7317/mcp` with the bearer from `mcp.json`.
`tools/list` must show exactly: `list_databases`, `list_tables`,
`get_table_schema`, `get_row`, `list_rows`, `search_rows`, `filter_rows`.

## Rollback

`docker compose -f examples/baserow/docker-compose.yml down` + revoke
the database token in Baserow.
