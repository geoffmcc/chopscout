from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .analysis import analyze
from .audio import decode_audio
from .exporter import export_package
from .models import AnalysisResult, ExportSettings
from .slicing import generate_markers


@dataclass(slots=True)
class LoadedProject:
    path: Path
    data: np.ndarray
    sample_rate: int
    analysis: AnalysisResult
    markers: list[float]
    mode: str


def load_project(path: str | Path, mode: str = "transient", sensitivity: float = 0.55) -> LoadedProject:
    data, rate, info = decode_audio(path)
    result = analyze(data, rate, info, sensitivity)
    markers = generate_markers(mode, info.duration, result.selected_bpm, result.downbeat, result.onset_times)
    return LoadedProject(Path(path), data, rate, result, markers, mode)


def change_mode(project: LoadedProject, mode: str) -> None:
    project.mode = mode
    project.markers = generate_markers(mode, project.analysis.audio.duration,
                                       project.analysis.selected_bpm, project.analysis.downbeat,
                                       project.analysis.onset_times)


def export_project(project: LoadedProject, output: str | Path, settings: ExportSettings) -> Path:
    return export_package(project.path, project.data, project.sample_rate, project.analysis,
                          project.markers, output, settings)
