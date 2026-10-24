"""A stand-in for the site's counter (functions/api/sayac.js), for front-end
work: GET answers with sample figures, POST adds to them.

    backend/.venv/Scripts/python tools/dev_counter_site.py [--port 8791]

tools/dev_server.py --counter starts it and points the app at it.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

now = datetime.now(timezone.utc)
ROWS = ([("felsefe", 30)] * 4 + [("siyaset", 26)] * 3 + [("rus-edebiyati", 20)] * 2 + [("turk-edebiyati", 50)] * 2
        + [("ekonomi", 70), ("sosyoloji", 90), ("sanat", 110), ("psikoloji", 130)])
EVENTS = [(tur, (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H")) for tur, h in ROWS]
EVENTS.sort(key=lambda e: e[1])
EVENTS = [("felsefe", (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H"))] + EVENTS[1:]


class Site(BaseHTTPRequestHandler):
    def _reply(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        counts = {}
        for tur, _ in EVENTS:
            counts[tur] = counts.get(tur, 0) + 1
        genres = sorted(({"tur": t, "n": n} for t, n in counts.items()), key=lambda g: (-g["n"], g["tur"]))
        recent = [{"tur": t, "saat": s} for t, s in sorted(EVENTS, key=lambda e: e[1], reverse=True)[:20]]
        self._reply(200, {"total": len(EVENTS), "genres": genres, "recent": recent})

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        tur = json.loads(self.rfile.read(n).decode("utf-8")).get("tur", "diger")
        EVENTS.append((tur, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")))
        self._reply(201, {"ok": True})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8791
    ThreadingHTTPServer(("127.0.0.1", port), Site).serve_forever()
