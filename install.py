#!/usr/bin/env python3
"""Create user launchers that run this checkout; no sudo required."""

import os
from pathlib import Path
import shlex
import subprocess
import sys


def desktop_quote(value: str) -> str:
    value = value.replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("`", "\\`").replace("$", "\\$").replace("%", "%%")
    return f'"{value}"'


def main() -> None:
    source = Path(__file__).resolve().parent / "locate-search.py"
    if not source.is_file():
        raise SystemExit(f"Application not found: {source}")
    command = f"{desktop_quote(sys.executable)} {desktop_quote(str(source))}"
    entry = (
        "[Desktop Entry]\n"
        "Version=1.0\nType=Application\nName=Locate Search\n"
        "GenericName=File Search\n"
        "Comment=Search filenames quickly with the locate index\n"
        f"Exec={command}\n"
        "Icon=system-search\nTerminal=false\n"
        "Categories=Utility;FileTools;\n"
        "Keywords=search;find;locate;files;everything;\n"
    )
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    application = data_home / "applications/locate-search.desktop"
    application.parent.mkdir(parents=True, exist_ok=True)
    application.write_text(entry, encoding="utf-8")
    print(f"Applications launcher: {application}")

    result = subprocess.run(
        ["xdg-user-dir", "DESKTOP"], check=True, text=True, capture_output=True
    )
    desktop = Path(result.stdout.strip())
    if not desktop.is_absolute():
        raise SystemExit("xdg-user-dir did not return an absolute desktop path.")
    if desktop == Path.home():
        print("Desktop directory is disabled; only the Applications entry was installed.")
    else:
        desktop.mkdir(parents=True, exist_ok=True)
        launcher = desktop / application.name
        launcher.write_text(entry, encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | 0o100)
        print(f"Desktop launcher: {launcher}")
        print("If prompted, right-click the icon and choose Allow Launching.")
    print("Custom keyboard shortcut command:")
    print(shlex.join([sys.executable, str(source)]))


if __name__ == "__main__":
    main()
