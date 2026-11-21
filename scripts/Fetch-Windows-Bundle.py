"""Download and check the pinned inputs for the offline Windows installer."""

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen


def verify(path, digest):
    if not path.is_file():
        return False
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest() == digest


def fetch(url, digest, destination, verify_only=False):
    if verify(destination, digest):
        print("Checked:", destination.name, flush=True)
        return
    if verify_only:
        raise ValueError("Missing file or checksum mismatch: " + str(destination))
    if urlsplit(url).scheme != "https":
        raise ValueError("Bundle downloads must use HTTPS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    try:
        with urlopen(url, timeout=120) as response, temporary.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
        if not verify(temporary, digest):
            raise ValueError("Download checksum mismatch: " + destination.name)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    print("Downloaded and checked:", destination.name, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("bundle-inputs"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    runtime = json.loads((root / "packaging/python-runtime.json").read_text())
    gamepad = json.loads((root / "packaging/vgamepad-source.json").read_text())
    records = json.loads((root / "packaging/windows-bundle-lock.json").read_text())["install"]
    inputs = [
        (runtime["url"], runtime["sha256"], args.output / "python-runtime.nupkg"),
        (gamepad["url"], gamepad["sha256"], args.output / "vgamepad.tar.gz"),
    ]
    for record in records:
        info = record["download_info"]
        name = unquote(urlsplit(info["url"]).path.rsplit("/", 1)[1])
        if Path(name).name != name or not name.endswith(".whl"):
            raise ValueError("Invalid wheel filename: " + name)
        inputs.append(
            (info["url"], info["archive_info"]["hashes"]["sha256"], args.output / "wheels" / name)
        )
    for url, digest, destination in inputs:
        fetch(url, digest, destination, args.verify_only)
    driver = json.loads((root / "packaging/driver.json").read_text())
    if not verify(root / "packaging" / driver["name"], driver["sha256"]):
        raise ValueError("Bundled controller-driver checksum mismatch")
    print("All bundle inputs and the controller driver passed SHA-256 checks.")


if __name__ == "__main__":
    main()
