"""Resource paths for source, wheel and frozen application installs."""

from pathlib import Path
import sys


def asset_path(name):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / "assets" / name
