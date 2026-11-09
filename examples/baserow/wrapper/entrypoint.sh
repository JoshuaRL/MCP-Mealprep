#!/bin/sh
# Re-permission secret copies into writable tmpfs. Host-side committed
# example files are 0644 (git does not preserve 0600); the wrapper
# refuses anything but 0600. Copied secrets land in /tmp only.
set -eu
mkdir -p /tmp/secrets
install -m 0600 /run/secrets/baserow.json /tmp/secrets/baserow.json
install -m 0600 /run/secrets/mcp.json /tmp/secrets/mcp.json
export BASEROW_FILE=/tmp/secrets/baserow.json
export MCP_FILE=/tmp/secrets/mcp.json
exec node /app/wrapper/server.mjs
