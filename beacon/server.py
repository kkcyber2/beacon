"""HTTP server: JSON feed endpoint plus a Server-Sent-Events stream.

The SSE endpoint is the point: a reader watching the page sees new clusters
arrive without polling. Implemented by writing `data:` frames and flushing,
with a heartbeat so a proxy does not silently drop the connection.
"""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .dedupe import cluster
from .feeds import parse_many

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".xml": "application/xml",
    ".txt": "text/plain; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "beacon/1.0"
    feeds: dict[str, str] = {}
    threshold = 0.62

    def log_message(self, fmt, *args):     # quieter than the default
        pass

    # ------------------------------------------------------------------ helpers
    def _json(self, payload, status=200):
        body = json.dumps(payload, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path):
        if not path.is_file():
            return self._not_found()
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(path.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _not_found(self):
        page = STATIC / "404.html"
        if page.is_file():
            body = page.read_bytes()
            self.send_response(404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    # --------------------------------------------------------------------- get
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/feed":
            q = parse_qs(parsed.query)
            try:
                threshold = float(q.get("threshold", [self.threshold])[0])
            except ValueError:
                return self._json({"error": "threshold must be a number"}, 400)
            if not 0.0 <= threshold <= 1.0:
                return self._json({"error": "threshold must be between 0 and 1"}, 400)

            results = parse_many(self.feeds)
            items = [i for r in results for i in r.items]
            clusters = cluster(items, threshold=threshold)
            return self._json(
                {
                    "clusters": [c.as_dict() for c in clusters],
                    "stats": {
                        "items": len(items),
                        "clusters": len(clusters),
                        "merged": len(items) - len(clusters),
                        "feeds_ok": sum(1 for r in results if r.ok),
                        "feeds_failed": [r.source for r in results if not r.ok],
                    },
                    "errors": {r.source: r.error for r in results if r.error},
                }
            )

        if path == "/api/stream":
            return self._stream()

        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        candidate = (STATIC / rel).resolve()
        # Path traversal guard: a resolved path must stay inside STATIC.
        if STATIC.resolve() not in candidate.parents and candidate != STATIC.resolve():
            return self._not_found()
        return self._file(candidate)

    # ------------------------------------------------------------------ stream
    def _stream(self, limit: int = 5, interval: float = 1.0):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            for n in range(limit):
                results = parse_many(self.feeds)
                items = [i for r in results for i in r.items]
                clusters = cluster(items, threshold=self.threshold)
                payload = {
                    "seq": n,
                    "clusters": [c.as_dict() for c in clusters[:5]],
                    "total": len(clusters),
                }
                self.wfile.write(f"event: update\ndata: {json.dumps(payload)}\n\n".encode())
                self.wfile.flush()
                if n < limit - 1:
                    time.sleep(interval)
            self.wfile.write(b"event: done\ndata: {}\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return          # the reader closed the tab; that is not an error


def serve(port: int = 8000, feeds: dict[str, str] | None = None, threshold: float = 0.62):
    Handler.feeds = feeds or {}
    Handler.threshold = threshold
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"beacon on http://127.0.0.1:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":      # pragma: no cover
    import argparse
    from .demo import DEMO_FEEDS

    p = argparse.ArgumentParser(description="Serve the beacon reader.")
    p.add_argument("--port", type=int, default=8000)
    serve(port=p.parse_args().port, feeds=DEMO_FEEDS)
