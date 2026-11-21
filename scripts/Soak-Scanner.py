"""Exercise local OCR against synthetic notifications without a game or driver."""

import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from droidops.scan_limits import MAX_WORKER_BYTES, configure_native_threads


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=180)
    parser.add_argument("--report", default="artifacts/scanner-soak.json")
    parser.add_argument(
        "--secondary", action="store_true", help="Opt into the experimental third-party OCR runtime"
    )
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error("--seconds must be between 1 and 3600")
    configure_native_threads()
    import psutil
    from PIL import Image, ImageDraw, ImageFont
    from tesserocr import OEM, PSM, PyTessBaseAPI
    from droidops.droid_alert import Word, cautious_label_repair, matching_droids, recognise
    from droidops.hybrid_droid_detection import RapidFallback
    from droidops.resources import asset_path

    font_path = (
        str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf")
        if os.name == "nt"
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    font = ImageFont.truetype(font_path, 30)
    process = psutil.Process()
    rapid = RapidFallback(enabled=args.secondary)
    if args.secondary and not rapid.enabled:
        raise RuntimeError("Secondary OCR could not initialise: " + str(rapid.disabled_reason))
    started = time.monotonic()
    samples, failures, cycles = [], [], 0
    labels = [("Kyber", "Mythic"), ("Diamond", "Mythic"), ("Rainbow", "Legendary")]
    backgrounds = [(8, 12, 20), (45, 70, 100), (55, 25, 16)]
    with PyTessBaseAPI(
        path=str(asset_path("tessdata")), lang="eng", oem=OEM.LSTM_ONLY, psm=PSM.SPARSE_TEXT
    ) as ocr:
        while time.monotonic() - started < args.seconds:
            began = time.monotonic()
            variant, rarity = labels[cycles % len(labels)]
            image = Image.new("RGB", (1280, 120), backgrounds[cycles % len(backgrounds)])
            ImageDraw.Draw(image).text(
                (12, 35),
                f"{variant} Droid {rarity} has spawned at the Sandcrawler",
                font=font,
                fill=(255, 170 + cycles % 70, 220),
                stroke_width=1,
                stroke_fill="black",
            )
            expected = f"{variant} {rarity}"
            primary = recognise(ocr, None, (0, 0), image=image)
            words = rapid.read(image, (0, 0), Word, cautious_label_repair, min_gap=0)
            secondary = matching_droids(words)
            if expected not in {m.pair for m in primary} or (
                args.secondary and expected not in {m.pair for m in secondary}
            ):
                failures.append(
                    {
                        "cycle": cycles,
                        "expected": expected,
                        "primary": [m.pair for m in primary],
                        "secondary": [m.pair for m in secondary],
                    }
                )
            rss = process.memory_info().rss
            samples.append(
                {
                    "seconds": round(time.monotonic() - started, 2),
                    "rss_bytes": rss,
                    "threads": process.num_threads(),
                }
            )
            if rss > MAX_WORKER_BYTES:
                raise RuntimeError("OCR exceeded the scanner memory budget")
            cycles += 1
            time.sleep(min(1.0, max(0.03, time.monotonic() - began)))
    warm = [s["rss_bytes"] for s in samples if s["seconds"] >= 30]
    report = {
        "platform": sys.platform,
        "secondary_ocr_tested": args.secondary,
        "duration_seconds": round(time.monotonic() - started, 2),
        "cycles": cycles,
        "peak_rss_mb": round(max(s["rss_bytes"] for s in samples) / 2**20, 2),
        "warm_rss_span_mb": round((max(warm) - min(warm)) / 2**20, 2) if warm else None,
        "max_threads": max(s["threads"] for s in samples),
        "recognition_failures": failures,
        "scope": "Synthetic OCR only; no Windows capture, virtual-controller driver or game exercised.",
        "samples": samples,
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {k: v for k, v in report.items() if k not in ("samples", "recognition_failures")}
    summary["recognition_failure_count"] = len(failures)
    summary["first_failures"] = failures[:5]
    print(json.dumps(summary, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
