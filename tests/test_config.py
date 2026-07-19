"""AppConfig persistence and tolerant-load tests."""

import json
from pathlib import Path

import pytest

from chopscout.config import AppConfig


@pytest.fixture()
def config_path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "config.json"
    monkeypatch.setattr(AppConfig, "path", staticmethod(lambda: path))
    return path


def test_missing_config_loads_defaults(config_path: Path):
    config = AppConfig.load()
    assert config.recent_files == []
    assert config.last_export_dir == ""


def test_round_trip_preserves_values(config_path: Path):
    config = AppConfig(recent_files=["a.wav"], last_export_dir="D:/exports")
    config.save()
    loaded = AppConfig.load()
    assert loaded.recent_files == ["a.wav"]
    assert loaded.last_export_dir == "D:/exports"


def test_legacy_config_with_unknown_keys_still_loads(config_path: Path):
    config_path.write_text(
        json.dumps(
            {
                "recent_files": ["old.wav"],
                "last_export_dir": "C:/old",
                "theme": "dark",
                "future_key": {"nested": True},
            }
        ),
        encoding="utf-8",
    )
    loaded = AppConfig.load()
    assert loaded.recent_files == ["old.wav"]
    assert loaded.last_export_dir == "C:/old"


def test_wrong_typed_config_falls_back_to_defaults(config_path: Path):
    config_path.write_text(
        json.dumps({"recent_files": "not a list", "last_export_dir": 5}), encoding="utf-8"
    )
    loaded = AppConfig.load()
    assert loaded.recent_files == []
    assert loaded.last_export_dir == ""


def test_corrupt_config_falls_back_to_defaults(config_path: Path):
    config_path.write_text("{not json", encoding="utf-8")
    loaded = AppConfig.load()
    assert loaded.recent_files == []
    assert loaded.last_export_dir == ""


def test_deeply_nested_config_falls_back_to_defaults(config_path: Path):
    config_path.write_text("[" * 100_000, encoding="utf-8")
    loaded = AppConfig.load()
    assert loaded.recent_files == []
    assert loaded.last_export_dir == ""


def test_oversized_config_falls_back_to_defaults(config_path: Path):
    config_path.write_text("{" + " " * 2_000_000 + "}", encoding="utf-8")
    loaded = AppConfig.load()
    assert loaded.recent_files == []


def test_non_string_recent_files_entries_are_dropped(config_path: Path):
    config_path.write_text(
        json.dumps({"recent_files": [1, None, "ok.wav", {"x": 1}], "last_export_dir": ""}),
        encoding="utf-8",
    )
    loaded = AppConfig.load()
    assert loaded.recent_files == ["ok.wav"]


def test_recent_files_are_capped_at_twenty(config_path: Path):
    config_path.write_text(
        json.dumps({"recent_files": [f"{i}.wav" for i in range(50)], "last_export_dir": ""}),
        encoding="utf-8",
    )
    loaded = AppConfig.load()
    assert len(loaded.recent_files) == 20
    assert loaded.recent_files[0] == "0.wav"
