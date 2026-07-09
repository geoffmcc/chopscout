from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .models import AudioInfo


class AudioError(RuntimeError):
    pass


def find_ffmpeg() -> tuple[str, str]:
    candidates = []
    root = Path(__file__).resolve().parents[2]
    candidates.append(root / "tools" / "ffmpeg" / "bin")
    for directory in candidates:
        exe = directory / ("ffmpeg.exe" if __import__("os").name == "nt" else "ffmpeg")
        probe = directory / ("ffprobe.exe" if __import__("os").name == "nt" else "ffprobe")
        if exe.exists() and probe.exists():
            return str(exe), str(probe)
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise AudioError("FFmpeg and ffprobe were not found. Install FFmpeg or place it in tools/ffmpeg/bin.")
    return ffmpeg, ffprobe


def source_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_audio(path: str | Path) -> dict:
    _, ffprobe = find_ffmpeg()
    command = [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AudioError(result.stderr.strip() or "ffprobe could not inspect this file.")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AudioError("ffprobe returned invalid metadata.") from exc


def decode_audio(path: str | Path, target_rate: int | None = None) -> tuple[np.ndarray, int, AudioInfo]:
    source = Path(path)
    if not source.is_file():
        raise AudioError(f"Audio file does not exist: {source}")
    ffmpeg, _ = find_ffmpeg()
    with tempfile.TemporaryDirectory(prefix="chopscout-") as temporary:
        wav = Path(temporary) / "decoded.wav"
        command = [ffmpeg, "-v", "error", "-y", "-i", str(source)]
        if target_rate:
            command += ["-ar", str(target_rate)]
        command += ["-c:a", "pcm_f32le", str(wav)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise AudioError(result.stderr.strip() or "FFmpeg could not decode this file.")
        data, sample_rate = sf.read(wav, dtype="float32", always_2d=True)
    if data.size == 0 or len(data) < 16:
        raise AudioError("The decoded audio is empty or too short.")
    peak = float(np.max(np.abs(data)))
    peak_dbfs = 20.0 * math.log10(max(peak, 1e-9))
    dc = float(np.mean(data))
    info = sf.info(source) if source.suffix.lower() in {".wav", ".aif", ".aiff", ".flac"} else None
    audio_info = AudioInfo(
        path=str(source.resolve()), sample_rate=sample_rate, channels=data.shape[1], frames=len(data),
        duration=len(data) / sample_rate, subtype=info.subtype if info else "decoded via FFmpeg",
        source_hash=source_hash(source), peak_dbfs=peak_dbfs, dc_offset=dc, clipped=peak >= 0.9999,
    )
    return data, sample_rate, audio_info


def mono_mix(data: np.ndarray) -> np.ndarray:
    return np.mean(data, axis=1, dtype=np.float32)


def waveform_peaks(data: np.ndarray, points: int = 4000) -> np.ndarray:
    mono = mono_mix(data)
    if len(mono) <= points:
        return mono.copy()
    width = int(math.ceil(len(mono) / points))
    padded = np.pad(mono, (0, width * points - len(mono)))
    blocks = padded.reshape(points, width)
    mins = blocks.min(axis=1)
    maxs = blocks.max(axis=1)
    return np.column_stack([mins, maxs]).astype(np.float32)


def write_wav(path: str | Path, data: np.ndarray, sample_rate: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, data, sample_rate, subtype="PCM_24")


def apply_edge_fades(data: np.ndarray, sample_rate: int, milliseconds: float) -> np.ndarray:
    if milliseconds <= 0:
        return data.copy()
    frames = min(int(sample_rate * milliseconds / 1000.0), len(data) // 2)
    if frames <= 0:
        return data.copy()
    result = data.copy()
    ramp = np.linspace(0.0, 1.0, frames, dtype=np.float32)[:, None]
    result[:frames] *= ramp
    result[-frames:] *= ramp[::-1]
    return result
