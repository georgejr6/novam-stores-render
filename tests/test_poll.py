import hashlib
import hmac
import io
import json
import os
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

SECRET = "test-secret-test-secret-test-secret"
os.environ["RENDER_WORKER_SECRET"] = SECRET
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "worker"))
import poll  # noqa: E402

LOG = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        m = dict(p.split("=", 1) for p in self.headers["X-Render-Signature"].split(","))
        want = hmac.new(SECRET.encode(), m["t"].encode() + b"." + body, hashlib.sha256).hexdigest()
        ok = hmac.compare_digest(want, m["v1"])
        LOG.append((self.path, ok, dict(self.headers)))
        out = {"jobs": [{"id": "j1", "leaseToken": "L" * 48, "recipe": {"type": "tee", "colors": [{"name": "Black / White", "hex": "#000000", "shots": ["flat"]}], "logoUrl": "/api/brand-logo/x/y.png", "logoPath": "/etc/passwd"}}]} if self.path.endswith("claim") else {"ok": True}
        data = json.dumps(out).encode()
        self.send_response(200 if ok else 401)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Poll(unittest.TestCase):
    def test_claim_render_upload_complete(self):
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_port}"
        poll.BASES = [base]
        work = pathlib.Path(tempfile.mkdtemp())
        self.assertEqual(poll.claim(work), 1)
        seen = {}

        def fake_render(recipe, w, b):
            seen["recipe"] = recipe
            seen["base"] = b
            return [{"color": "Black / White", "shot": "flat", "seconds": 1.5, "webp": b"RIFFxxxxWEBPyyyy"}]

        poll.render_recipe = fake_render
        poll.render(work)
        srv.shutdown()
        self.assertTrue(all(ok for _, ok, _ in LOG), "every request carried a valid signature")
        self.assertEqual([p for p, _, _ in LOG], ["/api/internal/render/claim", "/api/internal/render/upload", "/api/internal/render/complete"])
        up = LOG[1][2]
        self.assertEqual(urllib.parse.unquote(up["X-Render-Color"]), "Black / White")
        self.assertNotIn("/", up["X-Render-Color"])
        self.assertEqual(up["X-Render-Job"], "j1")
        self.assertNotIn("logoPath", seen["recipe"], "local paths from the API are stripped")
        self.assertEqual(seen["base"], base)


if __name__ == "__main__":
    unittest.main()
