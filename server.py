from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import os

HOST = "0.0.0.0"
PORT = 3000
BACKEND = "http://127.0.0.1:8000"
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def do_GET(self):
        parsed = urlsplit(self.path)

        if parsed.path in ("/search", "/health"):
            target = BACKEND + parsed.path
            if parsed.query:
                target += "?" + parsed.query

            try:
                req = Request(target, headers={"Accept": "application/json"})
                with urlopen(req, timeout=60) as response:
                    body = response.read()
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            except HTTPError as e:
                body = e.read()
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (URLError, TimeoutError) as e:
                body = ('{"error":"Backend non raggiungibile","detail":%r}' % str(e)).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return

        return super().do_GET()

if __name__ == "__main__":
    print(f"ScentHunter frontend: http://127.0.0.1:{PORT}")
    print(f"Proxy backend: {BACKEND}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
