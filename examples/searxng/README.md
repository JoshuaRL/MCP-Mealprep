# SearXNG example — web search behind the gateway

Two images: self-hosted SearXNG + the `mcp-searxng` MCP server launched
by this project's gateway. Validated live 2026-11-04 (see
`docs/ADDING-A-SERVICE.md`).

## The JSON requirement (read this first)

`mcp-searxng` parses **JSON search responses**. Most public SearXNG
instances do **not** serve JSON — they are HTML-only. Only use an
instance that has the `json` format enabled:

- **Self-hosted (recommended):** run the `searxng` service from
  `compose.overlay.yml` with `settings.yml` below. Its `formats:` list
  includes `json`, which is the non-default bit that makes this work.
- **Public instance:** only if that instance explicitly documents JSON
  output (e.g. its `/search?q=test&format=json` returns JSON).
  "Search works in a browser" does not imply JSON works.

## Use

```sh
# Terminal 1 — SearXNG
docker compose -f examples/searxng/compose.overlay.yml up -d searxng

# Terminal 2 — gateway + MCP server (uses the shipped stack's image)
SEARXNG_INSTANCE_URL=http://127.0.0.1:8888 \
  docker compose -f docker-compose.yml -f examples/searxng/compose.overlay.yml up -d mcp-mealprep-searxng
```

Then attach `http://127.0.0.1:8088/mcp` (bearer: your gateway key file)
to a client like the `examples/cursor.json` pattern.

## `settings.yml` (self-hosted SearXNG)

```yaml
use_default_settings: true
server:
  address: "0.0.0.0"
  port: 8080
  secret_key: "change-me"           # replace; keep out of git
search:
  formats:
    - html
    - json                          # REQUIRED for mcp-searxng
```

## Self-hosted SearXNG service

```yaml
services:
  searxng:
    image: searxng/searxng:latest   # pin a digest for production use
    ports: ["127.0.0.1:8888:8080"]
    environment:
      SEARXNG_BASE_URL: http://127.0.0.1:8888/
    volumes:
      - ./settings.yml:/etc/searxng/settings.yml:ro
```

Pin `searxng/searxng:<version-or-digest>` for production; `:latest` is
example-only.
