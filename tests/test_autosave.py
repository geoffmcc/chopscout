import json
import os
import stat
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox
from test_ui_state import close_window, make_project

from chopscout import autosave as autosave_module
from chopscout.audio import source_hash
from chopscout.autosave import (
    AutosaveUnreadable,
    clear_autosave,
    has_autosave,
    read_autosave,
    write_autosave,
)
from chopscout.config import AppConfig
from chopscout.models import Session
from chopscout.session import (
    SESSION_SUFFIX,
    SessionError,
    SourceStatus,
    check_source,
    load_session,
    save_session,
    session_payload,
)
from chopscout.ui import MainWindow, display_path


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def slot(tmp_path, monkeypatch):
    """Redirect the autosave slot away from the real user state directory."""
    path = tmp_path / "state" / "autosave" / "current.chopscout.json"
    monkeypatch.setattr(autosave_module, "autosave_path", lambda: path)
    return path


@pytest.fixture
def window(app, tmp_path, monkeypatch, slot):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(AppConfig, "path", staticmethod(lambda: config_path))
    win = MainWindow()
    yield win
    close_window(win)


def present_source(tmp_path) -> tuple[str, str]:
    """A real file on disk plus its hash, so a session verifies as SourceStatus.OK."""
    path = tmp_path / "break.wav"
    path.write_bytes(b"not really audio, but it exists and hashes")
    return str(path), source_hash(path)


def a_session(tmp_path, **overrides) -> Session:
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


# ----- storage module -------------------------------------------------------


def test_autosave_round_trips_the_session_and_its_metadata(tmp_path, slot):
    session = a_session(tmp_path, selected_bpm=93.5, markers=[0.0, 0.5, 2.0])

    write_autosave(session, tmp_path / f"take{SESSION_SUFFIX}", 1_700_000_000.0)
    record = read_autosave()

    assert record is not None
    assert record.session.selected_bpm == 93.5
    assert record.session.markers == [0.0, 0.5, 2.0]
    assert record.session_path == str(tmp_path / f"take{SESSION_SUFFIX}")
    assert record.saved_at == 1_700_000_000.0


def test_an_autosave_of_an_untitled_session_records_an_empty_origin(tmp_path, slot):
    write_autosave(a_session(tmp_path), None, 1.0)

    record = read_autosave()

    assert record is not None
    assert record.session_path == ""


def test_the_autosave_file_is_a_valid_session_file(tmp_path, slot):
    """The extra metadata keys must not break the hardened session validator."""
    write_autosave(a_session(tmp_path, selected_bpm=101.0), None, 5.0)

    session, _ = load_session(slot)

    assert session.selected_bpm == 101.0
    payload = json.loads(slot.read_text(encoding="utf-8"))
    assert payload["autosave_version"] == 1
    assert payload["schema_version"] == 2


def test_reading_a_missing_slot_returns_none(slot):
    assert read_autosave() is None
    assert has_autosave() is False


def test_a_corrupt_autosave_is_reported_as_absent_rather_than_raising(slot):
    slot.parent.mkdir(parents=True, exist_ok=True)
    slot.write_text("{not json", encoding="utf-8")

    assert read_autosave() is None
    assert has_autosave() is True  # present but unusable


def test_an_autosave_with_a_hostile_payload_is_rejected(tmp_path, slot):
    slot.parent.mkdir(parents=True, exist_ok=True)
    slot.write_text(
        json.dumps({"schema_version": 2, "source_path": "x", "markers": "not-a-list"}),
        encoding="utf-8",
    )

    assert read_autosave() is None


def test_clearing_the_slot_removes_it_and_tolerates_a_missing_file(tmp_path, slot):
    write_autosave(a_session(tmp_path), None, 1.0)
    assert has_autosave() is True

    clear_autosave()
    assert has_autosave() is False

    clear_autosave()  # must not raise


def test_writing_the_slot_is_atomic_and_leaves_no_temp_files(tmp_path, slot):
    write_autosave(a_session(tmp_path), None, 1.0)
    write_autosave(a_session(tmp_path, selected_bpm=140.0), None, 2.0)

    leftovers = [item for item in slot.parent.iterdir() if item.name != slot.name]
    assert leftovers == []
    record = read_autosave()
    assert record is not None and record.session.selected_bpm == 140.0


def write_raw_slot(slot, tmp_path, session_path='""', saved_at="1.0"):
    """Write a slot with raw JSON tokens for the metadata, so hostile literals
    (a 400-digit int, 1e999) can be planted exactly as an attacker would."""
    payload = session_payload(a_session(tmp_path))
    payload.update({"autosave_version": 1})
    body = json.dumps(payload)[:-1]  # drop the closing brace
    slot.parent.mkdir(parents=True, exist_ok=True)
    slot.write_text(
        f'{body}, "session_path": {session_path}, "saved_at": {saved_at}}}', encoding="utf-8"
    )


