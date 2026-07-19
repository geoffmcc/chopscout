# Changelog

All notable changes to ChopScout are documented here. The project follows [Semantic Versioning](https://semver.org/).

## Unreleased

- Hardened the session core ahead of the GUI session workflow: sessions are now versioned
  (schema 2) with forward migration from the legacy format and rejection of newer formats;
  loading validates untrusted session files (types, finite numbers, size and marker caps)
  instead of crashing; saves are atomic; source audio is verified by hash with distinct
  ok/missing/changed states; and a relink API re-points a session at moved audio, requiring
  explicit consent to rebind to different audio.
- Cleaned up stale and unfinished contracts: removed the never-implemented
  `ExportSettings.trim_silence` flag, the unused `SliceMarker` model, the unused config
  `theme` field, the constant `xpj_export_available`/`xpm_export_available` functions, and the
  redundant `proprietary_mpc_program_generated` metadata key.
- Added a GUI Overwrite checkbox wired to the transactional export replacement (off by
  default); the GUI can now re-export to an existing folder.
- Made config loading tolerant: unknown keys (including the removed `theme`) are ignored and
  malformed configs fall back to defaults without losing valid fields.
- Made `mpc.MPC_COMPATIBILITY` the single source of truth for MPC support claims and aligned
  code and documentation on the verified status: Banks A-D hardware-validated on MPC One+
  3.9.0.31. `TempoHypothesis` is documented as reserved for the analysis-improvement phase.
- Added GitHub Actions CI: lint, full test suite on Linux and Windows across Python
  3.11-3.13 with headless GUI tests, a Windows PyInstaller build smoke test whose output is
  discarded, and lockfile/version consistency checks. CI is verification-only — read-only
  permissions, SHA-pinned actions, no secrets, no artifact uploads, and no release or
  publishing jobs.
- Deepened package validation beyond file existence: generated WAVs are opened and checked for
  readable headers, sample rate, channel count, and expected lengths; all four MIDI files are
  parsed and checked for note sequence, tempo, and marker-accurate original-groove timing;
  metadata is cross-checked against the slice map, the source copy, and the files on disk, and
  unsafe or out-of-range metadata values are rejected with errors naming the failing file.
- Added malformed-package and corrupted-file validation tests.
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
