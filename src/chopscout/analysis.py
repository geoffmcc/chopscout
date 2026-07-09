from __future__ import annotations

import numpy as np
from scipy import signal

from .audio import mono_mix
from .models import AnalysisResult, AudioInfo
from .validation import replace_loop_duration_warning, validate_loop_duration


def _frame_rms(samples: np.ndarray, frame: int, hop: int) -> np.ndarray:
    if len(samples) < frame:
        return np.array([float(np.sqrt(np.mean(samples * samples)))], dtype=np.float32)
    count = 1 + (len(samples) - frame) // hop
    shape = (count, frame)
    strides = (samples.strides[0] * hop, samples.strides[0])
    windows = np.lib.stride_tricks.as_strided(samples, shape=shape, strides=strides)
    return np.sqrt(np.mean(windows * windows, axis=1) + 1e-12)


def onset_envelope(data: np.ndarray, sample_rate: int, hop: int = 256) -> tuple[np.ndarray, np.ndarray]:
    mono = mono_mix(data)
    frame = 1024
    rms = _frame_rms(mono, frame, hop)
    novelty = np.maximum(0.0, np.diff(rms, prepend=rms[0]))
    if len(novelty) >= 5:
        window = min(((len(novelty) - 1) // 2) * 2 + 1, 9)
        novelty = signal.savgol_filter(novelty, window, 2)
    novelty = np.maximum(novelty, 0.0)
    if novelty.max() > 0:
        novelty /= novelty.max()
    times = np.arange(len(novelty)) * hop / sample_rate
    return times.astype(float), novelty.astype(float)


def detect_transients(data: np.ndarray, sample_rate: int, sensitivity: float = 0.55) -> tuple[list[float], list[float]]:
    times, envelope = onset_envelope(data, sample_rate)
    if len(envelope) < 3:
        return [0.0], [1.0]
    threshold = float(np.quantile(envelope, max(0.35, min(0.9, sensitivity))))
    distance = max(1, int((0.045 * sample_rate) / 256))
    peaks, properties = signal.find_peaks(envelope, height=max(threshold, 0.05), distance=distance, prominence=0.025)
    values = properties.get("peak_heights", envelope[peaks])
    return [float(times[i]) for i in peaks], [float(v) for v in values]


def estimate_tempo(data: np.ndarray, sample_rate: int) -> tuple[float, float]:
    _, env = onset_envelope(data, sample_rate)
    if len(env) < 16 or np.max(env) <= 0:
        return 120.0, 0.0
    hop = 256
    centered = env - np.mean(env)
    autocorr = signal.fftconvolve(centered, centered[::-1], mode="full")[len(centered)-1:]
    min_bpm, max_bpm = 55.0, 210.0
    min_lag = max(1, int(60 * sample_rate / (max_bpm * hop)))
    max_lag = min(len(autocorr) - 1, int(60 * sample_rate / (min_bpm * hop)))
    if max_lag <= min_lag:
        return 120.0, 0.0
    region = autocorr[min_lag:max_lag + 1]
    lag = min_lag + int(np.argmax(region))
    bpm = 60.0 * sample_rate / (hop * lag)
    confidence = float(max(0.0, min(1.0, region.max() / (autocorr[0] + 1e-9))))
    while bpm < 80:
        bpm *= 2
    while bpm > 190:
        bpm /= 2
    return round(float(bpm), 2), confidence


def beat_grid(duration: float, bpm: float, downbeat: float = 0.0) -> list[float]:
    interval = 60.0 / max(bpm, 1e-6)
    start = downbeat
    while start - interval >= 0:
        start -= interval
    beats: list[float] = []
    value = start
    while value <= duration + 1e-6:
        if value >= 0:
            beats.append(round(value, 9))
        value += interval
    return beats


def silence_bounds(data: np.ndarray, sample_rate: int, threshold_db: float = -48.0) -> tuple[float, float]:
    mono = np.abs(mono_mix(data))
    threshold = 10 ** (threshold_db / 20.0)
    active = np.flatnonzero(mono >= threshold)
    if not len(active):
        return 0.0, len(mono) / sample_rate
    return float(active[0] / sample_rate), float((active[-1] + 1) / sample_rate)


def analyze(data: np.ndarray, sample_rate: int, info: AudioInfo, sensitivity: float = 0.55) -> AnalysisResult:
    bpm, tempo_conf = estimate_tempo(data, sample_rate)
    onsets, strengths = detect_transients(data, sample_rate, sensitivity)
    trim_start, trim_end = silence_bounds(data, sample_rate)
    downbeat = onsets[0] if onsets and onsets[0] < min(1.0, info.duration / 4) else trim_start
    interval = 60 / bpm
    beats = beat_grid(info.duration, bpm, downbeat)
    bars_float = max(1.0, info.duration / (interval * 4))
    bars = max(1, int(round(bars_float)))
    warnings: list[str] = []
    if tempo_conf < 0.15:
        warnings.append("Tempo confidence is low; verify BPM manually.")
    if trim_start > 0.02:
        warnings.append("The loop begins with silence or a lead-in; verify the first downbeat.")
    if info.clipped:
        warnings.append("The source reaches digital full scale and may be clipped.")
    if abs(info.dc_offset) > 0.01:
        warnings.append("The source has measurable DC offset.")
    duration_check = validate_loop_duration(
        total_samples=info.frames,
        sample_rate=sample_rate,
        bpm=bpm,
        bars=bars,
    )
    warnings = replace_loop_duration_warning(warnings, duration_check)
    return AnalysisResult(
        audio=info, detected_bpm=bpm, selected_bpm=bpm, tempo_confidence=tempo_conf,
        beat_times=beats, onset_times=onsets, onset_strengths=strengths,
        downbeat=downbeat, downbeat_confidence=min(1.0, (strengths[0] if strengths else 0.0) + 0.2),
        estimated_bars=bars, trim_start=trim_start, trim_end=trim_end, warnings=warnings,
    )
