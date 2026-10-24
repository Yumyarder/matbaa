"""The API on port 8000 for front-end work, on a scratch copy of the books.

Design and UI work converts, opens and edits books all day; doing that on
the reader's real library (~/Matbaa/projects) would leave test copies on
their shelf. This runs the same app with MATBAA_PROJECTS pointed at
.matbaa-work/dev-projects (git-ignored), seeded once from the real store.

    backend/.venv/Scripts/python tools/dev_server.py [--port 8000] [--counter]

--counter also starts a stand-in for the site's counter
(tools/dev_counter_site.py, port 8791) and points the app at it, so the
start screen shows the counter with sample figures.
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, ".matbaa-work", "dev-projects")


def seed():
    if os.path.isdir(STORE) and os.listdir(STORE):
        return
    os.makedirs(STORE, exist_ok=True)
    real = os.path.join(os.path.expanduser("~"), "Matbaa", "projects")
    if os.path.isdir(real):
        for name in os.listdir(real):
            if name.endswith(".json"):
                shutil.copy2(os.path.join(real, name), STORE)


def main():
    port = sys.argv[sys.argv.index("--port") + 1] if "--port" in sys.argv else "8000"
    seed()
    env = dict(os.environ, MATBAA_PROJECTS=STORE)
    if "--counter" in sys.argv:
        subprocess.Popen([sys.executable, os.path.join(ROOT, "tools", "dev_counter_site.py"), "--port", "8791"])
        env["MATBAA_COUNTER_URL"] = "http://127.0.0.1:8791/api/sayac"
    return subprocess.call([sys.executable, "-m", "uvicorn", "app.main:app", "--app-dir",
                            os.path.join(ROOT, "backend"), "--port", port], env=env)


if __name__ == "__main__":
    sys.exit(main())
