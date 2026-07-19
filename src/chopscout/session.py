from __future__ import annotations

import json
import math
import os
import secrets
from dataclasses import fields
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import __version__
from .audio import source_hash
from .models import SESSION_SCHEMA_VERSION, ExportFormat, ExportSettings, Session

MAX_SESSION_BYTES = 5_000_000
MAX_SESSION_MARKERS = 4096
MAX_SESSION_SECONDS = 1e6
MAX_SESSION_BPM = 1e5


class SessionError(RuntimeError):
    pass


class SourceStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    CHANGED = "changed"
    UNVERIFIED = "unverified"


def save_session(path: str | Path, session: Session) -> None:
    """Write a session atomically (exclusive temp file + rename) in the current schema."""
    session.schema_version = SESSION_SCHEMA_VERSION
    session.app_version = __version__
    if session.source_size <= 0 and not _is_remote_path(session.source_path):
        session.source_size = _probe_source_size(session.source_path)
    destination = Path(path)
    payload = json.dumps(session.to_dict(), indent=2)
    temporary = destination.with_name(f".{destination.name}.tmp-{secrets.token_hex(8)}")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(temporary, destination)
    except OSError as exc:
        raise SessionError(f"Could not save the session file: {destination}: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def load_session(path: str | Path, verify_source: bool = True) -> tuple[Session, SourceStatus]:
    """Load, migrate, and validate a session file, then check its source audio.

    Raises SessionError for unreadable, malformed, or unsupported files.
    """
    source = Path(path)
    try:
        if not source.is_file():
            raise SessionError(f"Session file does not exist: {source}")
        if source.stat().st_size > MAX_SESSION_BYTES:
            raise SessionError(f"Session file is unreasonably large: {source}")
        data = json.loads(source.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except SessionError:
        raise
    except (OSError, ValueError, RecursionError, MemoryError) as exc:
        raise SessionError(f"Session file is unreadable: {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise SessionError(f"Session file is not a JSON object: {source}")
    data = _migrate(data, source)
    session = _validated_session(data, source)
    return session, _source_status(session, verify_source)


def relink_source(session: Session, new_path: str | Path, allow_changed: bool = False) -> Session:
    """Point a session at a moved source file.

    The replacement must have identical content unless `allow_changed` is set,
    in which case the stored hash and size are deliberately rebound.
    """
    target = Path(new_path)
    try:
        if not target.is_file():
            raise SessionError(f"Relink target does not exist: {target}")
        digest = source_hash(target)
        size = target.stat().st_size
    except SessionError:
        raise
    except OSError as exc:
        raise SessionError(f"Relink target is unreadable: {target}: {exc}") from exc
    if digest != session.source_hash:
        if not allow_changed:
            raise SessionError(
                "Relink target does not match the session's original audio. "
                "Use allow_changed to rebind the session to different audio deliberately."
            )
        session.source_hash = digest
        session.source_size = size
    session.source_path = str(target)
    return session


def _reject_constant(value: str) -> float:
    raise ValueError(f"unsupported JSON constant: {value}")


def _is_remote_path(value: str) -> bool:
    return value.startswith(("\\\\", "//"))


def _probe_source_size(source_path: str) -> int:
    try:
        source = Path(source_path)
        if source.is_file():
            return source.stat().st_size
    except OSError:
        pass
    return 0


def _migrate(data: dict[str, Any], source: Path) -> dict[str, Any]:
    version = data.get("schema_version")
    if version is None and isinstance(data.get("version"), str):
        # Schema v1: app version stored as "version", no schema marker.
        migrated = dict(data)
        migrated["app_version"] = migrated.pop("version")
        migrated.setdefault("schema_version", SESSION_SCHEMA_VERSION)
        migrated.setdefault("source_size", 0)
        return migrated
    if isinstance(version, bool) or not isinstance(version, int):
        raise SessionError(f"Session file has no valid schema version: {source}")
    if version > SESSION_SCHEMA_VERSION:
        raise SessionError(
            f"Session was created by a newer ChopScout (schema {version}; "
            f"this build supports up to {SESSION_SCHEMA_VERSION}): {source}"
        )
    if version < 1:
        raise SessionError(f"Session file has no valid schema version: {source}")
    return data


def _finite(value: Any, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    if not math.isfinite(result) or not minimum <= result <= maximum:
        return None
    return result


def _validated_session(data: dict[str, Any], source: Path) -> Session:
    def fail(reason: str) -> SessionError:
        return SessionError(f"Session file is malformed ({reason}): {source}")

    source_path = data.get("source_path")
    digest = data.get("source_hash")
    if not isinstance(source_path, str) or not source_path:
        raise fail("source_path must be a non-empty string")
    if not isinstance(digest, str):
        raise fail("source_hash must be a string")
    detected_bpm = _finite(data.get("detected_bpm"), 1e-3, MAX_SESSION_BPM)
    selected_bpm = _finite(data.get("selected_bpm"), 1e-3, MAX_SESSION_BPM)
    if detected_bpm is None or selected_bpm is None:
        raise fail("BPM values must be finite positive numbers")
    bar_count = data.get("bar_count")
    if isinstance(bar_count, bool) or not isinstance(bar_count, int) or not 1 <= bar_count <= 999:
        raise fail("bar_count must be an integer between 1 and 999")
    downbeat = _finite(data.get("downbeat"), -MAX_SESSION_SECONDS, MAX_SESSION_SECONDS)
    if downbeat is None:
        raise fail("downbeat must be a finite number")
    raw_markers = data.get("markers")
    if not isinstance(raw_markers, list):
        raise fail("markers must be a list")
    if len(raw_markers) > MAX_SESSION_MARKERS:
        raise fail(f"markers exceed the maximum of {MAX_SESSION_MARKERS}")
    markers: list[float] = []
    for value in raw_markers:
        finite = _finite(value, -MAX_SESSION_SECONDS, MAX_SESSION_SECONDS)
        if finite is None:
            raise fail("markers must all be finite numbers")
        markers.append(finite)
    chop_mode = data.get("chop_mode")
    if not isinstance(chop_mode, str) or not chop_mode:
        raise fail("chop_mode must be a non-empty string")
    raw_pad_map = data.get("pad_map", {})
    if not isinstance(raw_pad_map, dict):
        raise fail("pad_map must be an object")
    pad_map: dict[str, int] = {}
    for key, value in raw_pad_map.items():
        if (
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= 127
        ):
            raise fail("pad_map must map pad names to MIDI notes 0-127")
        pad_map[key] = value
    raw_export = data.get("export_settings", {})
    if not isinstance(raw_export, dict):
        raise fail("export_settings must be an object")
    export_settings = _validated_export_settings(raw_export, fail)
    app_version = data.get("app_version", "")
    if not isinstance(app_version, str):
        app_version = ""
    source_size = data.get("source_size", 0)
    if isinstance(source_size, bool) or not isinstance(source_size, int) or source_size < 0:
        source_size = 0
    return Session(
        source_path=source_path,
        source_hash=digest,
        detected_bpm=detected_bpm,
        selected_bpm=selected_bpm,
        bar_count=bar_count,
        downbeat=downbeat,
        markers=markers,
        chop_mode=chop_mode,
        pad_map=pad_map,
        export_settings=export_settings,
        schema_version=SESSION_SCHEMA_VERSION,
        app_version=app_version,
        source_size=source_size,
    )


def _validated_export_settings(raw: dict[str, Any], fail) -> dict[str, Any]:
    """Keep only known ExportSettings fields, and only with usable values.

    Session export settings flow straight into the exporter when a session is
    restored, so hostile values are rejected at this trust boundary.
    """
    known = {item.name for item in fields(ExportSettings)}
    result: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in known:
            continue
        valid = True
        if key == "mode":
            valid = isinstance(value, str) and bool(value)
        elif key == "starting_note":
            valid = not isinstance(value, bool) and isinstance(value, int) and 0 <= value <= 127
        elif key == "bars":
            valid = not isinstance(value, bool) and isinstance(value, int) and 1 <= value <= 999
        elif key == "bpm":
            valid = _finite(value, 1e-3, MAX_SESSION_BPM) is not None
        elif key == "short_fades_ms":
            valid = _finite(value, 0.0, 10_000.0) is not None
        elif key == "overwrite":
            valid = isinstance(value, bool)
        elif key == "export_format":
            valid = isinstance(value, str) and value in {item.value for item in ExportFormat}
        elif key == "pad_count":
            valid = value is None or (
                not isinstance(value, bool) and isinstance(value, int) and value in (16, 32, 48, 64)
            )
        if not valid:
            raise fail(f"export_settings {key} is invalid")
        result[key] = value
    return result


def _source_status(session: Session, verify_source: bool) -> SourceStatus:
    if not verify_source:
        return SourceStatus.UNVERIFIED
    if _is_remote_path(session.source_path):
        # Never probe UNC/network paths automatically; the caller must decide.
        return SourceStatus.UNVERIFIED
    source = Path(session.source_path)
    try:
        if not source.is_file():
            return SourceStatus.MISSING
        if 0 < session.source_size != source.stat().st_size:
            return SourceStatus.CHANGED
        if source_hash(source) != session.source_hash:
            return SourceStatus.CHANGED
    except OSError:
        return SourceStatus.MISSING
    return SourceStatus.OK
