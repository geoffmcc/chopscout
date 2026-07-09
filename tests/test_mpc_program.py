from pathlib import Path

from chopscout.mpc import (
    create_mpc39_program,
    read_xpm,
    validate_generated_mpc_program,
    xpm_export_available,
)


def test_create_hardware_template_program(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "synthetic_break.wav"
    samples = []
    for index in range(16):
        target = tmp_path / f"source-{index:02d}.wav"
        target.write_bytes(source.read_bytes())
        samples.append(target)

    result = create_mpc39_program(
        program_name="Generated Program",
        sample_paths=samples,
        output_parent=tmp_path / "out",
        bpm=172.0,
    )

    assert xpm_export_available()
    validate_generated_mpc_program(result.program_dir)
    header, document = read_xpm(result.xpm_path)
    assert b"3.9.0.31" in header
    assert b"SerialisableProgramData" in header
    data = document["data"]
    assert data["name"] == "Generated Program"
    assert [item["path"] for item in data["samples"]] == [
        f"A{index:02d}.wav" for index in range(1, 17)
    ]
    assert [
        data["drum"]["instruments"][index]["layersv"][0]["sampleFile"]
        for index in range(16)
    ] == [f"A{index:02d}.wav" for index in range(1, 17)]


def test_create_64_pad_program(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "synthetic_break.wav"
    samples = []
    for index in range(64):
        target = tmp_path / f"source64-{index:02d}.wav"
        target.write_bytes(source.read_bytes())
        samples.append(target)
    result = create_mpc39_program(program_name="Banks A-D", sample_paths=samples, output_parent=tmp_path / "out64", bpm=120.0)
    validate_generated_mpc_program(result.program_dir, expected_count=64)
    _, document = read_xpm(result.xpm_path)
    assert document["data"]["drum"]["instruments"][63]["layersv"][0]["sampleFile"] == "D16.wav"
    assert document["data"]["padNoteMap"]["noteForPad"]["value63"] == 99
    assert (result.program_data_dir / "D16.wav").is_file()
