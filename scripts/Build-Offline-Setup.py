"""Compile the offline Windows installer with NSIS on Windows or Linux."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from droidops import __version__


def escaped(value):
    return value.replace("$", "$$").replace('"', '$\\"')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nsis-dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    payload = args.payload.resolve()
    files = sorted(p for p in payload.rglob("*") if p.is_file())
    if not (payload / "DroidOps.exe").is_file():
        raise SystemExit("Assemble the Windows payload first.")
    lines, directories = [], set()
    for file in files:
        relative = str(file.relative_to(payload)).replace("/", "\\")
        lines.append(f'Delete "$INSTDIR\\{escaped(relative)}"')
        for parent in file.parents:
            if parent == payload:
                break
            directories.add(parent)
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        relative = str(directory.relative_to(payload)).replace("/", "\\")
        lines.append(f'RMDir "$INSTDIR\\{escaped(relative)}"')
    listing = root / "artifacts/offline-uninstall-files.nsh"
    listing.parent.mkdir(exist_ok=True)
    listing.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = os.environ.copy()
    if args.nsis_dir:
        env["NSISDIR"] = str(args.nsis_dir.resolve())
    command = [
        str(args.compiler.resolve()),
        "-V3",
        f"-DVERSION={__version__}",
        f"-DPAYLOAD={payload}",
        f"-DOUTPUT={args.output.resolve()}",
        f"-DUNINSTALL_LIST={listing}",
        str(root / "packaging/DroidOps-Offline.nsi"),
    ]
    subprocess.run(command, env=env, check=True)


if __name__ == "__main__":
    main()
