"""Malformed-package and corrupted-file tests for deep export validation."""

import json
from pathlib import Path

import mido
import numpy as np
import pytest
import soundfile as sf
from test_atomic_export import do_export

from chopscout.exporter import validate_package


@pytest.fixture()
def package(tmp_path: Path) -> Path:
    return do_export(tmp_path, tmp_path / "out")


def edit_metadata(package: Path, mutate) -> None:
    path = package / "metadata" / "chopscout.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    mutate(metadata)
    path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def has_problem(package: Path, fragment: str) -> bool:
    problems = validate_package(package)
    assert problems, "expected validation problems, got none"
    return any(fragment in problem for problem in problems)


def test_pristine_package_is_valid(package: Path):
    assert validate_package(package) == []


def test_corrupted_wav_slice_is_rejected(package: Path):
    (package / "chops_equal16" / "A01.wav").write_bytes(b"not a wav file")
    assert has_problem(package, "WAV file is unreadable: chops_equal16/A01.wav")


def test_wrong_sample_rate_slice_is_rejected(package: Path):
    data = np.zeros((800, 1), dtype=np.float32)
    sf.write(package / "chops_equal16" / "A01.wav", data, 8000)
    assert has_problem(package, "sample rate 8000 does not match metadata")


def test_truncated_wav_slice_is_rejected(package: Path):
    original = package / "chops_equal16" / "A02.wav"
    data, rate = sf.read(original, dtype="float32", always_2d=True)
    sf.write(original, data[: len(data) // 2], rate)
    assert has_problem(package, "does not match the slice map")


def test_truncated_full_loop_is_rejected(package: Path):
    full_loop = next((package / "full_loop").glob("*.wav"))
    data, rate = sf.read(full_loop, dtype="float32", always_2d=True)
    sf.write(full_loop, data[: len(data) // 2], rate)
    assert has_problem(package, "does not match metadata")


def test_corrupted_midi_is_rejected(package: Path):
    (package / "midi" / "half_time.mid").write_bytes(b"garbage bytes")
    assert has_problem(package, "MIDI file is unreadable: midi/half_time.mid")


def test_missing_midi_is_rejected(package: Path):
    (package / "midi" / "straightened.mid").unlink()
    assert has_problem(package, "Missing or empty required file: midi/straightened.mid")


def test_wrong_midi_tempo_is_rejected(package: Path):
    path = package / "midi" / "double_time.mid"
    midi = mido.MidiFile(path)
    for track in midi.tracks:
        for message in track:
            if message.type == "set_tempo":
                message.tempo = mido.bpm2tempo(99.0)
    midi.save(path)
    assert has_problem(package, "midi/double_time.mid: tempo")


def test_wrong_midi_notes_are_rejected(package: Path):
    path = package / "midi" / "original_groove.mid"
    midi = mido.MidiFile(path)
    for track in midi.tracks:
        for message in track:
            if message.type == "note_on" and message.velocity > 0:
                message.note = 127
    midi.save(path)
    assert has_problem(package, "midi/original_groove.mid: note sequence does not match")


def test_shifted_midi_timing_is_rejected(package: Path):
    path = package / "midi" / "original_groove.mid"
    midi = mido.MidiFile(path)
    track = midi.tracks[0]
    note_ons = [message for message in track if message.type == "note_on" and message.velocity > 0]
    note_ons[-1].time += 200
    midi.save(path)
    assert has_problem(package, "midi/original_groove.mid: note")


def test_unsafe_source_filename_is_rejected(package: Path):
    edit_metadata(package, lambda m: m.update(source_filename="../evil.wav"))
    assert has_problem(package, "source_filename is not a safe bare filename")


def test_missing_source_copy_is_rejected(package: Path):
    (package / "source" / "break.wav").unlink()
    assert has_problem(package, "Source copy is missing: source/break.wav")


def test_out_of_range_marker_is_rejected(package: Path):
    def mutate(metadata):
        metadata["markers_seconds"][0] = -0.5

    edit_metadata(package, mutate)
    assert has_problem(package, "outside the audio duration")


def test_unordered_markers_are_rejected(package: Path):
    def mutate(metadata):
        markers = metadata["markers_seconds"]
        markers[1], markers[2] = markers[2], markers[1]

    edit_metadata(package, mutate)
    assert has_problem(package, "not in ascending order")


def test_slice_map_json_csv_mismatch_is_rejected(package: Path):
    def mutate(metadata):
        metadata["slice_map"][0]["pad"] = "Z99"

    edit_metadata(package, mutate)
    assert has_problem(package, "Metadata slice_map does not match slice_map.csv")


def test_missing_preview_is_rejected(package: Path):
    (package / "preview" / "reconstructed_preview.wav").unlink()
    assert has_problem(package, "preview/reconstructed_preview.wav")


def write_metadata_raw(package: Path, content: str | bytes) -> None:
    path = package / "metadata" / "chopscout.json"
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def test_non_object_metadata_is_rejected(package: Path):
    write_metadata_raw(package, "[1, 2, 3]")
    assert has_problem(package, "Metadata JSON is not an object")


def test_non_utf8_metadata_is_rejected(package: Path):
    write_metadata_raw(package, b"\xff\xfe\x00broken")
    assert has_problem(package, "Metadata JSON is unreadable")


def test_nan_json_constant_is_rejected(package: Path):
    def mutate(metadata):
        metadata["markers_seconds"][0] = float("nan")

    edit_metadata(package, mutate)
    assert has_problem(package, "Metadata JSON is unreadable")


def test_wrong_typed_sections_are_rejected(package: Path):
    def mutate(metadata):
        metadata["export"] = "not a dict"
        metadata["markers_seconds"] = 5

    edit_metadata(package, mutate)
    problems = validate_package(package)
    assert any("Metadata export section is invalid" in item for item in problems)
    assert any("Metadata markers_seconds is invalid" in item for item in problems)


def test_huge_bpm_is_rejected(package: Path):
    edit_metadata(package, lambda m: m["export"].update(bpm=10**400))
    assert has_problem(package, "bpm is not a finite positive number")


def test_non_finite_csv_times_are_rejected(package: Path):
    path = package / "metadata" / "slice_map.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    start_index = header.index("start_seconds")
    fields = lines[1].split(",")
    fields[start_index] = "inf"
    lines[1] = ",".join(fields)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert has_problem(package, "non-finite start/end times")


def test_short_csv_row_is_rejected(package: Path):
    path = package / "metadata" / "slice_map.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-1].split(",")[0]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert has_problem(package, "Slice map MIDI notes are invalid")


def test_traversal_slice_filename_is_rejected(package: Path):
    path = package / "metadata" / "slice_map.csv"
    text = path.read_text(encoding="utf-8").replace("A01.wav", "../A01.wav")
    path.write_text(text, encoding="utf-8")
    assert has_problem(package, "not a safe bare filename")


def test_zero_tempo_midi_is_rejected(package: Path):
    path = package / "midi" / "original_groove.mid"
    midi = mido.MidiFile(path)
    for track in midi.tracks:
        for message in track:
            if message.type == "set_tempo":
                message.tempo = 0
    midi.save(path)
    assert has_problem(package, "tempo message is invalid")


def test_oversized_slice_map_is_rejected(package: Path):
    path = package / "metadata" / "slice_map.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0]] + [lines[1]] * 100) + "\n", encoding="utf-8")
    assert has_problem(package, "the maximum supported is 64")


def test_row_beyond_duration_is_rejected(package: Path):
    csv_path = package / "metadata" / "slice_map.csv"
    text = csv_path.read_text(encoding="utf-8")

    def mutate(metadata):
        metadata["audio"]["duration"] = 0.5

    edit_metadata(package, mutate)
    assert text  # slice map untouched; rows now exceed the shrunken duration
    assert has_problem(package, "ends beyond the audio duration")
