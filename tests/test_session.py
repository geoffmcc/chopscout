from pathlib import Path

from chopscout.models import Session
from chopscout.session import load_session, save_session


def test_session_roundtrip(tmp_path: Path):
    item=Session("0.1.0","missing.wav","abc",120,120,4,0,[0,1],"manual",{"A01":36},{})
    path=tmp_path/"session.json"; save_session(path,item); loaded,changed=load_session(path)
    assert loaded.markers==[0,1]
    assert changed is False
