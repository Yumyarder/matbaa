// Matbaa in the browser: the service worker of /uygulama/.
//
// The app's page asks its server for everything under /api/ — that is how
// the desktop app works, and the page is the same page. Here there is no
// server: this worker answers those requests from the engine (Matbaa's own
// Python, on Pyodide) that the page runs in a Web Worker of its own. A
// request goes to the page as a message with a port; the page hands it to
// the engine; the answer comes back on the port. Nothing under /api/ leaves
// the browser, except the site's own counter (/api/sayac), which passes.
"use strict";

const ENGINE_TIMEOUT_MS = 10 * 60 * 1000; // a long book's conversion

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

function forEngine(url) {
  return url.origin === self.location.origin && url.pathname.startsWith("/api/") && url.pathname !== "/api/sayac";
}

// The window that runs the engine: the one that asked, or else the app's
// window (an iframe inside it, a worker it started, a download it began).
async function engineWindow(clientId) {
  const asking = clientId ? await self.clients.get(clientId) : null;
  if (asking && asking.type === "window" && new URL(asking.url).pathname.startsWith("/uygulama/")) return asking;
  const windows = await self.clients.matchAll({ type: "window" });
  return windows.find((w) => new URL(w.url).pathname.startsWith("/uygulama/")) || null;
}

async function relay(request, clientId) {
  const target = await engineWindow(clientId);
  if (!target) {
    return new Response(JSON.stringify({ detail: "Matbaa'nın tezgâhı açık değil." }),
      { status: 503, headers: { "Content-Type": "application/json" } });
  }
  const url = new URL(request.url);
  const headers = {};
  request.headers.forEach((value, key) => { headers[key] = value; });
  const body = ["GET", "HEAD"].includes(request.method) ? null : await request.arrayBuffer();
  const channel = new MessageChannel();
  const answer = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("timeout")), ENGINE_TIMEOUT_MS);
    channel.port1.onmessage = (event) => { clearTimeout(timer); resolve(event.data); };
  });
  const message = { kind: "matbaa-api", method: request.method, path: url.pathname + url.search, headers, body };
  target.postMessage(message, body ? [channel.port2, body] : [channel.port2]);
  try {
    const res = await answer;
    return new Response(res.status === 204 || res.status === 304 ? null : res.body,
      { status: res.status, headers: res.headers });
  } catch (err) {
    return new Response(JSON.stringify({ detail: "Tezgâh yanıt vermedi." }),
      { status: 504, headers: { "Content-Type": "application/json" } });
  }
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (!forEngine(url)) return; // the network, as usual
  event.respondWith(relay(event.request, event.clientId || event.resultingClientId));
});
