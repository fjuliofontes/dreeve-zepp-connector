"""Build a .FIT activity file from a decoded Zepp workout."""

from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import (
    Activity,
    Event,
    EventType,
    FileType,
    Manufacturer,
    Sport,
    SubSport,
)

from .decoder import ExportablePoint

EARTH_RADIUS_M = 6371000.0

# Fallback for genuinely generic/miscellaneous workouts. NOT (Sport.GENERIC,
# SubSport.GENERIC) - that combo is rejected outright ("Unsupported FIT
# sport 0 (sub sport 0)") by at least some deployed Dreeve versions, whose
# FitSportType::resolveGeneric() apparently predates the "always fall back
# to WORKOUT" fix present on Dreeve's current GitHub master. Sport.
# FITNESS_EQUIPMENT has its own long-standing, non-generic match arm ending
# in `default => SportType::WORKOUT`, so it resolves reliably either way.
_WORKOUT_FALLBACK = (Sport.FITNESS_EQUIPMENT, SubSport.GENERIC)

# Zepp workout `type` codes -> FIT (Sport, SubSport). See zepp-mcp's README
# for the code table this is based on; extend as new codes turn up (a warning
# is printed for any unmapped type actually seen, to help spot gaps).
TYPE_MAP: dict[int, tuple[Sport, SubSport]] = {
    1: (Sport.RUNNING, SubSport.GENERIC),
    6: (Sport.WALKING, SubSport.GENERIC),
    8: (Sport.RUNNING, SubSport.TREADMILL),
    9: (Sport.CYCLING, SubSport.GENERIC),
    10: (Sport.CYCLING, SubSport.INDOOR_CYCLING),
    14: (Sport.SWIMMING, SubSport.LAP_SWIMMING),
    15: (Sport.SWIMMING, SubSport.OPEN_WATER),
    16: _WORKOUT_FALLBACK,  # "free training" in the app
    17: (Sport.TENNIS, SubSport.GENERIC),
    49: (Sport.TRAINING, SubSport.STRENGTH_TRAINING),
    88: (Sport.VOLLEYBALL, SubSport.GENERIC),
    89: (Sport.RACKET, SubSport.TABLE_TENNIS),
    140: (Sport.KAYAKING, SubSport.GENERIC),
    223: _WORKOUT_FALLBACK,  # "just movement" in the app
}
_warned_types: set[int] = set()


def _in_range(value, lo: float, hi: float):
    """The ported decoder interpolates gapped samples using integer
    floor-division slopes (see decoder.Interpolate) - over a wide gap
    between two real samples this can under/overshoot into physically
    impossible territory (e.g. negative cadence). FIT encoding then rejects
    the out-of-range value outright, so drop it here instead of crashing."""
    return value if value is not None and lo <= value <= hi else None


