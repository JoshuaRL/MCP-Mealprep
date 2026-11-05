# MCP-Mealprep
Where you take a bunch of containers, put little MCP snacks in them, and keep 'em cool for later.

This project packages MCP server launch recipes with Supergateway and Docker Compose
for self-hosted AI tooling, with an optional separately authenticated mcpo bridge.

## Current source (unreleased repairs)
Rebuilt around [supergateway](https://github.com/supercorp-ai/supergateway), with an optional [mcpo](https://github.com/open-webui/mcpo) OpenAPI bridge.

> **Local development, not a new release:** The launcher requires explicit packages/
> runners and lets the installed Supergateway binary own its backend. The Dockerfile
> now uses Node 24, Debian Bookworm and a newer Python runtime. Real-image validation
> is limited to the small pinned test catalog described in [integration checks](docs/INTEGRATION.md).
> Compose now builds reviewed local source, requires gateway key files, binds host
> ports to loopback, runs non-root and persists Memory in a named volume. The old
> published `:main` image is unchanged. See [deployment boundaries](docs/DEPLOYMENT.md).
> This is not production certification or a TLS deployment. SSE is not encryption.

The Compose services are examples, not a validated production catalog. Each gateway
launches its configured stdio MCP backend and exposes Streamable HTTP by default
(explicit legacy SSE is available). The launcher does not
start a separate unconnected backend first. Remote access requires independently
configured HTTPS and network controls in addition to the required API key; a reverse proxy alone does
not guarantee safe tool access.

The current Dockerfile uses digest-pinned Node/Debian and uv images. Python's pip
runs in a virtual environment rather than overriding Debian's system packages.
Supergateway is installed at build time with an exact version, not downloaded by
the launcher on each start. Server packages still use npx/uvx at runtime; see the
integration guide for the exact tested versions and reproducibility limitations.

### mcpo Installation
The retired in-process `USE_MCPO=true` flag still fails explicitly. Use the optional
`docker-compose.mcpo.yml` overlay instead: it builds a separate pinned bridge,
requires a distinct key, and proxies an existing authenticated `/mcp` gateway.
See [client/bridge setup](docs/CLIENTS.md). Never use `MCP_ARGS` as an API key.

### startup.sh README
See [Startup README.md](<Startup README.md>) for the configuration contract, runner
mapping, trust boundaries and test limitations.

## Security checks
The launcher no longer schedules a scanner after a long-running foreground gateway.
That code was not a startup security check. Run a separately reviewed scanner such
as [mcp-shield](https://github.com/riseandignite/mcp-shield) with explicit targets
and configuration when needed. No automatic security scan or safety guarantee is
provided by these correctness fixes.

## Client Connection
Use `/mcp` for default Streamable HTTP, or `/sse` after explicitly selecting legacy
SSE. [Client connections](docs/CLIENTS.md) covers Open WebUI, n8n, Claude Code,
Cursor, OpenCode V2, exact protocol examples and distinct gateway/mcpo keys.
Wire-level checks are real; these client apps have not been run end-to-end here.
Flowise-specific setup remains outside the selected client scope.

## Overview

This is a small Docker Compose recipe collection built on maintained transport
tools, not a new MCP platform or a certified catalog. Real protocol tests cover
three pinned server versions and the optional bridge; the other recipes remain
unvalidated. Portainer instructions describe prerequisites and limitations, not
an end-to-end tested deployment.

## What is the Model Context Protocol?

The Model Context Protocol (MCP) standardizes how AI clients discover and call tools,
resources and services. Permissions, authentication and transport security still
depend on the implementation and deployment. Clients can:

- Retrieve information from different sources
- Perform actions across various platforms
- Extend AI capabilities beyond traditional language models

## Included MCP Servers

The Compose examples select packages for:

- Web Search (SearXNG and Brave)
- Everything (MCP testing)
- Calculator
- Slack
- Everart
- Google Maps
- Web Crawl (Fetch and Puppeteer)
- Sequential Thinking
- Supabase and Memory
- AWS KB Retrieval and Docker

Every service must set `MCP_COMMAND_TYPE` and `MCP_PACKAGE`; `MCP_SERVER_TYPE` is
only a log label. There is no silent fallback to the Everything test server.
Puppeteer, Slack, EverArt, Google Maps and the old official Brave package are
deprecated on npm. Their explicit identities are retained here to correct routing,
not to certify them for use. Replacing/validating the catalog is a separate step.

### Supabase configuration change

The old `uv mcp-server-supabase` command was invalid, and PyPI returned 404 for
that package during the repair. The example now selects the published npm CLI
`@supabase/mcp-server-supabase` using `npx`.

Mount a Supabase personal access token via `SUPABASE_ACCESS_TOKEN_FILE` (the Compose
secret `supabase_access_token`) and set `SUPABASE_PROJECT_REF` to the intended
project. The recipe passes `--read-only --project-ref ...`; the token
is inherited as `SUPABASE_ACCESS_TOKEN`, not placed in command arguments. The old
`MCP_QUERY_API_KEY` / `MCP_SUPABASE_*` database settings are not compatible with this
CLI. Use a test project first. No real Supabase API call has been validated here.

## Prerequisites

- Docker with a current Compose plugin supporting `pull_policy: build`.
- A private gateway key file readable by container UID 1000; a distinct key for mcpo.
- Provider credentials only for the selected integrations that require them.
- Portainer is optional; review its build/secret support limitations first.

## Installation with Compose / Portainer

Follow [deployment setup and boundaries](docs/DEPLOYMENT.md) for secret-file
permissions, explicit source builds, selecting services, authenticated client
headers, Memory storage and Portainer limitations. Pasting YAML alone is not enough
to supply a build context or host-side secret files. No real Portainer deployment
or external provider credentials have been tested by this local repair.

## Running

### Warnings
These are deployment examples, not proof that each integration currently works.
Offline tests exercise launch arguments, process handoff and recipe selection.
The separate real-image smoke checks selected MCP calls and container shutdown;
it does not validate provider credentials, production health or security. The old
published image still uses unsupported runtime versions until a replacement is
separately released. Review permissions, storage, network exposure and dependencies
before any deployment.

### Local regression checks

Python 3.8+, Bash and Docker Compose are required for the complete offline suite.
Docker Compose is used only to validate configuration; no daemon/container is needed.
Without Docker, the Compose checks are skipped and launcher checks still run.

```sh
bash -n startup.sh
docker compose --env-file /dev/null -f docker-compose.yml config --quiet
python3 -m unittest discover -s tests -v
```

Offline tests substitute local executables and never download server packages.
For the complete **local** release gate, build both targets and run
`tests/release_check.py` as described in [verification and release boundaries](docs/VERIFICATION.md).
It verifies real images and refuses incomplete/failed cleanup evidence. The future
workflow gates registry login/publication on these checks and promotes the tested
gateway without rebuilding. No hosted CI, push or signing result is implied here.

For the separate networked, credential-free Docker test, see
[real-image integration checks](docs/INTEGRATION.md). It is explicit, not part of the
offline unittest suite, and never publishes an image or runs the full Compose stack.

## Customization

### Adding/Removing Servers
- Simply comment out or remove the service block in the `docker-compose.yml`
- Ensure you have the necessary Dockerfile and dependencies

### Environment Variables
- Supply required credentials through mounted secret files, never committed values
  or `MCP_ARGS`. These recipes are not a secrets-management system.
- Ports are sequential and loopback-only; remote access requires separately reviewed HTTPS.

## Security Considerations
- Keep API tokens and sensitive information confidential
- Use read-only volumes where possible
- Regularly update your servers and dependencies

## Contributing
Any new MCP servers need a clean install command via npx, uv, or pip. If you have one you'd like added, please send a pull request or issue with a testing and known-working docker-compose container section 

### Adding New MCP Servers to this project
1. Ensure the server follows MCP protocol
2. Follows the above syntax, including all known environment variables and "startup.sh" command
3. Provide clear documentation, including GitHub repo for MCP server
4. Submit a pull request or issue with proposed additions

## Retired V1 deployment

The root `docker-compose-old.yml` and runnable README fallback are retired, not
supported alternatives. Historical content is preserved as deliberately non-runnable
[archive text](docs/archive/README.md). It contains unsafe/obsolete settings and
must not be deployed. The placeholder `mcp-shield.log` was not scan evidence and
has been removed. Use the current local-source setup instead.

## License

This project is open-source. Individual MCP servers may have their own licensing terms.

## Resources
- [Official MCP Servers Repository](https://github.com/modelcontextprotocol/servers)
- [Model Context Protocol Website](https://modelcontextprotocol.io)
- [MCP Evaluator](https://github.com/JeredBlu/custom-instructions/blob/main/mcpevaluatorv3.md)

## Disclaimer
This collection is community-maintained and not officially affiliated with the Model Context Protocol project, OpenWebUI, mcpo, or any other projects, implicit or implied.

---
