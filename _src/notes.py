"""Local preview with a feedback layer: sticky notes and drawings on the site, saved for Claude to read.

    python3 _src/notes.py            # then open http://127.0.0.1:8765
    python3 _src/notes.py --port 9000

Serves the repo like `python3 -m http.server`, never cached, and adds the notes toolbar
(_src/tools/notes.js) to index.html as it is sent. Nothing about the toolbar is written into
index.html or deployed. Notes are saved to _notes/notes.json (gitignored).
"""
import http.server
import json
import os
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES = os.path.join(REPO, "_notes", "notes.json")
SCRIPT = os.path.join(REPO, "_src", "tools", "notes.js")
LOCK = threading.Lock()


def load():
    try:
        with open(NOTES) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def save(notes):
    os.makedirs(os.path.dirname(NOTES), exist_ok=True)
    tmp = NOTES + ".tmp"
    with open(tmp, "w") as f:
        json.dump(notes, f, indent=1, ensure_ascii=False)
    os.replace(tmp, NOTES)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=REPO, **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass

    def send_body(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0].split("#")[0]
        if path == "/__notes":
            with LOCK:
                return self.send_body(json.dumps(load()).encode(), "application/json")
        if path == "/__notes.js":
            with open(SCRIPT, "rb") as f:
                return self.send_body(f.read(), "text/javascript; charset=utf-8")
        if path in ("/", "/index.html"):
            with open(os.path.join(REPO, "index.html"), encoding="utf-8") as f:
                doc = f.read()
            doc = doc.replace("</body>", '<script src="/__notes.js"></script>\n</body>', 1)
            return self.send_body(doc.encode(), "text/html; charset=utf-8")
        return super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/__notes":
            return self.send_error(404)
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.send_error(400)
        with LOCK:
            notes = load()
            act = req.get("action")
            if act == "add":
                n = dict(req.get("note") or {})
                n["id"] = max([x.get("id", 0) for x in notes] + [0]) + 1
                n["created"] = time.strftime("%Y-%m-%d %H:%M")
                n["done"] = False
                notes.append(n)
            elif act == "update":
                for x in notes:
                    if x.get("id") == req.get("id"):
                        x.update({k: v for k, v in (req.get("fields") or {}).items() if k != "id"})
            elif act == "delete":
                notes = [x for x in notes if x.get("id") != req.get("id")]
            elif act == "clear_done":
                notes = [x for x in notes if not x.get("done")]
            else:
                return self.send_error(400)
            save(notes)
            return self.send_body(json.dumps(notes).encode(), "application/json")


def main():
    port = 8765
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Site with notes: http://127.0.0.1:{port}   (notes saved to {os.path.relpath(NOTES, REPO)})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
