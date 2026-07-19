from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from platformdirs import user_config_dir

MAX_CONFIG_BYTES = 1_000_000
MAX_RECENT_FILES = 20


@dataclass(slots=True)
class AppConfig:
    recent_files: list[str] = field(default_factory=list)
    last_export_dir: str = ""
    last_session_dir: str = ""

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
            if (
                not isinstance(config.recent_files, list)
                or not isinstance(config.last_export_dir, str)
                or not isinstance(config.last_session_dir, str)
            ):
                return cls()
            config.recent_files = [
                item for item in config.recent_files if isinstance(item, str)
            ][:MAX_RECENT_FILES]
            return config
        except (OSError, ValueError, TypeError, RecursionError, MemoryError):
            return cls()

    def add_recent_file(self, path: str | Path) -> None:
        """Promote a session file to the front of the recent list, deduped and capped."""
        value = str(path)
        self.recent_files = [value] + [item for item in self.recent_files if item != value]
        del self.recent_files[MAX_RECENT_FILES:]

    def save(self) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @staticmethod
    def path() -> Path:
        return Path(user_config_dir("ChopScout", "ChopScout")) / "config.json"
