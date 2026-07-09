# MPC One+ 3.9.0 hardware validation checklist

Complete this checklist before publishing a release. Use a generated 64-pad package covering Banks A-D.

## Project (XPJ)

- [ ] XPJ opens on the MPC without warnings.
- [ ] The project title matches the generated name.
- [ ] Master tempo matches the exported BPM.
- [ ] Sequence length matches the exported bar count.
- [ ] The generated sequence plays all 64 pads in order.

## Drum program (XPM)

- [ ] XPM opens without missing-file warnings.
- [ ] Bank A contains 16 ascending pads (A01-A16).
- [ ] Bank B continues ascending after A16 (B01-B16).
- [ ] Bank C continues ascending after B16 (C01-C16).
- [ ] Bank D continues ascending after C16 (D01-D16).
- [ ] D16 is the highest pad and maps to note 99.
- [ ] Displayed filenames in the MPC browser match the pad order.

## Round-trip

- [ ] The project can be saved again on the MPC.
- [ ] The program can be saved again on the MPC.

## MIDI

- [ ] Imported original-groove MIDI triggers the intended pads and notes.
- [ ] Reconstruction timing matches the source slice timings.

## Record

- [ ] Validation date recorded.
- [ ] MPC firmware version recorded (e.g., 3.9.0.31).
- [ ] Result recorded (pass/fail per item).
