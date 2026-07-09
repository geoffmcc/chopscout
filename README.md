# ChopScout 0.1.0

ChopScout is a local Windows utility for turning drum breaks and rhythmic loops into playable Akai MPC projects and drum programs.

## What 0.1.0 exports

For 16, 32, 48, or 64 slices, ChopScout creates:

- WAV slices named in MPC bank order (`A01.wav` through `D16.wav`)
- a complete MPC 3.9.0 XPJ project with an embedded drum program and sequence
- a standalone MPC 3.9.0 XPM drum program
- the required matching `_[ProjectData]` and `_[ProgramData]` folders
- standard MIDI groove files
- a prepared full loop, preview, slice map, metadata, and loading instructions

Pad mapping is deterministic:

- Bank A: notes 36–51
- Bank B: notes 52–67
- Bank C: notes 68–83
- Bank D: notes 84–99

Bank A has been hardware-validated on an MPC One+ running MPC 3.9.0. Banks B, C, and D are confirmed through hardware testing.

## Install and run on Windows

Install Python 3.11+ and `uv`, then open PowerShell in the project folder:

```powershell
uv sync --extra dev
uv run chopscout-gui
```

FFmpeg and ffprobe must be on PATH or placed under:

```text
tools\ffmpeg\bin\ffmpeg.exe
tools\ffmpeg\bin\ffprobe.exe
```

## CLI

```powershell
uv run chopscout analyze "break.wav"
uv run chopscout export "break.wav" --mode equal16 --output .\exports
uv run chopscout export "break.wav" --mode equal32 --output .\exports
uv run chopscout export "break.wav" --mode equal48 --output .\exports
uv run chopscout export "break.wav" --mode equal64 --output .\exports
uv run chopscout validate ".\exports\break_172"
```

## Standalone XPM layout

Keep the XPM beside its matching ProgramData folder:

```text
ProgramName.xpm
ProgramName_[ProgramData]\
    A01.wav
    ...
    D16.wav
```

Do not move the WAV files beside the XPM.

## Complete XPJ layout

```text
ProjectName\
    ProjectName.xpj
    ProjectName_[ProjectData]\
        A01.wav
        ...
        D16.wav
```

## Test and build

```powershell
uv run ruff check .
uv run pytest
uv run python scripts\build_windows.py
```

The Windows directory build is written under `dist\ChopScout-MPC\`.

## Safety

ChopScout never modifies the original audio or an existing MPC project by default. Generated MPC files are read back and structurally validated before the export is reported as successful.
