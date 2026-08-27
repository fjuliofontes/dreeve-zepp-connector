"""Environment-based configuration, loaded from a local .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


def _parse_device_names(raw: str | None) -> dict[str, str]:
    """`ZEPP_DEVICE_NAMES` format: `<device_id>=<name>;<device_id>=<name>`.
    `device_id` is Zepp's `devicesource` summary field (also embedded in
    `source`, e.g. `run.9568513.huami.com`) - a stable per-physical-device
    ID, so an account with multiple watches can map each to its real model.
    Malformed entries are skipped rather than raising - a bad mapping should
    degrade to "no device name for that workout," not crash the export."""
    if not raw:
        return {}
    mapping: dict[str, str] = {}
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        device_id, name = entry.split("=", 1)
        device_id, name = device_id.strip(), name.strip()
        if device_id and name:
            mapping[device_id] = name
    return mapping


@dataclass
class Config:
    email: str
    password: str
    output_dir: Path
    ledger_path: Path
    since: str | None
    country: str
    device_names: dict[str, str]

    @classmethod
    def from_env(cls, since_override: str | None = None, output_dir_override: str | None = None) -> "Config":
        email = os.environ.get("ZEPP_EMAIL")
        password = os.environ.get("ZEPP_PASSWORD")
        if not email or not password:
            raise ConfigError("Set ZEPP_EMAIL and ZEPP_PASSWORD (in .env or env).")

        output_dir = Path(output_dir_override or os.environ.get("OUTPUT_DIR", "./output")).expanduser()
        ledger_path = Path(os.environ.get("LEDGER_PATH", output_dir / "ledger.json")).expanduser()
        since = since_override or os.environ.get("SINCE")
        country = os.environ.get("ZEPP_COUNTRY", "US")
        device_names = _parse_device_names(os.environ.get("ZEPP_DEVICE_NAMES"))

        return cls(
            email=email,
            password=password,
            output_dir=output_dir,
            ledger_path=ledger_path,
            since=since,
            country=country,
            device_names=device_names,
        )
