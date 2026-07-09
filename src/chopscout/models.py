from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AudioInfo:
    path: str
    sample_rate: int
    channels: int
    frames: int
    duration: float
    subtype: str = ""
    source_hash: str = ""
    peak_dbfs: float = -120.0
    dc_offset: float = 0.0
    clipped: bool = False


@dataclass(slots=True)
class TempoHypothesis:
    bpm: float
    confidence: float
    label: str = "main"


@dataclass(slots=True)
class SliceMarker:
    seconds: float
    name: str = ""
    strength: float = 0.0


@dataclass(slots=True)
class AnalysisResult:
    audio: AudioInfo
    detected_bpm: float
    selected_bpm: float
    tempo_confidence: float
    beat_times: list[float]
    onset_times: list[float]
    onset_strengths: list[float]
    downbeat: float
    downbeat_confidence: float
    estimated_bars: int
    trim_start: float
    trim_end: float
    warnings: list[str] = field(default_factory=list)

    @property
    def half_time_bpm(self) -> float:
        return self.selected_bpm / 2.0

    @property
    def double_time_bpm(self) -> float:
        return self.selected_bpm * 2.0


@dataclass(slots=True)
class ExportSettings:
    mode: str = "transient"
    starting_note: int = 36
    bars: int = 4
    bpm: float = 120.0
    trim_silence: bool = False
    short_fades_ms: float = 2.0
    overwrite: bool = False
    create_mpc_project: bool = True
    pad_count: int = 16


@dataclass(slots=True)
class Session:
    version: str
    source_path: str
    source_hash: str
    detected_bpm: float
    selected_bpm: float
    bar_count: int
    downbeat: float
    markers: list[float]
    chop_mode: str
    pad_map: dict[str, int]
    export_settings: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Session":
        return cls(**value)


def deterministic_project_name(path: str | Path, bpm: float) -> str:
    stem = Path(path).stem
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem).strip("_")
    return f"{safe or 'break'}_{round(bpm)}"
