// Read-only production wrapper for baserow-streamable-mcp.
//
// Reads two secret files only:
//   $BASEROW_FILE (default /run/secrets/baserow.json)
//     {"token": "<db token>", "url": "https://<baserow origin>"}
//   $MCP_FILE (default /run/secrets/mcp.json)
//     {"token": "<mcp bearer>"}
//
// A small entrypoint copies whatever the host mounts with 0600 into
// tmpfs, so host-side example files can be 0644 (git cannot keep 0600)
// while the wrapper still sees strictly 0600 files.
//
// The Baserow origin is never hard-coded, never read from the environment,
// and never accepted from request input. Only https origins without
// credentials, path, query, or fragment are accepted.
import fs from 'node:fs';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { serve } from '@hono/node-server';
import { createMcpHandler } from '@modelcontextprotocol/server';
import { createMcpHonoApp } from '@modelcontextprotocol/hono';
import { BaserowClient, BaserowApiError } from '../dist/src/baserow/client.js';
import { buildMcpServer } from '../dist/src/server/mcp-server.js';
import { noopLogger } from '../dist/src/operations/logger.js';

const READ_ONLY_TOOLS = new Set([
  'list_databases',
  'list_tables',
  'get_table_schema',
  'get_row',
  'list_rows',
  'search_rows',
  'filter_rows',
]);

const MAX_RESPONSE_BYTES = 1_048_576;
const MAX_REQUEST_URL_LENGTH = 16_384;
const BASEROW_FILE = process.env.BASEROW_FILE || '/run/secrets/baserow.json';
const MCP_FILE = process.env.MCP_FILE || '/run/secrets/mcp.json';

function privateJsonFile(file) {
  const stat = fs.lstatSync(file);
  if (stat.isSymbolicLink() || !stat.isFile() || (stat.mode & 0o077) !== 0 || stat.size > 4096) {
    throw new Error('Unsafe secret file');
  }
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

function requireString(value, field) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 512 || /[\u0000-\u001f\u007f]/.test(value)) {
    throw new Error(`Invalid ${field}`);
  }
  return value;
}

function requireBaserowUrl(value) {
  const urlText = requireString(value, 'Baserow URL');
  let url;
  try {
    url = new URL(urlText);
  } catch {
    throw new Error('Invalid Baserow URL');
  }
  if (url.protocol !== 'https:' || url.username || url.password ||
      url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Invalid Baserow URL');
  }
  return url.origin;
}

function readResponseWithLimit(response) {
  const contentLength = response.headers.get('content-length');
  if (contentLength !== null && Number(contentLength) > MAX_RESPONSE_BYTES) {
    response.body?.cancel().catch(() => {});
    throw new Error('Provider response too large');
  }
  if (response.status === 204) return new Response(null, { status: response.status });

  if (response.body === null) {
    return new Response('', { status: response.status, headers: { 'content-type': 'text/plain' } });
  }

  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  const appendAndCheck = chunk => {
    size += chunk.byteLength;
    if (size > MAX_RESPONSE_BYTES) {
      reader.cancel().catch(() => {});
      throw new Error('Provider response too large');
    }
    chunks.push(chunk);
  };

  return reader.read().then(function step({ done, value }) {
    if (done) {
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) {
        bytes.set(chunk, offset);
        offset += chunk.byteLength;
      }
      return new Response(bytes, {
        status: response.status,
        headers: { 'content-type': response.headers.get('content-type') ?? 'application/json' },
      });
    }
    appendAndCheck(value);
    return reader.read().then(step);
  });
}

