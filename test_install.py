from contextlib import redirect_stdout
import ast
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import install


class InstallerTests(unittest.TestCase):
    def test_quoted_desktop_arguments(self) -> None:
        self.assertEqual(
            install.desktop_quote('/tmp/a b/"$`%\\.py'),
            '"/tmp/a b/\\"\\$\\`%%\\\\.py"',
        )

    def test_user_launchers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            desktop = base / "Desktop"
            data = base / "data"
            result = subprocess.CompletedProcess([], 0, str(desktop) + "\n", "")
            with (
                patch.dict(os.environ, {"XDG_DATA_HOME": str(data)}),
                patch.object(install.subprocess, "run", return_value=result),
                patch.object(install, "install_shortcut") as shortcut,
                redirect_stdout(io.StringIO()),
            ):
                install.main()
                shortcut.assert_called_once()
            menu = data / "applications/locate-search.desktop"
            launcher = desktop / "locate-search.desktop"
            self.assertEqual(menu.read_text(), launcher.read_text())
            self.assertIn(str(Path(install.__file__).parent), menu.read_text())
            self.assertTrue(os.access(launcher, os.X_OK))
            subprocess.run(["desktop-file-validate", str(launcher)], check=True)

    def run_shortcut(self, state: dict, command: str = "/usr/bin/python3 /tmp/app.py") -> None:
        def run(arguments, **kwargs):
            _, action, schema, key, *values = arguments
            if action == "get":
                output = repr(state.get((schema, key), ""))
            elif action == "writable":
                output = "true"
            elif action == "set":
                state[schema, key] = ast.literal_eval(values[0])
                output = ""
            else:
                self.fail(f"Unexpected gsettings action: {action}")
            return subprocess.CompletedProcess(arguments, 0, output + "\n", "")

        with (
            patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}),
            patch.object(install.shutil, "which", return_value="/usr/bin/gsettings"),
            patch.object(install.subprocess, "run", side_effect=run),
            redirect_stdout(io.StringIO()),
        ):
            install.install_shortcut(command)

    def test_shortcut_preserves_existing_and_is_idempotent(self) -> None:
        schema = "org.gnome.settings-daemon.plugins.media-keys"
        existing = "/custom/other/"
        state = {(schema, "custom-keybindings"): [existing]}
        self.run_shortcut(state)
        first = dict(state)
        self.run_shortcut(state)
        self.assertEqual(state, first)
        paths = state[schema, "custom-keybindings"]
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0], existing)
        target = f"{schema}.custom-keybinding:{paths[1]}"
        self.assertEqual(state[target, "binding"], "<Control><Shift><Alt>f")
        self.assertEqual(state[target, "command"], "/usr/bin/python3 /tmp/app.py")

    def test_conflicting_shortcut_is_not_modified(self) -> None:
        schema = "org.gnome.settings-daemon.plugins.media-keys"
        path = "/custom/other/"
        target = f"{schema}.custom-keybinding:{path}"
        state = {
            (schema, "custom-keybindings"): [path],
            (target, "binding"): "<Alt><Primary><Shift>F",
            (target, "command"): "another-app",
        }
        before = dict(state)
        with self.assertRaisesRegex(SystemExit, "already assigned"):
            self.run_shortcut(state)
        self.assertEqual(state, before)

    def test_owned_path_is_not_overwritten(self) -> None:
        schema = "org.gnome.settings-daemon.plugins.media-keys"
        path = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/locate-search/"
        state = {
            (schema, "custom-keybindings"): [],
            (f"{schema}.custom-keybinding:{path}", "command"): "another-app",
        }
        before = dict(state)
        with self.assertRaisesRegex(SystemExit, "already in use"):
            self.run_shortcut(state)
        self.assertEqual(state, before)

    def test_non_gnome_reports_manual_setup(self) -> None:
        with (
            patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}),
            patch.object(install.subprocess, "run") as run,
            redirect_stdout(io.StringIO()) as output,
        ):
            install.install_shortcut("app")
        run.assert_not_called()
        self.assertIn("requires a GNOME session", output.getvalue())


if __name__ == "__main__":
    unittest.main()
