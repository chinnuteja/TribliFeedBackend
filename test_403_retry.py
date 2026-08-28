"""One intermittent 403 must be retried, not recorded as a block.
python test_403_retry.py"""
import os, threading
os.environ["TRIBLI_DELAY"] = "0"

from http.server import BaseHTTPRequestHandler, HTTPServer
from app import fetcher

hits = {"n": 0}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/flaky":
            hits["n"] += 1
            code = 403 if hits["n"] == 1 else 200      # 403 once, then fine
        elif self.path == "/hard":
            code = 403                                  # 403 always
        else:
            code = 404
        body = b"ok"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"

fetcher.take_retry_notes()
assert fetcher.get(f"{base}/flaky") == "ok"            # recovered on retry
assert hits["n"] == 2, hits
notes = fetcher.take_retry_notes()
assert notes and "403" in notes[0] and "retried" in notes[0], notes

try:
    fetcher.get(f"{base}/hard")
    raise AssertionError("a standing 403 must still raise Blocked")
except fetcher.Blocked as e:
    assert "retried once" in str(e), str(e)            # and say it was retried

srv.shutdown()
print("403 retry OK")
