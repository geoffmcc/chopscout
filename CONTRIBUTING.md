# Contributing to ChopScout

Contributions are welcome. This guide covers the development setup, code style, testing requirements, and pull request process.

## Development setup

Requirements: Windows 10 or 11, Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and FFmpeg/ffprobe on `PATH` or under `tools\ffmpeg\bin\`.

```powershell
git clone https://github.com/geoffmcc/chopscout.git
cd chopscout
uv sync --extra dev
uv run python scripts/generate_fixtures.py
uv run pytest
```

## Code style

- Ruff enforces linting. Run `uv run ruff check .` before committing.
- Line length is 100 characters. Target Python 3.11.
- Enabled rule sets: `E`, `F`, `I`, `UP`, `B`.
- Use `from __future__ import annotations` at the top of every module.
- Prefer `dataclass(slots=True)` for data containers.
- Do not add comments unless they explain non-obvious intent.

## Testing

All contributions must pass the existing test suite. Add tests for any new behavior:

```powershell
uv run ruff check .
uv run pytest
```

GUI tests run headless via `QT_QPA_PLATFORM=offscreen`, which is set automatically in `test_ui_state.py`.

### Test conventions

- Use `pytest` fixtures and `tmp_path` for filesystem isolation.
- Integration tests synthesize short audio fixtures in-memory; do not commit binary audio files.
- MPC tests copy the synthetic fixture from `tests/fixtures/` and exercise generation and validation directly.

## Project structure

```text
src/chopscout/      application source
tests/              test suite
scripts/            build, fixture, and validation scripts
docs/               documentation
```

See [Architecture](docs/architecture.md) for module responsibilities.

## Pull request process

1. Create a branch from `main`.
2. Write tests covering your change.
3. Ensure `uv run ruff check .` and `uv run pytest` pass.
4. Keep commits focused. Write clear commit messages.
5. Open a pull request describing the change, the motivation, and how it was tested.

## Adding or changing chop modes

1. Add the mode to `generate_markers` in `slicing.py`.
2. Add it to the CLI choices in `cli.py` and the GUI combo in `ui.py` if user-facing.
3. Add tests in `test_slicing.py` or `test_integration.py`.
4. If the mode produces 16, 32, 48, or 64 slices, verify that MPC export and package validation pass.

## Adding or changing MPC behavior

1. Modify `mpc.py` and update the corresponding `validate_generated_mpc_*` function.
2. Add or update tests in `test_mpc_program.py` and `test_mpc_project.py`.
3. Add an integration test in `test_integration.py` if the change affects end-to-end export.
4. Update [docs/mpc_compatibility.md](docs/mpc_compatibility.md) if the file format, pad mapping, or folder layout changes.

## Reporting issues

- Use a minimal reproducible fixture. Do not attach copyrighted sample libraries or personal project files.
- Include the ChopScout version (`uv run chopscout --help` or `__version__`), Python version, OS, and FFmpeg version.
- Report security vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under GPL-3.0-or-later.
