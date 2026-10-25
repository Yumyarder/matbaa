"""The site (site/) on 127.0.0.1:8790 for preview, with /api/sayac answered
by the sample counter of tools/dev_counter_site.py, as Cloudflare Pages
will answer it with functions/api/sayac.js, and with the headers of
site/_headers applied the way Pages applies them (a rule's `! Name` drops a
header an earlier rule set), so the browser build (site/uygulama/) runs
here under the policy it will have there.

    backend/.venv/Scripts/python tools/dev_site.py [--port 8790]
"""
import mimetypes
import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dev_counter_site  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mimetypes.add_type("application/wasm", ".wasm")


def header_rules(path):
    """site/_headers as [(regex, [(name, value or None to drop)])]."""
    rules = []
    if not os.path.exists(path):
        return rules
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line[0].isspace():
                pattern = "^" + re.escape(line.strip()).replace(r"\*", ".*") + "$"
                rules.append((re.compile(pattern), []))
            elif rules:
                item = line.strip()
                if item.startswith("!"):
                    rules[-1][1].append((item[1:].strip(), None))
                elif ":" in item:
                    name, value = item.split(":", 1)
                    rules[-1][1].append((name.strip(), value.strip()))
    return rules


RULES = header_rules(os.path.join(ROOT, "site", "_headers"))


class Site(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/api/sayac":
            dev_counter_site.Site.do_GET(self)
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802
        if self.path.split("?")[0] == "/api/sayac":
            dev_counter_site.Site.do_POST(self)
            return
        self.send_error(405)

    def _reply(self, status, data):
        dev_counter_site.Site._reply(self, status, data)

    def end_headers(self):
        path = self.path.split("?")[0]
        headers = {}
        for regex, items in RULES:
            if regex.match(path):
                for name, value in items:
                    key = name.lower()
                    if value is None:
                        headers.pop(key, None)
                    else:
                        headers[key] = (name, f"{headers[key][1]}, {value}" if key in headers else value)
        for name, value in headers.values():
            self.send_header(name, value)
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8790
    handler = partial(Site, directory=os.path.join(ROOT, "site"))
    print(f"site on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), handler).serve_forever()