function makeBoundedFetch(baserowOrigin) {
  return async function boundedBaserowFetch(input, init = {}) {
    const urlText = String(input);
    if (urlText.length > MAX_REQUEST_URL_LENGTH) throw new Error('Provider request URL too long');

    const url = new URL(urlText);
    if (url.origin !== baserowOrigin || !url.pathname.startsWith('/api/')) {
      throw new Error('Provider request outside configured origin');
    }

    const readTables = url.pathname === '/api/database/tables/all-tables/';
    const fieldRequest = /^\/api\/database\/fields\/table\/\d+\/$/.test(url.pathname);
    const rowsRequest = /^\/api\/database\/rows\/table\/\d+(?:\/\d+)?\/$/.test(url.pathname);
    if (!readTables && !fieldRequest && !rowsRequest) {
      throw new Error('Provider request outside read-only API allowlist');
    }

    const hadForeignHeaders = Object.keys(init.headers ?? {}).some(
      name => !['accept', 'authorization', 'content-type'].includes(name.toLowerCase())
    );
    if (hadForeignHeaders) throw new Error('Unexpected provider request header');

    const response = await fetch(url, {
      ...init,
      redirect: 'manual',
      keepalive: false,
    });

    if (response.status >= 300 && response.status < 400) {
      response.body?.cancel().catch(() => {});
      throw new Error('Provider redirect rejected');
    }
    return readResponseWithLimit(response);
  };
}

function sanitizedClient(underlying) {
  const methods = [
    'listDatabases',
    'listTables',
    'getTableSchema',
    'getRow',
    'listRows',
    'searchRows',
    'filterRows',
  ];
  const safeClient = {};
  for (const name of methods) {
    safeClient[name] = async (...args) => {
      try {
        return await underlying[name](...args);
      } catch (error) {
        if (error instanceof BaserowApiError) {
          throw new BaserowApiError(error.message, error.status, null);
        }
        throw new BaserowApiError('Baserow request failed', 502, null);
      }
    };
  }
  return safeClient;
}

const baseConfig = privateJsonFile(BASEROW_FILE);
const mcpConfig = privateJsonFile(MCP_FILE);
const rawToken = requireString(baseConfig?.token, 'Baserow token');
const baserowUrl = requireBaserowUrl(baseConfig?.url);
const mcpAuthToken = requireString(mcpConfig?.token, 'MCP bearer token');

const underlyingClient = new BaserowClient(baserowUrl, rawToken, 15_000, makeBoundedFetch(baserowUrl), 0);
const safeReadClient = sanitizedClient(underlyingClient);
const mcpServer = buildMcpServer(safeReadClient, undefined, noopLogger);

const registry = mcpServer._registeredTools;
if (!registry || typeof registry !== 'object') throw new Error('Vendor tool registry unavailable');
const actualToolNames = new Set(Object.keys(registry));
if (actualToolNames.size !== 12) throw new Error('Unexpected vendor tool surface');
for (const name of READ_ONLY_TOOLS) {
  if (!actualToolNames.has(name)) throw new Error('Missing expected read-only tool');
}
for (const name of actualToolNames) {
  if (!READ_ONLY_TOOLS.has(name)) registry[name].disable();
}

const handler = createMcpHandler(() => mcpServer);

// Compose-friendly binding: listen on all container interfaces, but keep
// DNS-rebinding protection with an explicit allowedHosts list, plus the
// bearer token. The published port must stay loopback-only (compose).
const ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '[::1]', 'host.docker.internal', 'host-gateway', 'baserow-mcp'];
const app = createMcpHonoApp({ host: '0.0.0.0', allowedHosts: ALLOWED_HOSTS });
app.get('/health', context => context.json({ status: 'ok', service: 'baserow-streamable-mcp', version: '0.1.0' }));
app.all('/mcp', async context => {
  const header = context.req.header('Authorization');
  const supplied = header?.startsWith('Bearer ') ? Buffer.from(header.slice('Bearer '.length)) : Buffer.alloc(0);
  const expected = Buffer.from(mcpAuthToken);
  if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) {
    return context.json({ error: 'UNAUTHORIZED' }, 401);
  }
  return handler.fetch(context.req.raw);
});

const server = serve(
  { fetch: app.fetch, hostname: '0.0.0.0', port: 7317 },
  info => {
    process.stderr.write(JSON.stringify({ event: 'ready', port: info.port }) + '\n');
  }
);

function shutdown() {
  server.close(() => process.exit(0));
}
process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);
