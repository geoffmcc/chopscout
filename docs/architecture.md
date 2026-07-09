# Architecture

The GUI and CLI call the same application core. `audio.py` owns decoding and PCM I/O; `analysis.py` contains deterministic DSP; `slicing.py` contains pure marker strategies; `midi.py` writes Standard MIDI; `exporter.py` creates and verifies portable packages; `mpc.py` is a compatibility gate that refuses proprietary output until verified fixtures exist.

Heavy GUI work runs in `QThreadPool` workers. The original source is never modified. Exports are deterministic for the same source, settings, and markers.
