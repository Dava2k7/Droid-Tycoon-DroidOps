"""Notification OCR fallback, learned visual hints and local diagnostic evidence.

No game-process access. The game must be visibly rendered in the selected area.
This module has no GUI dependencies and is safe to import in a Windows worker.
"""

from __future__ import annotations

from pathlib import Path
import json
import logging
import os
import queue
import re
import tempfile
import threading
import time

from .droid_catalog import VARIANTS, RARITIES
from .scan_limits import rapid_cpu_parameters


def rapidocr_words(engine, image, origin, Word, cautious_repair):
    """Convert RapidOCR text lines into positioned tokens for existing match rules.

    RapidOCR publishes line polygons, not necessarily word coordinates. Positions
    are approximated by character offsets; uncertain geometry requires repeat
    confirmation via the existing tracker before an alert is issued.
    """
    try:
        result = engine(image, use_cls=False)
        boxes = result.boxes if result is not None else None
        txts = result.txts if result is not None else None
        scores = result.scores if result is not None else None
    except Exception:
        raise
    if boxes is None or txts is None or scores is None:
        return []
    parsed = []
    for points, text, score in zip(boxes, txts, scores):
        if score is None or float(score) < 0.58 or not text:
            continue
        xs, ys = [float(p[0]) for p in points], [float(p[1]) for p in points]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x1 <= x0 or y1 <= y0:
            continue
        line = str(text).casefold()
        # Use character-proportional coordinates only for within-line pairing.
        for m in re.finditer(r"[a-z]+", line):
            token, approx = cautious_repair(m.group()), False
            # cautious_repair returns (token, approximate)
            if isinstance(token, tuple):
                token, approx = token
            xx0 = origin[0] + x0 + (x1 - x0) * m.start() / len(line)
            xx1 = origin[0] + x0 + (x1 - x0) * m.end() / len(line)
            parsed.append(Word(token, (xx0, origin[1] + y0, xx1, origin[1] + y1), approx))
    return parsed


class RapidFallback:
    """Best-effort local ONNX recogniser. A missing model does not stop Watch Droid."""

    def __init__(self, logger=None, *, enabled=True):
        self.logger = logger or logging.getLogger(__name__)
        self.engine = None
        self.enabled = False
        self.last_attempt = 0.0
        self.disabled_reason = None
        if not enabled:
            self.disabled_reason = "disabled_in_settings"
            return
        try:
            import onnxruntime

            onnxruntime.disable_telemetry_events()
            from rapidocr import RapidOCR

            self.engine = RapidOCR(params=rapid_cpu_parameters())
            self.enabled = True
            self.logger.info("rapidocr_loaded")
        except Exception as exc:
            self.disabled_reason = f"{type(exc).__name__}: {exc}"
            self.logger.warning(
                "rapidocr_unavailable using_tesseract_only reason=%s", self.disabled_reason
            )

    def read(self, image, origin, Word, repair, *, min_gap=0.50):
        if not self.enabled:
            return []
        now = time.monotonic()
        if now - self.last_attempt < min_gap:
            return []
        self.last_attempt = now
        try:
            return rapidocr_words(self.engine, image, origin, Word, repair)
        except Exception as exc:
            self.logger.warning("rapidocr_read_failed error=%s", exc)
            return []


