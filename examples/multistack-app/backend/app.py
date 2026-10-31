import os
from http.server import BaseHTTPRequestHandler, HTTPServer

port = int(os.environ.get("PORT") or os.environ.get("BACKEND_PORT") or 8001)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"hello":"from backend"}\n')


print(f"backend ready on :{port}", flush=True)
HTTPServer(("127.0.0.1", port), H).serve_forever()