@pytest.mark.parametrize(
    "saved_at",
    ["9" * 400, "1e999", "-1e18", "1e18", '"not-a-number"', "true"],
    ids=["huge-int", "inf", "negative-huge", "far-future", "string", "bool"],
)
def test_a_hostile_timestamp_degrades_instead_of_crashing(tmp_path, slot, saved_at):
    """float() raises OverflowError on a 400-digit int, and time.localtime raises
    on inf or an out-of-epoch value; either would crash the app at startup."""
    write_raw_slot(slot, tmp_path, saved_at=saved_at)

    record = read_autosave()

    assert record is not None
    assert record.saved_at == 0.0  # rejected, not propagated


@pytest.mark.parametrize(
    "session_path",
    ['"\\\\\\\\host\\\\share\\\\x.chopscout.json"', '"/etc/cron.d/payload"', '"/tmp/x.txt"', "42"],
    ids=["unc", "no-suffix-system", "wrong-suffix", "not-a-string"],
)
def test_a_hostile_session_path_is_not_adopted(tmp_path, slot, session_path):
    """The recovered path becomes the Save target and enters the recent list."""
    write_raw_slot(slot, tmp_path, session_path=session_path)

    record = read_autosave()

    assert record is not None
    assert record.session_path == ""


def test_reading_the_slot_never_probes_the_recorded_audio(tmp_path, slot, monkeypatch):
    """Startup must not stat or hash a path chosen by the slot file, before the
    user has consented to recovering it.

    The source must exist and hash-match, otherwise _source_status short-circuits
    at the is_file() check and never reaches source_hash — which would make this
    test pass even with the probe reinstated.
    """
    path, digest = present_source(tmp_path)
    write_autosave(a_session(tmp_path, source_path=path, source_hash=digest), None, 1.0)
    monkeypatch.setattr(
        "chopscout.session.source_hash",
        lambda *a, **k: pytest.fail("hashed the source before consent"),
    )

    assert read_autosave() is not None


def test_the_source_is_checked_once_the_user_consents(tmp_path, slot):
    """The counterpart to the test above: verification is deferred, not dropped."""
    path, digest = present_source(tmp_path)
    session = a_session(tmp_path, source_path=path, source_hash=digest)
    write_autosave(session, None, 1.0)
    record = read_autosave()

    assert record is not None
    assert check_source(record.session) is SourceStatus.OK

    Path(path).write_bytes(b"different audio entirely")
    assert check_source(record.session) is SourceStatus.CHANGED


def test_a_temporarily_unreadable_slot_is_not_treated_as_invalid(tmp_path, slot, monkeypatch):
    write_autosave(a_session(tmp_path), None, 1.0)

    def denied(*_args, **_kwargs):
        raise PermissionError("locked by another process")

    monkeypatch.setattr("pathlib.Path.read_text", denied)

    with pytest.raises(AutosaveUnreadable):
        read_autosave()


def test_an_unreadable_slot_is_preserved_rather_than_discarded(window, tmp_path, slot, monkeypatch):
    write_autosave(a_session(tmp_path), None, 1.0)
    monkeypatch.setattr(
        "chopscout.ui.read_autosave", lambda: (_ for _ in ()).throw(AutosaveUnreadable("locked"))
    )

    assert window.offer_recovery() is False
    assert has_autosave() is True  # the only copy of the work survives


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_the_slot_is_written_private_to_the_user(tmp_path, slot):
    write_autosave(a_session(tmp_path), None, 1.0)

    assert stat.S_IMODE(slot.stat().st_mode) == 0o600
    assert stat.S_IMODE(slot.parent.stat().st_mode) == 0o700


def test_control_characters_in_a_path_cannot_fabricate_dialog_lines():
    assert "\n" not in display_path("a\nb\nVerified as safe")
    assert display_path("a\nb") == "a?b"


# ----- GUI wiring -----------------------------------------------------------


def test_the_autosave_timer_runs_from_startup(window):
    assert window.autosave_timer.isActive()
    assert window.autosave_timer.interval() == 60_000


def test_autosave_writes_only_when_there_is_unsaved_work(window, tmp_path, slot):
    window.autosave()
    assert has_autosave() is False  # nothing loaded

    window.loaded(make_project(tmp_path / "break.wav", "equal16"))
    window.autosave()
    assert has_autosave() is False  # loaded but unmodified

    window.bpm.setValue(150.0)
    window.autosave()

    assert has_autosave() is True
    record = read_autosave()
    assert record is not None and record.session.selected_bpm == 150.0


def test_a_failing_autosave_does_not_raise(window, tmp_path, monkeypatch):
    window.loaded(make_project(tmp_path / "break.wav", "equal16"))
    window.bpm.setValue(150.0)

    def boom(*_args, **_kwargs):
        raise SessionError("disk full")

    monkeypatch.setattr("chopscout.ui.write_autosave", boom)

    window.autosave()  # must not propagate


def test_saving_a_session_clears_the_recovery_slot(window, tmp_path, slot):
    window.loaded(make_project(tmp_path / "break.wav", "equal16"))
    window.bpm.setValue(150.0)
    window.autosave()
    assert has_autosave() is True

    window._write_session(tmp_path / f"take{SESSION_SUFFIX}")

    assert has_autosave() is False