class EvidenceWriter:
    """Bounded, local-only asynchronous diagnostic screenshots; never blocks alerts."""

    def __init__(self, directory=None, enabled=True, keep=180, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.enabled = enabled
        self.keep = keep
        self.path = Path(
            directory
            or Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
            / "DroidTycoonAutoClicker"
            / "watch-evidence"
        )
        self.tasks = queue.Queue(maxsize=4)
        self.thread = None
        self.last_key_time = {}
        if enabled:
            try:
                self.path.mkdir(parents=True, exist_ok=True)
                self.thread = threading.Thread(
                    target=self._run, name="DroidEvidenceWriter", daemon=True
                )
                self.thread.start()
            except OSError as exc:
                self.enabled = False
                self.logger.warning("watch_evidence_unavailable error=%s", exc)

    def submit(self, image, kind, label, captured_at, *, gap=1.0):
        if not self.enabled or image is None:
            return
        key = (kind, label)
        previous = self.last_key_time.get(key, float("-inf"))
        if captured_at - previous < gap:
            return
        self.last_key_time[key] = captured_at
        try:
            self.tasks.put_nowait((image.copy(), kind, label, captured_at, time.time_ns()))
        except queue.Full:
            self.logger.warning("watch_evidence_queue_full type=%s label=%s", kind, label)

    def _run(self):
        while True:
            item = self.tasks.get()
            if item is None:
                self.tasks.task_done()
                return
            try:
                image, kind, label, captured_at, nonce = item
                stamp = time.strftime("%Y%m%d_%H%M%S")
                safe = re.sub(r"[^A-Za-z0-9_-]+", "_", label)[:40]
                name = f"{stamp}_{nonce % 1000000000:09d}_{kind}_{safe}"
                path = self.path / (name + ".png")
                image.save(path, format="PNG", optimize=False)
                (self.path / (name + ".json")).write_text(
                    json.dumps(
                        {
                            "type": kind,
                            "label": label,
                            "captured_monotonic": round(captured_at, 4),
                            "file": path.name,
                            "source": "watch_area_only",
                        }
                    ),
                    encoding="utf-8",
                )
                pictures = sorted(self.path.glob("*.png"), key=lambda p: p.stat().st_mtime)
                for old in pictures[: -self.keep]:
                    old.unlink(missing_ok=True)
                    old.with_suffix(".json").unlink(missing_ok=True)
            except (OSError, ValueError) as exc:
                self.logger.warning("watch_evidence_write_failed error=%s", exc)
            finally:
                self.tasks.task_done()

    def stop(self, timeout=0.8):
        if self.thread is not None:
            try:
                self.tasks.put_nowait(None)
            except queue.Full:
                pass
            self.thread.join(timeout=timeout)


class VisualLabelBank:
    """Learn edge templates from verified OCR labels and match later difficult frames.

    Requires OpenCV+NumPy. No templates are fabricated; until trained by
    actual notification text this component has no independent matches.
    """

    def __init__(self, directory=None, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.path = Path(
            directory
            or Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
            / "DroidTycoonAutoClicker"
            / "label-templates-v16"
        )
        self.templates = {}
        self.cv2 = self.np = None
        try:
            import cv2
            import numpy as np

            cv2.setNumThreads(1)
            cv2.ocl.setUseOpenCL(False)
            self.cv2, self.np = cv2, np
            self.path.mkdir(parents=True, exist_ok=True)
            for f in sorted(self.path.glob("*.png")):
                label = f.stem.split("__")[0]
                if label in VARIANTS or label in RARITIES:
                    template = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
                    if template is not None:
                        self.templates.setdefault(label, []).append(template)
        except (ImportError, OSError) as exc:
            self.logger.warning("visual_template_disabled reason=%s", exc)

    def _edge(self, image):
        arr = self.np.asarray(image.convert("RGB")).max(axis=2)
        # Light text strokes with dark outlines, insensitive to hue changes.
        return self.cv2.Canny(arr, 60, 125)

    def learn(self, image, matches, origin):
        if self.cv2 is None:
            return
        for match in matches:
            for word in match.labels:
                label = word.text
                if getattr(word, "approximate", False):
                    continue
                if label not in VARIANTS and label not in RARITIES:
                    continue
                label = {"stella": "stellar", "mythical": "mythic"}.get(label, label)
                if len(self.templates.get(label, ())) >= 3:
                    continue
                x0, y0, x1, y1 = word.box
                box = (
                    max(0, round(x0 - origin[0])),
                    max(0, round(y0 - origin[1])),
                    min(image.width, round(x1 - origin[0])),
                    min(image.height, round(y1 - origin[1])),
                )
                if box[2] - box[0] < 18 or box[3] - box[1] < 8:
                    continue
                edge = self._edge(image.crop(box))
                if self.np.count_nonzero(edge) < max(12, edge.size * 0.05):
                    continue
                # Save exact-size samples; matching adjusts +/- 12% HUD scale.
                index = len(self.templates.get(label, ()))
                try:
                    f = self.path / f"{label}__{index}.png"
                    if not self.cv2.imwrite(str(f), edge):
                        raise OSError("cv2.imwrite returned False")
                    self.templates.setdefault(label, []).append(edge)
                except OSError as exc:
                    self.logger.warning("template_save_failed error=%s", exc)

    def detect(self, image, origin, *, threshold=0.93):
        if self.cv2 is None or not self.templates:
            return []

        edge = self._edge(image)
        hits = []
        cv2 = self.cv2
        for label, samples in self.templates.items():
            for sample in samples:
                for scale in (0.90, 1.0, 1.10):
                    h, w = sample.shape
                    size = (max(8, round(w * scale)), max(7, round(h * scale)))
                    if size[0] > edge.shape[1] or size[1] > edge.shape[0]:
                        continue
                    tmpl = cv2.resize(sample, size, interpolation=cv2.INTER_NEAREST)
                    if self.np.std(tmpl) < 8:
                        continue
                    values = cv2.matchTemplate(edge, tmpl, cv2.TM_CCOEFF_NORMED)
                    _, best, _, point = cv2.minMaxLoc(values)
                    if best >= threshold:
                        x, y = point
                        box = (
                            origin[0] + x,
                            origin[1] + y,
                            origin[0] + x + size[0],
                            origin[1] + y + size[1],
                        )
                        if not any(
                            old[0] == label
                            and abs(old[1][0] - box[0]) <= 8
                            and abs(old[1][1] - box[1]) <= 8
                            for old in hits
                        ):
                            hits.append((label, box, round(float(best), 4)))
        return hits


def visual_pair_matches(hits, DroidMatch, Word):
    """Require TWO strong independently learned label shapes in one row.

    Raw visual matching produces candidates only; caller demands confirmation
    from a second captured frame and sends these through normal deduplication.
    """
    variants, rarities = VARIANTS, RARITIES
    found = []
    for variant, vbox, vc in hits:
        if variant not in variants:
            continue
        following = []
        for label, box, score in hits:
            if label not in variants and label not in rarities:
                continue
            h = max(8, vbox[3] - vbox[1], box[3] - box[1])
            if box[0] < vbox[2] or box[0] - vbox[2] > 15 * h:
                continue
            if abs((vbox[1] + vbox[3]) - (box[1] + box[3])) <= h:
                following.append((label, box, score))
        if not following:
            continue
        rarity, rbox, rc = min(following, key=lambda hit: hit[1][0])
        if rarity not in rarities:
            continue
        h = max(8, vbox[3] - vbox[1], rbox[3] - rbox[1])
        pair = f"{variants[variant]} {rarities[rarity]}"
        if not any(m.pair == pair and abs(m.box[1] - vbox[1]) < h for m in found):
            found.append(
                DroidMatch(
                    pair,
                    (vbox[0], min(vbox[1], rbox[1]), rbox[2], max(vbox[3], rbox[3])),
                    (Word(variant, vbox), Word(rarity, rbox)),
                )
            )
    return found
