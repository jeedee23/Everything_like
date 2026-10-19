#!/usr/bin/env python3
"""Build an architecture-independent Debian package without root."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def main() -> None:
    source = Path(__file__).resolve().parent
    version = (source / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        raise SystemExit(f"Invalid package version: {version!r}")
    subprocess.run(["dpkg", "--validate-version", version], check=True)
    output = source / "dist" / f"locate-search_{version}_all.deb"
    output.parent.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment.setdefault("SOURCE_DATE_EPOCH", "1792368000")
    with tempfile.TemporaryDirectory(prefix="locate-search-deb-") as temporary:
        root = Path(temporary) / "package"
        for directory in ("DEBIAN", "usr/bin", "usr/share/applications",
                          "usr/share/doc/locate-search"):
            (root / directory).mkdir(parents=True, exist_ok=True)
        executable = root / "usr/bin/locate-search"
        shutil.copyfile(source / "locate-search.py", executable)
        executable.chmod(0o755)
        shutil.copyfile(source / "README.md", root / "usr/share/doc/locate-search/README.md")
        (root / "usr/share/applications/locate-search.desktop").write_text(
            "[Desktop Entry]\n"
            "Version=1.0\nType=Application\nName=Locate Search\n"
            "GenericName=File Search\n"
            "Comment=Search filenames quickly with the locate index\n"
            "Exec=/usr/bin/locate-search\nIcon=system-search\nTerminal=false\n"
            "Categories=Utility;FileTools;\n"
            "Keywords=search;find;locate;files;everything;\n",
            encoding="utf-8",
        )
        size = sum(path.stat().st_size for path in (root / "usr").rglob("*") if path.is_file())
        (root / "DEBIAN/control").write_text(
            "Package: locate-search\n"
            f"Version: {version}\n"
            "Section: utils\nPriority: optional\nArchitecture: all\n"
            "Maintainer: Johan Degraeve <38980341+jeedee23@users.noreply.github.com>\n"
            "Depends: python3 (>= 3.10), python3-tk, plocate, xdg-utils\n"
            f"Installed-Size: {(size + 1023) // 1024}\n"
            "Homepage: https://github.com/jeedee23/Everything_like\n"
            "Description: Lightweight indexed filename search for Linux desktops\n"
            " Tkinter desktop application backed by plocate, featuring wildcard and\n"
            " AND search, category filters, sortable columns and appearance controls.\n",
            encoding="utf-8",
        )
        for path in root.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
            elif path != executable:
                path.chmod(0o644)
            os.utime(path, (int(environment["SOURCE_DATE_EPOCH"]),) * 2)
        root.chmod(0o755)
        os.utime(root, (int(environment["SOURCE_DATE_EPOCH"]),) * 2)
        subprocess.run(
            ["dpkg-deb", "--root-owner-group", "--build", str(root), str(output)],
            check=True, env=environment,
        )
    print(output)


if __name__ == "__main__":
    main()
