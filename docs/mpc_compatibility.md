# MPC compatibility

## Validated format facts

MPC 3.9.0 XPJ and XPM files used by ChopScout are gzip-compressed ACVS documents containing JSON after a Linux header marker.

XPJ uses `SerialisableProjectData`; XPM uses `SerialisableProgramData`.

Timing uses 960 PPQ. ChopScout-generated pad notes are sequential from 36.

## Banks

| Bank | Instrument slots | Notes | Filenames |
|---|---:|---:|---|
| A | 0–15 | 36–51 | A01–A16 |
| B | 16–31 | 52–67 | B01–B16 |
| C | 32–47 | 68–83 | C01–C16 |
| D | 48–63 | 84–99 | D01–D16 |

Bank A is hardware-validated. Banks B and C are evidenced by populated MPC programs. Bank D is generated from the same sequential 16-slot structure and awaits the final hardware check.

## Required folders

Standalone XPM:

```text
ProgramName.xpm
ProgramName_[ProgramData]/
```

Complete project:

```text
ProjectName/
  ProjectName.xpj
  ProjectName_[ProjectData]/
```

All sample paths are relative. Absolute host paths are forbidden.
