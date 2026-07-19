import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox
from test_ui_state import close_window, make_project

from chopscout.config import MAX_RECENT_FILES, AppConfig
from chopscout.models import ExportFormat, Session
from chopscout.session import SourceStatus, load_session, save_session
from chopscout.ui import SESSION_SUFFIX, MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    """A MainWindow whose config is redirected away from the real user config dir."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(AppConfig, "path", staticmethod(lambda: config_path))
    win = MainWindow()
    yield win
    close_window(win)


def loaded_window(window, tmp_path, mode="equal16"):
    window.loaded(make_project(tmp_path / "break.wav", mode))
    return window


def test_session_from_state_captures_project_and_widget_state(window, tmp_path):
    loaded_window(window, tmp_path)
    window.bpm.setValue(174.0)
    window.bars.setValue(8)
    window.export_format.setCurrentText(ExportFormat.PORTABLE.value)
    window.start_note.setValue(48)
    window.overwrite.setChecked(True)

    session = window._session_from_state()

    assert session.source_path == str(tmp_path / "break.wav")
    assert session.selected_bpm == 174.0
    assert session.bar_count == 8
    assert session.chop_mode == "equal16"
    assert session.markers == window.project.markers
    assert session.export_settings["export_format"] == ExportFormat.PORTABLE.value
    assert session.export_settings["starting_note"] == 48
    assert session.export_settings["overwrite"] is True


def test_saved_session_round_trips_through_the_session_core(window, tmp_path):
    loaded_window(window, tmp_path)
    window.bpm.setValue(93.5)
    window.bars.setValue(4)
    target = tmp_path / f"take{SESSION_SUFFIX}"

    assert window._write_session(target) is True

    restored, status = load_session(target)
    assert status is SourceStatus.MISSING  # the fixture audio was never written to disk
    assert restored.selected_bpm == 93.5
    assert restored.bar_count == 4
    assert restored.chop_mode == "equal16"
    assert restored.markers == window.project.markers


def test_apply_session_overlays_saved_values_onto_the_loaded_project(window, tmp_path):
    loaded_window(window, tmp_path, mode="equal8")
    session = Session(
        source_path=str(tmp_path / "break.wav"),
        source_hash="",
        detected_bpm=120.0,
        selected_bpm=88.0,
        bar_count=6,
        downbeat=0.25,
        markers=[0.0, 1.0, 2.5],
        chop_mode="manual",
        pad_map={"A01": 36},
        export_settings={
            "export_format": ExportFormat.PORTABLE.value,
            "starting_note": 60,
            "overwrite": True,
        },
    )

    window._apply_session(session)

    assert window.project.mode == "manual"
    assert window.project.markers == [0.0, 1.0, 2.5]
    assert window.wave.markers == [0.0, 1.0, 2.5]
    assert window.bpm.value() == 88.0
    assert window.bars.value() == 6
    assert window.downbeat.value() == 0.25
    assert window.mode.currentText() == "manual"
    assert window.export_format.currentText() == ExportFormat.PORTABLE.value
    assert window.start_note.value() == 60
    assert window.overwrite.isChecked() is True
    assert window.pad_map == {"A01": 36}


def test_manual_markers_survive_a_round_trip_that_reanalysis_cannot_reproduce(window, tmp_path):
    """generate_markers("manual", ...) returns only a placeholder, so the session
    values must win over whatever reanalysis produced."""
    loaded_window(window, tmp_path)
    window._adopt_manual_markers([0.0, 0.5, 1.75, 3.0])
    target = tmp_path / f"manual{SESSION_SUFFIX}"
    window._write_session(target)

    restored, _ = load_session(target)
    window._apply_session(restored)

    assert window.project.mode == "manual"
    assert window.project.markers == [0.0, 0.5, 1.75, 3.0]


def test_dirty_state_tracks_edits_and_clears_on_save(window, tmp_path):
    assert window.is_dirty() is False  # nothing loaded

    loaded_window(window, tmp_path)
    assert window.is_dirty() is False  # freshly analyzed audio is the baseline

    window.bpm.setValue(150.0)
    assert window.is_dirty() is True

    assert window._write_session(tmp_path / f"take{SESSION_SUFFIX}") is True
    assert window.is_dirty() is False

    window.bars.setValue(9)
    assert window.is_dirty() is True


def test_marker_edits_mark_the_session_dirty(window, tmp_path):
    loaded_window(window, tmp_path)
    assert window.is_dirty() is False

    window._adopt_manual_markers([0.0, 1.2])

    assert window.is_dirty() is True


def test_window_title_shows_the_session_name_and_unsaved_marker(window, tmp_path):
    loaded_window(window, tmp_path)
    assert window.windowTitle() == "ChopScout — Untitled"

    window._write_session(tmp_path / f"take{SESSION_SUFFIX}")
    assert window.windowTitle() == f"ChopScout — take{SESSION_SUFFIX}"

    window.bpm.setValue(101.0)
    assert window.windowTitle() == f"ChopScout — take{SESSION_SUFFIX}*"


def test_saving_records_a_recent_session_and_the_last_session_directory(window, tmp_path):
    loaded_window(window, tmp_path)
    target = tmp_path / f"take{SESSION_SUFFIX}"

    window._write_session(target)

    assert window.config.recent_files[0] == str(target)
    assert window.config.last_session_dir == str(tmp_path)
    assert AppConfig.load().recent_files[0] == str(target)


def test_new_session_clears_project_state(window, tmp_path):
    loaded_window(window, tmp_path)
    window._write_session(tmp_path / f"take{SESSION_SUFFIX}")

    window.session_new()

    assert window.project is None
    assert window.current_session_path is None
    assert window.pad_map == {}
    assert window.wave.markers == []
    assert window.is_dirty() is False
    assert not window.export_action.isEnabled()


def test_new_session_is_abandoned_when_the_discard_prompt_is_cancelled(
    window, tmp_path, monkeypatch
):
    loaded_window(window, tmp_path)
    window.bpm.setValue(140.0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Cancel)

    window.session_new()

    assert window.project is not None
    assert window.bpm.value() == 140.0


def test_close_is_refused_while_unsaved_changes_are_kept(window, tmp_path, monkeypatch):
    loaded_window(window, tmp_path)
    window.bpm.setValue(140.0)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Cancel)

    class Event:
        def __init__(self):
            self.accepted = None

        def accept(self):
            self.accepted = True

        def ignore(self):
            self.accepted = False

    event = Event()
    window.closeEvent(event)
    assert event.accepted is False

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Discard)
    event = Event()
    window.closeEvent(event)
    assert event.accepted is True


def test_open_session_reports_a_malformed_file_instead_of_raising(window, tmp_path, monkeypatch):
    broken = tmp_path / f"broken{SESSION_SUFFIX}"
    broken.write_text("{not json", encoding="utf-8")
    seen = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _parent, _title, text: seen.append(text))

    window._open_session_path(broken, confirmed=True)

    assert seen and "unreadable" in seen[0]
    assert window.current_session_path is None


def hostile_session(tmp_path, **overrides) -> Session:
    values = dict(
        source_path=str(tmp_path / "break.wav"),
        source_hash="",
        detected_bpm=120.0,
        selected_bpm=120.0,
        bar_count=4,
        downbeat=0.0,
        markers=[0.0, 1.0],
        chop_mode="equal16",
        pad_map={},
        export_settings={},
    )
    values.update(overrides)
    return Session(**values)


def test_apply_session_survives_an_empty_marker_list(window, tmp_path):
    loaded_window(window, tmp_path)

    window._apply_session(hostile_session(tmp_path, markers=[]))

    assert window.project.markers == [0.0]
    assert window.wave.markers == [0.0]


def test_apply_session_clamps_markers_to_the_audio_duration(window, tmp_path):
    loaded_window(window, tmp_path)
    duration = window.project.analysis.audio.duration

    window._apply_session(hostile_session(tmp_path, markers=[-500.0, 1e6, 2.0]))

    assert window.project.markers
    assert all(0.0 <= marker < duration for marker in window.project.markers)


def test_apply_session_clamps_out_of_range_tempo_and_downbeat(window, tmp_path):
    """The session core permits BPM up to 1e5 and downbeat to 1e6; unclamped these
    make beat_grid walk billions of steps on the GUI thread."""
    loaded_window(window, tmp_path)
    duration = window.project.analysis.audio.duration

    start = time.monotonic()
    window._apply_session(
        hostile_session(tmp_path, selected_bpm=99999.0, downbeat=999999.0, bar_count=999)
    )
    elapsed = time.monotonic() - start

    assert elapsed < 5.0
    assert window.bpm.value() <= window.bpm.maximum()
    assert window.project.analysis.selected_bpm == window.bpm.value()
    assert 0.0 <= window.project.analysis.downbeat <= duration
    assert window.project.analysis.downbeat == window.downbeat.value()
    assert window.wave.downbeat == window.downbeat.value()
    assert window.bars.value() <= window.bars.maximum()


def test_a_network_source_is_not_opened_without_consent(window, tmp_path, monkeypatch):
    session = hostile_session(tmp_path, source_path="\\\\attacker.example\\share\\break.wav")
    target = tmp_path / f"unc{SESSION_SUFFIX}"
    save_session(target, session)
    restored = []
    monkeypatch.setattr(
        MainWindow, "_restore_session", lambda self, *a, **k: restored.append(a)
    )
    monkeypatch.setattr(MainWindow, "_ask", lambda self, *a, **k: QMessageBox.No)

    window._open_session_path(target, confirmed=True)

    assert restored == []
    assert window.current_session_path is None


def test_a_network_source_is_opened_after_explicit_consent(window, tmp_path, monkeypatch):
    session = hostile_session(tmp_path, source_path="\\\\host.example\\share\\break.wav")
    target = tmp_path / f"unc{SESSION_SUFFIX}"
    save_session(target, session)
    restored = []
    monkeypatch.setattr(
        MainWindow, "_restore_session", lambda self, *a, **k: restored.append(a)
    )
    monkeypatch.setattr(MainWindow, "_ask", lambda self, *a, **k: QMessageBox.Yes)

    window._open_session_path(target, confirmed=True)

    assert len(restored) == 1


def test_source_status_unverified_is_reported_for_a_network_path(tmp_path):
    session = hostile_session(tmp_path, source_path="\\\\host.example\\share\\break.wav")
    target = tmp_path / f"unc{SESSION_SUFFIX}"
    save_session(target, session)

    _, status = load_session(target)

    assert status is SourceStatus.UNVERIFIED


def test_declining_to_relink_a_missing_source_abandons_the_open(window, tmp_path, monkeypatch):
    session = hostile_session(tmp_path)  # the fixture audio was never written to disk
    target = tmp_path / f"take{SESSION_SUFFIX}"
    save_session(target, session)
    restored = []
    monkeypatch.setattr(MainWindow, "_restore_session", lambda self, *a, **k: restored.append(a))
    monkeypatch.setattr(MainWindow, "_ask", lambda self, *a, **k: QMessageBox.Cancel)

    window._open_session_path(target, confirmed=True)

    assert restored == []
    assert window.current_session_path is None
    assert window.config.recent_files == []


def test_opening_defers_adopting_the_file_until_the_audio_loads(window, tmp_path, monkeypatch):
    """A restore that never completes must not leave Save pointed at the file or
    advertise it in the recent list."""
    session = hostile_session(tmp_path)
    target = tmp_path / f"take{SESSION_SUFFIX}"
    save_session(target, session)
    # Stand in for a restore that was dispatched but never reported success.
    monkeypatch.setattr(MainWindow, "_restore_session", lambda self, *a, **k: None)
    monkeypatch.setattr(MainWindow, "_ask", lambda self, *a, **k: QMessageBox.Ignore)

    window._open_session_path(target, confirmed=True)

    assert window.current_session_path is None
    assert window.config.recent_files == []

    # The commit happens only once the loaded project arrives.
    window._session_loaded(make_project(tmp_path / "break.wav", "equal16"), session, target, False)

    assert window.current_session_path == target
    assert window.config.recent_files == [str(target)]


def test_recent_files_are_deduped_and_capped():
    config = AppConfig()
    for index in range(MAX_RECENT_FILES + 5):
        config.add_recent_file(f"/tmp/session-{index}.json")
    config.add_recent_file("/tmp/session-0.json")

    assert len(config.recent_files) == MAX_RECENT_FILES
    assert config.recent_files[0] == "/tmp/session-0.json"
    assert config.recent_files.count("/tmp/session-0.json") == 1
