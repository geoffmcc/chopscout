from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .slicing import slice_ranges


class PlaybackMode(StrEnum):
    ORIGINAL = "original"
    SLICE = "slice"
    RECONSTRUCT = "reconstruct"


@dataclass(frozen=True, slots=True)
class PlaybackSegment:
    source_slice: int
    source_start: float
    source_end: float
    playback_start: float
    playback_end: float


@dataclass(frozen=True, slots=True)
class PlaybackContext:
    mode: PlaybackMode
    duration: float
    markers: tuple[float, ...]
    segments: tuple[PlaybackSegment, ...] = ()
    slice_index: int | None = None
    generation: int = 0


@dataclass(frozen=True, slots=True)
class WaveformPlaybackPosition:
    position_seconds: float | None
    active_slice: int | None


def active_slice_for_position(markers: list[float] | tuple[float, ...], duration: float, position: float) -> int | None:
    if not markers or duration <= 0 or position < 0:
        return None
    clamped = min(position, duration)
    for index, start in enumerate(markers):
        end = markers[index + 1] if index + 1 < len(markers) else duration
        if start <= clamped < end or (index == len(markers) - 1 and clamped <= end):
            return index
    return None


def original_playback_context(markers: list[float], duration: float, generation: int = 0) -> PlaybackContext:
    return PlaybackContext(PlaybackMode.ORIGINAL, duration, tuple(markers), generation=generation)


def slice_playback_context(markers: list[float], duration: float, index: int, generation: int = 0) -> PlaybackContext:
    ranges = slice_ranges(markers, duration)
    if index < 0 or index >= len(ranges):
        return PlaybackContext(PlaybackMode.SLICE, duration, tuple(markers), slice_index=None, generation=generation)
    start, end = ranges[index]
    return PlaybackContext(
        PlaybackMode.SLICE,
        duration,
        tuple(markers),
        (PlaybackSegment(index, start, end, 0.0, end - start),),
        slice_index=index,
        generation=generation,
    )


def reconstruct_playback_context(markers: list[float], duration: float, generation: int = 0) -> PlaybackContext:
    segments: list[PlaybackSegment] = []
    playback_start = 0.0
    for index, (start, end) in enumerate(slice_ranges(markers, duration)):
        playback_end = playback_start + (end - start)
        segments.append(PlaybackSegment(index, start, end, playback_start, playback_end))
        playback_start = playback_end
    return PlaybackContext(PlaybackMode.RECONSTRUCT, duration, tuple(markers), tuple(segments), generation=generation)


def map_player_position_to_waveform(context: PlaybackContext | None, position_seconds: float) -> WaveformPlaybackPosition:
    if context is None or context.duration <= 0:
        return WaveformPlaybackPosition(None, None)
    if context.mode is PlaybackMode.ORIGINAL:
        position = max(0.0, min(context.duration, position_seconds))
        return WaveformPlaybackPosition(
            position,
            active_slice_for_position(context.markers, context.duration, position),
        )
    for index, segment in enumerate(context.segments):
        is_last = index == len(context.segments) - 1
        if position_seconds < segment.playback_start and index == 0:
            position_seconds = segment.playback_start
        if segment.playback_start <= position_seconds < segment.playback_end or (is_last and position_seconds <= segment.playback_end):
            local = max(0.0, min(position_seconds - segment.playback_start, segment.source_end - segment.source_start))
            return WaveformPlaybackPosition(segment.source_start + local, segment.source_slice)
    return WaveformPlaybackPosition(None, None)
