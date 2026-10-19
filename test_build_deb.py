from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import build_deb


class DebianPackageTests(unittest.TestCase):
    def test_build_and_extract(self) -> None:
        build_deb.main()
        source = Path(__file__).resolve().parent
        version = (source / "VERSION").read_text().strip()
        package = source / "dist" / f"locate-search_{version}_all.deb"
        fields = subprocess.check_output(
            ["dpkg-deb", "-f", str(package), "Package", "Version", "Architecture", "Depends"],
            text=True,
        )
        self.assertIn("Package: locate-search", fields)
        self.assertIn(f"Version: {version}", fields)
        self.assertIn("Architecture: all", fields)
        self.assertIn("python3 (>= 3.10), python3-tk, plocate, xdg-utils", fields)
        with tempfile.TemporaryDirectory(prefix="locate-search-package-test-") as temporary:
            root = Path(temporary)
            subprocess.run(["dpkg-deb", "-x", str(package), temporary], check=True)
            executable = root / "usr/bin/locate-search"
            self.assertEqual(executable.read_bytes(), (source / "locate-search.py").read_bytes())
            self.assertEqual(executable.stat().st_mode & 0o777, 0o755)
            subprocess.run([sys.executable, "-B", str(executable), "--self-test"], check=True)
            subprocess.run(
                ["desktop-file-validate",
                 str(root / "usr/share/applications/locate-search.desktop")],
                check=True,
            )


if __name__ == "__main__":
    unittest.main()
