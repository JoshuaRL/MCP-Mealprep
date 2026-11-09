# Retired V1 material — not deployment examples

`docker-compose-v1.yml.txt` preserves the former root `docker-compose-old.yml` for
historical review. Its plain-text preamble deliberately makes it invalid Compose.
The old runnable path is removed so existing commands fail instead of silently
launching unsafe services. Do not rename or adapt the archive as a fallback.

The historical body contains privileged execution, broad host ports, a writable
home bind, mutable remote builds, deprecated packages and incorrect image/URLs.
Its original “still function”/backup statements are retained only as historical
text and are false as current deployment guidance. The claims about `uv.lock`
were not a general limitation of Docker and have been retired, not perpetuated.

The unchanged two-line `mcp-shield.log` placeholder was removed. It was not a scan
result; no automatic scan or security certification is claimed.

Use [current deployment](../DEPLOYMENT.md), [clients](../CLIENTS.md) and
[verification/release boundaries](../VERIFICATION.md). Reintroducing any legacy
integration needs a fresh least-privilege recipe and explicit validation.
