"""Non-interactive Windows runtime smoke checks for the packaged DroidOps EXE.

No game is launched, no virtual-controller input is sent, and no rare-droid
notification is simulated as an actual detection.  This validates installed
components and the UI's ability to initialise; gameplay must be tested separately.
"""

import importlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import time


def _child_probe(q):
    q.put(("ready", os.getpid()))


def run_self_check(report_path=None, *, desktop=True):
    started = time.time()
    checks = []
    report_path = report_path or str(Path(tempfile.gettempdir()) / "DroidOps_Runtime_Check.json")
    os.environ["DROIDOPS_HEALTH_CHECK"] = "1"

    def check(name, action):
        before = time.perf_counter()
        try:
            note = action()
            checks.append(
                {
                    "name": name,
                    "passed": True,
                    "elapsed_ms": round(1000 * (time.perf_counter() - before)),
                    "detail": str(note or "OK")[:350],
                }
            )
        except Exception as exc:
            checks.append(
                {
                    "name": name,
                    "passed": False,
                    "elapsed_ms": round(1000 * (time.perf_counter() - before)),
                    "detail": f"{type(exc).__name__}: {exc}"[:500],
                }
            )

    def assets():
        root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
        mandatory = [
            "app.ico",
            "hero_droid.png",
            "mono_spritesheet.png",
            "tessdata/eng.traineddata",
            "droid_alerts/kyber_mythic.wav",
            "droid_alerts/scourge_legendary.wav",
        ]
        absent = [name for name in mandatory if not (root / name).is_file()]
        if absent:
            raise FileNotFoundError("Missing bundled resources: " + ", ".join(absent))
        return f"{len(mandatory)} required resources present"

    def native_modules():
        names = [
            "numpy",
            "cv2",
            "tesserocr",
            "PIL.Image",
            "mss",
            "psutil",
            "PySide6.QtWidgets",
            "vgamepad",
        ]
        for name in names:
            importlib.import_module(name)
        return f"{len(names)} Python/native components importable"

    def primary_ocr():
        from PIL import Image, ImageDraw, ImageFont
        from tesserocr import PyTessBaseAPI, PSM, OEM

        root = (
            Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets" / "tessdata"
        )
        canvas = Image.new("RGB", (700, 160), "white")
        painter = ImageDraw.Draw(canvas)
        painter.text(
            (20, 30),
            "KYBER MYTHIC",
            fill="black",
            font=ImageFont.truetype(
                str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"), 58
            ),
        )
        with PyTessBaseAPI(
            path=str(root), lang="eng", oem=OEM.LSTM_ONLY, psm=PSM.SINGLE_LINE
        ) as engine:
            engine.SetImage(canvas)
            output = engine.GetUTF8Text().upper().strip()
        if not ("KYBER" in output and "MYTHIC" in output):
            raise RuntimeError("Tesseract did not read test label: " + repr(output[:120]))
        return "Synthetic Kyber Mythic text recognised by bundled Tesseract"

    def secondary_ocr():
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
        from rapidocr import RapidOCR

        canvas = Image.new("RGB", (720, 180), "white")
        ImageDraw.Draw(canvas).text(
            (25, 45),
            "KYBER MYTHIC",
            fill="black",
            font=ImageFont.truetype(
                str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arial.ttf"), 58
            ),
        )
        from .scan_limits import configure_native_threads, rapid_cpu_parameters

        configure_native_threads()
        import onnxruntime

        onnxruntime.disable_telemetry_events()
        engine = RapidOCR(params=rapid_cpu_parameters())
        result = engine(np.array(canvas), use_cls=False)
        if result is None or not hasattr(result, "txts"):
            raise RuntimeError("RapidOCR returned no structured result")
        output = " ".join(result.txts or ()).upper()
        if "KYBER" not in output or "MYTHIC" not in output:
            raise RuntimeError("RapidOCR did not recognise the test label: " + repr(output))
        return "RapidOCR models loaded and ONNX inference executed"

    def desktop_capture():
        from mss import MSS

        with MSS() as capture:
            screens = capture.monitors
            if len(screens) < 2:
                raise RuntimeError("No physical display available for capture")
            screen = screens[1]
            sample = capture.grab(
                {
                    "left": screen["left"],
                    "top": screen["top"],
                    "width": min(screen["width"], 48),
                    "height": min(screen["height"], 48),
                }
            )
            if sample.width < 1 or sample.height < 1:
                raise RuntimeError("MSS returned an empty frame")
            return f"{len(screens) - 1} monitor(s) available; capture {sample.width}x{sample.height} successful"

    def scanner_subprocess():
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue(maxsize=2)
        child = ctx.Process(target=_child_probe, args=(q,), name="DroidOpsSelfTest", daemon=True)
        child.start()
        try:
            kind, pid = q.get(timeout=12)
            if kind != "ready":
                raise RuntimeError(f"Unexpected subprocess response: {kind}")
            child.join(5)
            if child.is_alive() or child.exitcode != 0:
                raise RuntimeError(
                    f"Scanner-style process did not exit normally ({child.exitcode})"
                )
            return f"Independent Python worker launched and returned result (pid {pid})"
        finally:
            if child.is_alive():
                child.terminate()
                child.join(3)
            q.close()
            q.join_thread()

    def gui():
        # app.py is the executing __main__ module; importing app.py again would
        # duplicate class definitions and its Windows-side initialisation.
        from . import app as app_main
        from PySide6.QtWidgets import QApplication

        qt = QApplication.instance() or QApplication(["DroidOps runtime check"])
        window = app_main.Clicker()
        try:
            qt.processEvents()
            if window.windowTitle() != "Droid Tycoon DroidOps":
                raise RuntimeError("Unexpected application title")
            if not window.watch_btn or "DROID WATCH" not in window.watch_btn.text():
                raise RuntimeError("Watch Droid control failed to initialise")
            if not window.cb23_btn or not window.start_btn:
                raise RuntimeError("CB-23 / Auto Scrap controls unavailable")
            return "DroidOps GUI and all three primary controls initialised"
        finally:
            window.close()
            qt.processEvents()

    check("Bundled detection resources", assets)
    check("Native imports and OCR dependencies", native_modules)
    check("Tesseract OCR inference", primary_ocr)
    if os.environ.get("DROIDOPS_CHECK_SECONDARY_OCR") == "1":
        check("RapidOCR ONNX inference (optional)", secondary_ocr)
    if desktop:
        check("Desktop screenshot capture", desktop_capture)
    check("Separate scanner-process startup", scanner_subprocess)
    check("Main window and control initialization", gui)

    report = {
        "application": "Droid Tycoon DroidOps",
        "verified_executable": sys.executable,
        "mode": "Windows desktop check" if desktop else "Windows build check",
        "started_unix": started,
        "duration_seconds": round(time.time() - started, 2),
        "ok": all(c["passed"] for c in checks),
        "checks": checks,
        "desktop_capture_tested": desktop,
        "not_tested": [
            "Optional secondary OCR unless DROIDOPS_CHECK_SECONDARY_OCR=1",
            "Live Fortnite notifications and OCR accuracy in gameplay",
            "Detection when Fortnite is minimised or covered",
            "Virtual-controller movement inside Fortnite",
            "Rare-droid audio playback volume",
        ],
    }
    dest = Path(report_path)
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError:
        return 2
    return 0 if report["ok"] else 1
