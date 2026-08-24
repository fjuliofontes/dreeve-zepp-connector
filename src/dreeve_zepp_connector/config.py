"""Environment-based configuration, loaded from a local .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    email: str
    password: str
    output_dir: Path
    ledger_path: Path
    since: str | None

    @classmethod
    def from_env(cls, since_override: str | None = None, output_dir_override: str | None = None) -> "Config":
        email = os.environ.get("ZEPP_EMAIL")
        password = os.environ.get("ZEPP_PASSWORD")
        if not email or not password:
            raise ConfigError("Set ZEPP_EMAIL and ZEPP_PASSWORD (in .env or env).")

        output_dir = Path(output_dir_override or os.environ.get("OUTPUT_DIR", "./output")).expanduser()
        ledger_path = Path(os.environ.get("LEDGER_PATH", output_dir / "ledger.json")).expanduser()
        since = since_override or os.environ.get("SINCE")

        return cls(
            email=email,
            password=password,
            output_dir=output_dir,
            ledger_path=ledger_path,
            since=since,
        )
