import os
import sys
import yaml  # non déclaré dans requirements.txt : zero doit le deviner
from http.server import BaseHTTPRequestHandler, HTTPServer

print(yaml.safe_dump({"app": "python-demo", "python": sys.version.split()[0]}), end="")
port = int(os.environ.get("PORT", 8000))


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"hello from python-demo\n")


print(f"python-demo listening on :{port}", flush=True)
HTTPServer(("127.0.0.1", port), H).serve_forever()
