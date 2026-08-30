from pathlib import Path

from dreeve_zepp_connector.config import Config, _parse_device_names


def _set_required_env(monkeypatch):
    monkeypatch.setenv("ZEPP_EMAIL", "user@example.com")
    monkeypatch.setenv("ZEPP_PASSWORD", "secret")


def test_parse_device_names_parses_multiple_entries():
    mapping = _parse_device_names("9568513=Amazfit Balance 2;1234567=Old Watch")

    assert mapping == {"9568513": "Amazfit Balance 2", "1234567": "Old Watch"}


def test_parse_device_names_returns_empty_when_unset():
    assert _parse_device_names(None) == {}
    assert _parse_device_names("") == {}


def test_parse_device_names_skips_malformed_entries():
    # A bad mapping should degrade to "no device name for that entry," not
    # crash the whole export.
    mapping = _parse_device_names("9568513=Balance 2;no-equals-sign;=empty-id;1234567=")

    assert mapping == {"9568513": "Balance 2"}


def test_v2_fields_default_when_unset(monkeypatch):
    _set_required_env(monkeypatch)
    for var in (
        "LIMIT",
        "ZEPP_MAX_RETRIES",
        "ZEPP_RETRY_BASE_DELAY",
        "DOWNLOAD_DELAY_SECONDS",
        "MAX_DOWNLOADS_PER_CYCLE",
        "POLL_INTERVAL",
        "HEALTH_PORT",
    ):
        monkeypatch.delenv(var, raising=False)

    cfg = Config.from_env()

    assert cfg.limit == 200
    assert cfg.max_retries == 5
    assert cfg.retry_base_delay == 2.0
    assert cfg.download_delay_seconds == 0.0
    assert cfg.max_downloads_per_cycle is None
    assert cfg.poll_interval_seconds == 3600
    assert cfg.health_port == 8080


def test_v2_fields_read_from_env(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("LIMIT", "50")
    monkeypatch.setenv("ZEPP_MAX_RETRIES", "3")
    monkeypatch.setenv("ZEPP_RETRY_BASE_DELAY", "1.5")
    monkeypatch.setenv("DOWNLOAD_DELAY_SECONDS", "0.5")
    monkeypatch.setenv("MAX_DOWNLOADS_PER_CYCLE", "10")
    monkeypatch.setenv("POLL_INTERVAL", "60")
    monkeypatch.setenv("HEALTH_PORT", "9090")

    cfg = Config.from_env()

    assert cfg.limit == 50
    assert cfg.max_retries == 3
    assert cfg.retry_base_delay == 1.5
    assert cfg.download_delay_seconds == 0.5
    assert cfg.max_downloads_per_cycle == 10
    assert cfg.poll_interval_seconds == 60
    assert cfg.health_port == 9090


def test_limit_override_wins_over_env(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("LIMIT", "50")

    cfg = Config.from_env(limit_override=5)

    assert cfg.limit == 5


def test_watch_dir_and_state_dir_default_to_different_directories(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.delenv("WATCH_DIR", raising=False)
    monkeypatch.delenv("STATE_DIR", raising=False)
    monkeypatch.delenv("LEDGER_PATH", raising=False)

    cfg = Config.from_env()

    assert cfg.watch_dir != cfg.state_dir
    assert cfg.watch_dir == Path("./output")
    assert cfg.state_dir == Path("./state")
    # The ledger belongs under STATE_DIR, never WATCH_DIR - it must never
    # show up as a stray file in Dreeve's watch folder.
    assert cfg.ledger_path == cfg.state_dir / "ledger.json"


def test_watch_dir_and_state_dir_read_from_env(monkeypatch, tmp_path):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("WATCH_DIR", str(tmp_path / "watch"))
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))

    cfg = Config.from_env()

    assert cfg.watch_dir == tmp_path / "watch"
    assert cfg.state_dir == tmp_path / "state"
    assert cfg.ledger_path == tmp_path / "state" / "ledger.json"


def test_watch_dir_override_wins_over_env(monkeypatch, tmp_path):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("WATCH_DIR", str(tmp_path / "env-watch"))

    cfg = Config.from_env(watch_dir_override=str(tmp_path / "cli-watch"))

    assert cfg.watch_dir == tmp_path / "cli-watch"


def test_ledger_path_override_is_independent_of_state_dir(monkeypatch, tmp_path):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("LEDGER_PATH", str(tmp_path / "elsewhere" / "ledger.json"))

    cfg = Config.from_env()

    assert cfg.ledger_path == tmp_path / "elsewhere" / "ledger.json"
