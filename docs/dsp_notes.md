# DSP notes

ChopScout uses lightweight, deterministic digital signal processing. The goal is practical, transparent slicing on Windows without presenting a large model as "AI." All results are confidence-scored and editable in the GUI.

## Onset detection

The onset envelope is computed in `analysis.py`:

1. The input is reduced to mono by averaging channels.
2. Frame RMS is computed with a 1024-sample frame and 256-sample hop using stride tricks for efficiency.
3. A novelty function is derived as the positive first difference of the RMS envelope.
4. The novelty curve is smoothed with a Savitzky-Golay filter (window up to 9, order 2) when enough samples exist.
5. The curve is clamped to non-negative and normalized to its maximum.

Transients are detected with `scipy.signal.find_peaks` over the smoothed envelope:

- Height threshold: a sensitivity-controlled quantile of the envelope (clamped between 0.35 and 0.9), floored at 0.05.
- Minimum distance: 45 ms of hop frames to avoid double-triggers.
- Minimum prominence: 0.025 to reject low-energy fluctuations.

The default sensitivity is 0.55, adjustable in the GUI between 0.35 and 0.9.

## Tempo estimation

Tempo is estimated by autocorrelation of the mean-centered onset envelope via FFT convolution:

- The search range is 55-210 BPM, converted to lag indices over the 256-sample hop.
- The lag with the highest autocorrelation in range is selected.
- Confidence is the ratio of the peak autocorrelation to the zero-lag value, clamped to [0, 1].
- The result is octave-corrected into the 80-190 BPM range (doubled or halved as needed).
- Half-time and double-time alternatives are always exposed because breakbeats are inherently ambiguous.

When the envelope is too short or silent, tempo defaults to 120 BPM with zero confidence, and a low-confidence warning is emitted.

## Beat grid

A beat grid is generated from the selected BPM and downbeat. Beats are spaced at `60 / BPM` seconds, extended backward before the downbeat and forward to the end of the audio. Quarter, eighth, and sixteenth-note chop modes derive their markers from this grid.

## Downbeat

The downbeat is the first detected onset if it falls within the first second or first quarter of the duration; otherwise it falls back to the start of non-silent audio. The downbeat confidence is the first onset strength plus a small constant, clamped to [0, 1].

## Silence bounds

Silence is measured against an absolute threshold of -48 dBFS on the mono amplitude envelope. The trim start and trim end bound the first and last samples above threshold. A warning is emitted when the loop begins with silence or a lead-in.

## Loop-duration validation

`validation.py` checks whether the source duration closely matches the expected loop length for the selected BPM and bar count. The tolerance is the maximum of:

- 3 ms absolute allowance
- 4 decoded samples
- 0.02% of the expected duration

This accepts sample rounding and metadata/decoder noise without masking musically meaningful timing errors. When the check fails, a detailed warning is added (or refreshed) with expected/actual durations, the difference in milliseconds, BPM, bars, and time signature.

## Source integrity

Analysis never normalizes, stretches, denoises, compresses, converts channels, or alters the source. The source SHA-256 hash is recorded in metadata. Optional short edge fades (default 2 ms) are applied only to exported slice WAVs to reduce boundary clicks; the full loop and source copy are unaffected.
