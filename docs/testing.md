# Testing

Run `uv run python scripts/generate_fixtures.py` and then `uv run pytest`.

Hardware validation must be completed on MPC One+ 3.9.0: copy via SD and USB, load each WAV, confirm order, create a drum program, import original-groove MIDI, verify intended notes/pads, compare reconstruction timing, inspect displayed filenames, and save the validation date/firmware/result. XPM remains disabled until separate controlled validation passes.
