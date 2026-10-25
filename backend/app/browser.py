"""Matbaa in the browser: the FastAPI app called in-process on Pyodide.

browser/engine.worker.js loads this module and hands every request the page
makes under /api/ to handle(); the answer goes back the way it came (see
browser/sw.js). Nothing here runs on the desktop.

Pyodide has no threads and no sockets. Starlette runs a plain `def`
endpoint, and reads an uploaded file, in a worker thread: here they run
inline (the engine serves one page, one request at a time). urllib goes out
through the browser (pyodide-http), so the Wikidata, Vikisöz and counter
requests the desktop app makes still work, under the browser's own rules.
The request guard in main.py is for a server other programs on the computer
could reach; this one only the page that started it can, so the headers it
checks are those of a local page.
"""
from __future__ import annotations

import sys

# Headers a browser adds that describe the site, not the engine it reaches.
_SITE_HEADERS = {"host", "origin", "referer", "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest", "cookie"}

_app = None


def _no_threads() -> None:
    import anyio.to_thread
    import fastapi.dependencies.utils as dependencies
    import fastapi.routing as routing
    import starlette.concurrency as concurrency
    import starlette.datastructures as datastructures

    async def run_sync(func, *args, abandon_on_cancel=False, cancellable=None, limiter=None):
        return func(*args)

    async def run_in_threadpool(func, *args, **kwargs):
        return func(*args, **kwargs)

    anyio.to_thread.run_sync = run_sync
    for module in (concurrency, routing, dependencies, datastructures):
        if hasattr(module, "run_in_threadpool"):
            module.run_in_threadpool = run_in_threadpool


async def start() -> None:
    global _app
    if sys.platform != "emscripten":
        raise RuntimeError("app.browser runs only on Pyodide")
    import pyodide_http

    pyodide_http.patch_all()
    _no_threads()
    from app import main

    _app = main.app


async def handle(method: str, path: str, headers, body=None):
    """One request from the page; a JS object {status, headers, body}."""
    from js import Object, Uint8Array
    from pyodide.ffi import to_js

    # a GET has no body: JS null, which reaches Python as jsnull, not None
    raw = body.to_bytes() if hasattr(body, "to_bytes") else b""
    given = headers.to_py() if hasattr(headers, "to_py") else dict(headers or {})
    pairs = [(k.lower(), v) for k, v in given.items() if k.lower() not in _SITE_HEADERS]
    pairs.append(("host", "localhost"))
    query = ""
    if "?" in path:
        path, query = path.split("?", 1)
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method.upper(),
        "scheme": "http", "path": path, "raw_path": path.encode("utf-8"), "query_string": query.encode("latin-1"),
        "root_path": "", "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in pairs],
        "client": ("127.0.0.1", 0), "server": ("localhost", 80),
    }
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": raw, "more_body": False}

    status = 500
    out_headers: list = []
    chunks: list = []

    async def send(message):
        nonlocal status, out_headers
        if message["type"] == "http.response.start":
            status = message["status"]
            out_headers = [[k.decode("latin-1"), v.decode("latin-1")] for k, v in message.get("headers", [])]
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await _app(scope, receive, send)
    data = b"".join(chunks)
    array = Uint8Array.new(len(data))
    array.assign(data)
    return to_js({"status": status, "headers": out_headers, "body": array}, dict_converter=Object.fromEntries)
