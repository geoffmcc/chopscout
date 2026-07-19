"""Failure-injection tests for atomic, recoverable export replacement."""

import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import chopscout.exporter as exporter
from chopscout.exporter import ExportError, export_package, validate_package
from chopscout.models import AnalysisResult, AudioInfo, ExportSettings

SLICES = 16
SAMPLE_RATE = 22050
DURATION = 4.0


class InjectedFailure(Exception):
    pass


def make_project(tmp_path: Path):
    frames = int(SAMPLE_RATE * DURATION)
    data = np.zeros((frames, 1), dtype=np.float32)
    for index in range(SLICES):
        start = int(index * frames / SLICES)
        n = min(400, frames - start)
        data[start : start + n, 0] = np.linspace(1.0, 0.0, n)
    source = tmp_path / "break.wav"
    sf.write(source, data, SAMPLE_RATE)
    audio = AudioInfo(
        path=str(source),
        sample_rate=SAMPLE_RATE,
        channels=1,
        frames=frames,
        duration=DURATION,
        subtype="PCM_16",
        source_hash="test-hash",
    )
    analysis = AnalysisResult(
        audio=audio,
        detected_bpm=120.0,
        selected_bpm=120.0,
        tempo_confidence=1.0,
        beat_times=[],
        onset_times=[],
        onset_strengths=[],
        downbeat=0.0,
        downbeat_confidence=1.0,
        estimated_bars=2,
        trim_start=0.0,
        trim_end=DURATION,
    )
    markers = [index * DURATION / SLICES for index in range(SLICES)]
    return source, data, analysis, markers


def settings(**overrides) -> ExportSettings:
    values = {"mode": "equal16", "bpm": 120.0, "bars": 2}
    values.update(overrides)
    return ExportSettings(**values)


def do_export(tmp_path: Path, parent: Path, **overrides) -> Path:
    source, data, analysis, markers = make_project(tmp_path)
    return export_package(
        source, data, SAMPLE_RATE, analysis, markers, parent, settings(**overrides)
    )


def residue(parent: Path) -> list[str]:
    return sorted(path.name for path in parent.iterdir() if path.name.startswith("."))


def make_existing_export(tmp_path: Path, parent: Path) -> Path:
    dest = do_export(tmp_path, parent)
    (dest / "SENTINEL.txt").write_text("previous export", encoding="utf-8")
    return dest


def test_fresh_export_is_valid_and_leaves_no_temp_dirs(tmp_path: Path):
    parent = tmp_path / "out"
    dest = do_export(tmp_path, parent)
    assert dest == parent / "break_120"
    assert validate_package(dest) == []
    assert residue(parent) == []


def test_existing_export_without_overwrite_is_refused_and_untouched(tmp_path: Path):
    parent = tmp_path / "out"
    dest = make_existing_export(tmp_path, parent)
    with pytest.raises(ExportError, match="already exists"):
        do_export(tmp_path, parent)
    assert (dest / "SENTINEL.txt").read_text(encoding="utf-8") == "previous export"
    assert validate_package(dest) == []
    assert residue(parent) == []


def test_successful_overwrite_replaces_previous_export(tmp_path: Path):
    parent = tmp_path / "out"
    dest = make_existing_export(tmp_path, parent)
    result = do_export(tmp_path, parent, overwrite=True)
    assert result == dest
    assert not (dest / "SENTINEL.txt").exists()
    assert validate_package(dest) == []
    assert residue(parent) == []


@pytest.mark.parametrize(
    "target",
    ["write_wav", "write_reconstruction", "create_mpc39_project", "create_mpc39_program"],
)
def test_generation_failure_preserves_previous_export(tmp_path: Path, monkeypatch, target: str):
    parent = tmp_path / "out"
    dest = make_existing_export(tmp_path, parent)

    def fail(*args, **kwargs):
        raise InjectedFailure(f"injected {target} failure")

    monkeypatch.setattr(exporter, target, fail)
    with pytest.raises(InjectedFailure):
        do_export(tmp_path, parent, overwrite=True)
    monkeypatch.undo()
    assert (dest / "SENTINEL.txt").exists()
    assert validate_package(dest) == []
    assert residue(parent) == []


