#!/bin/bash
set -euo pipefail

echo "MCP Server Startup Script"
echo "========================="

# The type is a log label, not a package selector. Never guess an integration.
MCP_SERVER_TYPE=${MCP_SERVER_TYPE:-"custom"}
MCP_PORT=${MCP_PORT:-8081}
MCP_COMMAND_TYPE=${MCP_COMMAND_TYPE:-""}
MCP_PACKAGE=${MCP_PACKAGE:-""}
MCP_ARGS=${MCP_ARGS:-""}
MCP_TRANSPORT=${MCP_TRANSPORT:-streamable-http}
fail() { echo "Startup error: $1" >&2; exit 1; }

[[ -n "$MCP_COMMAND_TYPE" ]] || fail "MCP_COMMAND_TYPE is required (npx, uvx, uv or python3)."
[[ -n "${MCP_PACKAGE//[[:space:]]/}" ]] || fail "MCP_PACKAGE is required; there is no fallback server."
if [[ ! "$MCP_PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$MCP_PORT < 1 || 10#$MCP_PORT > 65535 )); then
  fail "MCP_PORT must be a decimal integer from 1 to 65535."
fi
MCP_PORT=$((10#$MCP_PORT))

# The old concurrent mcpo path never worked. Do not silently pretend it starts.
case "${USE_MCPO:-false}" in
  false) ;;
  true) fail "USE_MCPO=true is retired; use docker-compose.mcpo.yml as a separate service." ;;
  *) fail "USE_MCPO must be true or false." ;;
esac
if [[ "${USE_SUPERARGS:-false}" == "true" ]]; then
  echo "USE_SUPERARGS is deprecated and ignored; the gateway always owns the backend." >&2
fi

# Package/module is one literal argument, never a shell command to eval here.
case "$MCP_COMMAND_TYPE" in
  npx) server=(npx -y "$MCP_PACKAGE") ;;
  uvx) server=(uvx "$MCP_PACKAGE") ;;
  uv) server=(uv tool run "$MCP_PACKAGE") ;;
  python3) server=(python3 -m "$MCP_PACKAGE") ;;
  *) fail "Unknown MCP_COMMAND_TYPE; choose npx, uvx, uv or python3." ;;
esac

# One printable ASCII key (at least 16 characters); no inline gateway keys.
# Values never enter the gateway argv or launcher logs. Files remain readable by
# trusted backends in this container; this is not a backend isolation boundary.
[[ ! -v SUPERGATEWAY_API_KEY && ! -v SUPERGATEWAY_API_KEY_FILE ]] || fail "Use only MCP_API_KEY_FILE for gateway authentication."
MCP_API_KEY_FILE=${MCP_API_KEY_FILE:-}
[[ -n "$MCP_API_KEY_FILE" && -f "$MCP_API_KEY_FILE" && -r "$MCP_API_KEY_FILE" ]] || fail "MCP_API_KEY_FILE must name a readable regular file."
gateway_key=$(cat -- "$MCP_API_KEY_FILE") || fail "Cannot read gateway key file."
LC_ALL=C
export LC_ALL
[[ "$gateway_key" =~ ^[!-~]{16,}$ ]] || fail "Gateway key file must contain one printable ASCII key of at least 16 characters."
unset gateway_key

# Deliberately bounded credential mapping, not arbitrary *_FILE evaluation.
for name in SUPABASE_ACCESS_TOKEN SLACK_BOT_TOKEN EVERART_API_KEY GOOGLE_MAPS_API_KEY BRAVE_API_KEY AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN; do
    file_var="${name}_FILE"
    if [[ -v "$file_var" ]]; then
        [[ ! -v "$name" ]] || fail "Set either $name or $file_var, not both."
        path=${!file_var}
        [[ -n "$path" && -f "$path" && -r "$path" ]] || fail "$file_var must name a readable regular file."
        value=$(cat -- "$path") || fail "Cannot read $file_var."
        [[ -n "${value//[[:space:]]/}" && "$value" != *$'\n'* && "$value" != *$'\r'* ]] || fail "$file_var must contain one nonempty line."
        export "$name=$value"
        unset "$file_var"
    fi
done
unset value path name file_var

case "$MCP_TRANSPORT" in
    streamable-http) transport=(--outputTransport streamableHttp --streamableHttpPath /mcp --stateful) ;;
    sse) transport=(--outputTransport sse --baseUrl "http://localhost:$MCP_PORT" --ssePath /sse --messagePath /message) ;;
    *) fail "MCP_TRANSPORT must be streamable-http or sse." ;;
esac

# Supergateway takes a shell command string. Quote each fixed argument with POSIX
# single quotes; preserve MCP_ARGS as an explicitly trusted legacy shell fragment.
shell_quote() {
  local quoted=${1//\'/\'\\\'\'}
  printf "'%s'" "$quoted"
}
SERVER_CMD=""
for argument in "${server[@]}"; do
  SERVER_CMD+="$(shell_quote "$argument") "
done
SERVER_CMD+="$MCP_ARGS"

# No independent stdio prelaunch or post-exit startup tasks. The foreground gateway
# owns its backend and exit status. Image smoke coverage is limited to the tested catalog.
echo "Launching Supergateway (Type: $MCP_SERVER_TYPE, Port: $MCP_PORT)"
exec supergateway \
    --apiKeyFile "$MCP_API_KEY_FILE" --logLevel none \
    --stdio "$SERVER_CMD" \
    --port "$MCP_PORT" "${transport[@]}"
