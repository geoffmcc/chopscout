from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import mido
import numpy as np

from . import __version__
from .audio import apply_edge_fades, write_wav
from .midi import write_reconstruction
from .models import AnalysisResult, ExportFormat, ExportSettings, deterministic_project_name
from .mpc import (
    MpcCompatibilityError,
    create_mpc39_program,
    create_mpc39_project,
    validate_generated_mpc_program,
    validate_generated_mpc_project,
)
from .slicing import slice_ranges

MPC_STARTING_NOTE = 36
SUPPORTED_MPC_SLICE_COUNTS = (16, 32, 48, 64)


class ExportError(RuntimeError):
    pass


def pad_name(index: int) -> str:
    bank = chr(ord("A") + index // 16)
    pad = index % 16 + 1
    return f"{bank}{pad:02d}"


def package_paths(root: Path, mode: str) -> dict[str, Path]:
    return {
        "source": root / "source",
        "full_loop": root / "full_loop",
        "chops": root / f"chops_{mode}",
        "midi": root / "midi",
        "metadata": root / "metadata",
        "preview": root / "preview",
        "mpc_project": root / "mpc_project",
        "mpc_program": root / "mpc_program",
    }


def validate_export_contract(settings: ExportSettings, slice_count: int) -> None:
    try:
        export_format = ExportFormat(settings.export_format)
    except ValueError as exc:
        raise ExportError(f"Unknown export format: {settings.export_format}") from exc
    if slice_count < 1:
        raise ExportError("Export requires at least one slice.")
    if slice_count > 64:
        raise ExportError("MPC Banks A-D support a maximum of 64 slices.")
    if export_format is ExportFormat.MPC and slice_count not in SUPPORTED_MPC_SLICE_COUNTS:
        raise ExportError("MPC format requires exactly 16, 32, 48, or 64 slices.")
    if not 0 <= settings.starting_note <= 127:
        raise ExportError("Starting MIDI note must be between 0 and 127.")
    if settings.starting_note + slice_count - 1 > 127:
        raise ExportError("Starting MIDI note plus slice count exceeds MIDI note 127.")
    if settings.pad_count is not None:
        if settings.pad_count not in SUPPORTED_MPC_SLICE_COUNTS:
            raise ExportError("MPC layout must be 16, 32, 48, or 64 pads.")
        if settings.pad_count != slice_count:
            raise ExportError(
                f"Selected MPC layout requires {settings.pad_count} slices, "
                f"but the active markers produce {slice_count}."
            )
    if (
        settings.generates_mpc
        and slice_count in SUPPORTED_MPC_SLICE_COUNTS
        and settings.starting_note != MPC_STARTING_NOTE
    ):
        raise ExportError(
            "MPC XPJ/XPM export uses fixed drum notes 36-99. "
            "Use starting_note=36 for MPC export, or use portable format."
        )


def export_settings_dict(settings: ExportSettings) -> dict:
    data = asdict(settings)
    data["export_format"] = ExportFormat(settings.export_format).value
    return data


def render_reconstruction(
    data: np.ndarray, sample_rate: int, markers: list[float], duration: float
) -> np.ndarray:
    parts = []
    for start, end in slice_ranges(markers, duration):
        parts.append(data[round(start * sample_rate) : round(end * sample_rate)])
    return (
        np.concatenate(parts, axis=0) if parts else np.empty((0, data.shape[1]), dtype=np.float32)
    )


def export_package(
    source_path: str | Path,
    data: np.ndarray,
    sample_rate: int,
    analysis: AnalysisResult,
    markers: list[float],
    output_parent: str | Path,
    settings: ExportSettings,
) -> Path:
    ranges = slice_ranges(markers, analysis.audio.duration)
    validate_export_contract(settings, len(ranges))
    export_format = ExportFormat(settings.export_format)
    name = deterministic_project_name(source_path, settings.bpm)
    root = Path(output_parent) / name
    if root.exists():
        if not settings.overwrite:
            raise ExportError(f"Output already exists: {root}")
        shutil.rmtree(root)
    paths = package_paths(root, settings.mode)
    for key, value in paths.items():
        if export_format is ExportFormat.PORTABLE and key in {"mpc_project", "mpc_program"}:
            continue
        value.mkdir(parents=True, exist_ok=True)
    source = Path(source_path)
    shutil.copy2(source, paths["source"] / source.name)
    prepared = data
    write_wav(paths["full_loop"] / f"{name}_prepared.wav", prepared, sample_rate)
    rows = []
    for index, (start, end) in enumerate(ranges):
        label = pad_name(index)
        filename = f"{label}.wav"
        segment = data[round(start * sample_rate) : round(end * sample_rate)]
        segment = apply_edge_fades(segment, sample_rate, settings.short_fades_ms)
        write_wav(paths["chops"] / filename, segment, sample_rate)
        rows.append(
            {
                "pad": label,
                "midi_note": settings.starting_note + index,
                "filename": filename,
                "start_seconds": round(start, 9),
                "end_seconds": round(end, 9),
                "duration_seconds": round(end - start, 9),
            }
        )
    midi_specs = [
        ("original_groove.mid", False, 1.0),
        ("straightened.mid", True, 1.0),
        ("half_time.mid", False, 0.5),
        ("double_time.mid", False, 2.0),
    ]
    for filename, straight, scale in midi_specs:
        write_reconstruction(
            paths["midi"] / filename,
            markers,
            analysis.audio.duration,
            settings.bpm,
            settings.starting_note,
            straight,
            scale,
        )
    with (paths["metadata"] / "slice_map.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0].keys())
            if rows
            else [
                "pad",
                "midi_note",
                "filename",
                "start_seconds",
                "end_seconds",
                "duration_seconds",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "application": "ChopScout",
        "version": __version__,
        "source_filename": source.name,
        "source_sha256": analysis.audio.source_hash,
        "audio": asdict(analysis.audio),
        "analysis": {
            "detected_bpm": analysis.detected_bpm,
            "selected_bpm": settings.bpm,
            "tempo_confidence": analysis.tempo_confidence,
            "downbeat": analysis.downbeat,
            "downbeat_confidence": analysis.downbeat_confidence,
            "bars": settings.bars,
            "warnings": analysis.warnings,
        },
        "export": export_settings_dict(settings),
        "markers_seconds": markers,
        "slice_map": rows,
        "mpc_project_generated": False,
        "mpc_program_generated": False,
    }
    if export_format is ExportFormat.PORTABLE:
        instructions = """CHOPSCOUT PORTABLE IMPORT GUIDE

This package contains sampler-agnostic WAV slices, MIDI reconstruction files, metadata, and a rendered preview.

Load the WAV slices from the chops folder into your sampler or DAW, then use the MIDI files as reconstruction grooves. The slice_map.csv and chopscout.json metadata files describe pad names, MIDI notes, source timings, and export settings.
"""
        instructions_path = paths["metadata"] / "PORTABLE_IMPORT_README.txt"
    else:
        instructions = """CHOPSCOUT MPC IMPORT GUIDE

COMPLETE PROJECT
If mpc_project contains a project folder, copy that whole folder to SD or USB storage and open its XPJ on MPC One+ 3.9.0. The project contains the Bank A-D drum program and reconstructed sequence.

STANDALONE DRUM PROGRAM
If mpc_program contains a program folder, copy that whole folder to SD or USB storage. Browse to the XPM and load it. Keep the XPM beside its exactly matching ProgramName_[ProgramData] folder. Do not move the WAV files out of that folder.

Both proprietary outputs are generated from fixtures saved directly by an MPC One+ running MPC 3.9.0.31. Standard WAV and MIDI exports remain available as portable fallbacks.
"""
        instructions_path = paths["metadata"] / "MPC_IMPORT_README.txt"
    instructions_path.write_text(instructions, encoding="utf-8")
    preview = render_reconstruction(data, sample_rate, markers, analysis.audio.duration)
    write_wav(paths["preview"] / "reconstructed_preview.wav", preview, sample_rate)

    mpc_project_generated = False
    mpc_program_generated = False
    mpc_project_error = ""
    mpc_program_error = ""
    if settings.generates_mpc:
        if len(rows) in SUPPORTED_MPC_SLICE_COUNTS:
            sample_paths = [paths["chops"] / row["filename"] for row in rows]
            event_times = [float(row["start_seconds"]) for row in rows]
            try:
                create_mpc39_project(
                    project_name=name,
                    sample_paths=sample_paths,
                    output_parent=paths["mpc_project"],
                    bpm=settings.bpm,
                    bars=settings.bars,
                    event_times_seconds=event_times,
                    sequence_name=f"{name} Groove",
                    overwrite=True,
                )
                mpc_project_generated = True
            except MpcCompatibilityError as exc:
                mpc_project_error = str(exc)
            try:
                create_mpc39_program(
                    program_name=f"{name} Program",
                    sample_paths=sample_paths,
                    output_parent=paths["mpc_program"],
                    bpm=settings.bpm,
                    overwrite=True,
                )
                mpc_program_generated = True
            except MpcCompatibilityError as exc:
                mpc_program_error = str(exc)
            if export_format is ExportFormat.MPC and not (
                mpc_project_generated and mpc_program_generated
            ):
                raise ExportError(
                    "MPC format requires generated XPJ and XPM artifacts. "
                    f"Project error: {mpc_project_error or 'none'}; Program error: {mpc_program_error or 'none'}"
                )
        else:
            message = "MPC 3.9.0 XPJ/XPM export requires exactly 16, 32, 48, or 64 slices."
            mpc_project_error = message
            mpc_program_error = message

    metadata["mpc_project_generated"] = mpc_project_generated
    metadata["mpc_program_generated"] = mpc_program_generated
    metadata["proprietary_mpc_program_generated"] = mpc_project_generated or mpc_program_generated
    metadata["mpc_project_error"] = mpc_project_error
    metadata["mpc_program_error"] = mpc_program_error
    (paths["metadata"] / "chopscout.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    problems = validate_package(root)
    if problems:
        raise ExportError("Export verification failed: " + "; ".join(problems))
    return root


def validate_package(root: str | Path) -> list[str]:
    root = Path(root)
    problems: list[str] = []
    required = [
        root / "metadata" / "chopscout.json",
        root / "metadata" / "slice_map.csv",
        root / "midi" / "original_groove.mid",
    ]
    for path in required:
        if not path.is_file() or path.stat().st_size == 0:
            problems.append(f"Missing or empty required file: {path.relative_to(root)}")
    chop_dirs = list(root.glob("chops_*"))
    if len(chop_dirs) != 1:
        problems.append("Expected exactly one chop folder.")
    elif not list(chop_dirs[0].glob("*.wav")):
        problems.append("No WAV slices were exported.")
    try:
        metadata = json.loads((root / "metadata" / "chopscout.json").read_text(encoding="utf-8"))
        rows = list(
            csv.DictReader((root / "metadata" / "slice_map.csv").open(newline="", encoding="utf-8"))
        )
        export_settings = metadata.get("export", {})
        try:
            export_format = ExportFormat(
                export_settings.get("export_format", ExportFormat.BOTH.value)
            )
        except ValueError:
            problems.append("Metadata export_format is invalid.")
            export_format = None
        if export_format is ExportFormat.PORTABLE:
            required_readme = root / "metadata" / "PORTABLE_IMPORT_README.txt"
        else:
            required_readme = root / "metadata" / "MPC_IMPORT_README.txt"
        if not required_readme.is_file() or required_readme.stat().st_size == 0:
            problems.append(f"Missing or empty required file: {required_readme.relative_to(root)}")
        marker_count = len(metadata.get("markers_seconds", []))
        if rows and marker_count and len(rows) != marker_count:
            problems.append("Metadata marker count does not match slice map row count.")
        if chop_dirs:
            wav_count = len(list(chop_dirs[0].glob("*.wav")))
            if rows and wav_count != len(rows):
                problems.append("Exported WAV slice count does not match slice map row count.")
        pad_count = export_settings.get("pad_count")
        if pad_count is not None and rows:
            try:
                parsed_pad_count = int(pad_count)
            except (TypeError, ValueError):
                problems.append("Metadata pad_count is not an integer.")
                parsed_pad_count = None
            if parsed_pad_count is not None and parsed_pad_count != len(rows):
                problems.append("Metadata pad_count does not match slice map row count.")
        expected_pads = [pad_name(index) for index in range(len(rows))]
        actual_pads = [row.get("pad") for row in rows]
        if rows and actual_pads != expected_pads:
            problems.append("Slice map pads are not in Bank A-D order.")
        expected_filenames = [f"{pad}.wav" for pad in expected_pads]
        actual_filenames = [row.get("filename") for row in rows]
        if rows and actual_filenames != expected_filenames:
            problems.append("Slice map filenames are not in Bank A-D pad order.")
        if rows:
            try:
                expected_notes = [int(row["midi_note"]) for row in rows]
            except (KeyError, ValueError):
                problems.append("Slice map MIDI notes are invalid.")
                expected_notes = []
            try:
                midi_notes = _midi_note_ons(root / "midi" / "original_groove.mid")
            except Exception as exc:
                problems.append(f"Original-groove MIDI is unreadable: {exc}")
                midi_notes = []
            if midi_notes and expected_notes and midi_notes != expected_notes:
                problems.append("Original-groove MIDI notes do not match slice map MIDI notes.")
        project_generated = metadata.get("mpc_project_generated")
        program_generated = metadata.get("mpc_program_generated")
        projects = list((root / "mpc_project").glob("*/*.xpj"))
        programs = list((root / "mpc_program").glob("*/*.xpm"))
        if project_generated not in (True, False):
            problems.append("MPC project generation status is invalid.")
        if program_generated not in (True, False):
            problems.append("MPC program generation status is invalid.")
        if export_format is ExportFormat.MPC and not (project_generated and program_generated):
            problems.append("MPC format requires generated XPJ and XPM artifacts.")
        if (
            export_format is ExportFormat.BOTH
            and rows
            and len(rows) in SUPPORTED_MPC_SLICE_COUNTS
            and export_settings.get("starting_note") == MPC_STARTING_NOTE
            and not (project_generated and program_generated)
        ):
            problems.append("Both format requires MPC artifacts for MPC-compatible exports.")
        if export_format is ExportFormat.PORTABLE:
            if project_generated or program_generated:
                problems.append("Portable format must not report generated MPC artifacts.")
            if projects or programs:
                problems.append("Portable format must not contain XPJ or XPM artifacts.")
        if project_generated:
            if len(projects) != 1:
                problems.append("Generated MPC project XPJ is missing.")
            else:
                try:
                    validate_generated_mpc_project(projects[0].parent, expected_count=len(rows))
                except MpcCompatibilityError as exc:
                    problems.append(str(exc))
                if export_settings.get("starting_note") != MPC_STARTING_NOTE:
                    problems.append(
                        "MPC project was generated with non-fixed MIDI starting note metadata."
                    )
        if program_generated:
            if len(programs) != 1:
                problems.append("Generated MPC drum-program XPM is missing.")
            else:
                companion = programs[0].parent / f"{programs[0].stem}_[ProgramData]"
                if not companion.is_dir():
                    problems.append(
                        "Generated MPC drum program is missing its matching [ProgramData] folder."
                    )
                try:
                    validate_generated_mpc_program(programs[0].parent, expected_count=len(rows))
                except MpcCompatibilityError as exc:
                    problems.append(str(exc))
                if export_settings.get("starting_note") != MPC_STARTING_NOTE:
                    problems.append(
                        "MPC program was generated with non-fixed MIDI starting note metadata."
                    )
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        log_detail = f": {exc}" if str(exc) else ""
        problems.append(f"Metadata JSON is unreadable{log_detail}.")
    return problems


def _midi_note_ons(path: Path) -> list[int]:
    midi = mido.MidiFile(path)
    return [
        message.note
        for track in midi.tracks
        for message in track
        if message.type == "note_on" and message.velocity > 0
    ]
