"""Assemble the offline Windows payload from pinned Windows wheels and CPython."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import zipfile


def unpack(archive, destination, prefix=""):
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            if item.is_dir() or not item.filename.startswith(prefix):
                continue
            name = item.filename[len(prefix) :]
            parts = Path(name).parts
            if not parts or ".." in parts or Path(name).is_absolute():
                raise ValueError("Unsafe archive member: " + name)
            if len(parts) > 2 and parts[0].endswith(".data"):
                if parts[1] in ("purelib", "platlib"):
                    name = str(Path(*parts[2:]))
                else:
                    continue
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(item))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheels", type=Path, required=True)
    parser.add_argument("--resolution", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--vgamepad", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for path, lock in [
        (args.runtime, "python-runtime.json"),
        (args.vgamepad, "vgamepad-source.json"),
    ]:
        expected = json.loads((root / "packaging" / lock).read_text())["sha256"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("Bundle input checksum mismatch: " + path.name)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    runtime = output / "runtime"
    unpack(args.runtime, runtime, "tools/")
    site = runtime / "Lib/site-packages"
    records = json.loads(args.resolution.read_text())["install"]
    inventory = []
    for record in records:
        info = record["download_info"]
        path = args.wheels / info["url"].rsplit("/", 1)[1]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != info["archive_info"]["hashes"]["sha256"]:
            raise ValueError("Wheel checksum mismatch: " + path.name)
        unpack(path, site)
        inventory.append(
            {
                "name": record["metadata"]["name"],
                "version": record["metadata"]["version"],
                "sha256": digest,
            }
        )
    with tarfile.open(args.vgamepad) as t:
        for member in t.getmembers():
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            if len(parts) > 2 and parts[1] == "vgamepad":
                destination = site / Path(*parts[1:])
            elif len(parts) == 2 and parts[1].lower().startswith(("license", "copying")):
                destination = site / "vgamepad-0.2.0.dist-info/licenses" / parts[1]
            elif parts[-1] == "PKG-INFO":
                destination = site / "vgamepad-0.2.0.dist-info/METADATA"
            else:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(t.extractfile(member).read())
    inventory.append(
        {
            "name": "vgamepad",
            "version": "0.2.0",
            "sha256": hashlib.sha256(args.vgamepad.read_bytes()).hexdigest(),
        }
    )
    shutil.copytree(
        root / "droidops",
        output / "droidops",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for name in ["LICENSE", "THIRD_PARTY_NOTICES.md", "PRIVACY.md"]:
        shutil.copyfile(root / name, output / name)
    shutil.copytree(root / "third_party", output / "third_party", dirs_exist_ok=True)
    shutil.copyfile(root / "docs/USER_GUIDE.md", output / "USER_GUIDE.md")
    shutil.copyfile(root / "Collect-Diagnostics.bat", output / "Collect-Diagnostics.bat")
    (output / "scripts").mkdir(exist_ok=True)
    shutil.copyfile(
        root / "scripts/Collect-Diagnostics.ps1", output / "scripts/Collect-Diagnostics.ps1"
    )
    shutil.copyfile(root / "docs/RESTART_DIAGNOSTICS.md", output / "RESTART_DIAGNOSTICS.md")
    driver = output / "Driver"
    driver.mkdir(exist_ok=True)
    for name in ["ViGEmBus_1.22.0_x64_x86_arm64.exe", "ViGEmBus-LICENSE.txt"]:
        shutil.copyfile(root / "packaging" / name, driver / name)
    shutil.copyfile(root / "droidops/assets/app.ico", output / "app.ico")
    stub = (site / "pip/_vendor/distlib/w64.exe").read_bytes()
    if "<launcher_dir>".encode("utf-16le") not in stub:
        raise ValueError("The Windows launcher does not support a relative bundled runtime")
    source = """import os, sys
sys.dont_write_bytecode = True
from pathlib import Path
root = Path(sys.argv[0]).resolve().parent
sys.path.insert(0, str(root))
os.chdir(root)
try:
    from droidops.launcher import main
    raise SystemExit(main())
except BaseException as error:
    if isinstance(error, SystemExit) and error.code in (None, 0):
        raise
    import ctypes, traceback
    log = Path(os.environ.get("LOCALAPPDATA", str(root))) / "DroidTycoonAutoClicker/startup-error.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(traceback.format_exc(), encoding="utf-8")
    ctypes.windll.user32.MessageBoxW(None, str(error) + "\\n\\nDetails: " + str(log), "Danksy DroidOps could not start", 16)
    raise
"""
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("__main__.py", source)
    (output / "DroidOps.exe").write_bytes(
        stub + b"#!<launcher_dir>\\runtime\\pythonw.exe\r\n" + payload.getvalue()
    )
    manifest = {
        "runtime": "CPython 3.14.10 Windows x64",
        "dependencies": inventory,
        "validation": "Assembled on Linux; Windows installation and live game response require verification.",
    }
    (output / "BUNDLE_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for cache in output.rglob("__pycache__"):
        if cache.is_dir():
            shutil.rmtree(cache)
    print(f"Offline Windows bundle assembled: {len(inventory)} dependencies", flush=True)


if __name__ == "__main__":
    main()
