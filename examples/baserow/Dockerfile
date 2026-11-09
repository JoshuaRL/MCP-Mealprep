# Reproducible production image for the read-only Baserow MCP wrapper.
# Build context: this directory (docker-compose.yml). The vendor source is
# fetched at the pinned commit inside the builder; nothing from the host
# build context enters the runtime image except wrapper/server.mjs.
FROM node:22-alpine AS builder
RUN apk add --no-cache git ca-certificates
ARG BASEROW_MCP_REPO=https://github.com/bitingwaxen/baserow-streamable-mcp.git
ARG BASEROW_MCP_REF=dcbbd3d5fdc07a73af8b17a5b58eb522c70b2daa
WORKDIR /src
RUN git init -q . \
    && git remote add origin "$BASEROW_MCP_REPO" \
    && git fetch -q --depth=1 origin "$BASEROW_MCP_REF" \
    && git checkout -q FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "$BASEROW_MCP_REF"
COPY package.json.reference package.json
COPY package-lock.json.reference package-lock.json
RUN npm ci --ignore-scripts --no-audit --no-fund \
    && npm run build \
    && npm test

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY package.json.reference package.json
COPY package-lock.json.reference package-lock.json
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund && npm cache clean --force \
    && mkdir -p /app/wrapper /run/secrets /data \
    && chown -R node:node /app/wrapper /run/secrets /data
COPY --from=builder /src/dist ./dist
COPY wrapper/server.mjs ./wrapper/server.mjs
RUN node --check /app/wrapper/server.mjs
USER node
EXPOSE 7317
CMD ["node", "/app/wrapper/server.mjs"]
