import fs from "node:fs/promises";
import http from "node:http";
import path from "node:path";
import { randomBytes, randomUUID } from "node:crypto";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseEnv } from "node:util";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const isProduction = process.env.NODE_ENV === "production";
const host = process.env.FRONTEND_HOST ?? "127.0.0.1";
const port = Number(process.env.FRONTEND_PORT ?? process.env.PORT ?? "25183");
const hmrPort = Number(process.env.VITE_HMR_PORT ?? String(port + 1));
// The API accepts its Host header only with its own API_PORT, so both sides default to the same port.
const apiOrigin = process.env.API_ORIGIN ?? `http://127.0.0.1:${process.env.API_PORT ?? "18020"}`;
const flowerOrigin = process.env.FLOWER_ORIGIN ?? `http://127.0.0.1:${process.env.FLOWER_PORT ?? "15565"}`;
const upstreamTimeoutMs = Number(process.env.UPSTREAM_TIMEOUT_MS ?? "10000");
// Writes may run long synchronously (the PnL rebuild takes seconds per portfolio).
const upstreamWriteTimeoutMs = Number(process.env.UPSTREAM_WRITE_TIMEOUT_MS ?? "300000");

/** FRONTEND_ORIGIN from the environment, else from backend/.env, which the API reads it from too. */
async function readFrontendOrigin() {
  if (process.env.FRONTEND_ORIGIN) return process.env.FRONTEND_ORIGIN;
  try {
    return parseEnv(await fs.readFile(path.join(__dirname, "../backend/.env"), "utf-8")).FRONTEND_ORIGIN;
  } catch {
    return undefined;
  }
}

// The app has no login, so the server answers only to its own host names: a DNS-rebinding page
// (attacker.example resolving to 127.0.0.1) arrives with its own Host header and is refused.
const frontendOrigin = await readFrontendOrigin();
const allowedHosts = new Set(["localhost", "127.0.0.1", "[::1]", host]);
if (frontendOrigin) {
  allowedHosts.add(new URL(frontendOrigin).hostname);
}

// Request headers that describe the client's connection to this server, not the request itself.
const HOP_BY_HOP = new Set([
  "connection",
  "expect",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "proxy-connection",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);
// Response headers that no longer hold once fetch has decoded the body.
const STALE_RESPONSE_HEADERS = new Set([...HOP_BY_HOP, "content-encoding", "content-length", "set-cookie"]);
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

let vite;

if (!isProduction) {
  const { createServer } = await import("vite");
  vite = await createServer({
    server: {
      middlewareMode: true,
      ws: { port: hmrPort },
    },
    appType: "custom",
  });
}

function securityHeaders(nonce) {
  const headers = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
  };
  // Vite's dev client injects inline scripts and a websocket, so the full policy applies to production builds.
  headers["Content-Security-Policy"] = isProduction
    ? [
        "default-src 'self'",
        nonce ? `script-src 'self' 'nonce-${nonce}'` : "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
      ].join("; ")
    : "frame-ancestors 'none'";
  return headers;
}

function send(response, statusCode, headers, body) {
  response.writeHead(statusCode, { ...securityHeaders(""), ...headers });
  response.end(body);
}

function hostAllowed(request) {
  const hostHeader = request.headers.host;
  if (!hostHeader) return false;
  try {
    return allowedHosts.has(new URL(`http://${hostHeader}`).hostname);
  } catch {
    return false;
  }
}

/** A write must come from this app's own pages; see reject_cross_site_writes in backend/app/http.py. */
function crossSiteWrite(request) {
  if (SAFE_METHODS.has(request.method ?? "GET")) return false;
  const site = request.headers["sec-fetch-site"];
  if (site !== undefined) return site !== "same-origin" && site !== "none";
  const origin = request.headers.origin;
  if (origin === undefined) return false;
  try {
    return new URL(origin).host !== request.headers.host;
  } catch {
    return true;
  }
}

