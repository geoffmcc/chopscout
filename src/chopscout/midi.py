from __future__ import annotations

from pathlib import Path

import mido


def seconds_to_ticks(seconds: float, bpm: float, ticks_per_beat: int = 960) -> int:
    return round(seconds * bpm * ticks_per_beat / 60.0)


def write_reconstruction(
    path: str | Path,
    markers: list[float],
    duration: float,
    bpm: float,
    starting_note: int = 36,
    straightened: bool = False,
    tempo_scale: float = 1.0,
) -> None:
    ticks_per_beat = 960
    midi = mido.MidiFile(type=1, ticks_per_beat=ticks_per_beat)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    export_bpm = bpm * tempo_scale
    track.append(mido.MetaMessage("track_name", name="ChopScout Reconstruction", time=0))
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(export_bpm), time=0))
    track.append(mido.MetaMessage("time_signature", numerator=4, denominator=4, time=0))
    events: list[tuple[int, mido.Message]] = []
    if straightened and len(markers) > 1:
        step = duration / len(markers)
        starts = [index * step for index in range(len(markers))]
    else:
        starts = markers
    for index, start in enumerate(starts):
        source_end = markers[index + 1] if index + 1 < len(markers) else duration
        note_length = max(0.02, source_end - markers[index])
        note = starting_note + index
        if note > 127:
            break
        tick = seconds_to_ticks(start, export_bpm, ticks_per_beat)
        end_tick = tick + max(1, seconds_to_ticks(note_length, export_bpm, ticks_per_beat))
        events.append((tick, mido.Message("note_on", channel=9, note=note, velocity=100, time=0)))
        events.append((end_tick, mido.Message("note_off", channel=9, note=note, velocity=0, time=0)))
    events.sort(key=lambda item: (item[0], item[1].type == "note_on"))
    previous = 0
    for tick, message in events:
        message.time = max(0, tick - previous)
        previous = tick
        track.append(message)
    track.append(mido.MetaMessage("end_of_track", time=0))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    midi.save(path)
