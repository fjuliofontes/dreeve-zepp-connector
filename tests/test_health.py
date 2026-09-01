import json
import urllib.error
import urllib.request
from datetime import UTC, datetime

from dreeve_zepp_connector.health import HealthServer, HealthState
from dreeve_zepp_connector.main import SyncResult


def test_state_snapshot_before_any_cycle():
    state = HealthState()

    snap = state.snapshot()

    assert snap["total_cycles"] == 0
    assert snap["last_cycle_started_at"] is None
    assert snap["last_result"] is None
    assert snap["last_error"] is None


def test_state_records_success():
    state = HealthState()

    state.record_success(datetime.now(tz=UTC), SyncResult(exported=2, skipped=1, failed=0))

    snap = state.snapshot()
    assert snap["total_cycles"] == 1
    assert snap["last_result"] == {"exported": 2, "skipped": 1, "failed": 0}
    assert snap["last_error"] is None


def test_state_records_failure():
    state = HealthState()

    state.record_failure(datetime.now(tz=UTC), "boom")

    snap = state.snapshot()
    assert snap["total_cycles"] == 1
    assert snap["last_error"] == "boom"


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3) as resp:
        return json.loads(resp.read())


def test_server_serves_healthz_and_status():
    state = HealthState()
    state.record_success(datetime.now(tz=UTC), SyncResult(exported=1, skipped=0, failed=0))
    server = HealthServer(state, port=0)  # OS-assigned port
    server.start()
    try:
        health = _get_json(f"http://localhost:{server.port}/healthz")
        assert health == {"status": "ok"}

        status = _get_json(f"http://localhost:{server.port}/status")
        assert status["total_cycles"] == 1
        assert status["last_result"] == {"exported": 1, "skipped": 0, "failed": 0}
    finally:
        server.stop()


def test_server_404s_on_unknown_path():
    state = HealthState()
    server = HealthServer(state, port=0)
    server.start()
    try:
        try:
            urllib.request.urlopen(f"http://localhost:{server.port}/nope", timeout=3)
            raise AssertionError("expected HTTPError")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        server.stop()