function contentType(filePath) {
  if (filePath.endsWith(".js")) return "text/javascript";
  if (filePath.endsWith(".css")) return "text/css";
  if (filePath.endsWith(".html")) return "text/html";
  if (filePath.endsWith(".svg")) return "image/svg+xml";
  if (filePath.endsWith(".txt")) return "text/plain";
  if (filePath.endsWith(".xml")) return "application/xml";
  if (filePath.endsWith(".png")) return "image/png";
  if (filePath.endsWith(".webp")) return "image/webp";
  if (filePath.endsWith(".ico")) return "image/x-icon";
  return "application/octet-stream";
}

async function serveStatic(pathname, response) {
  const root = path.join(__dirname, "dist");
  const candidate = path.normalize(path.join(root, pathname));

  const relative = path.relative(root, candidate);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    send(response, 403, { "Content-Type": "text/plain" }, "Forbidden");
    return true;
  }
  // The server bundle and the raw page template are build inputs, not public files.
  if (relative === "index.html" || relative === "server" || relative.startsWith(`server${path.sep}`)) {
    return false;
  }

  try {
    const body = await fs.readFile(candidate);
    const immutable = pathname.startsWith("/assets/");
    send(
      response,
      200,
      {
        "Content-Type": contentType(candidate),
        "Cache-Control": immutable ? "public, max-age=31536000, immutable" : "no-cache",
      },
      body,
    );
    return true;
  } catch {
    return false;
  }
}

async function proxyRequest(request, response, url, origin) {
  const target = new URL(`${url.pathname}${url.search}`, origin);
  const headers = new Headers();
  const requestId = request.headers["x-request-id"] ?? randomUUID();

  for (const [key, value] of Object.entries(request.headers)) {
    if (value === undefined || HOP_BY_HOP.has(key.toLowerCase())) continue;
    headers.set(key, Array.isArray(value) ? value.join(", ") : value);
  }
  headers.set("x-request-id", String(requestId));

  const abortController = new AbortController();
  const timeoutMs = SAFE_METHODS.has(request.method ?? "GET") ? upstreamTimeoutMs : upstreamWriteTimeoutMs;
  const timeout = setTimeout(() => abortController.abort(), timeoutMs);
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" || request.method === "HEAD" ? undefined : request,
      duplex: "half",
      signal: abortController.signal,
      // Pass API redirects (for example broker OAuth handoffs) to the browser instead of following them.
      redirect: "manual",
    });
    const responseHeaders = {};
    for (const [key, value] of upstream.headers) {
      if (!STALE_RESPONSE_HEADERS.has(key)) responseHeaders[key] = value;
    }
    const cookies = upstream.headers.getSetCookie();
    if (cookies.length > 0) responseHeaders["set-cookie"] = cookies;
    response.writeHead(upstream.status, { ...securityHeaders(""), ...responseHeaders });
    if (upstream.body) {
      await pipeline(Readable.fromWeb(upstream.body), response);
    } else {
      response.end();
    }
  } catch (error) {
    console.error(JSON.stringify({ event: "proxy_error", request_id: requestId, target: target.pathname, error: String(error) }));
    if (response.headersSent) {
      response.destroy();
    } else {
      send(response, 502, { "Content-Type": "text/plain", "X-Request-ID": String(requestId) }, "Bad Gateway");
    }
  } finally {
    clearTimeout(timeout);
  }
}

/** Whether the "hide amounts" toggle is on, read from its cookie so the server render matches the client. */
function readHideAmounts(request) {
  const cookies = request.headers.cookie ?? "";
  return cookies.split(";").some((pair) => pair.trim() === "rp_hide_amounts=1");
}

function serializeInitialData(initialData) {
  return JSON.stringify(initialData).replace(/[<>&\u2028\u2029]/g, (character) => {
    switch (character) {
      case "<":
        return "\\u003c";
      case ">":
        return "\\u003e";
      case "&":
        return "\\u0026";
      case "\u2028":
        return "\\u2028";
      case "\u2029":
        return "\\u2029";
      default:
        return character;
    }
  });
}

