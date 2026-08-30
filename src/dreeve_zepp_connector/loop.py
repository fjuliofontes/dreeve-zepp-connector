"""Continuous polling daemon: runs `main.sync()` on a `POLL_INTERVAL`
cadence instead of relying on external cron, with `/healthz`/`/status`
endpoints for monitoring when run as a long-lived container (see `health.py`).
"""

from __future__ import annotations

import signal
import sys
import time
from datetime import datetime, timezone

from .config import Config, ConfigError
from .health import HealthServer, HealthState
from .ledger import Ledger
from .main import sync
from .zepp_client import ZeppDataClient


def run() -> int:
    try:
        cfg = Config.from_env()
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    cfg.watch_dir.mkdir(parents=True, exist_ok=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(cfg.ledger_path)

    client = ZeppDataClient(
        email=cfg.email,
        password=cfg.password,
        country=cfg.country,
        max_retries=cfg.max_retries,
        retry_base_delay=cfg.retry_base_delay,
    )
    cached_auth = ledger.cached_auth()
    if cached_auth and cached_auth.get("email") == cfg.email and cached_auth.get("country") == cfg.country:
        client.use_cached_auth(cached_auth["app_token"], cached_auth["user_id"])
    else:
        try:
            client.login()
        except Exception as e:
            print(f"login failed: {e}", file=sys.stderr)
            return 1

    state = HealthState()
    server = HealthServer(state, cfg.health_port)
    server.start()
    print(f"health server listening on :{cfg.health_port} (/healthz, /status)")

    stop = False

    def _handle_signal(signum, frame) -> None:
        nonlocal stop
        print(f"received signal {signum}, stopping after current cycle")
        stop = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print(f"starting poll loop: every {cfg.poll_interval_seconds}s")
    while not stop:
        cycle_start = datetime.now(tz=timezone.utc)
        try:
            result = sync(cfg, client, ledger, dry_run=False)
            state.record_success(cycle_start, result)
            print(f"cycle done: {result.exported} exported, {result.skipped} already synced, {result.failed} failed")
        except Exception as e:
            state.record_failure(cycle_start, str(e))
            print(f"cycle failed: {e}", file=sys.stderr)

        for _ in range(cfg.poll_interval_seconds):
            if stop:
                break
            time.sleep(1)

    server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(run())
