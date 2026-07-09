from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from .core import export_project, load_project
from .exporter import validate_package
from .models import ExportFormat, ExportSettings


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="chopscout", description="Prepare breaks for standalone MPC workflows."
    )
    sub = root.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze", help="Analyze an audio file")
    analyze.add_argument("input")
    export = sub.add_parser(
        "export",
        help="Analyze and export WAV/MIDI and, for 16, 32, 48, or 64 slices, MPC 3.9.0 projects/programs",
    )
    export.add_argument("input")
    export.add_argument(
        "--mode",
        default="transient",
        choices=[
            "transient",
            "equal8",
            "equal16",
            "equal32",
            "equal48",
            "equal64",
            "beat",
            "eighth",
            "sixteenth",
            "hybrid",
            "manual",
        ],
    )
    export.add_argument("--output", default="./exports")
    export.add_argument("--bpm", type=float)
    export.add_argument("--bars", type=int)
    export.add_argument("--starting-note", type=int, default=36)
    export.add_argument("--pad-count", type=int, choices=[16, 32, 48, 64])
    export.add_argument(
        "--format",
        choices=[item.value for item in ExportFormat],
        default=ExportFormat.BOTH.value,
        help="Export target: both portable files and MPC artifacts when compatible, MPC-oriented package, or portable files only",
    )
    export.add_argument("--overwrite", action="store_true")
    validate = sub.add_parser("validate", help="Validate an exported package")
    validate.add_argument("package")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "validate":
            problems = validate_package(args.package)
            if problems:
                for problem in problems:
                    print(f"ERROR: {problem}")
                return 1
            print("Package is valid.")
            return 0
        project = load_project(args.input, getattr(args, "mode", "transient"))
        if args.command == "analyze":
            result = project.analysis
            print(
                json.dumps(
                    {
                        "audio": asdict(result.audio),
                        "detected_bpm": result.detected_bpm,
                        "half_time_bpm": result.half_time_bpm,
                        "double_time_bpm": result.double_time_bpm,
                        "tempo_confidence": result.tempo_confidence,
                        "downbeat": result.downbeat,
                        "estimated_bars": result.estimated_bars,
                        "transients": len(result.onset_times),
                        "warnings": result.warnings,
                    },
                    indent=2,
                )
            )
            return 0
        if args.bpm:
            project.analysis.selected_bpm = args.bpm
        settings = ExportSettings(
            mode=args.mode,
            starting_note=args.starting_note,
            bars=args.bars or project.analysis.estimated_bars,
            bpm=args.bpm or project.analysis.selected_bpm,
            overwrite=args.overwrite,
            export_format=ExportFormat(args.format),
            pad_count=args.pad_count,
        )
        path = export_project(project, args.output, settings)
        print(path)
        return 0
    except Exception as exc:
        print(f"chopscout: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
