# Release process

1. Run Ruff and the full test suite on Python 3.11, 3.12, and 3.13.
2. Regenerate fixtures: `uv run python scripts/generate_fixtures.py`.
3. Generate a clean export from every supported slice count (16, 32, 48, 64) using the CLI.
4. Validate each package with `uv run chopscout validate <path>`.
5. Build on Windows: `uv run python scripts/build_windows.py`.
6. Test the built directory on a clean Windows 11 machine.
7. Complete and publish the [MPC hardware-validation checklist](hardware_validation_checklist.md).
8. Update `CHANGELOG.md` with the version entry.
9. Package FFmpeg only when redistribution terms for the selected build are satisfied. ChopScout does not redistribute FFmpeg by default.

## Versioning

ChopScout follows [Semantic Versioning](https://semver.org/). The version is defined in `src/chopscout/__init__.py` and mirrored in `pyproject.toml`.

## Build output

The Windows directory build is written under `dist\ChopScout-MPC\`. If `tools\ffmpeg\bin\` exists at build time, FFmpeg binaries are bundled into the build via PyInstaller's `--add-binary` flag.
