# MPC compatibility

## File format

MPC 3.9.0 XPJ and XPM files used by ChopScout are gzip-compressed ACVS documents. After decompression, each file begins with a header terminated by a `Linux\n` marker, followed by a JSON payload.

- XPJ uses the header kind `SerialisableProjectData`.
- XPM uses the header kind `SerialisableProgramData`.

The bundled fixtures (`src/chopscout/resources/`) were saved directly by an MPC One+ running MPC 3.9.0.31. ChopScout reads these fixtures, rewrites the JSON document, and writes the result back through gzip with a deterministic mtime. Every generated file is read back and structurally validated before the export is reported as successful.

## Timing

MPC timing uses 960 PPQ (pulses per quarter note). ChopScout converts source onset times to pulse positions with `seconds * BPM * 960 / 60`, clamped to the sequence length.

## Pad and note mapping

ChopScout-generated pad notes are sequential from MIDI note 36:

| Bank | Instrument slots | Pads | Notes | Filenames |
|---|---|---|---|---|
| A | 0-15 | 1-16 | 36-51 | `A01`-`A16` |
| B | 16-31 | 17-32 | 52-67 | `B01`-`B16` |
| C | 32-47 | 33-48 | 68-83 | `C01`-`C16` |
| D | 48-63 | 49-64 | 84-99 | `D01`-`D16` |

The fixture contains at least 64 instrument slots. Used pads are configured with sample references; unused pads in Banks A-D are cleared without disturbing banks beyond D.

## Hardware validation status

- **Banks A-D**: hardware-validated on an MPC One+ running MPC 3.9.0.31, covering the 16, 32,
  48, and 64-slice exports.

The authoritative status lives in code as `mpc.MPC_COMPATIBILITY`; `mpc.explain_xpm_status()`
derives its text from it, and a test asserts they stay consistent. Documentation must agree
with that structure — update both together when validation status changes.

See [Hardware validation checklist](hardware_validation_checklist.md) for the procedure used
to (re)validate a firmware version.

## Required folders

### Standalone XPM

```text
ProgramName.xpm
ProgramName_[ProgramData]/
    A01.wav
    ...
    D16.wav
```

### Complete project

```text
ProjectName/
    ProjectName.xpj
    ProjectName_[ProjectData]/
        A01.wav
        ...
        D16.wav
```

All sample paths inside MPC files are relative. Absolute host paths are forbidden. Copy the whole project or program folder to SD or USB storage and open it on the MPC. Do not move WAV files out of their `_[ProgramData]` or `_[ProjectData]` folder.

## Generation and validation

`mpc.py` exposes two generators:

- `create_mpc39_program` — writes a standalone XPM with its `_[ProgramData]` folder.
- `create_mpc39_project` — writes a complete XPJ with its `_[ProjectData]` folder, embedded drum program, and reconstructed sequence.

Both accept 16, 32, 48, or 64 sample paths. After writing, each calls its corresponding `validate_generated_mpc_*` function, which checks:

- Exactly one XPJ/XPM exists.
- The sample table is in Bank A-D pad order.
- The `_[ProgramData]` or `_[ProjectData]` folder exists and contains every expected WAV.
- Each instrument slot references the correct sample file.
- The pad-note map is sequential from note 36.
- (XPJ only) sequence event notes are sequential from 36 and the count matches.

The export-level `validate_package` function in `exporter.py` additionally checks the overall package structure, metadata, slice map, and MIDI note alignment.
