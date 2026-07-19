from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from platformdirs import user_config_dir

MAX_CONFIG_BYTES = 1_000_000
MAX_RECENT_FILES = 20


@dataclass(slots=True)
class AppConfig:
    # recent_files is persisted but not yet surfaced in the GUI; it is
    # reserved for the session/recent-files workflow (roadmap phase 5).
    recent_files: list[str] = field(default_factory=list)
    last_export_dir: str = ""

    @classmethod
    def load(cls) -> "AppConfig":
        path = cls.path()
        try:
            if not path.is_file() or path.stat().st_size > MAX_CONFIG_BYTES:
                return cls()
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return cls()
            known = {item.name for item in fields(cls)}
            config = cls(**{key: value for key, value in data.items() if key in known})
            if not isinstance(config.recent_files, list) or not isinstance(
                config.last_export_dir, str
            ):
                return cls()
            config.recent_files = [
                item for item in config.recent_files if isinstance(item, str)
            ][:MAX_RECENT_FILES]
            return config
        except (OSError, ValueError, TypeError, RecursionError, MemoryError):
            return cls()

    def save(self) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @staticmethod
    def path() -> Path:
        return Path(user_config_dir("ChopScout", "ChopScout")) / "config.json"
