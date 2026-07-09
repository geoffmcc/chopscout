from chopscout.slicing import equal_markers, normalize_markers, slice_ranges, snap_marker


def test_equal_16():
    values = equal_markers(8.0, 16)
    assert len(values) == 16
    assert values[1] == 0.5


def test_normalize_sorts_and_enforces_minimum():
    assert normalize_markers([1.0, 0.0, 0.01, 0.5], 2.0) == [0.0, 0.5, 1.0]


def test_snap():
    assert snap_marker(1.02, [0.0, 1.0, 2.0], 0.05) == 1.0
    assert snap_marker(1.2, [0.0, 1.0, 2.0], 0.05) == 1.2


def test_ranges_end_at_duration():
    assert slice_ranges([0, 1], 2) == [(0.0, 1.0), (1.0, 2)]
