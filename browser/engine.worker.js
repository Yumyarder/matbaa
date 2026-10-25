// Matbaa in the browser: the engine.
//
// Matbaa's own Python (backend/app, the same code as the desktop app) on
// Pyodide, in a worker of its own so a long conversion never freezes the
// page. The page's requests reach it from the service worker (sw.js) by
// way of the page; app/browser.py answers them by calling the FastAPI app
// in-process. The reader's home folder — their books (~/Matbaa/projects)
// and settings (~/.matbaa) — is kept in this browser's IndexedDB and
// written back after every request; nothing is sent anywhere.
"use strict";

// engine.json (tools/build_browser.py): where Pyodide is, the packages to
// load in order — Pyodide's own builds and PyMuPDF's official WebAssembly
// wheel — and the archive of Matbaa's Python.
let config = null;
let py = null;
let handle = null;
const waiting = [];
let saving = Promise.resolve();
let saveAgain = false;
let saveTimer = null;

function progress(step, detail) {
  self.postMessage({ kind: "progress", step, detail });
}

function syncfs(populate) {
  return new Promise((resolve, reject) => py.FS.syncfs(populate, (err) => (err ? reject(err) : resolve())));
}

// Write the home folder back to IndexedDB once requests settle; never two
// writes at once (Emscripten's syncfs does not queue them itself).
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    if (saveAgain) return;
    saveAgain = true;
    saving = saving.then(() => {
      saveAgain = false;
      return syncfs(false);
    }).catch((err) => self.postMessage({ kind: "save-failed", error: String(err) }));
  }, 250);
}

// Fetch every file the engine needs once, counting the bytes as they come,
// so the boot screen can show how far the download is; Pyodide then finds
// them in the HTTP cache (the files are served immutable).
async function download(files) {
  const total = files.reduce((sum, f) => sum + f.size, 0);
  let done = 0;
  let last = 0;
  const report = (force) => {
    const now = Date.now();
    if (force || now - last > 200) {
      last = now;
      progress("download", { done, total });
    }
  };
  const queue = files.slice();
  async function next() {
    for (let f = queue.shift(); f; f = queue.shift()) {
      const res = await fetch("./" + f.path);
      if (!res.ok) throw new Error(`${f.path}: ${res.status}`);
      const reader = res.body.getReader();
      for (;;) {
        const { done: end, value } = await reader.read();
        if (end) break;
        done += value.byteLength;
        report(false);
      }
    }
  }
  await Promise.all([next(), next(), next(), next()]);
  report(true);
}

async function boot(cfg) {
  config = cfg;
  const manifest = await (await fetch("./engine.json", { cache: "no-cache" })).json();
  if (manifest.files) await download(manifest.files);
  progress("core");
  const PYODIDE = manifest.pyodide;
  importScripts(PYODIDE + "pyodide.js");
  py = await self.loadPyodide({
    indexURL: PYODIDE,
    env: {
      HOME: "/home/pyodide",
      MATBAA_ONLINE: cfg.online ? "1" : "",
      MATBAA_COUNTER_URL: cfg.counterUrl || "",
      MATBAA_BROWSER: "1",
    },
  });

  progress("packages");
  await py.loadPackage(manifest.packages.map((p) => (p.endsWith(".whl") ? PYODIDE + p : p)),
    { messageCallback: () => {}, errorCallback: (m) => console.warn(m) });

  progress("library");
  py.FS.mkdirTree("/home/pyodide");
  py.FS.mount(py.FS.filesystems.IDBFS, {}, "/home/pyodide");
  await syncfs(true);

  progress("matbaa");
  const app = await (await fetch("./" + manifest.app)).arrayBuffer();
  py.unpackArchive(app, "zip", { extractDir: "/matbaa" });
  await py.runPythonAsync("import sys\nsys.path.insert(0, '/matbaa')\nfrom app import browser\nawait browser.start()");
  handle = py.pyimport("app.browser").handle;
  self.postMessage({ kind: "ready" });
  waiting.splice(0).forEach((go) => go());
}

async function answer(msg, port) {
  let res;
  try {
    const body = msg.body ? new Uint8Array(msg.body) : null;
    const headers = py.toPy(msg.headers || {});
    try {
      res = await handle(msg.method, msg.path, headers, body); // a plain object (app/browser.py)
    } finally {
      headers.destroy();
    }
  } catch (err) {
    console.error(err);
    const text = new TextEncoder().encode(JSON.stringify({ detail: "Tezgâhta bir hata oldu: " + String(err).slice(0, 300) }));
    res = { status: 500, headers: [["content-type", "application/json"]], body: text };
  }
  const buffer = res.body.buffer.byteLength === res.body.byteLength ? res.body.buffer : res.body.slice().buffer;
  port.postMessage({ status: res.status, headers: res.headers, body: buffer }, [buffer]);
  scheduleSave();
}

self.onmessage = (event) => {
  const msg = event.data || {};
  if (msg.kind === "boot") {
    boot(msg.config).catch((err) => {
      console.error(err);
      self.postMessage({ kind: "failed", error: String(err && err.message ? err.message : err) });
    });
  } else if (msg.kind === "matbaa-api") {
    // a request that comes before the engine is up waits for it
    const port = event.ports[0];
    if (handle) answer(msg, port);
    else waiting.push(() => answer(msg, port));
  }
};
