from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from platformdirs import user_config_dir


@dataclass(slots=True)
class AppConfig:
    recent_files: list[str]
    last_export_dir: str = ""
    theme: str = "dark"

    @classmethod
    def load(cls) -> "AppConfig":
        path = cls.path()
        if not path.exists():
            return cls(recent_files=[])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(**data)
        except (OSError, ValueError, TypeError):
            return cls(recent_files=[])

    def save(self) -> None:
        path = self.path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @staticmethod
    def path() -> Path:
        return Path(user_config_dir("ChopScout", "ChopScout")) / "config.json"
