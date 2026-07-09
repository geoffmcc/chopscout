from __future__ import annotations

import csv
import json
import shutil
from dataclasses import asdict
from pathlib import Path

import numpy as np

from . import __version__
from .audio import apply_edge_fades, write_wav
from .midi import write_reconstruction
from .models import AnalysisResult, ExportSettings, deterministic_project_name
from .mpc import MpcCompatibilityError, create_mpc39_program, create_mpc39_project
from .slicing import slice_ranges


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


def render_reconstruction(data: np.ndarray, sample_rate: int, markers: list[float], duration: float) -> np.ndarray:
    parts = []
    for start, end in slice_ranges(markers, duration):
        parts.append(data[round(start * sample_rate): round(end * sample_rate)])
    return np.concatenate(parts, axis=0) if parts else np.empty((0, data.shape[1]), dtype=np.float32)


def export_package(
    source_path: str | Path,
    data: np.ndarray,
    sample_rate: int,
    analysis: AnalysisResult,
    markers: list[float],
    output_parent: str | Path,
    settings: ExportSettings,
) -> Path:
    name = deterministic_project_name(source_path, settings.bpm)
    root = Path(output_parent) / name
    if root.exists():
        if not settings.overwrite:
            raise ExportError(f"Output already exists: {root}")
        shutil.rmtree(root)
    paths = package_paths(root, settings.mode)
    for value in paths.values():
        value.mkdir(parents=True, exist_ok=True)
    source = Path(source_path)
    shutil.copy2(source, paths["source"] / source.name)
    prepared = data
    write_wav(paths["full_loop"] / f"{name}_prepared.wav", prepared, sample_rate)
    ranges = slice_ranges(markers, analysis.audio.duration)
    if len(ranges) > 64:
        raise ExportError("MPC Banks A-D support a maximum of 64 slices.")
    rows = []
    for index, (start, end) in enumerate(ranges):
        label = pad_name(index)
        filename = f"{label}.wav"
        segment = data[round(start * sample_rate): round(end * sample_rate)]
        segment = apply_edge_fades(segment, sample_rate, settings.short_fades_ms)
        write_wav(paths["chops"] / filename, segment, sample_rate)
        rows.append({
            "pad": label, "midi_note": settings.starting_note + index, "filename": filename,
            "start_seconds": round(start, 9), "end_seconds": round(end, 9),
            "duration_seconds": round(end - start, 9),
        })
    midi_specs = [
        ("original_groove.mid", False, 1.0), ("straightened.mid", True, 1.0),
        ("half_time.mid", False, 0.5), ("double_time.mid", False, 2.0),
    ]
    for filename, straight, scale in midi_specs:
        write_reconstruction(paths["midi"] / filename, markers, analysis.audio.duration, settings.bpm,
                             settings.starting_note, straight, scale)
    with (paths["metadata"] / "slice_map.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["pad", "midi_note", "filename", "start_seconds", "end_seconds", "duration_seconds"])
        writer.writeheader(); writer.writerows(rows)
    metadata = {
        "application": "ChopScout", "version": __version__, "source_filename": source.name,
        "source_sha256": analysis.audio.source_hash, "audio": asdict(analysis.audio),
        "analysis": {
            "detected_bpm": analysis.detected_bpm, "selected_bpm": settings.bpm,
            "tempo_confidence": analysis.tempo_confidence, "downbeat": analysis.downbeat,
            "downbeat_confidence": analysis.downbeat_confidence, "bars": settings.bars,
            "warnings": analysis.warnings,
        },
        "export": asdict(settings), "markers_seconds": markers, "slice_map": rows,
        "mpc_project_generated": False,
        "mpc_program_generated": False,
    }
    instructions = """CHOPSCOUT MPC IMPORT GUIDE

COMPLETE PROJECT
If mpc_project contains a project folder, copy that whole folder to SD or USB storage and open its XPJ on MPC One+ 3.9.0. The project contains the Bank A-D drum program and reconstructed sequence.

STANDALONE DRUM PROGRAM
If mpc_program contains a program folder, copy that whole folder to SD or USB storage. Browse to the XPM and load it. Keep the XPM beside its exactly matching ProgramName_[ProgramData] folder. Do not move the WAV files out of that folder.

Both proprietary outputs are generated from fixtures saved directly by an MPC One+ running MPC 3.9.0.31. Standard WAV and MIDI exports remain available as portable fallbacks.
"""
    (paths["metadata"] / "MPC_IMPORT_README.txt").write_text(instructions, encoding="utf-8")
    preview = render_reconstruction(data, sample_rate, markers, analysis.audio.duration)
    write_wav(paths["preview"] / "reconstructed_preview.wav", preview, sample_rate)

    mpc_project_generated = False
    mpc_program_generated = False
    mpc_project_error = ""
    mpc_program_error = ""
    if settings.create_mpc_project:
        if len(rows) in (16, 32, 48, 64):
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
        else:
            message = "MPC 3.9.0 XPJ/XPM export requires exactly 16, 32, 48, or 64 slices."
            mpc_project_error = message
            mpc_program_error = message

    metadata["mpc_project_generated"] = mpc_project_generated
    metadata["mpc_program_generated"] = mpc_program_generated
    metadata["proprietary_mpc_program_generated"] = mpc_project_generated or mpc_program_generated
    metadata["mpc_project_error"] = mpc_project_error
    metadata["mpc_program_error"] = mpc_program_error
    (paths["metadata"] / "chopscout.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    problems = validate_package(root)
    if problems:
        raise ExportError("Export verification failed: " + "; ".join(problems))
    return root


def validate_package(root: str | Path) -> list[str]:
    root = Path(root)
    problems: list[str] = []
    required = [root / "metadata" / "chopscout.json", root / "metadata" / "slice_map.csv",
                root / "metadata" / "MPC_IMPORT_README.txt", root / "midi" / "original_groove.mid"]
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
        project_generated = metadata.get("mpc_project_generated")
        program_generated = metadata.get("mpc_program_generated")
        if project_generated not in (True, False):
            problems.append("MPC project generation status is invalid.")
        if program_generated not in (True, False):
            problems.append("MPC program generation status is invalid.")
        if project_generated:
            projects = list((root / "mpc_project").glob("*/*.xpj"))
            if len(projects) != 1:
                problems.append("Generated MPC project XPJ is missing.")
        if program_generated:
            programs = list((root / "mpc_program").glob("*/*.xpm"))
            if len(programs) != 1:
                problems.append("Generated MPC drum-program XPM is missing.")
            else:
                companion = programs[0].parent / f"{programs[0].stem}_[ProgramData]"
                if not companion.is_dir():
                    problems.append("Generated MPC drum program is missing its matching [ProgramData] folder.")
    except (OSError, json.JSONDecodeError):
        problems.append("Metadata JSON is unreadable.")
    return problems
