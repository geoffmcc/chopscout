from __future__ import annotations

from dataclasses import dataclass

LOOP_DURATION_WARNING_PREFIX = "Loop length does not closely match the selected BPM and bar count"


@dataclass(frozen=True, slots=True)
class LoopDurationValidation:
    expected_seconds: float
    actual_seconds: float
    difference_seconds: float
    tolerance_seconds: float
    bpm: float
    bars: int
    beats_per_bar: int

    @property
    def is_valid(self) -> bool:
        return abs(self.difference_seconds) <= self.tolerance_seconds


def expected_loop_duration_seconds(bpm: float, bars: int, beats_per_bar: int = 4) -> float:
    if bpm <= 0:
        raise ValueError("BPM must be greater than zero.")
    if bars < 1:
        raise ValueError("Bar count must be at least one.")
    if beats_per_bar < 1:
        raise ValueError("Beats per bar must be at least one.")
    return bars * beats_per_bar * 60.0 / bpm


def validate_loop_duration(
    *,
    total_samples: int,
    sample_rate: int,
    bpm: float,
    bars: int,
    beats_per_bar: int = 4,
    absolute_tolerance_seconds: float = 0.003,
    sample_tolerance: int = 4,
    relative_tolerance: float = 0.0002,
) -> LoopDurationValidation:
    """Validate loop duration with realistic audio-decoding tolerance.

    The tolerance is the maximum of a small absolute allowance, a few decoded
    samples, and a tiny relative allowance. This accepts sample rounding and
    metadata/decoder noise without masking musically meaningful timing errors.
    """
    if sample_rate <= 0:
        raise ValueError("Sample rate must be greater than zero.")
    expected = expected_loop_duration_seconds(bpm, bars, beats_per_bar)
    actual = total_samples / sample_rate
    tolerance = max(
        absolute_tolerance_seconds,
        sample_tolerance / sample_rate,
        expected * relative_tolerance,
    )
    return LoopDurationValidation(
        expected_seconds=expected,
        actual_seconds=actual,
        difference_seconds=actual - expected,
        tolerance_seconds=tolerance,
        bpm=bpm,
        bars=bars,
        beats_per_bar=beats_per_bar,
    )


def format_loop_duration_warning(result: LoopDurationValidation) -> str:
    diff_ms = result.difference_seconds * 1000.0
    return (
        "Loop length does not closely match the selected BPM and bar count "
        f"(expected {result.expected_seconds:.3f}s, actual {result.actual_seconds:.3f}s, "
        f"difference {diff_ms:+.1f} ms, BPM {result.bpm:.2f}, "
        f"bars {result.bars}, time signature {result.beats_per_bar}/4)."
    )


def replace_loop_duration_warning(warnings: list[str], result: LoopDurationValidation) -> list[str]:
    filtered = [warning for warning in warnings if not warning.startswith(LOOP_DURATION_WARNING_PREFIX)]
    if not result.is_valid:
        filtered.append(format_loop_duration_warning(result))
    return filtered
