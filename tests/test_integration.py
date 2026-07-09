import json
from pathlib import Path

import mido
import numpy as np
import pytest
import soundfile as sf

import chopscout.exporter as exporter
from chopscout.cli import main, parser
from chopscout.core import export_project, load_project
from chopscout.exporter import ExportError, validate_export_contract, validate_package
from chopscout.models import ExportFormat, ExportSettings
from chopscout.mpc import MpcCompatibilityError


def make_break(path: Path):
    sr = 22050
    duration = 4.0
    data = np.zeros((int(sr * duration), 1), dtype=np.float32)
    for second in np.arange(0, duration, 0.5):
        start = int(second * sr)
        n = min(500, len(data) - start)
        data[start : start + n, 0] = np.linspace(1, 0, n)
    sf.write(path, data, sr)


def midi_note_ons(path: Path) -> list[int]:
    midi = mido.MidiFile(path)
    return [
        message.note
        for track in midi.tracks
        for message in track
        if message.type == "note_on" and message.velocity > 0
    ]


def test_decode_analyze_export(tmp_path: Path):
    source = tmp_path / "break.wav"
    make_break(source)
    project = load_project(source, "equal8")
    settings = ExportSettings(mode="equal8", bpm=120, bars=2)
    result = export_project(project, tmp_path / "out", settings)
    assert validate_package(result) == []
    assert len(list((result / "chops_equal8").glob("*.wav"))) == 8


def test_equal16_export_includes_xpj_and_xpm(tmp_path: Path):
    source = tmp_path / "break16.wav"
    make_break(source)
    project = load_project(source, "equal16")
    settings = ExportSettings(mode="equal16", bpm=120, bars=4)
    result = export_project(project, tmp_path / "out16", settings)
    metadata = json.loads((result / "metadata" / "chopscout.json").read_text(encoding="utf-8"))
    assert metadata["export"]["export_format"] == "both"
    assert validate_package(result) == []
    assert len(list((result / "mpc_project").glob("*/*.xpj"))) == 1
    assert len(list((result / "mpc_program").glob("*/*.xpm"))) == 1
    program = next((result / "mpc_program").glob("*/*.xpm"))
    companion = program.parent / f"{program.stem}_[ProgramData]"
    assert len(list(companion.glob("A??.wav"))) == 16


def test_equal64_export_includes_banks_a_through_d(tmp_path: Path):
    source = tmp_path / "break64.wav"
    make_break(source)
    project = load_project(source, "equal64")
    settings = ExportSettings(mode="equal64", bpm=120, bars=4, pad_count=64)
    result = export_project(project, tmp_path / "out64", settings)
    assert validate_package(result) == []
    assert (result / "chops_equal64" / "A01.wav").is_file()
    assert (result / "chops_equal64" / "D16.wav").is_file()
    program = next((result / "mpc_program").glob("*/*.xpm"))
    companion = program.parent / f"{program.stem}_[ProgramData]"
    assert len(list(companion.glob("*.wav"))) == 64


def test_explicit_both_format_matches_default_mpc_outputs(tmp_path: Path):
    source = tmp_path / "break16_both.wav"
    make_break(source)
    project = load_project(source, "equal16")
    settings = ExportSettings(mode="equal16", bpm=120, bars=2, export_format=ExportFormat.BOTH)

    result = export_project(project, tmp_path / "out_both", settings)
    metadata = json.loads((result / "metadata" / "chopscout.json").read_text(encoding="utf-8"))

    assert metadata["export"]["export_format"] == "both"
    assert metadata["mpc_project_generated"] is True
    assert len(list((result / "mpc_project").glob("*/*.xpj"))) == 1
    assert len(list((result / "mpc_program").glob("*/*.xpm"))) == 1


def test_explicit_mpc_format_generates_complete_mpc_oriented_package(tmp_path: Path):
    source = tmp_path / "break16_mpc.wav"
    make_break(source)
    project = load_project(source, "equal16")
    settings = ExportSettings(mode="equal16", bpm=120, bars=2, export_format=ExportFormat.MPC)

    result = export_project(project, tmp_path / "out_mpc", settings)
    metadata = json.loads((result / "metadata" / "chopscout.json").read_text(encoding="utf-8"))

    assert metadata["export"]["export_format"] == "mpc"
    assert (result / "midi" / "original_groove.mid").is_file()
    assert metadata["mpc_project_generated"] is True
    assert len(list((result / "mpc_project").glob("*/*.xpj"))) == 1


def test_explicit_pad_count_must_match_active_slice_count(tmp_path: Path):
    source = tmp_path / "break8.wav"
    make_break(source)
    project = load_project(source, "equal8")
    settings = ExportSettings(mode="equal8", bpm=120, bars=2, pad_count=16)

    with pytest.raises(ExportError, match="requires 16 slices"):
        export_project(project, tmp_path / "out_mismatch", settings)


def test_mpc_export_rejects_custom_starting_note(tmp_path: Path):
    source = tmp_path / "break16_custom_note.wav"
    make_break(source)
    project = load_project(source, "equal16")
    settings = ExportSettings(mode="equal16", bpm=120, bars=2, starting_note=40)

    with pytest.raises(ExportError, match="fixed drum notes 36-99"):
        export_project(project, tmp_path / "out_custom_note", settings)


