from __future__ import annotations

import json
from pathlib import Path

from .audio import source_hash
from .models import Session


def save_session(path: str | Path, session: Session) -> None:
    Path(path).write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")


def load_session(path: str | Path, verify_source: bool = True) -> tuple[Session, bool]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    session = Session.from_dict(data)
    changed = False
    if verify_source and Path(session.source_path).exists():
        changed = source_hash(session.source_path) != session.source_hash
    return session, changed
