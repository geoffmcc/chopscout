"""Crash-recovery autosave for the active session.

An autosave file is a normal session file with a few extra top-level keys, so
the hardened `session.load_session` validator does all the work of reading it
back; the extra keys are simply ignored by that validator.

This version keeps a single slot holding whatever session is currently open.
The record carries `autosave_version` and the originating `session_path` so a
later move to per-session slots can key files by path without changing the
record shape. Slot indexing, stale-entry pruning, and a recovery picker are
deliberately not implemented here.

The slot is read automatically at startup, before the user has done anything,
so everything in it is treated as untrusted: the source audio is deliberately
NOT verified during the read (that would stat and hash a path chosen by the
file), and the metadata is range-checked rather than merely type-checked.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_state_dir

from .models import Session
from .session import (
    MAX_SESSION_BYTES,
    SESSION_SUFFIX,
    SessionError,
    is_remote_path,
    load_session,
    session_payload,
    write_json_atomic,
)

AUTOSAVE_VERSION = 1
# Bounds a plausible epoch timestamp: 1970 through roughly the year 3000.
MAX_AUTOSAVE_TIMESTAMP = 32_503_680_000.0
SLOT_MODE = 0o600
SLOT_DIR_MODE = 0o700


class AutosaveUnreadable(RuntimeError):
    """The slot exists but could not be read right now (locked, permissions).

    Distinct from an invalid slot: transient failures must not cause the only
    copy of the user's unsaved work to be discarded.
    """


@dataclass(slots=True)
class AutosaveRecord:
    """A recovered autosave. The source audio is not verified until consent."""

    session: Session
    session_path: str
    saved_at: float


def autosave_dir() -> Path:
    return Path(user_state_dir("ChopScout", "ChopScout")) / "autosave"


def autosave_path() -> Path:
    # Single slot. Per-session slots would add a path-derived name here.
    return autosave_dir() / "current.chopscout.json"


def write_autosave(session: Session, session_path: str | Path | None, saved_at: float) -> None:
    """Overwrite the autosave slot atomically. Raises SessionError on failure."""
    payload = session_payload(session)
    payload["autosave_version"] = AUTOSAVE_VERSION
    payload["session_path"] = str(session_path) if session_path else ""
    payload["saved_at"] = float(saved_at)
    try:
        text = json.dumps(payload, indent=2, allow_nan=False)
    except ValueError as exc:
        raise SessionError(f"Could not encode the autosave: {exc}") from exc
    path = autosave_path()
    _prepare_dir(path.parent)
    write_json_atomic(path, text, "autosave", file_mode=SLOT_MODE)


def read_autosave() -> AutosaveRecord | None:
    """Return the stored autosave, or None if there is nothing usable.

    Returns None for an absent or structurally invalid slot, which the caller
    may safely discard. Raises AutosaveUnreadable when the slot is present but
    temporarily unreadable, which must NOT be treated as invalid.
    """
    path = autosave_path()
    try:
        if not path.is_file():
            return None
        if path.stat().st_size > MAX_SESSION_BYTES:
            return None
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AutosaveUnreadable(str(exc)) from exc
    try:
        # verify_source=False: never stat or hash the recorded audio path here.
        # The status is computed after the user consents to recovering.
        session, _ = load_session(path, verify_source=False)
        metadata = json.loads(text)
    except (SessionError, ValueError, RecursionError, MemoryError):
        return None
    except OSError as exc:
        raise AutosaveUnreadable(str(exc)) from exc
    if not isinstance(metadata, dict):
        return None
    return AutosaveRecord(
        session=session,
        session_path=_validated_session_path(metadata.get("session_path")),
        saved_at=_validated_timestamp(metadata.get("saved_at")),
    )


def clear_autosave() -> None:
    """Drop the autosave slot. A missing or unremovable file is not an error."""
    try:
        autosave_path().unlink(missing_ok=True)
    except OSError:
        pass


def has_autosave() -> bool:
    """True when a slot is present, which means the last run did not exit cleanly."""
    try:
        return autosave_path().is_file()
    except OSError:
        return False


def _prepare_dir(directory: Path) -> None:
    """Create the slot directory private to this user where the OS supports it."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, SLOT_DIR_MODE)
    except OSError:
        # write_json_atomic reports a genuine write failure; a chmod that the
        # platform ignores (Windows) or refuses must not block the autosave.
        pass


def _validated_timestamp(value: object) -> float:
    """Coerce a stored timestamp, rejecting values that would break formatting."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return 0.0
    if not math.isfinite(result) or not 0.0 <= result <= MAX_AUTOSAVE_TIMESTAMP:
        return 0.0
    return result


def _validated_session_path(value: object) -> str:
    """Accept an origin path only if it looks like a local session file.

    The recovered path becomes the Save target and is written into the recent
    list, so a slot cannot be used to aim either at an arbitrary or remote file.
    """
    if not isinstance(value, str) or not value:
        return ""
    if is_remote_path(value) or not value.endswith(SESSION_SUFFIX):
        return ""
    return value
