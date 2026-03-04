from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    src_assets = repo_root / "src" / "watchback" / "assets"
    entrypoint = repo_root / "src" / "watchback" / "main.py"

    is_windows = platform.system().lower() == "windows"
    icon_file = src_assets / ("wbicon.ico" if is_windows else "wbicon.png")
    add_data_sep = ";" if is_windows else ":"
    add_data = f"{src_assets}{add_data_sep}assets"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name",
        "watchback",
        "--paths",
        "src",
        "--icon",
        str(icon_file),
        "--add-data",
        add_data,
        str(entrypoint),
    ]

    print("Building executable for host OS...")
    print(" ".join(cmd))

    result = subprocess.run(cmd, cwd=repo_root, check=False)
    if result.returncode != 0:
        print(f"Build failed with exit code {result.returncode}.", file=sys.stderr)
        return result.returncode

    if is_windows:
        output = repo_root / "dist" / "watchback.exe"
    else:
        output = repo_root / "dist" / "watchback"

    print(f"Build complete: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
