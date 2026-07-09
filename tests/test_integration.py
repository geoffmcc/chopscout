from pathlib import Path

import numpy as np
import soundfile as sf

from chopscout.core import export_project, load_project
from chopscout.exporter import validate_package
from chopscout.models import ExportSettings


def make_break(path: Path):
    sr=22050; duration=4.0; data=np.zeros((int(sr*duration),1),dtype=np.float32)
    for second in np.arange(0,duration,.5):
        start=int(second*sr); n=min(500,len(data)-start); data[start:start+n,0]=np.linspace(1,0,n)
    sf.write(path,data,sr)


def test_decode_analyze_export(tmp_path: Path):
    source=tmp_path/"break.wav"; make_break(source)
    project=load_project(source,"equal8")
    settings=ExportSettings(mode="equal8",bpm=120,bars=2)
    result=export_project(project,tmp_path/"out",settings)
    assert validate_package(result)==[]
    assert len(list((result/"chops_equal8").glob("*.wav")))==8


def test_equal16_export_includes_xpj_and_xpm(tmp_path: Path):
    source = tmp_path / "break16.wav"
    make_break(source)
    project = load_project(source, "equal16")
    settings = ExportSettings(mode="equal16", bpm=120, bars=4)
    result = export_project(project, tmp_path / "out16", settings)
    assert validate_package(result) == []
    assert len(list((result / "mpc_project").glob("*/*.xpj"))) == 1
    assert len(list((result / "mpc_program").glob("*/*.xpm"))) == 1
    program = next((result / "mpc_program").glob("*/*.xpm"))
    companion = program.parent / f"{program.stem}_[ProgramData]"
    assert len(list(companion.glob("A??.wav"))) == 16


def test_equal64_export_includes_banks_a_through_d(tmp_path: Path):
    source = tmp_path / "break64.wav"
    make_break(source)
    project = load_project(source, "equal64")
    settings = ExportSettings(mode="equal64", bpm=120, bars=4, pad_count=64)
    result = export_project(project, tmp_path / "out64", settings)
    assert validate_package(result) == []
    assert (result / "chops_equal64" / "A01.wav").is_file()
    assert (result / "chops_equal64" / "D16.wav").is_file()
    program = next((result / "mpc_program").glob("*/*.xpm"))
    companion = program.parent / f"{program.stem}_[ProgramData]"
    assert len(list(companion.glob("*.wav"))) == 64
