# Pin runtime image indexes; top-level package pins are not a full dependency lock.
FROM ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 AS uv
FROM node:24-bookworm-slim@sha256:c86ecead9e55a5210ac1727de38a4ca840bf03dcaf34dc9749addbf383b1920c AS runtime

ARG SUPERGATEWAY_VERSION=4.2.1
ARG CONTEXT7_VERSION=1.0.1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl git nano python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# One uv installation. A venv keeps optional pip installs off Debian's system Python.
COPY --from=uv /uv /uvx /usr/local/bin/
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
ENV npm_config_engine_strict=true
RUN npm install --global --no-audit --no-fund \
      "supergateway@${SUPERGATEWAY_VERSION}" "c7-mcp-server@${CONTEXT7_VERSION}"

# Do not copy Git history, environment files, logs or the review/test harness.
COPY startup.sh /app/startup.sh
RUN bash -n /app/startup.sh && chmod +x /app/startup.sh \
    && node --version && python3 --version && uv --version \
    && python3 -m pip --version && command -v supergateway

RUN mkdir -p /data/memory /home/node/.cache /home/node/.npm \
    && chown -R node:node /data/memory /home/node/.cache /home/node/.npm
ENV HOME=/home/node
USER 1000:1000
CMD ["/app/startup.sh"]

# Optional OpenAPI bridge: separate target and Python dependency environment.
# mcpo 0.0.20 uses FastAPI constructor kwargs removed by 0.162.0; keep the
# live-tested compatibility pins until an upstream upgrade is revalidated.
FROM runtime AS mcpo
USER root
RUN python3 -m venv /opt/mcpo \
    && uv pip install --python /opt/mcpo/bin/python \
      'mcpo==0.0.20' 'mcp==1.26.0' 'fastapi==0.135.0' 'starlette==1.10.0'
COPY mcpo_bridge.py /app/mcpo_bridge.py
USER 1000:1000
CMD ["/opt/mcpo/bin/python", "/app/mcpo_bridge.py"]

# Default builds remain the gateway runtime, without optional bridge dependencies.
FROM runtime AS mealprep
