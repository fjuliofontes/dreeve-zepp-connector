"""Tracks which workouts have already been exported, so re-runs skip them."""

from __future__ import annotations

import json
from pathlib import Path


class Ledger:
    def __init__(self, path: Path):
        self.path = path
        self._entries: dict[str, dict] = {}
        if self.path.exists():
            self._entries = json.loads(self.path.read_text())

    def has(self, trackid: str) -> bool:
        return str(trackid) in self._entries

    def mark(self, trackid: str, filename: str, exported_at: str) -> None:
        self._entries[str(trackid)] = {"filename": filename, "exported_at": exported_at}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries, indent=2, sort_keys=True))
