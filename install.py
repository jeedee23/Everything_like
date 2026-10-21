#!/usr/bin/env python3
"""Create user launchers and a GNOME shortcut; no sudo required."""

import ast
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys


def install_shortcut(command: str) -> None:
    if "GNOME" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":"):
        print("Shortcut not installed: automatic setup requires a GNOME session.")
        return
    if shutil.which("gsettings") is None:
        raise SystemExit("Shortcut not installed: gsettings is unavailable.")

    schema = "org.gnome.settings-daemon.plugins.media-keys"
    custom_schema = schema + ".custom-keybinding"
    path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/locate-search/"
    binding = "<Control><Shift><Alt>f"

    def setting(action: str, target: str, key: str, value: str | None = None) -> str:
        arguments = ["gsettings", action, target, key]
        if value is not None:
            arguments.append(value)
        return subprocess.run(
            arguments, check=True, text=True, capture_output=True
        ).stdout.strip()

    def read(target: str, key: str) -> object:
        value = setting("get", target, key)
        return ast.literal_eval(value.removeprefix("@as "))

    def normalized(value: str) -> tuple[tuple[str, ...], str]:
        modifiers = value.lower().split(">")
        aliases = {"ctrl": "control", "primary": "control", "mod1": "alt"}
        return (
            tuple(sorted(aliases.get(item.lstrip("<"), item.lstrip("<"))
                         for item in modifiers[:-1])),
            modifiers[-1],
        )

    paths = read(schema, "custom-keybindings")
    if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
        raise SystemExit("Shortcut not installed: unexpected GNOME shortcut list.")
    target = f"{custom_schema}:{path}"
    for existing in dict.fromkeys([*paths, path]):
        existing_target = f"{custom_schema}:{existing}"
        existing_command = read(existing_target, "command")
        existing_binding = read(existing_target, "binding")
        if not isinstance(existing_binding, str):
            raise SystemExit("Shortcut not installed: unexpected GNOME key binding.")
        if existing == path and existing_command not in ("", command):
            raise SystemExit("Shortcut not installed: Locate Search shortcut path is already in use.")
        if (existing != path and normalized(existing_binding) == normalized(binding)
                and existing_command != command):
            raise SystemExit(
                f"Shortcut not installed: Ctrl+Shift+Alt+F is already assigned at {existing}."
            )

    for owner, key in [(schema, "custom-keybindings"),
                       (target, "name"), (target, "command"), (target, "binding")]:
        if setting("writable", owner, key) != "true":
            raise SystemExit(f"Shortcut not installed: GNOME setting {key} is locked.")
    for key, value in [("name", "Locate Search"), ("command", command), ("binding", binding)]:
        setting("set", target, key, repr(value))
    if path not in paths:
        setting("set", schema, "custom-keybindings", repr([*paths, path]))
    print("Keyboard shortcut installed: Ctrl+Shift+Alt+F")


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
    shortcut_command = shlex.join([sys.executable, str(source)])
    print(shortcut_command)
    install_shortcut(shortcut_command)


if __name__ == "__main__":
    main()
