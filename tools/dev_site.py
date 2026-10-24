"""The site (site/) on 127.0.0.1:8790 for preview, with /api/sayac answered
by the sample counter of tools/dev_counter_site.py, as Cloudflare Pages
will answer it with functions/api/sayac.js.

    backend/.venv/Scripts/python tools/dev_site.py [--port 8790]
"""
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dev_counter_site  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Site(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/api/sayac":
            dev_counter_site.Site.do_GET(self)
            return
        super().do_GET()

    def _reply(self, status, data):
        dev_counter_site.Site._reply(self, status, data)


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8790
    handler = partial(Site, directory=os.path.join(ROOT, "site"))
    print(f"site on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
