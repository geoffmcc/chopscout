# Architecture

## Overview

The GUI and CLI call the same application core. No audio or MPC logic lives in the presentation layer; both `cli.py` and `ui.py` delegate to shared modules.

## Module responsibilities

| Module | Responsibility |
|---|---|
| `audio.py` | FFmpeg/ffprobe discovery, audio decoding to float32 PCM, source hashing, mono mix, waveform peak reduction, WAV writing (24-bit PCM), edge fades |
| `analysis.py` | Deterministic DSP: onset envelope, transient detection, tempo estimation, beat grid, silence bounds, full analysis pipeline |
| `slicing.py` | Pure marker strategies: normalization, equal/grid/transient/hybrid/manual modes, marker snapping, slice range computation |
| `midi.py` | Standard MIDI File writing (Type 1, 960 PPQ) for groove reconstructions |
| `exporter.py` | Package assembly, metadata/slice-map generation, export contract validation, per-package structural verification |
| `mpc.py` | MPC 3.9.0 XPJ/XPM generation and validation from bundled ACVS fixtures; pad/note mapping; sample and instrument configuration |
| `validation.py` | Loop-duration validation with decoder-aware tolerance; warning formatting |
| `playback.py` | Playback context objects mapping media-player positions back to waveform positions and active slices |
| `session.py` | Session save/load with source-hash change detection |
| `config.py` | GUI configuration persistence via platformdirs |
| `logging_config.py` | File and console logging setup via platformdirs |
| `core.py` | Orchestration: `load_project`, `change_mode`, `export_project` |
| `models.py` | Dataclasses: `AudioInfo`, `AnalysisResult`, `ExportSettings`, `Session`, etc. |
| `cli.py` | Argparse CLI with `analyze`, `export`, and `validate` subcommands |
| `ui.py` | PySide6 main window, waveform widget, transport, workers |
| `app.py` | QApplication entry point with dark stylesheet |

## Bundled resources

`src/chopscout/resources/` contains two MPC 3.9.0 fixture files saved directly by an MPC One+:

- `mpc39_16pad_template.xpj` — project template with a 64-instrument drum program and an editable sequence
- `mpc39_16pad_template.xpm` — drum program template with a 64-instrument slot structure

These are gzip-compressed ACVS documents. `mpc.py` reads them, rewrites the instrument slots, sample table, pad-note map, and sequence events, then writes and round-trip validates the result.

## Concurrency

Heavy GUI work (audio loading and exporting) runs in `QThreadPool` workers via `QRunnable`. The UI stays responsive during analysis and export. Worker signals report success or failure back to the main thread.

## Determinism and safety

- Exports are deterministic for the same source, settings, and markers.
- The original source file is never modified; a copy is placed in the export's `source/` folder.
- Generated MPC XPJ/XPM files are read back and structurally validated before an export is reported as successful.
- The `validate` command re-checks any package on demand.
- Output folders are not overwritten unless `--overwrite` is passed.
