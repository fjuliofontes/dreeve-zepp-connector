"""
Decoder for Zepp's encoded per-sample workout track fields.

Ported from rolandsz/Mi-Fit-and-Zepp-workout-exporter's `base_exporter.py`
(MIT), itself based on https://github.com/mireq/MiFitDataExport. Adapted to
read from the raw `workout_detail()` dict instead of a pydantic model, and
simplified by dropping the device-specific "BIP gap fixing" branch (an
always-disabled quirk workaround in the source project not needed here).

Field format, as reverse-engineered by the above projects:
- Each field (`time`, `longitude_latitude`, `altitude`, `heart_rate`, `gait`)
  is a `;`-delimited string of samples; `longitude_latitude`/`heart_rate`/
  `gait` samples are further `,`-delimited sub-fields.
- `time`, both halves of `longitude_latitude`, and `heart_rate`'s value
  column are delta-encoded (each sample is relative to the previous one) and
  must be cumulatively summed.
- `altitude` and `gait`'s stride/cadence columns are absolute values, but
  sampled on their own irregular timestamps and need interpolating onto a
  unified timeline (the union of the GPS/HR/step timestamps).
- Latitude/longitude are scaled by 1e8; altitude is in centimeters.
"""

from __future__ import annotations

import array
from bisect import bisect_left
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import accumulate
from typing import Optional

NO_VALUE = -2000000

RawTrackData = namedtuple(
    "RawTrackData",
    ["times", "lat", "lon", "alt", "hrtimes", "hr", "steptimes", "stride", "cadence"],
)
Position = namedtuple("Position", ["lat", "lon", "alt"])
TrackPoint = namedtuple("TrackPoint", ["time", "position", "hr", "stride", "cadence"])


@dataclass
class ExportablePoint:
    time: datetime
    latitude: float
    longitude: float
    altitude: Optional[float]
    heart_rate: Optional[float]
    cadence: Optional[float]


class Interpolate:
    def __init__(self, x_list, y_list):
        intervals = zip(x_list, x_list[1:], y_list, y_list[1:])
        self.x_list = x_list
        self.y_list = y_list
        self.slopes = [(y2 - y1) // ((x2 - x1) or 1) for x1, x2, y1, y2 in intervals]

    def __getitem__(self, x):
        i = bisect_left(self.x_list, x) - 1
        if i >= len(self.slopes):
            return self.y_list[-1]
        if i < 0:
            return self.y_list[0]
        return self.y_list[i] + self.slopes[i] * (x - self.x_list[i])


def _samples(raw: str | None) -> list[str]:
    return list(filter(None, raw.split(";"))) if raw else []


def parse_track_data(detail: dict) -> RawTrackData:
    return RawTrackData(
        times=array.array("q", [int(v) for v in _samples(detail.get("time"))]),
        lat=array.array(
            "q", [int(v.split(",")[0]) for v in _samples(detail.get("longitude_latitude"))]
        ),
        lon=array.array(
            "q", [int(v.split(",")[1]) for v in _samples(detail.get("longitude_latitude"))]
        ),
        alt=array.array("q", [int(v) for v in _samples(detail.get("altitude"))]),
        hrtimes=array.array(
            "q", [int(v.split(",")[0] or 1) for v in _samples(detail.get("heart_rate"))]
        ),
        hr=array.array(
            "q", [int(v.split(",")[1]) for v in _samples(detail.get("heart_rate"))]
        ),
        steptimes=array.array(
            "q", [int(v.split(",")[0]) for v in _samples(detail.get("gait"))]
        ),
        stride=array.array(
            "q", [int(v.split(",")[2]) for v in _samples(detail.get("gait"))]
        ),
        cadence=array.array(
            "q", [int(v.split(",")[3]) for v in _samples(detail.get("gait"))]
        ),
    )


def interpolate_column(data, original_points, new_points):
    data = array.array("q", data)
    old_value = NO_VALUE
    for old_value in data:
        if old_value != NO_VALUE:
            break
    for i, value in enumerate(data):
        if value == NO_VALUE:
            data[i] = old_value
        else:
            old_value = value

    if len(new_points) == 0:
        return array.array("q", [])
    if len(original_points) == 0:
        return array.array("q", [0] * len(new_points))
    if len(original_points) == 1:
        return array.array("q", [original_points[0]] * len(new_points))
    interpolate = Interpolate(original_points, data)
    return array.array("q", (interpolate[point] for point in new_points))


def track_points(track_data: RawTrackData):
    for time, lat, lon, alt, hr, stride, cadence in zip(
        track_data.times,
        track_data.lat,
        track_data.lon,
        track_data.alt,
        track_data.hr,
        track_data.stride,
        track_data.cadence,
    ):
        # NO_VALUE survives interpolation only when a channel has zero valid
        # samples for the whole workout (e.g. no barometer data) - the
        # forward-fill in interpolate_column can't fix what was never there.
        altitude = None if alt == NO_VALUE else alt / 100
        yield TrackPoint(
            time=time,
            position=Position(lat=lat / 100000000, lon=lon / 100000000, alt=altitude),
            hr=hr,
            stride=stride,
            cadence=cadence,
        )


def interpolate_data(track_data: RawTrackData) -> RawTrackData:
    track_times = array.array("q", accumulate(track_data.times))
    hr_times = array.array("q", accumulate(track_data.hrtimes))
    step_times = array.array("q", accumulate(track_data.steptimes))

    times = list(sorted(set(track_times).union(hr_times).union(step_times)))

    return track_data._replace(
        times=times,
        lat=interpolate_column(accumulate(track_data.lat), track_times, times),
        lon=interpolate_column(accumulate(track_data.lon), track_times, times),
        alt=interpolate_column(track_data.alt, track_times, times),
        hrtimes=times,
        hr=interpolate_column(accumulate(track_data.hr), hr_times, times),
        steptimes=times,
        stride=interpolate_column(track_data.stride, step_times, times),
        cadence=interpolate_column(track_data.cadence, step_times, times),
    )


def parse_points(start_time: int, detail: dict) -> list[ExportablePoint]:
    """Decode a `workout_detail()` response into a list of track points.

    `start_time` is the workout's start (unix seconds) — Zepp's `trackid`
    doubles as this timestamp. Returns [] if the workout has no GPS track
    (e.g. an indoor/strength session).
    """
    track_data = parse_track_data(detail)

    if not track_data.lat:
        return []

    return [
        ExportablePoint(
            time=datetime.fromtimestamp(point.time + start_time, tz=timezone.utc),
            latitude=point.position.lat,
            longitude=point.position.lon,
            altitude=point.position.alt,
            heart_rate=point.hr,
            cadence=point.cadence,
        )
        for point in track_points(interpolate_data(track_data))
    ]
