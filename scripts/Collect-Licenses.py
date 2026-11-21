"""Collect installed distribution notices and exact dependency versions."""

from importlib import metadata
from pathlib import Path
import json
import re
import shutil

root = Path(__file__).resolve().parents[1]
out = root / "artifacts/third-party"
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)
for notice in (root / "third_party").glob("*.txt"):
    shutil.copyfile(notice, out / notice.name)
inventory = []
for dist in sorted(metadata.distributions(), key=lambda d: d.metadata.get("Name", "").lower()):
    name = dist.metadata.get("Name", "unknown")
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    target = out / safe
    target.mkdir()
    files = []
    for entry in dist.files or ():
        parts = [str(p).lower() for p in Path(entry).parts]
        filename = Path(entry).name.lower()
        if not (
            any(p in ("licenses", "license_files") for p in parts)
            or filename.startswith(("license", "copying", "notice"))
            or filename.endswith(".lic")
        ):
            continue
        source = Path(dist.locate_file(entry))
        if not source.is_file():
            continue
        relative = Path(*[p for p in Path(entry).parts if p not in ("..", ".")])
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        files.append(str(dest.relative_to(out)))
    item = {
        "name": name,
        "version": dist.version,
        "license": dist.metadata.get("License-Expression") or dist.metadata.get("License") or "",
        "project_urls": dist.metadata.get_all("Project-URL") or [],
        "notice_files": files,
    }
    (target / "metadata.json").write_text(json.dumps(item, indent=2), encoding="utf-8")
    inventory.append(item)
shutil.copyfile(root / "packaging/ViGEmBus-LICENSE.txt", out / "ViGEmBus-LICENSE.txt")
(out / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")
print(f"Collected metadata and available notices for {len(inventory)} distributions")