async function renderPage(request, response) {
  const url = request.url ?? "/";
  try {
    let template;
    let render;

    if (!isProduction) {
      template = await fs.readFile(path.join(__dirname, "index.html"), "utf-8");
      template = await vite.transformIndexHtml(url, template);
      render = (await vite.ssrLoadModule("/src/entry-server.tsx")).render;
    } else {
      template = await fs.readFile(path.join(__dirname, "dist/index.html"), "utf-8");
      const serverEntry = path.join(__dirname, "dist/server/entry-server.js");
      const serverEntryStat = await fs.stat(serverEntry);
      render = (await import(`${pathToFileURL(serverEntry).href}?mtime=${serverEntryStat.mtimeMs}`)).render;
    }

    const nonce = randomBytes(16).toString("base64");
    const initialData = { hideAmounts: readHideAmounts(request) };
    const rendered = render(url, initialData);
    const initialScript = `<script nonce="${nonce}">window.__RETURNS_PORTAL_INITIAL_DATA__=${serializeInitialData(initialData)}</script>`;
    // Replacer functions: a string replacement would expand "$&" and friends inside the rendered page.
    const html = template
      .replace("<!--app-head-->", () => rendered.css ?? "")
      .replace("<!--app-html-->", () => rendered.html)
      .replace("<!--initial-data-->", () => initialScript);

    response.writeHead(rendered.statusCode, { ...securityHeaders(nonce), "Content-Type": "text/html" });
    response.end(html);
  } catch (error) {
    if (vite) {
      vite.ssrFixStacktrace(error);
    }
    console.error(error);
    send(
      response,
      500,
      { "Content-Type": "text/plain" },
      isProduction ? "Internal Server Error" : (error.stack ?? String(error)),
    );
  }
}

async function handle(request, response) {
  if (!hostAllowed(request)) {
    send(response, 421, { "Content-Type": "text/plain" }, "Misdirected Request");
    return;
  }

  let url;
  let pathname;
  try {
    url = new URL(request.url ?? "/", "http://localhost");
    pathname = decodeURIComponent(url.pathname);
  } catch {
    send(response, 400, { "Content-Type": "text/plain" }, "Bad Request");
    return;
  }

  const isApi = pathname.startsWith("/api/");
  const isFlower = pathname === "/flower" || pathname.startsWith("/flower/");
  if ((isApi || isFlower) && crossSiteWrite(request)) {
    send(response, 403, { "Content-Type": "text/plain" }, "Cross-site requests may not change anything");
    return;
  }

  if (isApi) {
    await proxyRequest(request, response, url, apiOrigin);
    return;
  }

  if (isFlower) {
    if (!isProduction) {
      if (pathname === "/flower") {
        send(response, 302, { Location: "/flower/" });
        return;
      }
      await proxyRequest(request, response, url, flowerOrigin);
      return;
    }
    send(response, 404, { "Content-Type": "text/plain" }, "Not Found");
    return;
  }

  if (!isProduction && vite) {
    let handled = false;
    await new Promise((resolve) => {
      vite.middlewares(request, response, () => {
        resolve();
      });
      response.on("finish", () => {
        handled = true;
        resolve();
      });
    });
    if (handled || response.writableEnded) {
      return;
    }
  }

  if (isProduction && (await serveStatic(pathname, response))) {
    return;
  }

  await renderPage(request, response);
}

const server = http.createServer((request, response) => {
  handle(request, response).catch((error) => {
    console.error(error);
    if (response.headersSent) {
      response.destroy();
    } else {
      send(response, 500, { "Content-Type": "text/plain" }, "Internal Server Error");
    }
  });
});

server.listen(port, host, () => {
  console.log(`SSR frontend listening at http://${host}:${port}`);
});

server.requestTimeout = 30_000;
server.headersTimeout = 15_000;
server.keepAliveTimeout = 5_000;

function shutdown(signal) {
  console.log(JSON.stringify({ event: "shutdown", signal }));
  server.close((error) => {
    process.exitCode = error ? 1 : 0;
  });
  setTimeout(() => server.closeAllConnections(), 10_000).unref();
}

process.once("SIGTERM", () => shutdown("SIGTERM"));
process.once("SIGINT", () => shutdown("SIGINT"));
