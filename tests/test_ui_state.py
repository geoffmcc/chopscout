import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from chopscout.analysis import beat_grid
from chopscout.core import LoadedProject
from chopscout.models import AnalysisResult, AudioInfo
from chopscout.playback import PlaybackMode, original_playback_context
from chopscout.slicing import generate_markers
from chopscout.ui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def make_project(path: Path, mode: str, duration: float = 4.0) -> LoadedProject:
    sample_rate = 1000
    data = np.zeros((round(duration * sample_rate), 1), dtype=np.float32)
    info = AudioInfo(str(path), sample_rate, 1, len(data), len(data) / sample_rate)
    onsets = [0.0, 0.21, 0.83, 1.49, 2.25, 3.12]
    analysis = AnalysisResult(
        audio=info,
        detected_bpm=120.0,
        selected_bpm=120.0,
        tempo_confidence=0.75,
        beat_times=beat_grid(info.duration, 120.0, 0.0),
        onset_times=onsets,
        onset_strengths=[1.0] * len(onsets),
        downbeat=0.0,
        downbeat_confidence=1.0,
        estimated_bars=2,
        trim_start=0.0,
        trim_end=info.duration,
        warnings=[],
    )
    markers = generate_markers(mode, info.duration, analysis.selected_bpm, analysis.downbeat, analysis.onset_times)
    return LoadedProject(path, data, sample_rate, analysis, markers, mode)


def test_loaded_project_mode_and_waveform_markers_stay_synchronized(app, tmp_path: Path):
    window = MainWindow()
    window.mode.setCurrentText("equal16")
    project = make_project(tmp_path / "one.wav", "equal16")

    window.loaded(project)

    assert window.mode.currentText() == "equal16"
    assert window.project.mode == "equal16"
    assert len(window.project.markers) == 16
    assert window.wave.markers == window.project.markers
    assert window.project.markers != project.analysis.onset_times

    window.set_chop_mode("transient")
    assert window.mode.currentText() == "transient"
    assert window.project.mode == "transient"
    assert window.wave.markers == window.project.markers
    assert window.project.markers == generate_markers("transient", 4.0, 120.0, 0.0, project.analysis.onset_times)

    window.set_chop_mode("equal16")
    assert window.mode.currentText() == "equal16"
    assert window.project.mode == "equal16"
    assert len(window.project.markers) == 16
    assert window.wave.markers == window.project.markers

    second = make_project(tmp_path / "two.wav", "equal8", duration=2.0)
    window.loaded(second)
    assert window.mode.currentText() == "equal8"
    assert window.project.mode == "equal8"
    assert len(window.project.markers) == 8
    assert window.wave.markers == window.project.markers
    assert max(window.wave.markers) < second.analysis.audio.duration

    window.close()


def test_player_position_updates_waveform_and_stop_resets_visuals(app, tmp_path: Path):
    window = MainWindow()
    window.loaded(make_project(tmp_path / "one.wav", "equal8"))
    window._playback_generation += 1
    window._playback_context = original_playback_context(
        window.project.markers,
        window.project.analysis.audio.duration,
        window._playback_generation,
    )

    window.player_position_changed(1250)
    assert window.wave.playhead == 1.25
    assert window.wave.active_slice == 2

    window.stop_playback()
    assert window.wave.playhead is None
    assert window.wave.active_slice is None

    window.close()


def test_bpm_and_bar_changes_refresh_loop_duration_warning(app, tmp_path: Path):
    window = MainWindow()
    window.loaded(make_project(tmp_path / "one.wav", "equal8"))

    assert not any(warning.startswith("Loop length does not closely match") for warning in window.project.analysis.warnings)
    window.bars.setValue(3)
    assert any(warning.startswith("Loop length does not closely match") for warning in window.project.analysis.warnings)
    window.bars.setValue(2)
    assert not any(warning.startswith("Loop length does not closely match") for warning in window.project.analysis.warnings)

    window.close()


def test_transport_handlers_create_matching_playback_contexts(app, tmp_path: Path, monkeypatch):
    class FakePlayer:
        def __init__(self):
            self.sources = []
            self.play_count = 0
            self.stop_count = 0

        def setSource(self, source):
            self.sources.append(source)

        def play(self):
            self.play_count += 1

        def stop(self):
            self.stop_count += 1

    window = MainWindow()
    window.loaded(make_project(tmp_path / "one.wav", "equal8"))
    fake = FakePlayer()
    window.player = fake
    monkeypatch.setattr("chopscout.ui.write_wav", lambda path, data, sample_rate: None)

    window.play_original()
    assert window._playback_context.mode is PlaybackMode.ORIGINAL
    assert window._playback_context.generation == window._playback_generation

    window.wave.selected = 2
    window.play_slice()
    assert window._playback_context.mode is PlaybackMode.SLICE
    assert window._playback_context.slice_index == 2

    window.play_reconstruction()
    assert window._playback_context.mode is PlaybackMode.RECONSTRUCT
    assert len(window._playback_context.segments) == len(window.project.markers)
    assert fake.play_count == 3

    window.close()