def _to_int(value) -> int | None:
    """Zepp's API mixes ints, floats, and numeric strings like "375.0" for
    the same fields across workouts - `int("375.0")` raises, so route
    through `float()` first."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _sport_for(zepp_type) -> tuple[Sport, SubSport]:
    code = _to_int(zepp_type)
    if code not in TYPE_MAP and code not in _warned_types:
        _warned_types.add(code)
        print(f"warning: unmapped Zepp workout type {code}, exporting as a generic workout", file=sys.stderr)
    return TYPE_MAP.get(code, _WORKOUT_FALLBACK)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _millis(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _synthetic_records(
    start_ms: int, end_ms: int, avg_heart_rate: int | None, total_distance: float, target_count: int = 60
) -> list[RecordMessage]:
    """Evenly-spaced placeholder records for a workout with no decoded GPS
    track (pool swims, strength training, ...).

    Dreeve's own FIT importer (FitFileParser.php) throws "No FIT 'record'
    messages found" and rejects the file outright if `record` is empty -
    unconditionally, before it even looks at sport/session data. It doesn't
    need GPS, just a non-empty record stream, matching how real Garmin/Wahoo
    pool-swim FIT files carry per-interval records without positions.
    """
    duration_ms = max(end_ms - start_ms, 0)
    step_count = 0 if duration_ms == 0 else max(1, min(target_count, duration_ms // 1000))

    records = []
    for i in range(step_count + 1):
        record = RecordMessage()
        record.timestamp = start_ms + round(i * duration_ms / step_count) if step_count else start_ms
        if avg_heart_rate:
            record.heart_rate = avg_heart_rate
        if total_distance:
            record.distance = total_distance * (i / step_count if step_count else 1.0)
        records.append(record)
    return records


def build_fit(summary: dict, points: list[ExportablePoint]) -> bytes:
    """Build a FIT activity file's bytes from a workout summary + decoded points.

    `summary` is a raw item from `ZeppDataClient.workouts()`; `points` is the
    (possibly empty, for indoor/strength workouts with no GPS track) output
    of `decoder.parse_points()`.
    """
    zepp_type = summary.get("type")
    sport, sub_sport = _sport_for(zepp_type)

    start_time = datetime.fromtimestamp(int(summary["trackid"]), tz=timezone.utc)
    if points:
        end_time = points[-1].time
    else:
        run_time_s = float(summary.get("run_time") or 0)
        end_time = datetime.fromtimestamp(start_time.timestamp() + run_time_s, tz=timezone.utc)

    start_ms, end_ms = _millis(start_time), _millis(end_time)
    total_elapsed_s = max((end_ms - start_ms) / 1000, 0.0)
    total_calories = _to_int(summary.get("calorie"))
    avg_heart_rate = _to_int(summary.get("avg_heart_rate"))

    builder = FitFileBuilder(auto_define=True, min_string_size=50)

    file_id = FileIdMessage()
    file_id.type = FileType.ACTIVITY
    file_id.manufacturer = Manufacturer.ZEPP.value
    file_id.product = 0
    file_id.time_created = start_ms
    builder.add(file_id)

    start_event = EventMessage()
    start_event.event = Event.TIMER
    start_event.event_type = EventType.START
    start_event.timestamp = start_ms
    builder.add(start_event)

    if points:
        distance_m = 0.0
        prev_point: ExportablePoint | None = None
        records = []
        for point in points:
            if prev_point is not None:
                distance_m += _haversine_m(
                    prev_point.latitude, prev_point.longitude, point.latitude, point.longitude
                )
            record = RecordMessage()
            record.timestamp = _millis(point.time)
            record.position_lat = point.latitude
            record.position_long = point.longitude
            record.distance = distance_m
            altitude = _in_range(point.altitude, -500, 12000)
            if altitude is not None:
                record.altitude = altitude
            heart_rate = _in_range(point.heart_rate, 1, 255)
            if heart_rate is not None:
                record.heart_rate = int(heart_rate)
            cadence = _in_range(point.cadence, 1, 255)
            if cadence is not None:
                record.cadence = int(cadence)
            records.append(record)
            prev_point = point
        total_distance = distance_m
    else:
        total_distance = float(summary.get("dis") or 0)
        records = _synthetic_records(start_ms, end_ms, avg_heart_rate, total_distance)
    builder.add_all(records)

    stop_event = EventMessage()
    stop_event.event = Event.TIMER
    stop_event.event_type = EventType.STOP
    stop_event.timestamp = end_ms
    builder.add(stop_event)

    lap = LapMessage()
    lap.timestamp = end_ms
    lap.start_time = start_ms
    lap.total_elapsed_time = total_elapsed_s
    lap.total_timer_time = total_elapsed_s
    lap.total_distance = total_distance
    if total_calories is not None:
        lap.total_calories = total_calories
    if avg_heart_rate:
        lap.avg_heart_rate = avg_heart_rate
    lap.sport = sport
    lap.sub_sport = sub_sport
    builder.add(lap)

    session = SessionMessage()
    session.timestamp = end_ms
    session.start_time = start_ms
    session.total_elapsed_time = total_elapsed_s
    session.total_timer_time = total_elapsed_s
    session.total_distance = total_distance
    if total_calories is not None:
        session.total_calories = total_calories
    if avg_heart_rate:
        session.avg_heart_rate = avg_heart_rate
    session.sport = sport
    session.sub_sport = sub_sport
    session.first_lap_index = 0
    session.num_laps = 1
    builder.add(session)

    activity = ActivityMessage()
    activity.timestamp = end_ms
    activity.total_timer_time = total_elapsed_s
    activity.num_sessions = 1
    activity.type = Activity.MANUAL
    builder.add(activity)

    return builder.build().to_bytes()


def write_fit(summary: dict, points: list[ExportablePoint], output_path: Path) -> None:
    """Write the FIT file atomically: build to a .tmp file, then rename."""
    data = build_fit(summary, points)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp_path.write_bytes(data)
    tmp_path.rename(output_path)