def test_custom_starting_note_allowed_with_portable_format(tmp_path: Path):
    source = tmp_path / "break16_custom_note.wav"
    make_break(source)
    project = load_project(source, "equal16")
    settings = ExportSettings(
        mode="equal16", bpm=120, bars=2, starting_note=40, export_format=ExportFormat.PORTABLE
    )

    result = export_project(project, tmp_path / "out_custom_note_portable", settings)
    metadata = json.loads((result / "metadata" / "chopscout.json").read_text(encoding="utf-8"))

    assert metadata["export"]["export_format"] == "portable"
    assert metadata["mpc_project_generated"] is False
    assert metadata["mpc_program_generated"] is False
    assert not (result / "mpc_project").exists()
    assert not (result / "mpc_program").exists()
    assert (result / "metadata" / "PORTABLE_IMPORT_README.txt").is_file()
    assert not (result / "metadata" / "MPC_IMPORT_README.txt").exists()
    assert list((result / "mpc_project").glob("*/*.xpj")) == []
    assert list((result / "mpc_program").glob("*/*.xpm")) == []
    assert midi_note_ons(result / "midi" / "original_groove.mid") == list(range(40, 56))
    assert validate_package(result) == []


def test_validate_package_rejects_pad_count_metadata_mismatch(tmp_path: Path):
    source = tmp_path / "break16_validate.wav"
    make_break(source)
    project = load_project(source, "equal16")
    result = export_project(
        project, tmp_path / "out_validate", ExportSettings(mode="equal16", bpm=120, bars=2)
    )
    metadata_path = result / "metadata" / "chopscout.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["export"]["pad_count"] = 32
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    assert "Metadata pad_count does not match slice map row count." in validate_package(result)


def test_validate_package_rejects_invalid_export_format_metadata(tmp_path: Path):
    source = tmp_path / "break16_bad_format.wav"
    make_break(source)
    project = load_project(source, "equal16")
    result = export_project(
        project, tmp_path / "out_bad_format", ExportSettings(mode="equal16", bpm=120, bars=2)
    )
    metadata_path = result / "metadata" / "chopscout.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["export"]["export_format"] = "unknown"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    assert "Metadata export_format is invalid." in validate_package(result)


def test_validate_package_rejects_mpc_format_without_artifacts(tmp_path: Path):
    source = tmp_path / "break16_missing_mpc.wav"
    make_break(source)
    project = load_project(source, "equal16")
    result = export_project(
        project,
        tmp_path / "out_missing_mpc",
        ExportSettings(mode="equal16", bpm=120, bars=2, export_format=ExportFormat.PORTABLE),
    )
    metadata_path = result / "metadata" / "chopscout.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["export"]["export_format"] = "mpc"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    assert "MPC format requires generated XPJ and XPM artifacts." in validate_package(result)


def test_validate_package_rejects_portable_format_with_mpc_artifacts(tmp_path: Path):
    source = tmp_path / "break16_portable_artifacts.wav"
    make_break(source)
    project = load_project(source, "equal16")
    result = export_project(
        project,
        tmp_path / "out_portable_artifacts",
        ExportSettings(mode="equal16", bpm=120, bars=2, export_format=ExportFormat.PORTABLE),
    )
    artifact_dir = result / "mpc_project" / "unexpected"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "unexpected.xpj").write_bytes(b"not a real project")

    assert "Portable format must not contain XPJ or XPM artifacts." in validate_package(result)


def test_mpc_format_fails_if_mpc_generation_fails(tmp_path: Path, monkeypatch):
    source = tmp_path / "break16_generation_fail.wav"
    make_break(source)
    project = load_project(source, "equal16")

    def fail_project(**_kwargs):
        raise MpcCompatibilityError("fixture unavailable")

    monkeypatch.setattr(exporter, "create_mpc39_project", fail_project)

    with pytest.raises(ExportError, match="MPC format requires generated XPJ and XPM artifacts"):
        export_project(
            project,
            tmp_path / "out_generation_fail",
            ExportSettings(mode="equal16", bpm=120, bars=2, export_format=ExportFormat.MPC),
        )


def test_cli_portable_format_allows_custom_starting_note_for_supported_slice_count(tmp_path: Path):
    source = tmp_path / "break16_cli.wav"
    make_break(source)
    output = tmp_path / "cli_out"

    assert (
        main(
            [
                "export",
                str(source),
                "--mode",
                "equal16",
                "--output",
                str(output),
                "--bpm",
                "120",
                "--bars",
                "2",
                "--starting-note",
                "40",
                "--format",
                "portable",
            ]
        )
        == 0
    )

    result = output / "break16_cli_120"
    metadata = json.loads((result / "metadata" / "chopscout.json").read_text(encoding="utf-8"))
    assert metadata["export"]["export_format"] == "portable"
    assert metadata["mpc_project_generated"] is False
    assert not (result / "mpc_project").exists()
    assert not (result / "mpc_program").exists()
    assert (result / "metadata" / "PORTABLE_IMPORT_README.txt").is_file()
    assert list((result / "mpc_project").glob("*/*.xpj")) == []
    assert list((result / "mpc_program").glob("*/*.xpm")) == []
    assert midi_note_ons(result / "midi" / "original_groove.mid") == list(range(40, 56))


def test_cli_rejects_invalid_export_format():
    with pytest.raises(SystemExit):
        parser().parse_args(["export", "break.wav", "--format", "unknown"])


def test_mpc_format_requires_supported_slice_count(tmp_path: Path):
    source = tmp_path / "break8_mpc.wav"
    make_break(source)
    project = load_project(source, "equal8")
    settings = ExportSettings(mode="equal8", bpm=120, bars=2, export_format=ExportFormat.MPC)

    with pytest.raises(ExportError, match="MPC format requires exactly"):
        export_project(project, tmp_path / "out_equal8_mpc", settings)


@pytest.mark.parametrize("export_format", list(ExportFormat))
def test_64_slice_maximum_applies_to_all_formats(export_format: ExportFormat):
    with pytest.raises(ExportError, match="maximum of 64 slices"):
        validate_export_contract(ExportSettings(export_format=export_format), 65)