def test_validation_failure_preserves_previous_export(tmp_path: Path, monkeypatch):
    parent = tmp_path / "out"
    dest = make_existing_export(tmp_path, parent)
    monkeypatch.setattr(
        exporter, "validate_package", lambda root: ["injected validation problem"]
    )
    with pytest.raises(ExportError, match="injected validation problem"):
        do_export(tmp_path, parent, overwrite=True)
    monkeypatch.undo()
    assert (dest / "SENTINEL.txt").exists()
    assert validate_package(dest) == []
    assert residue(parent) == []


def test_backup_rename_failure_leaves_existing_export_untouched(tmp_path: Path, monkeypatch):
    parent = tmp_path / "out"
    dest = make_existing_export(tmp_path, parent)
    real_rename = os.rename

    def fail_backup(src, dst, *args, **kwargs):
        if ".backup-" in Path(dst).name:
            raise PermissionError("injected sharing violation")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail_backup)
    with pytest.raises(ExportError, match="existing export was not modified"):
        do_export(tmp_path, parent, overwrite=True)
    monkeypatch.undo()
    assert (dest / "SENTINEL.txt").exists()
    assert validate_package(dest) == []
    assert residue(parent) == []


def test_final_swap_failure_restores_previous_export(tmp_path: Path, monkeypatch):
    parent = tmp_path / "out"
    dest = make_existing_export(tmp_path, parent)
    real_rename = os.rename

    def fail_swap(src, dst, *args, **kwargs):
        if ".build-" in Path(src).name and not Path(dst).name.startswith("."):
            raise PermissionError("injected sharing violation")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail_swap)
    with pytest.raises(ExportError, match="previous export was restored"):
        do_export(tmp_path, parent, overwrite=True)
    monkeypatch.undo()
    assert (dest / "SENTINEL.txt").exists()
    assert validate_package(dest) == []
    assert residue(parent) == []


def test_fresh_export_swap_failure_leaves_nothing_behind(tmp_path: Path, monkeypatch):
    parent = tmp_path / "out"
    real_rename = os.rename

    def fail_swap(src, dst, *args, **kwargs):
        if ".build-" in Path(src).name:
            raise PermissionError("injected sharing violation")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail_swap)
    with pytest.raises(ExportError, match="No existing export was modified"):
        do_export(tmp_path, parent)
    monkeypatch.undo()
    assert not (parent / "break_120").exists()
    assert residue(parent) == []


def test_swap_and_restore_failure_names_preserved_backup(tmp_path: Path, monkeypatch):
    parent = tmp_path / "out"
    make_existing_export(tmp_path, parent)
    real_rename = os.rename

    def fail(src, dst, *args, **kwargs):
        src_name = Path(src).name
        if ".build-" in src_name or ".backup-" in src_name:
            raise PermissionError("injected sharing violation")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "rename", fail)
    with pytest.raises(ExportError, match="preserved at"):
        do_export(tmp_path, parent, overwrite=True)
    monkeypatch.undo()
    backups = [path for path in parent.iterdir() if ".backup-" in path.name]
    assert len(backups) == 1
    assert (backups[0] / "SENTINEL.txt").exists()
    assert validate_package(backups[0]) == []


def test_destination_that_is_a_file_is_refused(tmp_path: Path):
    parent = tmp_path / "out"
    parent.mkdir()
    blocker = parent / "break_120"
    blocker.write_text("not a folder", encoding="utf-8")
    with pytest.raises(ExportError, match="not a folder"):
        do_export(tmp_path, parent)
    assert blocker.read_text(encoding="utf-8") == "not a folder"
    assert residue(parent) == []


def test_destination_created_during_build_without_overwrite_is_refused(
    tmp_path: Path, monkeypatch
):
    parent = tmp_path / "out"
    real_validate = exporter.validate_package
    interloper = parent / "break_120"

    def create_then_validate(root):
        problems = real_validate(root)
        interloper.mkdir(parents=True)
        (interloper / "INTERLOPER.txt").write_text("other export", encoding="utf-8")
        return problems

    monkeypatch.setattr(exporter, "validate_package", create_then_validate)
    with pytest.raises(ExportError, match="already exists"):
        do_export(tmp_path, parent)
    monkeypatch.undo()
    assert (interloper / "INTERLOPER.txt").read_text(encoding="utf-8") == "other export"
    assert residue(parent) == []


def test_symlinked_destination_is_refused(tmp_path: Path):
    parent = tmp_path / "out"
    parent.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    try:
        os.symlink(elsewhere, parent / "break_120", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available in this environment")
    with pytest.raises(ExportError, match="is a link"):
        do_export(tmp_path, parent)
    assert list(elsewhere.iterdir()) == []
