from pathlib import Path

from chopscout.mpc import create_mpc39_project, read_xpj, validate_generated_mpc_project


def test_create_hardware_template_project(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "synthetic_break.wav"
    samples = []
    for index in range(16):
        target = tmp_path / f"source-{index:02d}.wav"
        target.write_bytes(source.read_bytes())
        samples.append(target)
    result = create_mpc39_project(
        project_name="Generated Test",
        sample_paths=samples,
        output_parent=tmp_path / "out",
        bpm=123.0,
        bars=4,
        event_times_seconds=[index * (60.0 / 123.0) for index in range(16)],
    )
    validate_generated_mpc_project(result.project_dir)
    _, document = read_xpj(result.xpj_path)
    sequence = document["data"]["sequences"][0]["value"]
    assert sequence["bpm"] == 123.0
    assert sequence["lengthBars"] == 4
    events = sequence["trackClipMaps"][0][0]["value"]["eventList"]["events"]
    assert len(events) == 16
    assert [event["note"]["note"] for event in events] == list(range(36, 52))


def test_create_64_pad_project(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "synthetic_break.wav"
    samples = []
    for index in range(64):
        target = tmp_path / f"project64-{index:02d}.wav"
        target.write_bytes(source.read_bytes())
        samples.append(target)
    result = create_mpc39_project(project_name="Banks A-D Project", sample_paths=samples, output_parent=tmp_path / "out64", bpm=120.0, bars=4, event_times_seconds=[index * 0.1 for index in range(64)])
    validate_generated_mpc_project(result.project_dir, expected_count=64)
    _, document = read_xpj(result.xpj_path)
    program = document["data"]["tracks"][0]["program"]
    assert program["drum"]["instruments"][63]["layersv"][0]["sampleFile"] == "D16.wav"
    assert (result.project_data_dir / "D16.wav").is_file()
