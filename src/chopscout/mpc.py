from __future__ import annotations

import copy
import gzip
import json
import math
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import soundfile as sf

PPQ = 960
SUPPORTED_PAD_COUNTS = (16, 32, 48, 64)
MAX_PADS = 64
XPM_HEADER_KIND = b"SerialisableProgramData"
XPJ_HEADER_KIND = b"SerialisableProjectData"


class MpcCompatibilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MpcProjectResult:
    project_dir: Path
    xpj_path: Path
    project_data_dir: Path


@dataclass(frozen=True, slots=True)
class MpcProgramResult:
    program_dir: Path
    xpm_path: Path
    program_data_dir: Path
    sample_paths: tuple[Path, ...]


def xpj_export_available() -> bool:
    return True


def xpm_export_available() -> bool:
    return True


def explain_xpm_status() -> str:
    return (
        "MPC 3.9.0 XPJ and XPM export supports 16, 32, 48, or 64 slices across "
        "Banks A-D. Bank A is hardware-verified; Banks B-C are supported by populated "
        "MPC fixtures; Bank D uses the same confirmed slot pattern and awaits final hardware confirmation."
    )


def pad_name(index: int) -> str:
    if not 0 <= index < MAX_PADS:
        raise ValueError("Pad index must be between 0 and 63.")
    return f"{chr(ord('A') + index // 16)}{index % 16 + 1:02d}"


def pad_note(index: int) -> int:
    return 36 + index


def _validate_pad_count(count: int) -> None:
    if count not in SUPPORTED_PAD_COUNTS:
        raise MpcCompatibilityError("MPC export requires exactly 16, 32, 48, or 64 slices.")


def _template_path() -> Path:
    return Path(str(files("chopscout").joinpath("resources/mpc39_16pad_template.xpj")))


def _xpm_template_path() -> Path:
    return Path(str(files("chopscout").joinpath("resources/mpc39_16pad_template.xpm")))


def _read_acvs(path: str | Path, kind: bytes) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = gzip.decompress(Path(path).read_bytes())
    except (OSError, gzip.BadGzipFile) as exc:
        raise MpcCompatibilityError(f"Could not decompress MPC file: {exc}") from exc
    marker = b"Linux\n"
    if marker not in raw or kind not in raw.split(marker, 1)[0]:
        raise MpcCompatibilityError("MPC file header is not a supported MPC 3.9.0 JSON document.")
    prefix, payload = raw.split(marker, 1)
    try:
        document = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise MpcCompatibilityError(f"MPC JSON is invalid: {exc}") from exc
    return prefix + marker, document


def _write_acvs(path: str | Path, header: bytes, document: dict[str, Any], kind: bytes) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=0, separators=(",", ": "), ensure_ascii=False).encode("utf-8")
    with destination.open("wb") as handle:
        with gzip.GzipFile(filename=destination.name, mode="wb", fileobj=handle, mtime=0, compresslevel=9) as gz:
            gz.write(header + payload)
    check_header, check_doc = _read_acvs(destination, kind)
    if check_header != header or check_doc != document:
        raise MpcCompatibilityError("Generated MPC file failed its structural round-trip check.")
    return destination


