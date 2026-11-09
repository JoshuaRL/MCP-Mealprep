"""File-authenticated entrypoint for pinned mcpo; no credentials in argv/config."""
import asyncio
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


def key_file(name):
    path = os.environ.get(name, "")
    try:
        if not path or not Path(path).is_file():
            raise ValueError()
        value = Path(path).read_text(encoding="ascii").rstrip("\n")
        if not re.fullmatch(r"[!-~]{16,}", value):
            raise ValueError()
    except (OSError, ValueError, UnicodeError):
        raise ValueError(name + " must name a readable file with one ASCII key of at least 16 characters.") from None
    return value


def settings():
    inbound = key_file("MCPO_API_KEY_FILE")
    upstream = key_file("MCP_API_KEY_FILE")
    if inbound == upstream:
        raise ValueError("Bridge and gateway require distinct keys.")
    port = os.environ.get("MCPO_PORT", "8000")
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
        raise ValueError("MCPO_PORT must be a decimal integer from 1 to 65535.")
    url = os.environ.get("MCPO_UPSTREAM_URL", "")
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                 and not parsed.username and not parsed.password and not parsed.query
                 and not parsed.fragment and parsed.path == "/mcp"
                 and (parsed.port is None or 1 <= parsed.port <= 65535)
                 and not any(character.isspace() for character in url))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("MCPO_UPSTREAM_URL must be an HTTP(S) /mcp URL without credentials, query or fragment.")
    origin = os.environ.get("MCPO_ALLOWED_ORIGIN", "http://localhost:3000")
    try:
        parsed = urlsplit(origin)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname and "*" not in origin
                 and not parsed.username and not parsed.password and not parsed.query
                 and not parsed.fragment and parsed.path == ""
                 and (parsed.port is None or 1 <= parsed.port <= 65535)
                 and not any(character.isspace() for character in origin))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("MCPO_ALLOWED_ORIGIN must be one exact HTTP(S) origin, without a trailing slash.")
    return dict(host="0.0.0.0", port=int(port), api_key=inbound, strict_auth=True,
                server_type="streamable-http", server_command=[url],
                headers={"Authorization": "Bearer " + upstream}, cors_allow_origins=[origin])


def main():
    try:
        options = settings()
    except ValueError as error:
        print("Bridge startup error: " + str(error), file=sys.stderr)
        return 1
    # mcpo has no file-key CLI flag. Pass values only in memory to its pinned API.
    # Force quiet logging regardless of inherited debug settings.
    os.environ["LOG_LEVEL"] = "WARNING"
    from mcpo.main import run
    asyncio.run(run(**options))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
