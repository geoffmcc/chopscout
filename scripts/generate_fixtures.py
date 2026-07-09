from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf

root = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
root.mkdir(parents=True, exist_ok=True)
sr = 44100
bpm = 120
seconds = 8.0
t = np.arange(int(sr * seconds)) / sr
signal = np.zeros_like(t, dtype=np.float32)
for beat in np.arange(0, seconds, 60 / bpm):
    start = int(beat * sr)
    length = int(0.08 * sr)
    env = np.exp(-np.arange(length) / (0.015 * sr))
    tone = np.sin(2 * np.pi * (70 if round(beat/(60/bpm)) % 4 == 0 else 180) * np.arange(length) / sr)
    signal[start:start+length] += (env * tone).astype(np.float32)
sf.write(root / "synthetic_break.wav", signal, sr, subtype="PCM_16")
