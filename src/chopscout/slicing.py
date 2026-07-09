from __future__ import annotations

import bisect
from collections.abc import Iterable

MIN_SLICE_SECONDS = 0.025


def normalize_markers(markers: Iterable[float], duration: float, minimum: float = MIN_SLICE_SECONDS) -> list[float]:
    values = sorted(max(0.0, min(duration, float(value))) for value in markers)
    result: list[float] = []
    for value in values:
        if not result or value - result[-1] >= minimum:
            result.append(value)
    if not result or result[0] > 1e-6:
        result.insert(0, 0.0)
    return [value for value in result if value < duration - 1e-6]


def equal_markers(duration: float, count: int, start: float = 0.0, end: float | None = None) -> list[float]:
    end = duration if end is None else end
    length = max(0.0, end - start)
    return [start + (length * index / count) for index in range(count)]


def grid_markers(duration: float, bpm: float, division: int, downbeat: float) -> list[float]:
    quarter = 60.0 / bpm
    step = quarter * 4 / division
    values = []
    value = downbeat
    while value < duration:
        if value >= 0:
            values.append(value)
        value += step
    return normalize_markers(values, duration)


def transient_markers(onsets: list[float], duration: float, downbeat: float = 0.0, downbeat_first: bool = False) -> list[float]:
    values = list(onsets)
    if downbeat_first:
        values = [downbeat] + [x for x in values if x > downbeat + MIN_SLICE_SECONDS]
    return normalize_markers(values, duration)


def hybrid_markers(onsets: list[float], duration: float, bpm: float, downbeat: float, tolerance: float = 0.06) -> list[float]:
    grid = grid_markers(duration, bpm, 16, downbeat)
    output: list[float] = []
    for point in grid:
        nearest = min(onsets, key=lambda x: abs(x - point), default=point)
        output.append(nearest if abs(nearest - point) <= tolerance else point)
    return normalize_markers(output, duration)


def generate_markers(mode: str, duration: float, bpm: float, downbeat: float, onsets: list[float]) -> list[float]:
    key = mode.lower().replace("-", "")
    if key in {"transient", "transients"}:
        return transient_markers(onsets, duration)
    if key in {"downbeattransient", "downbeatfirst"}:
        return transient_markers(onsets, duration, downbeat, True)
    if key in {"equal8", "8"}:
        return equal_markers(duration, 8)
    if key in {"equal16", "16"}:
        return equal_markers(duration, 16)
    if key in {"equal32", "32"}:
        return equal_markers(duration, 32)
    if key in {"equal48", "48"}:
        return equal_markers(duration, 48)
    if key in {"equal64", "64"}:
        return equal_markers(duration, 64)
    if key in {"beat", "quarter", "quarters"}:
        return grid_markers(duration, bpm, 4, downbeat)
    if key in {"eighth", "eighths"}:
        return grid_markers(duration, bpm, 8, downbeat)
    if key in {"sixteenth", "sixteenths"}:
        return grid_markers(duration, bpm, 16, downbeat)
    if key == "hybrid":
        return hybrid_markers(onsets, duration, bpm, downbeat)
    if key == "manual":
        return [max(0.0, downbeat)]
    raise ValueError(f"Unknown chop mode: {mode}")


def snap_marker(value: float, candidates: list[float], tolerance: float = 0.08) -> float:
    if not candidates:
        return value
    index = bisect.bisect_left(candidates, value)
    nearby = candidates[max(0, index - 1): min(len(candidates), index + 2)]
    nearest = min(nearby, key=lambda x: abs(x - value))
    return nearest if abs(nearest - value) <= tolerance else value


def slice_ranges(markers: list[float], duration: float) -> list[tuple[float, float]]:
    points = normalize_markers(markers, duration)
    ends = points[1:] + [duration]
    return [(start, end) for start, end in zip(points, ends, strict=True) if end - start >= MIN_SLICE_SECONDS]
