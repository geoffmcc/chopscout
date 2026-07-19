# ChopScout 0.1.0

ChopScout is a local Windows utility for turning drum breaks and rhythmic loops into playable Akai MPC projects and standalone drum programs. It analyzes an audio file, slices it across MPC Banks A-D, and exports a complete, validated package with WAV slices, Standard MIDI Files, metadata, and MPC 3.9.0 XPJ/XPM artifacts.

All processing happens offline. ChopScout never modifies the original source file and performs no network requests.

## Highlights

- 16, 32, 48, and 64-slice MPC exports across Banks A-D
- Deterministic pad naming in MPC bank order (`A01.wav` through `D16.wav`)
- Complete MPC 3.9.0 XPJ project with embedded drum program and reconstructed sequence
- Standalone MPC 3.9.0 XPM drum program with its required `_[ProgramData]` folder
- Standard MIDI Files: original groove, straightened, half-time, and double-time
- Portable, sampler-agnostic export with custom MIDI starting note
- Per-export structural validation of generated MPC artifacts
- GUI and CLI share the same analysis and export core

## Requirements

- Windows 10 or 11
- Python 3.11, 3.12, or 3.13
- [`uv`](https://docs.astral.sh/uv/) (recommended) or pip
- FFmpeg and ffprobe (see [FFmpeg](#ffmpeg) below)

## Install and run

Install `uv`, then open PowerShell in the project folder:

```powershell
uv sync --extra dev
uv run chopscout-gui
```

To use the CLI only, the base dependencies are sufficient:

```powershell
uv sync
uv run chopscout --help
```

### FFmpeg

FFmpeg and ffprobe must be on `PATH` or placed under:

```text
tools\ffmpeg\bin\ffmpeg.exe
tools\ffmpeg\bin\ffprobe.exe
```

The `tools\` folder is git-ignored, so bundling a local FFmpeg build there will not be committed. ChopScout does not redistribute FFmpeg; obtain it from its official source and comply with its license.

## CLI

```powershell
uv run chopscout analyze "break.wav"
uv run chopscout export "break.wav" --mode equal16 --output .\exports
uv run chopscout export "break.wav" --mode equal32 --output .\exports
uv run chopscout export "break.wav" --mode equal48 --output .\exports
uv run chopscout export "break.wav" --mode equal64 --output .\exports
uv run chopscout export "break.wav" --mode equal16 --format portable --starting-note 40 --output .\exports
uv run chopscout validate ".\exports\break_120"
```

### `analyze`

Prints a JSON summary of the detected audio: sample rate, channels, duration, detected BPM with half-time and double-time alternatives, tempo confidence, downbeat, estimated bar count, transient count, and any warnings.

### `export`

Analyzes the input, slices it, and writes a validated package. Options:

| Option | Default | Description |
|---|---|---|
| `--mode` | `transient` | Chop mode (see [Chop modes](#chop-modes)) |
| `--output` | `./exports` | Output parent directory |
| `--bpm` | detected | Override the selected BPM |
| `--bars` | estimated | Override the bar count |
| `--starting-note` | `36` | First MIDI note (portable format only; MPC uses fixed 36) |
| `--pad-count` | mode-derived | Explicit MPC layout: 16, 32, 48, or 64 |
| `--format` | `both` | Export target (see [Export formats](#export-formats)) |
| `--overwrite` | off | Replace an existing output folder |

#### Overwrite and recovery guarantees

Exports are transactional. The package is first built in a hidden temporary folder next to the
destination (on the same drive), fully validated there, and only then moved into place. When
`--overwrite` replaces an existing export, the previous package is kept as a temporary backup
until the replacement has fully succeeded:

- If anything fails while generating WAV, MIDI, or MPC artifacts — or if the new package fails
  validation — the existing export is left untouched and the temporary build folder is removed.
- If the final move fails (for example because another program has the folder open), the
  previous export is restored automatically. In the unlikely case that the restore itself also
  fails, the error names the backup folder so nothing is lost.
- A destination that is a link (symlink or junction) is refused rather than replaced.
- If the process is killed hard (power loss) mid-export, a leftover hidden `.<name>.build-*`
  folder may remain next to your exports. It never affects the real export and is safe to
  delete.

The GUI currently has no overwrite option; export to a fresh folder or remove the old package
first (a GUI overwrite control is planned in a later phase).

### `validate`

Checks an exported package for structural integrity: required files, slice-map and metadata consistency, WAV counts, MIDI note alignment, and MPC artifact round-trip validation. Prints `Package is valid.` on success or a list of problems.

### Chop modes

| Mode | Description |
|---|---|
| `transient` | Slices at detected onset positions |
| `equal8` | 8 equal divisions |
| `equal16` | 16 equal divisions (MPC Bank A) |
| `equal32` | 32 equal divisions (MPC Banks A-B) |
| `equal48` | 48 equal divisions (MPC Banks A-C) |
| `equal64` | 64 equal divisions (MPC Banks A-D) |
| `beat` | One slice per quarter-note beat |
| `eighth` | One slice per eighth-note |
| `sixteenth` | One slice per sixteenth-note |
| `hybrid` | Sixteenth-note grid snapped to nearby transients |
| `manual` | A single marker at the downbeat; add and drag markers in the GUI |

### Export formats

- **`both`** (default) — Writes portable WAV, MIDI, metadata, and preview outputs, and adds MPC XPJ/XPM output when the slice count and note mapping are MPC-compatible.
- **`mpc`** — Writes the complete MPC-oriented package, including the portable support files. Requires MPC-compatible slice counts (16, 32, 48, or 64) and the fixed MPC starting note.
- **`portable`** — Writes sampler-agnostic WAV, MIDI, metadata, and preview outputs only. Does not write XPJ/XPM files and supports a custom MIDI starting note.

All formats are limited to 64 slices because ChopScout's naming, pad mapping, validation, and GUI are designed around MPC Banks A-D.

MPC XPJ/XPM exports use the fixed MPC drum-note map (notes 36-99). Use `--format portable` when you need a custom MIDI starting note.

## Pad and note mapping

Pad mapping is deterministic across Banks A-D:

| Bank | Pads | MIDI notes | Filenames |
|---|---|---|---|
| A | 1-16 | 36-51 | `A01`-`A16` |
| B | 17-32 | 52-67 | `B01`-`B16` |
| C | 33-48 | 68-83 | `C01`-`C16` |
| D | 49-64 | 84-99 | `D01`-`D16` |

Bank A is hardware-validated on an MPC One+ running MPC 3.9.0. Banks B, C, and D are confirmed through hardware testing. See [MPC compatibility](docs/mpc_compatibility.md) for details.

## GUI

Launch with `uv run chopscout-gui`. The window provides:

- Drag-and-drop or file dialog to open audio (WAV, AIFF, FLAC, MP3, OGG, M4A)
- Waveform display with zoom, beat grid, downbeat marker, and editable slice markers
- Chop mode, export format, and MPC layout selectors
- BPM and bar controls with half-time/double-time buttons
- Detection sensitivity and marker snap controls
- Transport buttons: play original, play selected slice, play reconstruction, stop
- Export with the same `both`, `mpc`, and `portable` format choices as the CLI

When the export format is `both` or `mpc`, the first MIDI note is locked to 36. Switch to `portable` to set a custom starting note.

## Exported package structure

Every export produces a folder named `<source-stem>_<bpm>` under the chosen output directory:

```text
break_120\
    source\
        break.wav                     original file copy
    full_loop\
        break_120_prepared.wav        decoded full loop (24-bit PCM WAV)
    chops_<mode>\
        A01.wav                       slices in MPC bank order
        ...
        D16.wav
    midi\
        original_groove.mid           reconstruction at detected timings
        straightened.mid              reconstruction on an even grid
        half_time.mid                 reconstruction at half tempo
        double_time.mid               reconstruction at double tempo
    metadata\
        chopscout.json                full export metadata and analysis
        slice_map.csv                 pad, MIDI note, filename, and timing per slice
        MPC_IMPORT_README.txt         or PORTABLE_IMPORT_README.txt
    preview\
        reconstructed_preview.wav     rendered slice reconstruction
    mpc_project\                      MPC format only
        break_120\
            break_120.xpj
            break_120_[ProjectData]\
                A01.wav
                ...
    mpc_program\                      MPC format only
        break_120 Program\
            break_120 Program.xpm
            break_120 Program_[ProgramData]\
                A01.wav
                ...
```

### Standalone XPM layout

Keep the XPM beside its matching ProgramData folder:

```text
ProgramName.xpm
ProgramName_[ProgramData]\
    A01.wav
    ...
    D16.wav
```

Do not move the WAV files beside the XPM.

### Complete XPJ layout

```text
ProjectName\
    ProjectName.xpj
    ProjectName_[ProjectData]\
        A01.wav
        ...
        D16.wav
```

All sample paths inside MPC files are relative. Copy the whole project or program folder to SD or USB storage and open it on the MPC.

## Testing and building

```powershell
uv run ruff check .
uv run pytest
uv run python scripts\generate_fixtures.py
uv run python scripts\build_windows.py
```

The Windows directory build is written under `dist\ChopScout-MPC\`.

See [Testing](docs/testing.md) and [Release process](docs/release.md) for full details.

## Configuration and logs

The GUI stores its configuration and logs under the Windows local app data directory:

- Config: `%LOCALAPPDATA%\ChopScout\ChopScout\config.json`
- Logs: `%LOCALAPPDATA%\ChopScout\ChopScout\Logs\chopscout.log`

The config file records recent files, last export directory, and theme. It is created automatically and can be deleted safely.

## Safety

ChopScout never modifies the original audio file or an existing MPC project. Generated MPC files are read back and structurally validated before the export is reported as successful. The `validate` command re-checks any package on demand.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE) and <https://www.gnu.org/licenses/gpl-3.0.txt>.

## Documentation

- [Architecture](docs/architecture.md)
- [DSP notes](docs/dsp_notes.md)
- [MPC compatibility](docs/mpc_compatibility.md)
- [Testing](docs/testing.md)
- [Release process](docs/release.md)
- [Hardware validation checklist](docs/hardware_validation_checklist.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Changelog](CHANGELOG.md)
