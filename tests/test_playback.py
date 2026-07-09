from chopscout.playback import (
    active_slice_for_position,
    map_player_position_to_waveform,
    original_playback_context,
    reconstruct_playback_context,
    slice_playback_context,
)


def test_original_playback_maps_directly_to_waveform_position():
    context = original_playback_context([0.0, 1.0, 2.0], 3.0)
    mapped = map_player_position_to_waveform(context, 1.25)
    assert mapped.position_seconds == 1.25
    assert mapped.active_slice == 1


def test_slice_playback_maps_local_position_to_source_slice():
    context = slice_playback_context([0.0, 1.0, 2.0], 3.0, 1)
    mapped = map_player_position_to_waveform(context, 0.25)
    assert mapped.position_seconds == 1.25
    assert mapped.active_slice == 1


def test_reconstruct_playback_maps_across_source_slice_boundaries():
    context = reconstruct_playback_context([0.0, 0.5, 2.0], 3.0)
    first = map_player_position_to_waveform(context, 0.25)
    boundary = map_player_position_to_waveform(context, 0.5)
    second = map_player_position_to_waveform(context, 0.75)
    third = map_player_position_to_waveform(context, 2.25)
    assert first.position_seconds == 0.25
    assert first.active_slice == 0
    assert boundary.position_seconds == 0.5
    assert boundary.active_slice == 1
    assert second.position_seconds == 0.75
    assert second.active_slice == 1
    assert third.position_seconds == 2.25
    assert third.active_slice == 2


def test_active_slice_boundaries_and_final_position():
    markers = [0.0, 1.0, 2.0]
    assert active_slice_for_position(markers, 3.0, 0.999) == 0
    assert active_slice_for_position(markers, 3.0, 1.0) == 1
    assert active_slice_for_position(markers, 3.0, 3.0) == 2


def test_mapping_handles_no_file_and_empty_slices():
    assert map_player_position_to_waveform(None, 1.0).position_seconds is None
    context = original_playback_context([], 0.0)
    mapped = map_player_position_to_waveform(context, 1.0)
    assert mapped.position_seconds is None
    assert mapped.active_slice is None


def test_stale_generation_can_be_ignored_by_caller():
    context = original_playback_context([0.0, 1.0], 2.0, generation=2)
    assert context.generation != 3
