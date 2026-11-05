# Real-image integration checks

This is a small credential-free smoke, not validation of all 14 recipes or a
production security clearance. It executes real packages inside isolated Docker
containers, then verifies completed MCP responses rather than HTTP status alone.
It does not call a model or use provider/account credentials.

## Runtime brought forward from the modernization work

The old Bullseye image failed its Python dependency installation with HTTP 404s.
Current Everything and Memory require Node >=24; current Fetch requires Python >=3.10.
The Dockerfile now uses:

- Official Node 24 / Debian Bookworm slim, pinned by image-index digest.
- Python 3.11 from Debian and a pip virtual environment.
- uv 0.13.7 from its digest-pinned official image, copied once.
- Supergateway 4.2.1 installed globally at build time; the launcher execs its binary.
- c7-mcp-server 1.0.1 retained as an existing image capability, but not integration-tested.

The exact resolved Node/Python versions and image ID belong in each run's evidence.
Base/top-level pins do not lock apt or every transitive npm/Python dependency.
Server npx/uvx launches can still download packages; this is not an offline image or
a hermetic/reproducible-build claim. The image now runs as UID 1000; see
[deployment boundaries](DEPLOYMENT.md) for the authentication/storage contract.

## Narrow catalog

`tests/integration-catalog.json` records the exact requested versions:

| Server | Package | Representative checks |
| --- | --- | --- |
| Everything | `@modelcontextprotocol/server-everything@2.1.0` | initialize, list tools, echo a synthetic marker |
| Memory | `@modelcontextprotocol/server-memory@2.0.1` | create, retrieve, remove/recreate container on same named volume, retrieve, delete and confirm deletion |
| Fetch | `mcp-server-fetch==2026.10.28` | reject a private address by default; separately fetch a controlled fixture with explicit opt-in |

The original `integration_smoke.py` explicitly selects legacy HTTP+SSE and
negotiates protocol `2025-11-25`. The separate `integration_optional.py` tests the
new default stateful Streamable HTTP and the optional OpenAPI bridge. Neither
establishes support for modern `2026-07-28` requests, every client or every tool.

Fetch's successful fixture test uses `--allow-private-ips` **only in that disposable
test instance** to reach a synthetic server on the test network. Its first test
asserts the default refusal. The flag is not added to the production recipe and
must not be treated as a recommended security default.

## Run deliberately

Requirements: usable Docker daemon, Python 3.8+, internet for image/package downloads,
and enough space for the local build/cache. No sudo, host data mounts, Docker socket
mount inside a container, privileged mode, account tokens or registry push is used.

Review the source first, then from the checkout:

```sh
docker build --tag mealprep:integration .
python3 tests/integration_smoke.py \
  --image mealprep:integration --output /private/new-mealprep-evidence
```

Use a new output directory; existing paths are refused. This builds the current
Dockerfile, not the old GHCR `:main` image. `.dockerignore` allowlists only build
inputs so Git history, environment files, tests and logs do not enter the image.

The smoke never builds/pulls an image implicitly: it requires the explicit local
image. It creates uniquely named/labeled containers and a network, binds gateway
ports to random loopback-only host ports, and uses only synthetic data. It applies
test resource limits and no-new-privileges/capability restrictions, not a claim of
production hardening. Containers download server dependencies into their own filesystems.

It records the image ID, copied launcher hash, runtime/server versions, negotiated
protocol, tool counts, completed operations, non-root UID, container exit/OOM status
and cleanup. Each gateway rejects absent/wrong keys on both SSE and message POST;
the synthetic correct key completes MCP operations. A synthetic key file is copied
into each disposable container, not passed by value in argv or configured env.
The test checks gateway argv, Docker's configured environment and logs for accidental
synthetic-key disclosure. Missing and empty key files must fail real-container startup.
Containers are stopped with an open MCP connection, not merely after closing SSE.
A forced kill or failed fixture teardown must not produce an overall passing result.
Only resources created by that run, checked by ownership labels, are removed. Other
containers/networks are not inspected or modified; no global pruning is done. The
owned synthetic Memory volume is label-checked and removed after recreation tests;
no user volume is used or deleted.

## Streamable HTTP and optional mcpo smoke

Build the separate target and run the second explicit harness:

```sh
docker build --tag mealprep:integration .
docker build --target mcpo --tag mealprep:mcpo-integration .
python3 tests/integration_optional.py --image mealprep:integration \
  --bridge-image mealprep:mcpo-integration --output /private/new-optional-evidence
```

It uses the same three exact server versions, synthetic keys and owned-resource
boundaries. Checks include Streamable HTTP initialize/list/calls, absent/wrong/bridge
keys rejected on GET/POST/DELETE, session termination and refusal of deleted sessions.
The Everything test supplies nonempty backend arguments and verifies a native MCP
call while mcpo is connected. The separate bridge requires a different inbound key;
its schema/docs/tools reject absent/wrong/gateway keys, an authenticated `/echo`
returns the marker, and invalid upstream authentication fails bridge startup.

The actual overlay listener-readiness command is executed against the test gateway;
it is not a full Compose or Portainer deployment test. mcpo 0.0.20, Python MCP SDK
1.26.0, FastAPI 0.135.0 and Starlette 1.10.0 are checked in the real bridge image.
The first attempt with unconstrained FastAPI resolved 0.162.0 and failed before
serving because mcpo passed removed constructor arguments. The compatibility pin
is intentional and does not claim the full dependency set is vulnerability-free.

This harness removes its own containers and network; it uses no persistent Memory
volume. The first harness separately retains the recreate/durability test. Native
and bridge sessions do **not** imply shared backend state or multi-writer Memory
safety. Client-app and model-level validation remain deferred; see [CLIENTS.md](CLIENTS.md).

## Reading evidence honestly

`summary.json` is the result; private per-container logs retain diagnostics. Logs
may include synthetic requests, paths and session identifiers. Keep them local;
redact them before sharing. A failed/incomplete run remains evidence, not a pass.

Offline `unittest` tests additionally check the smoke parser, response matching,
endpoint restrictions and teardown gating. These tests are not real integration
evidence. The future workflow now invokes the unified live gate before registry
login/publication; that workflow has not been run here. No remote CI result is
implied, and these local commands do not publish an image. See
[verification/release boundaries](VERIFICATION.md).

Memory persistence is tested across removal/recreation on one disposable named
volume. Production backup/restore, concurrent writers and crash recovery are not tested.
Graceful gateway/container exit does not prove durability of arbitrary in-flight
backend work. Real external services, TLS, unselected packages
and other CPU/OS combinations remain outside this smoke.