def test_a_clean_close_clears_the_recovery_slot(window, tmp_path, slot):
    window.loaded(make_project(tmp_path / "break.wav", "equal16"))
    window.bpm.setValue(150.0)
    window.autosave()
    assert has_autosave() is True

    window._mark_clean()  # so closeEvent does not prompt
    window.close()

    assert has_autosave() is False
    assert not window.autosave_timer.isActive()


# ----- recovery -------------------------------------------------------------


def test_a_normal_open_does_not_claim_the_source_was_relinked(
    window, tmp_path, slot, monkeypatch
):
    """The relink-specific status message must not leak onto ordinary opens.

    Driven through _open_session_path, which is where the message is chosen;
    asserting on _session_loaded directly would bypass that choice entirely.
    """
    path, digest = present_source(tmp_path)
    session = a_session(tmp_path, source_path=path, source_hash=digest)
    target = tmp_path / f"take{SESSION_SUFFIX}"
    save_session(target, session)
    calls = []
    monkeypatch.setattr(MainWindow, "_restore_session", lambda self, *a, **k: calls.append(k))

    window._open_session_path(target, confirmed=True)

    assert len(calls) == 1
    assert calls[0]["unsaved"] is False
    assert calls[0]["message"] == "Session restored"


def test_saving_a_session_with_a_non_finite_value_reports_cleanly(window, tmp_path, monkeypatch):
    """allow_nan=False makes json.dumps raise ValueError; Save must surface that
    as a SessionError-backed dialog rather than throwing through a Qt slot."""
    window.loaded(make_project(tmp_path / "break.wav", "equal16"))
    broken = a_session(tmp_path, selected_bpm=float("inf"))
    monkeypatch.setattr(MainWindow, "_session_from_state", lambda self: broken)
    seen = []
    monkeypatch.setattr(
        "chopscout.ui.QMessageBox.critical", lambda _p, _t, text: seen.append(text)
    )

    assert window._write_session(tmp_path / f"take{SESSION_SUFFIX}") is False
    assert seen and "encode" in seen[0].lower()


def test_cancelling_source_resolution_keeps_the_slot_for_next_time(
    window, tmp_path, slot, monkeypatch
):
    """Deliberate: a cancelled recovery must not destroy the unsaved work."""
    write_autosave(a_session(tmp_path), None, 1.0)  # source does not exist -> MISSING
    # Yes to recover, then Cancel the missing-source prompt.
    answers = iter([QMessageBox.Yes, QMessageBox.Cancel])
    monkeypatch.setattr(MainWindow, "_ask", lambda self, *a, **k: next(answers))

    assert window.offer_recovery() is False
    assert has_autosave() is True


def test_offer_recovery_does_nothing_without_a_slot(window):
    assert window.offer_recovery() is False


def test_declining_recovery_discards_the_slot(window, tmp_path, slot, monkeypatch):
    write_autosave(a_session(tmp_path), None, 1.0)
    monkeypatch.setattr(MainWindow, "_ask", lambda self, *a, **k: QMessageBox.No)

    assert window.offer_recovery() is False
    assert has_autosave() is False


def test_accepting_recovery_restores_the_session_as_unsaved_work(
    window, tmp_path, slot, monkeypatch
):
    path, digest = present_source(tmp_path)
    write_autosave(a_session(tmp_path, source_path=path, source_hash=digest), None, 1.0)
    restored = []
    monkeypatch.setattr(
        MainWindow, "_restore_session", lambda self, *a, **k: restored.append((a, k))
    )
    # The source verifies as OK, so recovery asks exactly one question.
    monkeypatch.setattr(MainWindow, "_ask", lambda self, *a, **k: QMessageBox.Yes)

    assert window.offer_recovery() is True
    assert len(restored) == 1
    assert restored[0][1]["unsaved"] is True


def test_a_corrupt_slot_cannot_block_startup(window, slot, monkeypatch):
    slot.parent.mkdir(parents=True, exist_ok=True)
    slot.write_text("{not json", encoding="utf-8")
    asked = []
    monkeypatch.setattr(MainWindow, "_ask", lambda self, *a, **k: asked.append(a))

    assert window.offer_recovery() is False
    assert asked == []  # no dialog at all
    assert has_autosave() is False  # the unusable remnant is dropped


def test_a_recovered_untitled_session_is_restored_without_a_session_path(
    window, tmp_path, slot, monkeypatch
):
    path, digest = present_source(tmp_path)
    write_autosave(a_session(tmp_path, source_path=path, source_hash=digest), "", 1.0)
    restored = []
    monkeypatch.setattr(
        MainWindow, "_restore_session", lambda self, *a, **k: restored.append((a, k))
    )
    monkeypatch.setattr(MainWindow, "_ask", lambda self, *a, **k: QMessageBox.Yes)

    window.offer_recovery()

    assert restored[0][0][1] is None  # no path to adopt
