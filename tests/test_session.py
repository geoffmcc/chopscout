"""Session round-trip, migration, source-status, relink, and malformed-file tests."""

import json
import shutil
from pathlib import Path

import pytest

from chopscout.audio import source_hash
from chopscout.models import SESSION_SCHEMA_VERSION, Session
from chopscout.session import (
    SessionError,
    SourceStatus,
    load_session,
    relink_source,
    save_session,
)


def make_source(path: Path, content: bytes = b"RIFF-fake-audio-content") -> str:
    path.write_bytes(content)
    return source_hash(path)


def make_session(source: Path, digest: str) -> Session:
    return Session(
        source_path=str(source),
        source_hash=digest,
        detected_bpm=93.2,
        selected_bpm=186.4,
        bar_count=2,
        downbeat=0.125,
        markers=[0.0, 0.5, 1.25, 2.0],
        chop_mode="hybrid",
        pad_map={"A01": 36, "A02": 37},
        export_settings={"mode": "hybrid", "bpm": 186.4, "bars": 2, "overwrite": True},
    )


def test_session_round_trip_preserves_manual_state(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    session = make_session(source, digest)
    path = tmp_path / "take.chopscout.json"
    save_session(path, session)
    loaded, status = load_session(path)
    assert status is SourceStatus.OK
    assert loaded.markers == [0.0, 0.5, 1.25, 2.0]
    assert loaded.selected_bpm == 186.4
    assert loaded.detected_bpm == 93.2
    assert loaded.downbeat == 0.125
    assert loaded.chop_mode == "hybrid"
    assert loaded.pad_map == {"A01": 36, "A02": 37}
    assert loaded.export_settings["overwrite"] is True
    assert loaded.schema_version == SESSION_SCHEMA_VERSION
    assert loaded.app_version


def test_missing_source_is_reported(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "session.json"
    save_session(path, make_session(source, digest))
    source.unlink()
    _, status = load_session(path)
    assert status is SourceStatus.MISSING


def test_changed_source_is_reported(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "session.json"
    save_session(path, make_session(source, digest))
    source.write_bytes(b"different audio bytes")
    _, status = load_session(path)
    assert status is SourceStatus.CHANGED


def test_skipping_verification_is_explicit(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "session.json"
    save_session(path, make_session(source, digest))
    _, status = load_session(path, verify_source=False)
    assert status is SourceStatus.UNVERIFIED


def test_legacy_v1_session_migrates(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    legacy = {
        "version": "0.1.0",
        "source_path": str(source),
        "source_hash": digest,
        "detected_bpm": 120.0,
        "selected_bpm": 120.0,
        "bar_count": 4,
        "downbeat": 0.0,
        "markers": [0.0, 1.0],
        "chop_mode": "manual",
        "pad_map": {"A01": 36},
        "export_settings": {"mode": "manual", "trim_silence": True},
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    loaded, status = load_session(path)
    assert status is SourceStatus.OK
    assert loaded.schema_version == SESSION_SCHEMA_VERSION
    assert loaded.app_version == "0.1.0"
    assert loaded.markers == [0.0, 1.0]
    assert "trim_silence" not in loaded.export_settings
    assert loaded.export_settings["mode"] == "manual"


def test_future_schema_version_is_rejected(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    session = make_session(source, digest)
    path = tmp_path / "future.json"
    save_session(path, session)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = SESSION_SCHEMA_VERSION + 7
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SessionError, match="newer ChopScout"):
        load_session(path)


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (lambda d: d.update(markers="not a list"), "markers must be a list"),
        (lambda d: d.update(markers=[0.0, "x"]), "finite numbers"),
        (lambda d: d.update(markers=[1e999]), "unsupported JSON constant"),
        (lambda d: d.update(selected_bpm=0), "finite positive numbers"),
        (lambda d: d.update(selected_bpm=1e999), "unsupported JSON constant"),
        (lambda d: d.update(bar_count="four"), "bar_count"),
        (lambda d: d.update(bar_count=0), "bar_count"),
        (lambda d: d.update(downbeat=None), "downbeat"),
        (lambda d: d.update(chop_mode=""), "chop_mode"),
        (lambda d: d.update(pad_map=[1, 2]), "pad_map"),
        (lambda d: d.update(pad_map={"A01": "x"}), "pad_map"),
        (lambda d: d.update(export_settings="x"), "export_settings"),
        (lambda d: d.update(source_path=""), "source_path"),
        (lambda d: d.update(source_hash=5), "source_hash"),
        (lambda d: d.update(markers=[0.0] * 5000), "maximum"),
    ],
)
def test_malformed_sessions_are_rejected(tmp_path: Path, mutation, reason: str):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "bad.json"
    save_session(path, make_session(source, digest))
    data = json.loads(path.read_text(encoding="utf-8"))
    mutation(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SessionError, match=reason):
        load_session(path)


def test_unreadable_and_non_object_sessions_are_rejected(tmp_path: Path):
    garbage = tmp_path / "garbage.json"
    garbage.write_text("{not json", encoding="utf-8")
    with pytest.raises(SessionError, match="unreadable"):
        load_session(garbage)
    array = tmp_path / "array.json"
    array.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(SessionError, match="not a JSON object"):
        load_session(array)
    missing = tmp_path / "nope.json"
    with pytest.raises(SessionError, match="does not exist"):
        load_session(missing)
    nan = tmp_path / "nan.json"
    nan.write_text('{"schema_version": 2, "downbeat": NaN}', encoding="utf-8")
    with pytest.raises(SessionError, match="unreadable"):
        load_session(nan)


def test_oversized_session_is_rejected(tmp_path: Path):
    path = tmp_path / "huge.json"
    path.write_text("{" + " " * 6_000_000 + "}", encoding="utf-8")
    with pytest.raises(SessionError, match="large"):
        load_session(path)


def test_relink_to_moved_source(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "session.json"
    save_session(path, make_session(source, digest))
    moved = tmp_path / "elsewhere" / "break.wav"
    moved.parent.mkdir()
    shutil.move(source, moved)
    session, status = load_session(path)
    assert status is SourceStatus.MISSING
    relink_source(session, moved)
    assert session.source_path == str(moved)
    save_session(path, session)
    _, status = load_session(path)
    assert status is SourceStatus.OK


def test_relink_to_different_audio_requires_explicit_consent(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    session = make_session(source, digest)
    other = tmp_path / "other.wav"
    other.write_bytes(b"completely different audio")
    with pytest.raises(SessionError, match="does not match"):
        relink_source(session, other)
    relink_source(session, other, allow_changed=True)
    assert session.source_path == str(other)
    assert session.source_hash == source_hash(other)


def test_relink_to_missing_target_is_rejected(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    session = make_session(source, digest)
    with pytest.raises(SessionError, match="does not exist"):
        relink_source(session, tmp_path / "ghost.wav")


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path: Path):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "session.json"
    save_session(path, make_session(source, digest))
    save_session(path, make_session(source, digest))
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".session")]
    assert leftovers == []
    loaded, _ = load_session(path, verify_source=False)
    assert loaded.markers == [0.0, 0.5, 1.25, 2.0]


@pytest.mark.parametrize("bad_version", [True, 0, "2", None])
def test_invalid_schema_versions_are_rejected(tmp_path: Path, bad_version):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "bad_version.json"
    save_session(path, make_session(source, digest))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = bad_version
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SessionError, match="schema version"):
        load_session(path)


def test_unreadable_source_reports_missing(tmp_path: Path, monkeypatch):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "session.json"
    save_session(path, make_session(source, digest))

    def deny(_path):
        raise PermissionError("locked")

    monkeypatch.setattr("chopscout.session.source_hash", deny)
    _, status = load_session(path)
    assert status is SourceStatus.MISSING


def test_unc_source_paths_are_never_probed(tmp_path: Path, monkeypatch):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "session.json"
    session = make_session(source, digest)
    session.source_path = "\\\\attacker\\share\\break.wav"
    save_session(path, session)
    monkeypatch.setattr(
        "chopscout.session.source_hash", lambda _p: pytest.fail("must not hash UNC paths")
    )
    _, status = load_session(path)
    assert status is SourceStatus.UNVERIFIED


def test_size_mismatch_reports_changed_without_hashing(tmp_path: Path, monkeypatch):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "session.json"
    session = make_session(source, digest)
    session.source_size = source.stat().st_size + 100
    save_session(path, session)
    monkeypatch.setattr(
        "chopscout.session.source_hash", lambda _p: pytest.fail("size gate must run first")
    )
    _, status = load_session(path)
    assert status is SourceStatus.CHANGED


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["export_settings"].update(overwrite="yes"),
        lambda d: d["export_settings"].update(starting_note=200),
        lambda d: d["export_settings"].update(export_format="garbage"),
        lambda d: d["export_settings"].update(pad_count=17),
        lambda d: d["export_settings"].update(bpm="fast"),
        lambda d: d["pad_map"].update(A03=300),
    ],
)
def test_hostile_setting_values_are_rejected(tmp_path: Path, mutation):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    path = tmp_path / "hostile.json"
    save_session(path, make_session(source, digest))
    data = json.loads(path.read_text(encoding="utf-8"))
    mutation(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SessionError, match="malformed"):
        load_session(path)


def test_save_never_probes_unc_source_paths(tmp_path: Path, monkeypatch):
    source = tmp_path / "break.wav"
    digest = make_source(source)
    session = make_session(source, digest)
    session.source_path = "\\\\attacker\\share\\break.wav"
    monkeypatch.setattr(
        "chopscout.session._probe_source_size",
        lambda _p: pytest.fail("must not stat UNC paths on save"),
    )
    save_session(tmp_path / "session.json", session)
    assert session.source_size == 0
