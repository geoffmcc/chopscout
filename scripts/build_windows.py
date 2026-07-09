from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
command = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
    "--name", "ChopScout-MPC", "--paths", str(root / "src"),
    str(root / "src" / "chopscout" / "app.py"),
]
ffmpeg_dir = root / "tools" / "ffmpeg" / "bin"
if ffmpeg_dir.exists():
    separator = ";" if os.name == "nt" else ":"
    command += ["--add-binary", f"{ffmpeg_dir}{separator}tools/ffmpeg/bin"]
raise SystemExit(subprocess.call(command, cwd=root))
