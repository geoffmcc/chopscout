# Changelog

All notable changes to ChopScout are documented here. The project follows [Semantic Versioning](https://semver.org/).

## Unreleased

- Made export replacement transactional: packages are built in a hidden sibling temporary
  folder, fully validated there, and atomically swapped into place. Overwrites keep the
  previous export as a temporary backup until the replacement succeeds and restore it if the
  final move fails, so a failed export can no longer destroy or corrupt an existing package.
- Refused symlink/junction export destinations and destinations resolving outside the output
  folder.
- Added failure-injection tests covering WAV, MIDI, XPM, XPJ, validation, backup, and final
  replacement failures.

## 0.1.0

- Added 16, 32, 48, and 64-slice MPC exports.
- Added Banks A-D naming and note mapping.
- Added instrument-slot support through slot 63.
- Corrected standalone XPM packaging to use the required matching `_[ProgramData]` folder.
- Added complete XPJ Bank A-D generation with matching `_[ProjectData]` folder.
- Added equal-32, equal-48, and equal-64 chop modes.
- Added Banks A-D controls and clearer pad labels in the GUI.
- Added 64-pad XPM, XPJ, and full-package tests.
- Added MPC 3.9.0 XPM generation from a hardware fixture.
