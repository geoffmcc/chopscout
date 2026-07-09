from pathlib import Path

import mido

from chopscout.midi import seconds_to_ticks, write_reconstruction


def test_seconds_to_ticks():
    assert seconds_to_ticks(0.5, 120, 960) == 960


def test_midi_notes(tmp_path: Path):
    path = tmp_path / "test.mid"
    write_reconstruction(path, [0.0, 0.5, 1.0], 1.5, 120, 36)
    midi = mido.MidiFile(path)
    notes = [m.note for track in midi.tracks for m in track if m.type == "note_on"]
    assert notes == [36, 37, 38]
