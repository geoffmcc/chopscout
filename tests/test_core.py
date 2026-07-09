from pathlib import Path

import numpy as np

from chopscout import core
from chopscout.models import AnalysisResult, AudioInfo, ExportSettings


def test_export_project_refreshes_loop_duration_warning_for_effective_settings(monkeypatch, tmp_path: Path):
    sample_rate = 48000
    data = np.zeros((sample_rate * 4, 1), dtype=np.float32)
    analysis = AnalysisResult(
        audio=AudioInfo(str(tmp_path / "loop.wav"), sample_rate, 1, len(data), 4.0),
        detected_bpm=120.0,
        selected_bpm=120.0,
        tempo_confidence=1.0,
        beat_times=[],
        onset_times=[0.0],
        onset_strengths=[1.0],
        downbeat=0.0,
        downbeat_confidence=1.0,
        estimated_bars=2,
        trim_start=0.0,
        trim_end=4.0,
        warnings=[],
    )
    project = core.LoadedProject(tmp_path / "loop.wav", data, sample_rate, analysis, [0.0], "manual")
    monkeypatch.setattr(core, "export_package", lambda *args, **kwargs: tmp_path / "out")

    core.export_project(project, tmp_path, ExportSettings(bpm=120.0, bars=3))
    assert any(warning.startswith("Loop length does not closely match") for warning in analysis.warnings)

    core.export_project(project, tmp_path, ExportSettings(bpm=120.0, bars=2))
    assert not any(warning.startswith("Loop length does not closely match") for warning in analysis.warnings)
