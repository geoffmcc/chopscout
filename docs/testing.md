# Testing

## Continuous integration

Every push to `main` and every pull request runs `.github/workflows/ci.yml`. CI verifies; it
never publishes. There are no release jobs, no uploaded executables, and no deployment — the
Windows build-smoke output is discarded when the runner is destroyed. The workflow runs with
read-only repository permissions, uses no secrets, and pins every action to an immutable
commit SHA.

CI verifies:

- **lint** — `ruff check .` on Linux.
- **test** — the full pytest suite on Linux and Windows across Python 3.11, 3.12, and 3.13,
  with FFmpeg installed and GUI tests running headless (`QT_QPA_PLATFORM=offscreen`). This
  covers the core, CLI, export, package-validation, session, and GUI-state tests, and
  regenerates the synthetic fixture to confirm the generator stays deterministic.
- **build-smoke** — `scripts/build_windows.py` (PyInstaller) on Windows, verifying the
  executable is produced. The output is deliberately not uploaded anywhere.
- **metadata** — `uv lock --check` (lockfile matches `pyproject.toml`) and that
  `chopscout.__version__` matches the `pyproject.toml` version.

The job names `lint`, `test (...)`, `build-smoke`, and `metadata` are stable so they can later
be marked as required status checks. Repository protection settings are not changed by CI.

What remains manual:

- MPC hardware validation (see below) — never claimed by CI.
- Launching the built Windows executable (the smoke test builds a windowed app; CI cannot run
  it headlessly) and any listening/audio-quality checks.
- Dependency caching is deliberately not enabled yet; each run installs from the lockfile.

## Running the test suite

Generate the synthetic fixture first, then run the full suite:

```powershell
uv run python scripts/generate_fixtures.py
uv run pytest
```

Lint with Ruff:

```powershell
uv run ruff check .
```

## Test modules

| Module | Coverage |
|---|---|
| `test_slicing.py` | Marker normalization, equal division, snapping, slice ranges |
| `test_midi.py` | Tick conversion, MIDI note sequence generation |
| `test_models.py` | Deterministic project name derivation |
| `test_validation.py` | Loop-duration validation across sample rates, BPMs, and bar counts; beats-per-bar support; rejection of meaningful timing errors |
| `test_playback.py` | Playback context mapping for original, slice, and reconstruct modes; boundary conditions; stale-generation handling |
| `test_session.py` | Session round-trip, v1 migration, future-version rejection, malformed/hostile session files, missing/changed source detection, relink workflow, atomic save |
| `test_core.py` | Loop-duration warning refresh on BPM/bar changes during export |
| `test_mpc_program.py` | 16-pad and 64-pad XPM generation, round-trip validation, pad-note map, sample table order |
| `test_mpc_project.py` | 16-pad and 64-pad XPJ generation, sequence events, bar count, BPM, Bank D slot configuration |
| `test_integration.py` | End-to-end decode-analyze-export-validate, all three export formats, pad-count contracts, custom starting-note rules, CLI behavior, 64-slice maximum across formats, package validation edge cases |
| `test_ui_state.py` | GUI mode/marker synchronization, playback position mapping, BPM/bar warning refresh, transport contexts, export-format control state, pad-count layout sync (requires `QT_QPA_PLATFORM=offscreen`) |

## Fixture generation

`scripts/generate_fixtures.py` creates `tests/fixtures/synthetic_break.wav`: an 8-second, 44.1 kHz, 120 BPM synthetic drum pattern with alternating kick and snare transients. The script is deterministic and safe to re-run.

## Hardware validation

Hardware validation must be completed on MPC One+ running MPC 3.9.0:

1. Copy the generated project and program folders to SD and USB storage.
2. Load each WAV slice and confirm pad order across Banks A-D.
3. Open the XPJ project and confirm the reconstructed sequence plays all pads in order.
4. Load the standalone XPM program and confirm no missing-file warnings.
5. Import the original-groove MIDI and verify intended notes and pads.
6. Compare reconstruction timing against the source.
7. Inspect displayed filenames in the MPC browser.
8. Save the project and program again on the MPC.
9. Record the validation date, firmware version, and result.

See [Hardware validation checklist](hardware_validation_checklist.md).
