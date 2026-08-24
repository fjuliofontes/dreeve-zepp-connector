import json
from datetime import datetime, timezone
from pathlib import Path

from dreeve_zepp_connector.decoder import parse_points

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "sample_workout_detail.json").read_text()
)
START_TIME = 1_700_000_000


def test_parse_points_decodes_all_channels():
    points = parse_points(START_TIME, FIXTURE)

    assert len(points) == 3
    assert [p.time for p in points] == [
        datetime.fromtimestamp(START_TIME + offset, tz=timezone.utc) for offset in (0, 10, 20)
    ]
    assert [round(p.latitude, 8) for p in points] == [40.0, 40.00001, 40.00002]
    assert [round(p.longitude, 8) for p in points] == [-73.95, -73.94999, -73.94998]
    assert [round(p.altitude, 2) for p in points] == [10.0, 11.0, 12.0]
    assert [p.heart_rate for p in points] == [120, 130, 150]
    assert [p.cadence for p in points] == [170, 180, 160]


def test_parse_points_returns_empty_for_trackless_workout():
    assert parse_points(START_TIME, {}) == []
    assert parse_points(START_TIME, {"longitude_latitude": ""}) == []


def test_parse_points_treats_all_missing_altitude_as_none():
    # Some workouts (no barometer reading, certain indoor-with-GPS modes)
    # report NO_VALUE (-2000000) for every altitude sample. Real accounts hit
    # this - it must decode to `None`, not the literal sentinel scaled to
    # -20000.0 meters.
    detail = dict(FIXTURE)
    detail["altitude"] = "-2000000;-2000000;-2000000"

    points = parse_points(START_TIME, detail)

    assert [p.altitude for p in points] == [None, None, None]
