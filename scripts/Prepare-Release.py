"""Create a portable archive and SHA-256 checksums from a completed build."""

from pathlib import Path
import hashlib
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from droidops import __version__

root = Path(__file__).resolve().parents[1]
bundle = root / "dist/DroidTycoonDroidOps"
if not (bundle / "DroidTycoonDroidOps.exe").is_file():
    raise SystemExit("Build the Windows executable before preparing a release.")
shutil.copyfile(root / "LICENSE", bundle / "LICENSE")
shutil.copyfile(root / "THIRD_PARTY_NOTICES.md", bundle / "THIRD_PARTY_NOTICES.md")
shutil.copyfile(root / "docs/USER_GUIDE.md", bundle / "USER_GUIDE.md")
shutil.copyfile(root / "PRIVACY.md", bundle / "PRIVACY.md")
shutil.copyfile(root / "Collect-Diagnostics.bat", bundle / "Collect-Diagnostics.bat")
(bundle / "scripts").mkdir(exist_ok=True)
shutil.copyfile(
    root / "scripts/Collect-Diagnostics.ps1", bundle / "scripts/Collect-Diagnostics.ps1"
)
shutil.copyfile(root / "docs/RESTART_DIAGNOSTICS.md", bundle / "RESTART_DIAGNOSTICS.md")
driver = bundle / "Driver"
driver.mkdir(exist_ok=True)
for name in ("ViGEmBus_1.22.0_x64_x86_arm64.exe", "ViGEmBus-LICENSE.txt"):
    shutil.copyfile(root / "packaging" / name, driver / name)
# Keep replaceable third-party libraries and their notices alongside the EXE.
release = root / "release"
release.mkdir(exist_ok=True)
archive = shutil.make_archive(
    str(release / f"Danksy_DroidOps_{__version__}_Portable"),
    "zip",
    root_dir=bundle.parent,
    base_dir=bundle.name,
)
setup = release / f"Danksy_DroidOps_{__version__}_Setup.exe"
if not setup.is_file():
    raise SystemExit("The installer was not produced; refusing an incomplete release.")
paths = [Path(archive), setup]
(release / "SHA256SUMS.txt").write_text(
    "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in paths),
    encoding="utf-8",
)
print("Release files:", ", ".join(p.name for p in paths))
