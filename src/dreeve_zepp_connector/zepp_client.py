"""
Zepp / Amazfit cloud data client.

Ported from zepp-mcp's `huami_client.py`, with the token-saving truncation
of GPS/heart-rate/altitude track fields removed — this project needs the
full encoded track strings to decode into FIT records.

Login uses the maintained `huami-token` lib (handles the 2025 encrypted
`api-user.zepp.com` handshake). Data queries are issued here against
api-mifit.zepp.com with the app_token.
"""

from __future__ import annotations

import json
import base64
import sys
import uuid
from dataclasses import dataclass, field

import requests
from loguru import logger

from huami_token.constants import HEADERS
from huami_token.zepp import ZeppSession

# Silence the lib's DEBUG/INFO logging so credentials/tokens never hit stdout.
logger.remove()
logger.add(sys.stderr, level="WARNING")

DATA_HOST = "api-mifit.zepp.com"


class ZeppClientError(RuntimeError):
    pass


def _data_headers(app_token: str) -> dict:
    h = HEADERS.ZEPP_DEVICES.value.copy()
    h["apptoken"] = app_token
    h["x-request-id"] = str(uuid.uuid4())
    return h


@dataclass
class ZeppDataClient:
    email: str
    password: str
    session: ZeppSession | None = None
    _http: requests.Session = field(default_factory=requests.Session)
    _source_cache: dict[str, str] = field(default_factory=dict)

    # ---- auth -----------------------------------------------------------

    def login(self) -> None:
        self.session = ZeppSession(self.email, self.password)
        self.session.login()

    @property
    def app_token(self) -> str | None:
        return self.session._app_token if self.session else None

    @property
    def user_id(self) -> str | None:
        return self.session._user_id if self.session else None

    def _ensure(self) -> None:
        if not self.session or not self.session._app_token:
            self.login()

    def _get(self, path: str, params: dict) -> dict:
        self._ensure()
        url = f"https://{DATA_HOST}{path}"
        r = self._http.get(
            url, headers=_data_headers(self.app_token), params=params, timeout=30
        )
        try:
            return r.json()
        except ValueError:
            raise ZeppClientError(f"{path} -> {r.status_code} non-JSON: {r.text[:300]}")

    # ---- data -----------------------------------------------------------

    def workouts(self, limit: int = 50) -> list[dict]:
        """List the most recent workout/sport sessions (single page). Each
        has a `trackid` for detail. For paging further back, use
        `workouts_page()` directly."""
        return self.workouts_page(limit=limit)[0]

    def workouts_page(
        self, limit: int = 50, before_trackid: int | str | None = None
    ) -> tuple[list[dict], int | None]:
        """One page of workout summaries, newest-first.

        Zepp's history endpoint pages via a `trackid` cursor rather than an
        offset: pass the previous call's returned cursor as `before_trackid`
        to continue further into the past. Returns `(items, next_cursor)`;
        `next_cursor` is None once there are no more pages.
        """
        params = {"source": "run.mi.com", "userid": self.user_id, "limit": str(limit)}
        if before_trackid is not None:
            params["trackid"] = str(before_trackid)
        j = self._get("/v1/sport/run/history.json", params)
        items = _extract_list(j)
        for w in items:
            if isinstance(w, dict) and w.get("trackid") and w.get("source"):
                self._source_cache[str(w["trackid"])] = w["source"]
        data = j.get("data", j)
        next_cursor = data.get("next") if isinstance(data, dict) else None
        if next_cursor in (None, -1):
            next_cursor = None
        return items, next_cursor

    def workout_detail(self, trackid: str, source: str | None = None) -> dict:
        """Full raw track for one workout: GPS, pace, HR series, altitude, gait.

        `source` auto-resolves from recent workouts if omitted. Unlike
        zepp-mcp, the encoded track-data strings are returned in full,
        untouched, for decoding by `decoder.py`.
        """
        trackid = str(trackid)
        if source is None:
            source = self._source_cache.get(trackid)
            if source is None:
                self.workouts(limit=200)  # populate source cache
                source = self._source_cache.get(trackid, "run.mi.com")
        j = self._get(
            "/v1/sport/run/detail.json",
            {"trackid": str(trackid), "source": source, "userid": self.user_id},
        )
        return j.get("data", j)


def _maybe_b64_json(raw):
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        try:
            return json.loads(raw)
        except Exception:
            return {"_raw": raw}


def _extract_list(j: dict) -> list[dict]:
    data = j.get("data", j)
    if isinstance(data, dict):
        summary = data.get("summary")
        if isinstance(summary, str):
            try:
                summary = json.loads(summary)
            except Exception:
                pass
        if isinstance(summary, dict) and isinstance(summary.get("data"), list):
            return summary["data"]
        if isinstance(summary, list):
            return summary
        if isinstance(data.get("items"), list):
            return data["items"]
    if isinstance(data, list):
        return data
    return [{"_raw": j}]
