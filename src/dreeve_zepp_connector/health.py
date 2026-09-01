"""Minimal health/status HTTP server for running as a long-lived container.

Stdlib-only (`http.server`) - the project has no web-framework dependency
and two JSON endpoints don't warrant adding one.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class HealthState:
    """Thread-safe in-memory snapshot of the poll loop's status. Written by
    `loop.py` after each cycle, read by `HealthServer`'s request handler on
    a different thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.started_at = datetime.now(tz=UTC)
        self.total_cycles = 0
        self.last_cycle_started_at: datetime | None = None
        self.last_cycle_finished_at: datetime | None = None
        self.last_result: dict | None = None
        self.last_error: str | None = None

    def record_success(self, cycle_start: datetime, result) -> None:
        with self._lock:
            self.total_cycles += 1
            self.last_cycle_started_at = cycle_start
            self.last_cycle_finished_at = datetime.now(tz=UTC)
            self.last_result = {
                "exported": result.exported,
                "skipped": result.skipped,
                "failed": result.failed,
            }
            self.last_error = None

    def record_failure(self, cycle_start: datetime, error: str) -> None:
        with self._lock:
            self.total_cycles += 1
            self.last_cycle_started_at = cycle_start
            self.last_cycle_finished_at = datetime.now(tz=UTC)
            self.last_error = error

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "started_at": self.started_at.isoformat(),
                "total_cycles": self.total_cycles,
                "last_cycle_started_at": self.last_cycle_started_at.isoformat() if self.last_cycle_started_at else None,
                "last_cycle_finished_at": self.last_cycle_finished_at.isoformat()
                if self.last_cycle_finished_at
                else None,
                "last_result": self.last_result,
                "last_error": self.last_error,
            }


def _make_handler(state: HealthState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _write_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._write_json(200, {"status": "ok"})
            elif self.path == "/status":
                self._write_json(200, state.snapshot())
            else:
                self._write_json(404, {"error": "not found"})

        def log_message(self, format: str, *args) -> None:
            pass  # quiet by default - loop.py already prints cycle summaries

    return Handler


class HealthServer:
    def __init__(self, state: HealthState, port: int) -> None:
        self._server = ThreadingHTTPServer(("0.0.0.0", port), _make_handler(state))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
