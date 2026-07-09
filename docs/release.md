# Release process

1. Run Ruff and pytest on Python 3.11 and 3.12.
2. Generate a clean export from every legal synthetic fixture.
3. Validate each package with the CLI.
4. Build on Windows using `uv run python scripts/build_windows.py`.
5. Test on a clean Windows 11 machine.
6. Complete and publish the MPC hardware-validation checklist.
7. Package FFmpeg only when redistribution terms for the selected build are satisfied.
