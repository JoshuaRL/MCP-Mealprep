# Verification and release boundaries

This checkout is a **local tested candidate, not a published release**. No new
image was pushed/signed, no hosted workflow was triggered, and no deployment or
installed client was changed during this repair. The old GHCR `:main` is unchanged
and does not implement the new contract. See the local
[verification snapshot](verification-snapshot.json) for exact final image IDs,
source hashes, selected versions, architecture and evidence limits.

## One explicit local gate

Requirements: Docker daemon + current Compose plugin, Git checkout, Bash, Python
3.8+, package-network access for backend downloads, and enough disk space. Use
reviewed source, disposable resources and synthetic keys; no account token is needed.

```sh
docker build --tag mealprep:verify .
docker build --target mcpo --tag mealprep:verify-mcpo .
python3 tests/release_check.py --image mealprep:verify \
  --bridge-image mealprep:verify-mcpo --output /private/new-mealprep-verification
```

The gate requires **already-built local images**; it never builds, pulls, pushes,
signs, deploys the full Compose stack or prunes resources. It refuses an existing
output path. It records image IDs/non-root defaults, checkout base and dirty status,
and source/build/config/test/doc hashes, then runs:

1. Bash syntax and base, optional mcpo and explicit SSE Compose validation.
2. Non-executing proof that retired V1 archive text is not valid Compose.
3. Offline launcher, provider-file, protocol, client-example and release-contract tests.
4. Real legacy SSE checks for Everything/Memory/Fetch, invalid gateway-key startup,
   auth failures, representative tool calls, Memory container recreation and cleanup.
5. Real Streamable HTTP and separate mcpo checks for auth, schema/tool calls,
   concurrent native/bridge connections, sessions, upstream-auth failure, CORS,
   non-root execution, key non-disclosure and shutdown.

It refuses incomplete case/cleanup counts, OOMs, detected key disclosure, changed
source/image identities or missing teardown evidence. Thirteen run-owned containers,
two networks and one synthetic Memory volume must be removed across the two live
harnesses; only exact labeled resources from those runs are touched. The expected
negative cases exit nonzero and are recorded separately, not hidden as successful
service startups. No real providers, host-data mounts or Docker socket mounts are used.

The output directory is private. `summary.json`, `legacy/summary.json` and
`optional/summary.json` are the scope-limited results; raw diagnostic logs/key files
stay private. A failed/incomplete check is not a pass. Preserve failed evidence and
inspect run-owned resources before retrying after interruption/daemon failure;
never substitute a global prune for exact cleanup. No cancellation/host-crash
recovery guarantee is made by a normal successful teardown test.

## What the evidence establishes

| Component | Tested identity / boundary |
| --- | --- |
| Runtime | Node 24.22.2, Python 3.11.2, uv 0.13.7, Supergateway 4.2.1; Linux/amd64 |
| Everything | `@modelcontextprotocol/server-everything@2.1.0`, synthetic echo |
| Memory | `@modelcontextprotocol/server-memory@2.0.1`, synthetic CRUD and named-volume recreation |
| Fetch | `mcp-server-fetch==2026.10.28`, default private-IP refusal and separate test-only fixture opt-in |
| mcpo target | mcpo 0.0.20, MCP Python SDK 1.26.0, FastAPI 0.135.0, Starlette 1.10.0 |
| Wire protocols | Legacy SSE and stateful Streamable HTTP, initialize handshake `2025-11-25`; separate OpenAPI bridge |
| Client files | Docs-derived placeholders for Open WebUI/n8n/Claude Code/Cursor/OpenCode V2; apps not launched |

Detailed cases are in [INTEGRATION.md](INTEGRATION.md). The first optional-image
attempt failed with FastAPI 0.162.0 rejecting mcpo constructor arguments; a compatible
pin fixed the demonstrated failure. The first step-2 harness also missed a fixture
forced kill in its aggregate result; that gate was corrected and rerun. Neither
failure is erased by the later passing reports. Top-level pins do **not** lock the
entire apt/npm/Python dependency closure, and production Compose recipes remain
unpinned. A receipt/hash is evidence, not an authentic approval or security certificate.

## Future hosted workflow (source only; not run here)

`.github/workflows/docker-publish.yml` retains the existing main/manual/PR triggers.
It builds/loads the single-platform gateway candidate, builds the optional mcpo
target, and runs the same local gate before registry login or publication. PRs
never publish. On an authorized main/manual run, it checks the local gateway ID
against the gate result, tags/pushes **that image without rebuilding**, then signs
the resulting registry digest. The optional bridge is tested but is **not** published
by this workflow. No multi-architecture publication is claimed.

Only synthetic summaries are selected for artifact retention (14 days), including
on failure; raw logs and key files are excluded. Normal step-success semantics
keep login/push/sign blocked after a failed gate. The workflow definition is locally
reviewed/tested, not evidence that hosted build, registry permissions, artifact
upload, cosign or a published signature currently work. Local image IDs are not
published registry digests. Those identities must be recorded after an actual
separately authorized publication; do not invent them now.

## Remaining deployment/release decisions

- **Publication is separate:** commit/push, hosted CI, registry push/signing and
  deployment need explicit authorization. Review the final diff and intended tags
  first. Retain the exact old deployment image/config/state before any migration.
- **Security supply chain:** no SBOM, vulnerability scan, signature verification,
  full dependency lock or independent security audit was performed. Upgraded runtime
  versions and image signing are not substitutes. Refresh/revalidate pinned action
  and dependency versions deliberately before relying on a release process.
- **Catalog:** only the three pinned server versions above were live-tested. The
  remaining provider recipes are unvalidated; several are deprecated. SearXNG needs
  a reachable separately configured service; its container-local placeholder is not
  a working dependency. No Docker socket is supplied to the Docker recipe.
- **Real environments:** no account credentials/provider APIs, installed client apps,
  Portainer/Swarm deployment, remote HTTPS/OAuth, load/concurrency, restart/outage
  resilience or backup/restore verification. Native and bridge MCP sessions do not
  guarantee shared backend state or safe concurrent Memory writers.
- **Operations:** loopback and shared-key auth do not provide per-tool authorization,
  multi-tenancy, data encryption or a sandbox against trusted backend packages.
  Existing root-owned/imported volumes require explicit migration; no automatic
  ownership rewrite/deletion is performed. Keep secrets and raw backend logs private.

See [deployment](DEPLOYMENT.md), [client examples](CLIENTS.md) and
[retired V1 material](archive/README.md). These limits do not invalidate the tested
local repair scope, but they do prevent a blanket production-readiness claim.
