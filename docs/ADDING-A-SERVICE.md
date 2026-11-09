# Adding a service: find → validate → include

How every connector in `examples/` was vetted — and how to add the next
one. The rule is **no provider is ever trusted on first sight**: pin it,
test it synthetically, and only then document it.

## 1. Find (source review, no execution)

- Prefer first-party or widely-used packages. Record: upstream URL,
  license, exact version/commit, declared entrypoints, network calls.
- Check what it wants: URLs, env vars, SDK behavior. Anything that
  sends data somewhere you didn't expect is a reject.
- Skip paid/credit-based providers as stack examples (Firecrawl: a
  validation shim is fine in a test, never as a shipped example).

## 2. Pin (exact, reproducible)

- If there's a version: pin it (`mcp-searxng@2.10.0`).
- If there's only a commit: pin the SHA and verify `HEAD` equals it at
  build time (`examples/baserow/Dockerfile`).
- No floating `:latest` in anything but a commented example.

## 3. Validate (bounded, synthetic, secret-free)

- Offline first: upstream tests + typecheck/build in the image build.
- Then ONE live run, smallest scope possible: synthetic data or a
  public page, single request, no retries, timeouts everywhere.
- Credentials arrive **only** via 0600 secret files your host writes —
  never argv/env, never git, never logs. Read-only tokens wherever the
  provider offers them; prove a valid write is denied (401/403) and the
  downstream data is unchanged.
- Rely on **fixed oracle checks** (exact strings/booleans in the data),
  not vibes. Our proven oracles:

  | Service | Oracle that counted as proof |
  |---|---|
  | Everything | `echo` round-trip of a synthetic marker |
  | Memory | create → read → delete of a synthetic entity, survives container recreation |
  | Fetch | default refusal of private IPs; opt-in fixture fetch returns marker |
  | SearXNG | one real search → results contain a known expected domain |
  | Baserow | 3-row synthetic fixture read via a table-scoped token; write denied |
  | Microsoft Learn (client example) | tool actually called (n=1); result contained `$PSVersionTable`; answer cited a URL **from that result** |

- Model/tool-call competency is *not* part of the gate: small local
  models may call tools and still answer badly. Connection proof =
  tool executed + grounded citation, not answer polish.

## 4. Include (examples, not defaults)

- New services go in `examples/<name>/` as **opt-in overlays**:
  `docker-compose.yml` defaults never change first-run behavior.
- Ship: README (hosted vs self-hosted, secrets setup, rollback),
  compose fragment, and any non-secret config templates.
- `docs/verification-snapshot.json` + the release gate stay the source
  of truth for what the default stack actually contains — examples are
  documented, gate-verified, and clearly labeled as examples.

## Rejected/instructive misses (so you don't repeat them)

- Secret-bearing SSE URLs for MCP auth (Baserow's installed native):
  rejected — bearer tokens in URLs end up in logs.
- Host-header validation means a loopback-only listener can't be
  reached through a published port: debug *inside* the netns
  (`--network container:<name>`) before concluding the service is down.
- Docker SandboxFile path casing/whitespace: quote paths with spaces.
