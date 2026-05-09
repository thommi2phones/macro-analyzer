"""Lightweight health check HTTP server for container orchestration."""

import json
import logging
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)

# Shared state — updated by the agent loop
_status = {
    "status": "starting",
    "started_at": datetime.now(timezone.utc).isoformat(),
    "last_scan": None,
    "last_scan_signals": 0,
    "total_scans": 0,
    "watchlist_size": 0,
    "errors": [],
}


def update_status(**kwargs):
    """Update health status from the agent loop."""
    _status.update(kwargs)


def record_scan(signal_count: int):
    """Record a completed scan cycle."""
    _status["last_scan"] = datetime.now(timezone.utc).isoformat()
    _status["last_scan_signals"] = signal_count
    _status["total_scans"] = _status.get("total_scans", 0) + 1
    _status["status"] = "running"


def record_error(error: str):
    """Record an error (keep last 10)."""
    _status["errors"] = (_status.get("errors", []) + [
        {"time": datetime.now(timezone.utc).isoformat(), "error": error}
    ])[-10:]


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = json.dumps(_status).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress access logs


def start_health_server(port: int = 8081):
    """Start the health server in a daemon thread."""
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health server listening on :%d", port)
    return server
