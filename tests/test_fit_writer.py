from datetime import datetime, timezone

from fit_tool.fit_file import FitFile

from dreeve_zepp_connector.decoder import ExportablePoint
from dreeve_zepp_connector.fit_writer import build_fit

START_TRACKID = 1_700_000_000


def _session_and_lap(data: bytes):
    messages = [r.message for r in FitFile.from_bytes(data).records]
    session = next(m for m in messages if type(m).__name__ == "SessionMessage")
    lap = next(m for m in messages if type(m).__name__ == "LapMessage")
    return session, lap


def test_build_fit_accepts_decimal_string_summary_fields():
    # Zepp's API returns numeric summary fields as strings like "375.0" for
    # some workouts - a bare int("375.0") raises ValueError.
    summary = {
        "trackid": str(START_TRACKID),
        "type": "1",
        "dis": "5000.0",
        "calorie": "375.0",
        "avg_heart_rate": "152.0",
        "run_time": "1800.0",
    }

    data = build_fit(summary, [])
    session, lap = _session_and_lap(data)

    assert session.total_calories == 375
    assert session.avg_heart_rate == 152
    assert lap.total_calories == 375
    assert lap.avg_heart_rate == 152
    assert session.sport == 1  # Sport.RUNNING, resolved despite "type" being a string


def test_build_fit_omits_altitude_when_entirely_missing():
    points = [
        ExportablePoint(
            time=datetime.fromtimestamp(START_TRACKID + i, tz=timezone.utc),
            latitude=40.0 + i * 0.0001,
            longitude=-73.95,
            altitude=None,
            heart_rate=120,
            cadence=170,
        )
        for i in range(3)
    ]
    summary = {"trackid": str(START_TRACKID), "type": 1, "dis": 100, "calorie": 10, "avg_heart_rate": 120}

    data = build_fit(summary, points)  # must not raise

    records = [
        r.message
        for r in FitFile.from_bytes(data).records
        if type(r.message).__name__ == "RecordMessage"
    ]
    assert len(records) == 3
    assert all(r.altitude is None for r in records)


def test_build_fit_never_emits_generic_generic_sport():
    # Confirmed live: at least some deployed Dreeve versions reject
    # sport=0/sub_sport=0 outright ("Unsupported FIT sport 0 (sub sport 0)"),
    # even though it's a valid FIT combo and Dreeve's current GitHub master
    # has a fallback that would accept it. Never emit that exact pair -
    # covers both an explicitly-mapped generic type and a totally unknown one.
    for zepp_type in (16, 223, 9999):
        summary = {"trackid": str(START_TRACKID), "type": zepp_type, "run_time": "60"}
        session, _ = _session_and_lap(build_fit(summary, []))
        assert (session.sport, session.sub_sport) != (0, 0), f"type {zepp_type} resolved to (0, 0)"


def test_build_fit_emits_synthetic_records_for_trackless_workouts():
    # Dreeve's FitFileParser.php unconditionally rejects any FIT file with
    # zero `record` messages, regardless of how complete the Session/Lap
    # summary data is - confirmed against its source. Pool swims, strength
    # training, etc. have no decoded GPS track, so build_fit must synthesize
    # a placeholder record stream rather than leaving `record` empty.
    summary = {
        "trackid": str(START_TRACKID),
        "type": 14,  # pool swim
        "dis": "1000.0",
        "calorie": "300.0",
        "avg_heart_rate": "130.0",
        "run_time": "1800.0",
    }

    data = build_fit(summary, [])

    records = [
        r.message
        for r in FitFile.from_bytes(data).records
        if type(r.message).__name__ == "RecordMessage"
    ]
    assert len(records) > 1
    assert records[0].timestamp == START_TRACKID * 1000
    assert records[-1].timestamp == (START_TRACKID + 1800) * 1000
    assert all(r.heart_rate == 130 for r in records)
    assert records[0].distance == 0
    assert records[-1].distance == 1000.0
    assert all(r.position_lat is None for r in records)


def test_build_fit_drops_out_of_range_interpolated_values():
    # decoder's floor-division interpolation can under/overshoot into
    # physically impossible values across a wide gap between real samples
    # (seen live: cadence of -46). FIT's uint8/uint16 encoding would raise on
    # these; build_fit must drop just the offending field, not the point.
    point = ExportablePoint(
        time=datetime.fromtimestamp(START_TRACKID, tz=timezone.utc),
        latitude=40.0,
        longitude=-73.95,
        altitude=-20000.0,  # NO_VALUE sentinel leaking through unscaled
        heart_rate=-46,
        cadence=-46,
    )
    summary = {"trackid": str(START_TRACKID), "type": 1, "dis": 0, "calorie": 0, "avg_heart_rate": 0}

    data = build_fit(summary, [point])  # must not raise

    record = next(
        r.message for r in FitFile.from_bytes(data).records if type(r.message).__name__ == "RecordMessage"
    )
    assert record.altitude is None
    assert record.heart_rate is None
    assert record.cadence is None