def read_xpj(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    return _read_acvs(path, XPJ_HEADER_KIND)


def write_xpj(path: str | Path, header: bytes, document: dict[str, Any]) -> Path:
    return _write_acvs(path, header, document, XPJ_HEADER_KIND)


def read_xpm(path: str | Path) -> tuple[bytes, dict[str, Any]]:
    header, document = _read_acvs(path, XPM_HEADER_KIND)
    data = document.get("data")
    if not isinstance(data, dict) or data.get("type") != 0:
        raise MpcCompatibilityError("XPM is not a supported drum program.")
    return header, document


def write_xpm(path: str | Path, header: bytes, document: dict[str, Any]) -> Path:
    return _write_acvs(path, header, document, XPM_HEADER_KIND)


def _safe_mpc_name(value: str, fallback: str) -> str:
    result = "".join(char if char.isalnum() or char in " -_" else "_" for char in value).strip()
    return result or fallback


def _sequence(document: dict[str, Any]) -> dict[str, Any]:
    try:
        return document["data"]["sequences"][0]["value"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MpcCompatibilityError("Bundled XPJ fixture has no editable sequence.") from exc


def _drum_clip(sequence: dict[str, Any]) -> dict[str, Any]:
    try:
        return sequence["trackClipMaps"][0][0]["value"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MpcCompatibilityError("Bundled XPJ fixture has no editable drum clip.") from exc


def seconds_to_pulses(seconds: float, bpm: float) -> int:
    return max(0, round(seconds * bpm * PPQ / 60.0))


def _sample_descriptors(sample_paths: Sequence[str | Path]) -> list[tuple[Path, str, int]]:
    _validate_pad_count(len(sample_paths))
    result: list[tuple[Path, str, int]] = []
    for index, item in enumerate(sample_paths):
        source = Path(item)
        if not source.is_file():
            raise MpcCompatibilityError(f"Missing MPC slice: {source}")
        try:
            frames = int(sf.info(source).frames)
        except Exception as exc:
            raise MpcCompatibilityError(f"Could not inspect {source.name}: {exc}") from exc
        result.append((source, pad_name(index), frames))
    return result


def _configure_program(program: dict[str, Any], descriptors: list[tuple[Path, str, int]], bpm: float, name: str) -> None:
    program["name"] = name
    instruments = program.get("drum", {}).get("instruments")
    if not isinstance(instruments, list) or len(instruments) < MAX_PADS:
        raise MpcCompatibilityError("MPC fixture does not contain at least 64 instrument slots.")

    # Configure used pads and clear unused pads in A-D without disturbing banks beyond D.
    for index in range(MAX_PADS):
        instrument = instruments[index]
        layers = instrument.get("layersv")
        if not isinstance(layers, list) or not layers:
            raise MpcCompatibilityError(f"MPC fixture instrument slot {index} has no layer structure.")
        instrument["tempo"] = float(bpm)
        for layer_index, layer in enumerate(layers):
            if index < len(descriptors) and layer_index == 0:
                _, stem, frames = descriptors[index]
                layer["active"] = True
                layer["sampleName"] = stem
                layer["sampleFile"] = f"{stem}.wav"
                layer["sampleStart"] = 0
                layer["sampleEnd"] = 0
                layer["loop"] = False
                layer["loopStart"] = 0
                layer["loopEnd"] = 0
                info = layer.setdefault("sliceInfo", {})
                info["Start"] = 0
                info["End"] = frames
                info["LoopStart"] = 0
            else:
                layer["active"] = False
                layer["sampleName"] = ""
                layer["sampleFile"] = ""
                info = layer.setdefault("sliceInfo", {})
                info["Start"] = 0
                info["End"] = 0
                info["LoopStart"] = 0

    note_map = program.get("padNoteMap", {}).get("noteForPad")
    if not isinstance(note_map, dict):
        raise MpcCompatibilityError("MPC fixture has no pad-note map.")
    for index in range(MAX_PADS):
        note_map[f"value{index}"] = pad_note(index)

    original_samples = program.get("samples")
    if not isinstance(original_samples, list) or not original_samples:
        raise MpcCompatibilityError("MPC fixture has no sample table.")
    prototypes = {str(item.get("name", "")): item for item in original_samples}
    default = original_samples[0]
    rebuilt: list[dict[str, Any]] = []
    for _, stem, _frames in descriptors:
        item = copy.deepcopy(prototypes.get(stem, default))
        item["name"] = stem
        item["path"] = f"{stem}.wav"
        item.setdefault("metadata", {})["tempo"] = float(bpm)
        rebuilt.append(item)
    program["samples"] = rebuilt


def create_mpc39_program(
    *,
    program_name: str,
    sample_paths: Sequence[str | Path],
    output_parent: str | Path,
    bpm: float,
    overwrite: bool = False,
) -> MpcProgramResult:
    descriptors = _sample_descriptors(sample_paths)
    if bpm <= 0 or not math.isfinite(bpm):
        raise MpcCompatibilityError("BPM must be a positive finite number.")

    safe_name = _safe_mpc_name(program_name, "ChopScout Program")
    program_dir = Path(output_parent) / safe_name
    if program_dir.exists():
        if not overwrite:
            raise MpcCompatibilityError(f"MPC program folder already exists: {program_dir}")
        shutil.rmtree(program_dir)
    program_dir.mkdir(parents=True)
    program_data_dir = program_dir / f"{safe_name}_[ProgramData]"
    program_data_dir.mkdir()

    copied: list[Path] = []
    for source, stem, _frames in descriptors:
        destination = program_data_dir / f"{stem}.wav"
        shutil.copy2(source, destination)
        copied.append(destination)

    header, document = read_xpm(_xpm_template_path())
    _configure_program(document["data"], descriptors, bpm, safe_name)
    xpm_path = write_xpm(program_dir / f"{safe_name}.xpm", header, document)
    validate_generated_mpc_program(program_dir, expected_count=len(descriptors))
    return MpcProgramResult(program_dir, xpm_path, program_data_dir, tuple(copied))


def create_mpc39_project(
    *,
    project_name: str,
    sample_paths: Sequence[str | Path],
    output_parent: str | Path,
    bpm: float,
    bars: int,
    event_times_seconds: Sequence[float],
    sequence_name: str = "ChopScout Groove",
    overwrite: bool = False,
) -> MpcProjectResult:
    descriptors = _sample_descriptors(sample_paths)
    if len(event_times_seconds) != len(descriptors):
        raise MpcCompatibilityError("Sequence-event count must match the slice count.")
    if bpm <= 0 or not math.isfinite(bpm):
        raise MpcCompatibilityError("BPM must be a positive finite number.")
    if bars < 1 or bars > 999:
        raise MpcCompatibilityError("Bar count must be between 1 and 999.")

    safe_name = _safe_mpc_name(project_name, "ChopScout Project")
    project_dir = Path(output_parent) / safe_name
    if project_dir.exists():
        if not overwrite:
            raise MpcCompatibilityError(f"MPC project folder already exists: {project_dir}")
        shutil.rmtree(project_dir)
    project_data_dir = project_dir / f"{safe_name}_[ProjectData]"
    project_data_dir.mkdir(parents=True)
    for source, stem, _frames in descriptors:
        shutil.copy2(source, project_data_dir / f"{stem}.wav")

    header, document = read_xpj(_template_path())
    root = document["data"]
    root["masterTempo"] = float(bpm)
    root["info"]["title"] = safe_name
    root["info"]["notes"] = "Generated by ChopScout from an MPC One+ 3.9.0 fixture."

    track = root["tracks"][0]
    track["name"] = "ChopScout Drum Program"
    program = track["program"]
    _configure_program(program, descriptors, bpm, "ChopScout Drum Program")
    # Project-level sample table mirrors the embedded program table.
    root["samples"] = copy.deepcopy(program["samples"])

    sequence = _sequence(document)
    total_pulses = bars * 4 * PPQ
    sequence.update({
        "name": sequence_name,
        "bpm": float(bpm),
        "lengthBars": bars,
        "loopStartBar": 0,
        "loopEndBar": bars,
        "loop": True,
        "tempoEnable": True,
        "lengthPulses": total_pulses,
        "loopStartPulses": 0,
        "loopEndPulses": total_pulses,
    })
    clip = _drum_clip(sequence)
    clip.update({
        "startPulses": 0,
        "endPulses": total_pulses,
        "loopStartPulses": 0,
        "loopEndPulses": total_pulses,
        "loop": True,
        "name": "ChopScout Drum Program",
    })
    original_events = [event for event in clip["eventList"]["events"] if "note" in event]
    if not original_events:
        raise MpcCompatibilityError("Bundled XPJ fixture has no note-event template.")
    prototype = original_events[0]
    generated_events: list[dict[str, Any]] = []
    for index, seconds in enumerate(event_times_seconds):
        event = copy.deepcopy(original_events[index] if index < len(original_events) else prototype)
        event["time"] = min(seconds_to_pulses(float(seconds), bpm), max(0, total_pulses - 1))
        event["note"]["note"] = pad_note(index)
        event["note"]["velocity"] = 1.0
        event["note"]["length"] = max(1, PPQ // 8)
        event["selected"] = False
        event["muted"] = False
        event["invented"] = False
        generated_events.append(event)
    generated_events.sort(key=lambda event: (event["time"], event["note"]["note"]))
    clip["eventList"]["events"] = generated_events
    clip["eventList"]["length"] = total_pulses

    xpj_path = write_xpj(project_dir / f"{safe_name}.xpj", header, document)
    validate_generated_mpc_project(project_dir, expected_count=len(descriptors))
    return MpcProjectResult(project_dir, xpj_path, project_data_dir)


def validate_generated_mpc_program(program_dir: str | Path, expected_count: int | None = None) -> None:
    root = Path(program_dir)
    xpm_files = list(root.glob("*.xpm"))
    if len(xpm_files) != 1:
        raise MpcCompatibilityError("Generated MPC program must contain exactly one XPM.")
    _, document = read_xpm(xpm_files[0])
    data = document["data"]
    count = expected_count or len(data.get("samples", []))
    _validate_pad_count(count)
    expected = [f"{pad_name(i)}.wav" for i in range(count)]
    actual = [item.get("path") for item in data.get("samples", [])]
    if actual != expected:
        raise MpcCompatibilityError("Generated XPM sample table is not in Bank A-D pad order.")
    program_data = root / f"{xpm_files[0].stem}_[ProgramData]"
    if not program_data.is_dir():
        raise MpcCompatibilityError("Generated XPM is missing its matching [ProgramData] folder.")
    instruments = data["drum"]["instruments"]
    for index, filename in enumerate(expected):
        if instruments[index]["layersv"][0].get("sampleFile") != filename:
            raise MpcCompatibilityError(f"Generated XPM pad {pad_name(index)} does not reference {filename}.")
        if not (program_data / filename).is_file():
            raise MpcCompatibilityError(f"Generated XPM dependency is missing: {filename}")
    note_map = data["padNoteMap"]["noteForPad"]
    notes = [note_map[f"value{i}"] for i in range(count)]
    if notes != list(range(36, 36 + count)):
        raise MpcCompatibilityError("Generated XPM pad-note map is not sequential from note 36.")


def validate_generated_mpc_project(project_dir: str | Path, expected_count: int | None = None) -> None:
    root = Path(project_dir)
    xpj_files = list(root.glob("*.xpj"))
    if len(xpj_files) != 1:
        raise MpcCompatibilityError("Generated MPC project must contain exactly one XPJ.")
    _, document = read_xpj(xpj_files[0])
    sequence = _sequence(document)
    clip = _drum_clip(sequence)
    events = [event for event in clip["eventList"]["events"] if "note" in event]
    count = expected_count or len(events)
    _validate_pad_count(count)
    if len(events) != count:
        raise MpcCompatibilityError(f"Generated MPC project contains {len(events)} events, expected {count}.")
    if sorted(event["note"]["note"] for event in events) != list(range(36, 36 + count)):
        raise MpcCompatibilityError("Generated MPC project notes are not sequential from note 36.")
    data_dir = root / f"{xpj_files[0].stem}_[ProjectData]"
    if not data_dir.is_dir():
        raise MpcCompatibilityError("Generated XPJ is missing its matching [ProjectData] folder.")
    for index in range(count):
        if not (data_dir / f"{pad_name(index)}.wav").is_file():
            raise MpcCompatibilityError(f"Generated XPJ dependency is missing: {pad_name(index)}.wav")
