"""Write the Windows version resource used by PyInstaller."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from droidops import __version__

parts = tuple(map(int, __version__.split("."))) + (0,)
text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, mask=0x3f, flags=0,
                   OS=0x40004, fileType=0x1, subtype=0, date=(0,0)),
  kids=[StringFileInfo([StringTable('080904B0', [
    StringStruct('CompanyName', 'Danksy'),
    StringStruct('FileDescription', 'Danksy DroidOps'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('InternalName', 'DroidTycoonDroidOps'),
    StringStruct('LegalCopyright', 'Copyright 2026 Danksy'),
    StringStruct('OriginalFilename', 'DroidTycoonDroidOps.exe'),
    StringStruct('ProductName', 'Droid Tycoon DroidOps'),
    StringStruct('ProductVersion', '{__version__}')
  ])]), VarFileInfo([VarStruct('Translation', [2057, 1200])])]
)
"""
dest = Path(__file__).resolve().parents[1] / "artifacts/version-info.txt"
dest.parent.mkdir(exist_ok=True)
dest.write_text(text, encoding="utf-8")
