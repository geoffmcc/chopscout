import pytest

from chopscout.validation import validate_loop_duration


@pytest.mark.parametrize("sample_rate", [44100, 48000, 96000])
@pytest.mark.parametrize("bpm,bars", [(120.0, 4), (93.5, 2), (174.0, 8)])
def test_loop_duration_accepts_exact_and_near_exact_sample_counts(sample_rate: int, bpm: float, bars: int):
    expected_samples = round(bars * 4 * 60.0 / bpm * sample_rate)
    for delta in [0, 1, -1, 4, round(sample_rate * 0.001), round(sample_rate * 0.0025)]:
        result = validate_loop_duration(
            total_samples=expected_samples + delta,
            sample_rate=sample_rate,
            bpm=bpm,
            bars=bars,
        )
        assert result.is_valid


def test_loop_duration_rejects_meaningful_timing_error():
    sample_rate = 48000
    expected_samples = round(4 * 4 * 60.0 / 120.0 * sample_rate)
    result = validate_loop_duration(
        total_samples=expected_samples + round(sample_rate * 0.025),
        sample_rate=sample_rate,
        bpm=120.0,
        bars=4,
    )
    assert not result.is_valid


def test_loop_duration_uses_beats_per_bar():
    sample_rate = 48000
    samples_3_4 = round(2 * 3 * 60.0 / 90.0 * sample_rate)
    assert validate_loop_duration(
        total_samples=samples_3_4,
        sample_rate=sample_rate,
        bpm=90.0,
        bars=2,
        beats_per_bar=3,
    ).is_valid
    assert not validate_loop_duration(
        total_samples=samples_3_4,
        sample_rate=sample_rate,
        bpm=90.0,
        bars=2,
    ).is_valid
