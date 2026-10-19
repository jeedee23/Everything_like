from contextlib import redirect_stdout
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
                redirect_stdout(io.StringIO()),
            ):
                install.main()
            menu = data / "applications/locate-search.desktop"
            launcher = desktop / "locate-search.desktop"
            self.assertEqual(menu.read_text(), launcher.read_text())
            self.assertIn(str(Path(install.__file__).parent), menu.read_text())
            self.assertTrue(os.access(launcher, os.X_OK))
            subprocess.run(["desktop-file-validate", str(launcher)], check=True)


if __name__ == "__main__":
    unittest.main()
