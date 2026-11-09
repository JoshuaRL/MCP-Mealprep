# Local hardening and deployment boundaries

These are local source changes, **not an updated GHCR release**. The Compose file
uses `build: .`, `pull_policy: build` and `mealprep:local-hardened`, never the old
published `:main`. Use a current Docker Compose plugin supporting that pull policy.
Do not substitute the old image: it does not implement this security contract.

## Start only a reviewed service

From this checkout, prepare a gateway key file using your secret manager or a
cryptographically random generator (for example `openssl rand -hex 32`). The file
must contain a single printable ASCII key of at least 16 characters, no spaces.
The length check is not an entropy check: use a random key, not a passphrase/example.
Never put its value in Compose, `.env`, command arguments, URLs or Git.

The default source is `./secrets/gateway_api_key`; alternatively set
`MEALPREP_SECRET_DIR` to a private directory outside this checkout. Both `secrets/`
and `.secrets/` are ignored, and excluded from the image build. Protect the parent
directory on the host and make each mounted file readable by container UID 1000.
For Linux bind-backed Compose secrets, arrange host ownership/group and permissions
(for example owner UID 1000 and mode 0400); `uid`/`mode` in Compose are not a reliable
way to change permissions on file-backed secrets. Do not make real keys world-readable.

```sh
docker compose config --quiet
docker compose up --build -d mcp-mealprep-memory
```

Select only the service you need; do not launch all 14 recipes as a compatibility
test. Provider secret files are needed only for selected services that reference
them. Most legacy providers remain unvalidated/deprecated. The three smoke-tested
package versions are in `tests/integration-catalog.json`; Compose catalog entries
are still unpinned recipes, not a locked deployment manifest.

## Client authentication and transport

Clients must send `Authorization: Bearer <key>` (or Supergateway's `X-API-Key`)
on every Streamable HTTP request at `/mcp` (the new default), or **both** the SSE
GET and every message POST when explicitly selecting `MCP_TRANSPORT=sse`.
[Client/optional bridge examples](CLIENTS.md) explain this compatibility change.
Browser EventSource clients that
cannot supply headers need a separately reviewed adapter; do not put keys in URLs.
There is no unauthenticated opt-out in the launcher. Missing, unreadable or invalid
key files stop startup. Gateway logging is fixed to `none` to avoid request/tool
payload logging; backend stderr can still contain sensitive data.

Host ports bind only to `127.0.0.1`. This is not encryption and does not restrict
other containers on the shared bridge from reaching the gateway: they still need
the key. The sample shares one gateway key across services; use per-service keys
and separate networks for stronger separation in your own reviewed configuration.
All holders of a service key can invoke all tools it exposes; this is not per-tool
authorization, OAuth, rate limiting or multi-tenant isolation.

**Remote access requires HTTPS** with a separately configured, reviewed TLS endpoint,
network rules and client authentication. No working TLS/proxy deployment is supplied
or claimed. Do not broaden bindings to `0.0.0.0` or publish raw HTTP to a LAN/internet.

## Provider credentials and trust

The launcher maps these `_FILE` settings to the provider's inherited environment:
`SUPABASE_ACCESS_TOKEN`, `SLACK_BOT_TOKEN`, `EVERART_API_KEY`, `GOOGLE_MAPS_API_KEY`,
`BRAVE_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`.
Each accepts `<NAME>_FILE`; a simultaneous direct `<NAME>` is rejected. Files must
be readable regular files containing one nonempty line. Direct provider environment
values remain compatible but are not the Compose examples' secret mechanism.
AWS file support requires your own selected mounts; no AWS keys are supplied.

Compose mounts only the selected provider's files plus its gateway key. Provider
values do not enter Docker's configured environment or gateway argv when loaded
from files, but **do enter the gateway/backend process environment**. Secret files
and process memory are accessible to trusted code in that container; Docker admins
and host root can read them. Runtime-downloaded backend packages, `MCP_ARGS` shell
fragments and authenticated tools must all be trusted. File mounts are not a secret
manager, encryption-at-rest guarantee or sandbox against malicious dependencies.

The image and Compose run as UID/GID `1000:1000`, drop capabilities and prohibit new
privileges. npm/uv caches under `/home/node` and Memory storage are writable. No
Docker socket or host-data mount is supplied. Some legacy servers may not work
non-root; do not silently undo hardening to accommodate them. Additional pip/global
installs should be done in a reviewed image build, not as root in a running container.

## Memory lifecycle

Memory writes `/data/memory/memory.jsonl` on the project-scoped `memory_data` named
volume. New volumes inherit the image directory's UID 1000 ownership. Existing
root-owned or imported volumes need an explicit migration/backup; no automatic
recursive chown or deletion is performed. Never mount several writers to this
file: concurrent multi-client/process safety is not established.

Container replacement and ordinary `docker compose down` preserve named volumes.
**`docker compose down -v` deletes Memory data.** Back up the volume while the
service is stopped and test restoring it before relying on durability. The smoke
proves synthetic data survives container removal/recreation, not backups, host
loss, corruption recovery, encryption or safe concurrent writes.

## Portainer

This remains a Compose-based project. A pasted YAML file by itself is insufficient
for a local source build: the Dockerfile and startup.sh must be available as the
build context, and secret paths refer to files on the Docker host, not your browser.
Portainer editions/modes differ in build and secret support. Use a reviewed local
checkout/build workflow first; for a mode that cannot build, explicitly prepare the
reviewed local image and adapt the build/pull policy without enabling registry pulls.
No Portainer/Swarm end-to-end deployment has been validated here. Never fall back
to the old GHCR image or store raw keys in the stack editor to make deployment pass.
