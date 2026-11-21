"""Read visible Fortnite droid cards and announce selected rarity pairs."""

from collections import deque
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from itertools import product
import math
import logging
import multiprocessing
import queue
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile
import re
import threading
import time
import wave

from mss import MSS
from .session_alert_history import SessionAlertHistory
from .resources import asset_path
from . import __version__
from .scan_limits import configure_native_threads, scanner_over_budget, validate_capture_region
from .hybrid_droid_detection import (
    EvidenceWriter,
    RapidFallback,
    VisualLabelBank,
    visual_pair_matches,
)
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRubberBand,
    QSystemTrayIcon,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QScrollArea,
    QWidget,
    QLayout,
    QApplication,
)


from .droid_catalog import VARIANTS, RARITIES, VARIANT_NAMES, RARITY_NAMES, ALERT_CHOICES

DEFAULT_ALERT_CHOICES = tuple(
    f"{variant} {rarity}"
    for variant, rarity in product(("Stellar", "Kyber", "Galactic"), ("Legendary", "Mythic"))
)
PAIR_SETTING_PREFIX = "droidAlert/pairs/"
GA_ROOT = 2
GW_HWNDPREV = 3
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
OTHER_VARIANTS = set()
OTHER_RARITIES = {"uncommon", "iconic"}
NON_CARD_WORDS = {"surge", "surges", "track", "selected", "crystal", "crystals", "token", "tokens"}
VARIANT_WORDS = VARIANTS.keys() | OTHER_VARIANTS
RARITY_WORDS = RARITIES.keys() | OTHER_RARITIES
CARD_BOUNDARIES = VARIANT_WORDS | RARITY_WORDS | NON_CARD_WORDS
JOINED_DROID_LABEL = re.compile(
    r"^("
    + "|".join(sorted(VARIANT_WORDS, key=len, reverse=True))
    + r")[a-z]?(droid|blueprint)[a-z]*$"
)
JOINED_RARITY_LABEL = re.compile(
    r"(?:oid|blueprint)[a-z]{0,2}(" + "|".join(sorted(RARITY_WORDS, key=len, reverse=True)) + r")$"
)
MERGED_HUD_MARKER = re.compile(r"[a-z]{3,}(droid|blueprint)[a-z]{0,2}$")
PAIR_LABELS = VARIANT_WORDS | RARITY_WORDS
HUD_MARKERS = {"droid", "blueprint"}
HUD_WORDS = CARD_BOUNDARIES | HUD_MARKERS
LABEL_PREFIXES = {label[:length] for label in PAIR_LABELS for length in range(1, len(label))}
SCAN_INTERVAL = 0.125  # At most eight captures per second in the independent process.
CAPTURE_BUFFER_SIZE = 4
CAPTURE_BUFFER_BYTES = 8 * 1024 * 1024
COMBAT_PASS_INTERVAL = 0.20
LABEL_MEMORY_SECONDS = 0.32
REAPPEAR_AFTER = 4.0  # avoid suppressing a distinct repeat spawn for twelve seconds
CONFIRMED_CLEAR_SECONDS = 0.48
WATCH_MARGIN = 48
PAUSED_STATUS = "Paused · Keep the selected Fortnite area visible (it may be out of focus)."


@dataclass(frozen=True)
class Word:
    text: str
    box: tuple[float, float, float, float]
    approximate: bool = False


@dataclass(frozen=True)
class DroidMatch:
    pair: str
    box: tuple[float, float, float, float]
    labels: tuple[Word, ...] = field(default=(), compare=False, repr=False)


def watch_logger():
    logger = logging.getLogger("droid_watch")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            folder = (
                Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
                / "DroidTycoonAutoClicker"
            )
            folder.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(
                folder / "droid-watch.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            logger.addHandler(handler)
        except OSError:
            logger.addHandler(logging.NullHandler())
    return logger


def same_row(first, second):
    _, top, _, bottom = first.box
    _, other_top, _, other_bottom = second.box
    height = max(bottom - top, other_bottom - other_top)
    return abs(top + bottom - other_top - other_bottom) <= height


def matching_droids(words):
    """Match the ordered variant and rarity on each row, including other tiers as boundaries."""
    labels = sorted(words, key=lambda word: word.box[0])
    matches = []
    for index, variant in enumerate(labels):
        if variant.text not in VARIANT_WORDS:
            continue
        left, top, right, bottom = variant.box
        name_words = 0
        for other in labels[index + 1 :]:
            if not same_row(variant, other):
                continue
            other_left, other_top, other_right, other_bottom = other.box
            height = max(bottom - top, other_bottom - other_top)
            if other_left - right > 2.5 * height:
                break
            if other.text not in CARD_BOUNDARIES:
                # A name can sit between the variant and rarity. Follow its
                # words only while they are close together on the same row.
                if other_right > right:
                    right = other_right
                    name_words += 1
                if name_words > 4:
                    break
                continue
            # The first relevant word to the right owns the outcome. An Epic
            # label, next droid, or a banner word prevents borrowing a later rarity.
            if other.text in RARITY_WORDS:
                variant_name = VARIANTS.get(variant.text, variant.text.title())
                rarity = RARITIES.get(other.text, other.text.title())
                bounds = (left, min(top, other_top), other_right, max(bottom, other_bottom))
                matches.append(DroidMatch(f"{variant_name} {rarity}", bounds, (variant, other)))
            break
    return matches


def join_split_labels(words):
    """Put a label back together when OCR inserts a space inside its spelling."""
    ordered = sorted(words, key=lambda word: word.box[0])
    consumed = set()
    result = []
    for index, first in enumerate(ordered):
        if index in consumed:
            continue
        if first.text in LABEL_PREFIXES and first.text not in PAIR_LABELS:
            left, top, right, bottom = first.box
            for second_index in range(index + 1, len(ordered)):
                second = ordered[second_index]
                x0, y0, x1, y1 = second.box
                if not same_row(first, second) or second_index in consumed:
                    continue
                if x0 - right > 0.65 * max(bottom - top, y1 - y0):
                    break
                combined = first.text + second.text
                if combined in PAIR_LABELS:
                    first = Word(combined, (left, min(top, y0), x1, max(bottom, y1)))
                    consumed.add(second_index)
                break
        result.append(first)
    return result


@dataclass
class WatchedRow:
    match: DroidMatch
    outlines: tuple[tuple[Word, Image.Image], ...] = ()
    missing_since: float | None = None
    clear_since: float | None = None
    shapes: tuple = ()

    def seen(self, match, image, origin):
        if image is not None and (not self.outlines or self.match.labels != match.labels):
            self.outlines = notification_outlines(match, image, origin)
            self.shapes = tuple((w, shape_mask(image, w.box, origin)) for w in match.labels)
        self.match = match
        self.missing_since = None
        self.clear_since = None

    def still_visible(self, image, origin):
        if image is None or not self.outlines:
            return False
        if all(
            same_outline(outline, glyph_mask(image, word.box, origin))
            for word, outline in self.outlines
        ):
            return True
        if not self.shapes or any(mask is None for _, mask in self.shapes):
            return False
        height = max(w.box[3] - w.box[1] for w, _ in self.shapes)
        # Both exact label shapes must move together as feed rows shift.
        offsets = [0] + [sign * d for d in range(1, round(3 * height) + 1) for sign in (-1, 1)]
        for dy in offsets:
            for dx in (0, -2, 2):
                if all(
                    shape_agrees(mask, shape_mask(image, shifted_box(w.box, dx, dy), origin))
                    for w, mask in self.shapes
                ):
                    return True
        return False

    def clearly_empty(self, image, origin):
        # Textured or occluded frames remain uncertain.
        if image is None or not self.match.labels:
            return False
        for word in self.match.labels:
            crop = local_crop(image, word.box, origin)
            if crop is None:
                return False
            low, high = ImageOps.grayscale(crop).getextrema()
            if high - low > 18:
                return False
        return True


class DroidTracker:
    def __init__(self):
        # One slot per observed occurrence. A missing slot stays reserved
        # through OCR dropouts so a shifted or redrawn line is not a new spawn.
        self.tracks: dict[str, list[WatchedRow]] = {}

    def reset(self):
        self.tracks.clear()

    def suspend(self):
        for rows in self.tracks.values():
            for row in rows:
                row.missing_since = None
                row.clear_since = None

    def update(self, matches, now, image=None, origin=(0, 0)):
        observed = {}
        for match in matches:
            observed.setdefault(match.pair, []).append(match)

        updated = {}
        new_matches = []
        for pair in self.tracks.keys() | observed.keys():
            present = observed.get(pair, [])
            remembered = [
                row
                for row in self.tracks.get(pair, [])
                if (row.missing_since is None or now - row.missing_since < REAPPEAR_AFTER)
                and (row.clear_since is None or now - row.clear_since < CONFIRMED_CLEAR_SECONDS)
                # A *different* fully recognised notification in the old slot
                # proves the previous occurrence was replaced. Otherwise a
                # second Kyber Mythic in the same location can be suppressed
                # for up to twelve seconds by the old track.
                and not any(
                    other.pair != pair and same_notification(row.match, other) for other in matches
                )
            ]
            candidates = sorted(
                (row_distance(row.match, match), row_index, match_index)
                for row_index, row in enumerate(remembered)
                for match_index, match in enumerate(present)
                if plausible_same_occurrence(row.match, match)
            )
            assignments = {}
            used = set()
            for _, row_index, match_index in candidates:
                if row_index not in used and match_index not in assignments:
                    assignments[match_index] = remembered[row_index]
                    used.add(row_index)
            rows = []
            for index, match in enumerate(present):
                row = assignments.get(index)
                if row is None:
                    row = WatchedRow(match)
                    new_matches.append(match)
                row.seen(match, image, origin)
                rows.append(row)
            for index, row in enumerate(remembered):
                if index in used:
                    continue
                # A missing OCR read is not evidence of a despawn if both
                # label outlines are still visible in the same place.
                occupied = any(duplicate_notification(row.match, match) for match in present)
                if not occupied and row.still_visible(image, origin):
                    row.missing_since = None
                    row.clear_since = None
                elif row.missing_since is None:
                    row.missing_since = now
                if row.missing_since is not None:
                    if row.clearly_empty(image, origin):
                        if row.clear_since is None:
                            row.clear_since = now
                    else:
                        row.clear_since = None
                rows.append(row)
            if rows:
                updated[pair] = rows
        self.tracks = updated
        return sorted(new_matches, key=lambda match: (match.box[1], match.box[0]))


def one_edit_or_swap(first, second):
    """One insertion, deletion, substitution or adjacent letter transposition."""
    if first == second:
        return True
    if abs(len(first) - len(second)) > 1:
        return False
    if len(first) == len(second):
        differences = [i for i, (a, b) in enumerate(zip(first, second)) if a != b]
        return len(differences) == 1 or (
            len(differences) == 2
            and differences[1] == differences[0] + 1
            and first[differences[0]] == second[differences[1]]
            and first[differences[1]] == second[differences[0]]
        )
    shorter, longer = sorted((first, second), key=len)
    return any(shorter == longer[:i] + longer[i + 1 :] for i in range(len(longer)))


def cautious_label_repair(token):
    """Correct one damaged character only if every plausible label has the same identity."""
    if token in VARIANT_WORDS or token in RARITY_WORDS:
        return token, False
    if len(token) < 4 or len(token) > 10:
        return token, False
    candidates = [word for word in (*VARIANTS, *RARITIES) if one_edit_or_swap(token, word)]
    meanings = {VARIANTS.get(word, RARITIES.get(word)) for word in candidates}
    if len(meanings) != 1:
        return token, False
    chosen = min(candidates, key=lambda word: (abs(len(word) - len(token)), word))
    return chosen, True


def read_words(ocr, image, origin, *, outlined=False, single_row=False, native_scale=False):
    from tesserocr import RIL

    width, height = image.size
    preferred_scale = 1 if native_scale else 3 if single_row else 1.5 if outlined else 2
    scale = max(1, min(preferred_scale, 1800 / width, 1100 / height))
    if scale > 1:
        image = image.resize(
            (round(width * scale), round(height * scale)), Image.Resampling.BICUBIC
        )
    x_scale, y_scale = width / image.width, height / image.height
    border = 12
    image = ImageOps.expand(image, border=border, fill=255 if outlined else 0)
    ocr.SetImage(image)
    ocr.Recognize()
    iterator = ocr.GetIterator()
    if iterator is None:
        return []
    words = []
    while True:
        box = iterator.BoundingBox(RIL.WORD)
        if box:
            raw = iterator.GetUTF8Text(RIL.WORD) or ""
            left, top, right, bottom = box
            x, y = origin
            bounds = (
                x + (left - border) * x_scale,
                y + (top - border) * y_scale,
                x + (right - border) * x_scale,
                y + (bottom - border) * y_scale,
            )
            for part in re.finditer(r"[a-z]+", raw.casefold()):
                token = part.group()
                width = bounds[2] - bounds[0]
                token_box = (
                    bounds[0] + width * part.start() / len(raw),
                    bounds[1],
                    bounds[0] + width * part.end() / len(raw),
                    bounds[3],
                )
                joined = JOINED_DROID_LABEL.fullmatch(token)
                if joined:
                    start, top, end, bottom = token_box
                    unit = (end - start) / len(token)
                    words.append(
                        Word(joined.group(1), (start, top, start + unit * joined.end(1), bottom))
                    )
                    marker_box = (
                        start + unit * joined.start(2),
                        top,
                        start + unit * joined.end(2),
                        bottom,
                    )
                    words.append(Word(joined.group(2), marker_box))
                else:
                    repaired, approximate = cautious_label_repair(token)
                    words.append(Word(repaired, token_box, approximate))
                joined_rarity = JOINED_RARITY_LABEL.search(token)
                if joined_rarity:
                    suffix = joined_rarity.group(1)
                    for marker in HUD_MARKERS:
                        if token.startswith(marker):
                            marker_end = token_box[0] + (token_box[2] - token_box[0]) * len(
                                marker
                            ) / len(token)
                            words.append(
                                Word(marker, (token_box[0], token_box[1], marker_end, token_box[3]))
                            )
                    left = token_box[2] - (token_box[2] - token_box[0]) * len(suffix) / len(token)
                    words.append(Word(suffix, (left, token_box[1], token_box[2], token_box[3])))
        if not iterator.Next(RIL.WORD):
            return join_split_labels(words)


def same_notification(first, second):
    """Associate readings of the same line across OCR passes."""
    left, top, right, bottom = first.box
    other_left, other_top, other_right, other_bottom = second.box
    height = max(bottom - top, other_bottom - other_top)
    overlap_x = min(right, other_right) - max(left, other_left)
    overlap_y = min(bottom, other_bottom) - max(top, other_top)
    same_column = abs(left - other_left) <= height or overlap_x >= 0.6 * min(
        right - left,
        other_right - other_left,
    )
    overlapping_row = overlap_y >= 0.6 * min(bottom - top, other_bottom - other_top)
    return same_column and (same_row(first, second) or overlapping_row)


def duplicate_notification(first, second):
    return same_notification(first, second) or (
        first.pair == second.pair
        and any(same_notification(a, b) for a, b in zip(first.labels, second.labels))
    )


def row_distance(first, second):
    return abs(first.box[0] - second.box[0]) + abs(first.box[1] - second.box[1])


def plausible_same_occurrence(first, second):
    """Do not merge two alerts from unrelated positions merely because the names match."""
    height = max(8, first.box[3] - first.box[1], second.box[3] - second.box[1])
    return abs(first.box[0] - second.box[0]) <= max(35, 5 * height) and abs(
        first.box[1] - second.box[1]
    ) <= max(50, 5 * height)


def frame_image(frame):
    return Image.frombytes("RGB", frame.size, frame.bgra, "raw", "BGRX")


def brightest_channel(image):
    red, green, blue = image.split()
    return ImageChops.lighter(ImageChops.lighter(red, green), blue)


def hud_row_labels(words, marker):
    left, top, right, bottom = marker.box
    height = bottom - top
    variants, rarities = [], []
    for word in words:
        if not same_row(word, marker):
            continue
        x0, _, x1, _ = word.box
        if word.text in VARIANT_WORDS and x0 < left and -height <= left - x1 <= 2.5 * height:
            variants.append(word)
        if word.text in RARITY_WORDS and x1 > right and -height <= x0 - right <= 2.5 * height:
            rarities.append(word)
    variant = max(variants, key=lambda word: word.box[2], default=None)
    rarity = min(rarities, key=lambda word: word.box[0], default=None)
    return variant, rarity


def same_hud_marker(first, second):
    if first.text != second.text:
        return False
    tolerance = max(3, 0.20 * (first.box[3] - first.box[1]))
    return all(abs(a - b) <= tolerance for a, b in zip(first.box, second.box))


def shifted_box(box, dx, dy):
    return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)


def local_crop(image, bounds, origin):
    x, y = origin
    box = (
        math.floor(bounds[0] - x),
        math.floor(bounds[1] - y),
        math.ceil(bounds[2] - x),
        math.ceil(bounds[3] - y),
    )
    if box[0] < 0 or box[1] < 0 or box[2] > image.width or box[3] > image.height:
        return None
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    return image.crop(box)


def shape_mask(image, bounds, origin):
    crop = local_crop(image, bounds, origin)
    if crop is None:
        return None
    gray = brightest_channel(crop)
    lo, hi = gray.getextrema()
    if hi - lo < 18:
        return None
    edges = ImageOps.autocontrast(gray).filter(ImageFilter.FIND_EDGES)
    return edges.crop((1, 1, edges.width - 1, edges.height - 1)).point(
        lambda v: 255 if v >= 65 else 0
    )


def shape_agrees(first, second):
    if first is None or second is None or first.size != second.size:
        return False
    a, b = first.histogram()[255], second.histogram()[255]
    if min(a, b) < first.width * first.height * 0.08 or min(a, b) < 0.65 * max(a, b):
        return False
    return ImageChops.darker(first, second).histogram()[255] >= 0.70 * max(a, b)


def glyph_mask(image, bounds, origin):
    left, top, right, bottom = bounds
    x, y = origin
    box = (
        max(0, math.floor(left - x)),
        max(0, math.floor(top - y)),
        min(image.width, math.ceil(right - x)),
        min(image.height, math.ceil(bottom - y)),
    )
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        return None
    value = brightest_channel(image.crop(box))
    dark = value.point(lambda pixel: 255 if pixel < 78 else 0)
    near_bright = value.filter(ImageFilter.MaxFilter(5)).point(
        lambda pixel: 255 if pixel >= 118 else 0
    )
    return ImageChops.darker(dark, near_bright)


def same_outline(first, second):
    if first is None or second is None or first.size != second.size:
        return False
    union = ImageChops.lighter(first, second).histogram()[255]
    shared = ImageChops.darker(first, second).histogram()[255]
    return union >= 0.06 * first.width * first.height and shared >= 0.75 * union


def notification_outlines(match, image, origin):
    outlines = tuple((word, glyph_mask(image, word.box, origin)) for word in match.labels)
    if len(outlines) == 2 and all(outline is not None for _, outline in outlines):
        return outlines
    return ()


def same_glyph_outline(previous, current, word, marker, origin):
    left, top, right, bottom = word.box
    # When OCR joined the variant with Droid/Blueprint, compare only the variant.
    if word.text in VARIANT_WORDS:
        right = min(right, marker.box[0])
    bounds = (left, top, right, bottom)
    return same_outline(glyph_mask(previous, bounds, origin), glyph_mask(current, bounds, origin))


def recover_hud_labels(words, image, origin, recent_reads, captured_at):
    """Reuse an exact reading only while its marker and letter outline stay in place."""
    recovered = []
    for marker in (word for word in words if word.text in HUD_MARKERS):
        current = hud_row_labels(words, marker)
        if (current[0] is None) == (current[1] is None):
            continue
        missing = 0 if current[0] is None else 1
        for previous_at, previous_image, previous_words in reversed(recent_reads):
            if captured_at - previous_at > LABEL_MEMORY_SECONDS:
                break
            anchor = next((word for word in previous_words if same_hud_marker(marker, word)), None)
            if anchor is None:
                continue
            previous = hud_row_labels(previous_words, anchor)
            candidate = previous[missing]
            if candidate is None:
                continue
            if previous[1 - missing] and previous[1 - missing].text != current[1 - missing].text:
                break
            if same_glyph_outline(previous_image, image, candidate, anchor, origin):
                recovered.append(candidate)
                break
    return recovered


def retry_hud_rows(ocr, words, matches, gray, maximum, origin):
    """Re-read an incomplete spawn as a single, enlarged line."""
    from tesserocr import PSM

    retries = 0
    x, y = origin
    markers = [word for word in words if word.text in HUD_MARKERS]
    for word in words:
        merged = MERGED_HUD_MARKER.fullmatch(word.text)
        if merged:
            left, top, right, bottom = word.box
            unit = (right - left) / len(word.text)
            box = (left + unit * merged.start(1), top, left + unit * merged.end(1), bottom)
            marker = Word(merged.group(1), box)
            if not any(same_notification(marker, old) for old in markers):
                markers.append(marker)
    for marker in markers:
        variant, rarity = hud_row_labels(words, marker)
        if (variant is None) == (rarity is None):
            continue
        if (variant and variant.text not in VARIANTS) or (rarity and rarity.text not in RARITIES):
            continue
        left, _, right, _ = marker.box
        if any(same_row(marker, match) and match.box[0] < left < match.box[2] for match in matches):
            continue
        _, top, _, bottom = (variant or rarity).box
        height = bottom - top
        if height < 5:
            continue
        start = variant.box[0] if variant else left - 8 * height
        end = rarity.box[2] + height if rarity else right + 9 * height
        for word in markers:
            if same_row(marker, word) and word.box[2] < left:
                start = max(start, word.box[2])
            elif same_row(marker, word) and word.box[0] > right:
                end = min(end, word.box[0])
        for word in words:
            if word.text == "spawned" and same_row(marker, word) and word.box[0] > right:
                end = min(end, word.box[0])
        box = (
            max(0, math.floor(start - x - 0.35 * height)),
            max(0, math.floor(top - y - 0.30 * height)),
            min(gray.width, math.ceil(end - x)),
            min(gray.height, math.ceil(bottom - y + 0.30 * height)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        retries += 1
        crop_origin = (x + box[0], y + box[1])
        ocr.SetPageSegMode(PSM.SINGLE_LINE)
        contrast = ImageOps.autocontrast(maximum.crop(box))
        if variant is None:
            # Retain narrow letter strokes while suppressing broad bright areas.
            background = contrast.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))
            threshold = 36
        else:
            # Emphasise the transition from the dark outline to the rarity fill.
            background = contrast.filter(ImageFilter.MinFilter(3))
            threshold = 58
        strokes = ImageChops.subtract(contrast, background)
        outlines = strokes.point(lambda value: 0 if value >= threshold else 255)
        for source, outlined in ((contrast, False), (gray.crop(box), False), (outlines, True)):
            read = read_words(ocr, source, crop_origin, outlined=outlined, single_row=True)
            fresh_variant, fresh_rarity = hud_row_labels(read, marker)
            if variant and fresh_variant and variant.text != fresh_variant.text:
                continue
            if rarity and fresh_rarity and rarity.text != fresh_rarity.text:
                continue
            first, last = variant or fresh_variant, rarity or fresh_rarity
            if first and last and same_row(first, last):
                for match in matching_droids([first, marker, last]):
                    if not any(same_notification(previous, match) for previous in matches):
                        matches.append(match)
                break
        if retries >= 3:
            break


def marker_like(text):
    """Tolerate one damaged marker character; identity and rarity stay exact."""
    if text in HUD_MARKERS:
        return True
    for marker in HUD_MARKERS:
        if len(text) == len(marker) and sum(a != b for a, b in zip(text, marker)) == 1:
            return True
        if len(text) == len(marker) + 1 and any(
            text[:i] + text[i + 1 :] == marker for i in range(len(text))
        ):
            return True
    return False


def spawn_context(match, words):
    first, last = match.labels
    height = max(first.box[3] - first.box[1], last.box[3] - last.box[1])
    row = [word for word in words if same_row(first, word)]
    if any(
        marker_like(word.text)
        and first.box[2] - height * 0.3 <= word.box[0]
        and word.box[2] <= last.box[0] + height * 0.3
        for word in row
    ):
        return True
    suffix = [
        word.text for word in row if last.box[2] - height < word.box[0] < last.box[2] + 20 * height
    ]
    return any("spawned" in text for text in suffix) and "sandcrawler" in suffix


def recover_spawn_rows(ocr, words, matches, gray, maximum, origin):
    """Read individual notification rows independently, using all OCR geometry."""
    from statistics import median
    from tesserocr import PSM

    x, y = origin
    bands = []
    for word in sorted(words, key=lambda w: (w.box[1], w.box[0])):
        height = word.box[3] - word.box[1]
        if len(word.text) < 3 or height < 7 or height > gray.height * 0.5:
            continue
        centre = (word.box[1] + word.box[3]) / 2
        band = next(
            (
                b
                for b in bands
                if abs(centre - median((w.box[1] + w.box[3]) / 2 for w in b)) < 0.55 * height
            ),
            None,
        )
        if band is None:
            bands.append([word])
        else:
            band.append(word)
    for band in sorted(bands, key=lambda b: min(w.box[1] for w in b))[:6]:
        height = min(w.box[3] - w.box[1] for w in band)
        centre = median((w.box[1] + w.box[3]) / 2 for w in band)
        band = [w for w in band if abs((w.box[1] + w.box[3]) / 2 - centre) < 0.5 * height]
        if not band:
            continue
        anchor = min(band, key=lambda w: w.box[0])
        if any(same_row(anchor, m) and spawn_context(m, words) for m in matches):
            continue
        variants = [w for w in band if w.text in VARIANT_WORDS]
        markers = [w for w in band if marker_like(w.text)]
        rarities = [w for w in band if w.text in RARITY_WORDS]
        if variants and all(w.text not in VARIANTS for w in variants):
            continue
        if rarities and all(w.text not in RARITIES for w in rarities):
            continue
        if not (
            variants
            or markers
            or rarities
            or any(
                w.text.startswith(
                    (
                        "spawn",
                        "sandcrawl",
                        "kyb",
                        "myth",
                        "galact",
                        "stel",
                        "beskar",
                        "scour",
                        "rainbow",
                    )
                )
                for w in band
            )
        ):
            # Random scenery and unrelated HUD text previously triggered up
            # to eight high-cost OCR retries per row, overwhelming the buffer.
            # Such rows have no evidence of a droid notification to recover.
            continue
        starts = [w.box[0] for w in words if w.text in VARIANT_WORDS]
        shared_left = median(starts) if starts else anchor.box[0]
        start = min(
            (w.box[0] for w in variants),
            default=max(anchor.box[0], min(shared_left, anchor.box[0] + height)),
        )
        if markers and not variants:
            start = max(x, min(w.box[0] for w in markers) - 9 * height)
        suffix = [
            w.box[0]
            for w in band
            if ("spawn" in w.text or w.text.startswith("spam")) and w.box[0] > start + 5 * height
        ]
        end = (
            min(suffix) - 0.20 * height
            if suffix
            else max((w.box[2] + 0.8 * height for w in rarities), default=start + 21 * height)
        )
        box = (
            max(0, math.floor(start - x - 0.35 * height)),
            max(0, math.floor(centre - y - 1.0 * height)),
            min(gray.width, math.ceil(end - x)),
            min(gray.height, math.ceil(centre - y + 1.0 * height)),
        )
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        crop_origin = (x + box[0], y + box[1])
        bright = ImageOps.autocontrast(maximum.crop(box))
        strokes = ImageChops.subtract(
            bright, bright.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))
        )
        local = ImageChops.subtract(bright, bright.filter(ImageFilter.MinFilter(3)))
        sources = [
            gray.crop(box),
            bright,
            strokes.point(lambda v: 0 if v >= 36 else 255),
            local.point(lambda v: 0 if v >= 58 else 255),
        ]
        resolved = False
        for mode in (PSM.SINGLE_LINE, PSM.RAW_LINE):
            ocr.SetPageSegMode(mode)
            for index, source in enumerate(sources):
                read = read_words(ocr, source, crop_origin, outlined=index >= 2, single_row=True)
                for match in matching_droids(read):
                    if match.pair not in ALERT_CHOICES or not spawn_context(match, read + band):
                        continue
                    if any(
                        w.text in VARIANT_WORDS
                        and VARIANTS.get(w.text, w.text.title()) != match.pair.split()[0]
                        and same_notification(w, match.labels[0])
                        for w in variants
                    ):
                        continue
                    if any(
                        w.text in RARITY_WORDS
                        and RARITIES.get(w.text, w.text.title()) != match.pair.split()[1]
                        and same_notification(w, match.labels[1])
                        for w in rarities
                    ):
                        continue
                    if not any(duplicate_notification(old, match) for old in matches):
                        matches.append(match)
                    words.extend(read)
                    resolved = True
                if resolved:
                    break
            if resolved:
                break


def combat_text_mask(history):
    """Isolate fixed, outlined HUD lettering from moving scenery."""
    first, second, third = history
    lower = ImageChops.darker(first, second)
    upper = ImageChops.lighter(first, second)
    minimum = ImageChops.darker(lower, third)
    maximum = ImageChops.lighter(upper, third)
    motion = brightest_channel(ImageChops.subtract(maximum, minimum))
    moving = motion.point(lambda value: 255 if value >= 28 else 0)
    if moving.histogram()[255] < first.width * first.height * 0.04:
        return None

    median = ImageChops.lighter(lower, ImageChops.darker(upper, third))
    dark = brightest_channel(median).point(lambda value: 255 if value >= 100 else 0)
    outlines = ImageChops.lighter(dark, moving)
    outlines = outlines.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    # Fill enclosed letter strokes, then restore holes that reveal moving scenery.
    enclosed = ImageOps.expand(outlines, border=1, fill=255)
    ImageDraw.floodfill(enclosed, (0, 0), 128)
    enclosed = enclosed.crop((1, 1, outlines.width + 1, outlines.height + 1))
    filled = enclosed.point(lambda value: 255 if value == 128 else 0)
    return ImageChops.lighter(filled, moving)


def recognise(
    ocr,
    frame,
    origin,
    *,
    image=None,
    combat_mask=None,
    recent_reads=None,
    captured_at=0.0,
    return_uncertain=False,
):
    from tesserocr import PSM

    if image is None:
        image = frame_image(frame)
    ocr.SetPageSegMode(PSM.SPARSE_TEXT)
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    primary = read_words(ocr, gray, origin)
    matches = matching_droids(primary)
    if not matches:
        # Grayscale/upsampling can erase coloured glyphs on blue scenery.
        # Let Tesseract threshold the original RGB pixels once before the
        # more specialised masks, keeping exact-word/context checks intact.
        ocr.SetPageSegMode(PSM.SINGLE_BLOCK)
        colour_words = read_words(ocr, image, origin, native_scale=True)
        primary.extend(colour_words)
        matches = matching_droids(primary)

    # The feed uses brightly coloured letters with dark outlines. Luminance
    # alone can lose the pink Mythic label on blue scenery, so also read the
    # dark outlines against the brightest of the three colour channels.
    red, green, blue = image.split()
    maximum = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    minimum = ImageChops.darker(ImageChops.darker(red, green), blue)
    saturation = ImageChops.subtract(maximum, minimum).histogram()
    masks = []
    if sum(saturation[75:]) >= image.width * image.height * 0.04:
        suffix_starts = [
            word.box[0] - origin[0] + max(18, word.box[3] - word.box[1])
            for word in primary
            if word.text == "spawned"
        ]
        mask_source = maximum
        if suffix_starts and image.width - max(suffix_starts) > 180:
            # Exclude most of the repeated spawn sentence on the contrast
            # pass. The primary pass still reads the entire watch area.
            mask_source = maximum.crop((0, 0, math.ceil(max(suffix_starts)), image.height))
        mask = mask_source.point(lambda value: 255 if value >= 80 else 0)
        masks.append(mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3)))
    if combat_mask is not None:
        masks.append(combat_mask)

    ocr.SetPageSegMode(PSM.SINGLE_BLOCK)
    primary_labels = [word for word in primary if word.text in CARD_BOUNDARIES]
    observed = primary.copy()
    row_evidence = primary.copy()
    for mask in masks:
        alternate = read_words(ocr, mask, origin, outlined=True)
        row_evidence.extend(alternate)
        # The two passes can recover different halves of one label pair.
        recovered = [
            word
            for word in alternate
            if word.text in CARD_BOUNDARIES
            and not any(same_notification(word, old) for old in primary_labels)
        ]
        for candidate in matching_droids(alternate) + matching_droids(primary + recovered):
            if not any(same_notification(match, candidate) for match in matches):
                matches.append(candidate)
        observed.extend(
            word
            for word in alternate
            if (word.text in HUD_WORDS or MERGED_HUD_MARKER.fullmatch(word.text))
            and not any(same_notification(word, old) for old in observed if old.text in HUD_WORDS)
        )
    if recent_reads is not None:
        recovered = recover_hud_labels(observed, image, origin, recent_reads, captured_at)
        if recovered:
            for candidate in matching_droids(observed + recovered):
                if not any(same_notification(match, candidate) for match in matches):
                    matches.append(candidate)
        recent_reads.append((captured_at, image, observed))
    retry_hud_rows(ocr, observed, matches, gray, maximum, origin)
    row_evidence.extend(observed)
    recover_spawn_rows(ocr, row_evidence, matches, gray, maximum, origin)
    wanted = []
    uncertain = []
    for match in matches:
        if match.pair not in ALERT_CHOICES:
            continue
        # A fuzzy-repaired label is NEVER trusted from just one frame, even
        # if the surrounding 'Droid' marker is readable.
        if spawn_context(match, row_evidence) and not any(
            word.approximate for word in match.labels
        ):
            if not any(duplicate_notification(previous, match) for previous in wanted):
                wanted.append(match)
        elif not any(duplicate_notification(previous, match) for previous in uncertain):
            # No context was readable, but both exact droid + rarity tokens
            # were. Require independent verification on another captured frame.
            uncertain.append(match)
    if recent_reads is not None and recent_reads:
        recent_reads[-1] = (captured_at, image, row_evidence)
    wanted.sort(key=lambda match: (match.box[1], match.box[0]))
    if return_uncertain:
        return wanted, uncertain
    return wanted


def notification_motion_agrees(first, second):
    """Permit a notification to slide vertically between two OCR samples."""
    height = max(8, first.box[3] - first.box[1], second.box[3] - second.box[1])
    return (
        abs(first.box[0] - second.box[0]) <= 1.5 * height
        and abs(first.box[1] - second.box[1]) <= 2.0 * height
    )


class UncertainMatchConfirmation:
    """Recover exact Kyber/Mythic-style pairs if the 'Droid' marker was unreadable.

    Never confirm from a single frame, multiple OCR variants of one frame, or
    two unrelated rows. Tracker then provides ordinary occurrence deduplication.
    """

    def __init__(self):
        self.previous = []
        self.last_at = None

    def reset(self):
        self.previous.clear()
        self.last_at = None

    def confirm(self, candidates, captured_at):
        verified = []
        if self.last_at is not None and 0 < captured_at - self.last_at <= 1.8:
            for candidate in candidates:
                if any(
                    old.pair == candidate.pair
                    and (
                        same_notification(old, candidate)
                        or notification_motion_agrees(old, candidate)
                    )
                    for old in self.previous
                ):
                    verified.append(candidate)
        self.previous = list(candidates)
        self.last_at = captured_at
        return verified


def client_area(window):
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    origin = wintypes.POINT()
    hwnd = wintypes.HWND(window)
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        return None
    return origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom


@dataclass(frozen=True)
class RelativeWatchArea:
    x0: float
    y0: float
    x1: float
    y1: float


def anchor_watch_area(client_bounds, selected):
    """Save the user's crop as game-client-relative fractions (0..1)."""
    left, top, right, bottom = client_bounds
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0 or not contains(client_bounds, selected):
        raise ValueError("Watch area must be inside the Fortnite client window")
    l, t, r, b = selected
    return RelativeWatchArea(
        (l - left) / width, (t - top) / height, (r - left) / width, (b - top) / height
    )


def project_watch_area(client_bounds, area):
    """Restore a crop after the window moves or changes its resolution."""
    left, top, right, bottom = client_bounds
    width, height = right - left, bottom - top
    if (
        width < 40
        or height < 20
        or not (0 <= area.x0 < area.x1 <= 1 and 0 <= area.y0 < area.y1 <= 1)
    ):
        return None
    result = (
        round(left + area.x0 * width),
        round(top + area.y0 * height),
        round(left + area.x1 * width),
        round(top + area.y1 * height),
    )
    if result[2] - result[0] < 40 or result[3] - result[1] < 20:
        return None
    return result


def find_game_window(identify):
    """Enumerate top-level desktop windows, independent of foreground focus."""
    user32 = ctypes.windll.user32
    candidates = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = (callback_type, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    user32.IsWindowVisible.restype = wintypes.BOOL

    @callback_type
    def each_window(hwnd, _):
        if user32.IsWindowVisible(hwnd) and identify(hwnd) and client_area(hwnd):
            candidates.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(each_window, 0)
    return candidates[0] if candidates else None


def give_background_scan_lower_priority():
    """Keep the PySide6 GUI and gameplay inputs ahead of OCR/desktop capture."""
    if os.name != "nt":
        return
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentThread.restype = wintypes.HANDLE
        kernel32.SetThreadPriority.argtypes = (wintypes.HANDLE, ctypes.c_int)
        kernel32.SetThreadPriority.restype = wintypes.BOOL
        # THREAD_PRIORITY_BELOW_NORMAL = -1. Only the calling worker thread
        # is adjusted; never alter the process or game process priority.
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), -1)
    except (AttributeError, OSError):
        pass


def contains(outer, inner):
    return (
        outer[0] <= inner[0] < inner[2] <= outer[2] and outer[1] <= inner[1] < inner[3] <= outer[3]
    )


def padded_region(region, bounds):
    left, top, right, bottom = region
    if not bounds:
        return region
    return (
        max(bounds[0], left - WATCH_MARGIN),
        max(bounds[1], top - WATCH_MARGIN),
        min(bounds[2], right + WATCH_MARGIN),
        min(bounds[3], bottom + WATCH_MARGIN),
    )


class FortniteVisibility:
    """Check whether the desktop capture region shows Fortnite, independently of focus."""

    def __init__(self, identify):
        self.identify = identify
        self.user32 = ctypes.windll.user32
        self.dwm_attribute = ctypes.windll.dwmapi.DwmGetWindowAttribute
        hwnd, uint = wintypes.HWND, wintypes.UINT
        self.user32.WindowFromPhysicalPoint.argtypes = (wintypes.POINT,)
        self.user32.WindowFromPhysicalPoint.restype = hwnd
        self.user32.GetAncestor.argtypes = (hwnd, uint)
        self.user32.GetAncestor.restype = hwnd
        self.user32.GetWindow.argtypes = (hwnd, uint)
        self.user32.GetWindow.restype = hwnd
        self.user32.IsWindowVisible.argtypes = (hwnd,)
        self.user32.IsIconic.argtypes = (hwnd,)
        self.user32.GetWindowRect.argtypes = (hwnd, ctypes.POINTER(wintypes.RECT))
        self.dwm_attribute.argtypes = (hwnd, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)

    def window_at_centre(self, region):
        left, top, right, bottom = region
        point = wintypes.POINT((left + right) // 2, (top + bottom) // 2)
        hit = self.user32.WindowFromPhysicalPoint(point)
        return self.user32.GetAncestor(hit, GA_ROOT) if hit else None

    def window_drawn(self, window):
        if not self.user32.IsWindowVisible(window) or self.user32.IsIconic(window):
            return False
        cloaked = wintypes.DWORD()
        result = self.dwm_attribute(
            window, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        return result != 0 or not cloaked.value

    def area_clear(self, window, region):
        """Check what actually receives hit-testing inside the selected game area.

        The previous Z-order bounding-box sweep treated transparent/click-through
        overlays as opaque and incorrectly marked a visible Fortnite image PAUSED.
        WindowFromPhysicalPoint ignores click-through regions. Probe the selected
        crop and overlapping window intersections, not just a window's bounds.
        """
        bounds = client_area(window) if self.window_drawn(window) else None
        if not bounds or not contains(bounds, region):
            return False
        left, top, right, bottom = region
        width, height = right - left, bottom - top
        if width < 2 or height < 2:
            return False
        xs = (left + 1, (left + right) // 2, right - 2)
        ys = (top + 1, (top + bottom) // 2, bottom - 2)
        for x in xs:
            for y in ys:
                if self.window_at_centre((x, y, x + 1, y + 1)) != window:
                    return False
        # Also sample the visible intersections of windows above the game.
        # A transparent overlay should not pause Watch Droid if a point still
        # hit-tests to Fortnite; a genuine covering window should.
        seen = {window}
        above = window
        while above := self.user32.GetWindow(above, GW_HWNDPREV):
            if above in seen:
                return False
            seen.add(above)
            if not self.window_drawn(above):
                continue
            rect = wintypes.RECT()
            result = self.dwm_attribute(
                above,
                DWMWA_EXTENDED_FRAME_BOUNDS,
                ctypes.byref(rect),
                ctypes.sizeof(rect),
            )
            if result != 0 and not self.user32.GetWindowRect(above, ctypes.byref(rect)):
                continue  # Do not pause the scanner because DWM lacks metadata.
            x0, y0 = max(left, rect.left), max(top, rect.top)
            x1, y1 = min(right, rect.right), min(bottom, rect.bottom)
            if x1 <= x0 or y1 <= y0:
                continue
            # If a window above Fortnite genuinely blocks any of the probe
            # points, the capture may be obscured. Click-through shells are ignored.
            probes = ((x0, y0), ((x0 + x1) // 2, (y0 + y1) // 2), (x1 - 1, y1 - 1))
            if any(self.window_at_centre((x, y, x + 1, y + 1)) != window for x, y in probes):
                return False
        return True

    def visible_window(self, region):
        window = self.window_at_centre(region)
        if window and self.identify(window) and self.area_clear(window, region):
            return window
        return None


def identify_fortnite_for_scan(window):
    """Identify the game by process path or exact title, without importing the UI."""
    if not window:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
    process = kernel32.OpenProcess(0x1000, False, pid.value)
    if process:
        try:
            path = ctypes.create_unicode_buffer(1024)
            length = wintypes.DWORD(len(path))
            if kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
                if Path(path.value).name.casefold().startswith("fortniteclient-"):
                    return True
        finally:
            kernel32.CloseHandle(process)
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextW(window, title, len(title))
    return title.value.strip().casefold() == "fortnite"


class _ProcessEventSignal:
    """Minimal signal adapter for the unmodified OCR and deduplication routines."""

    def __init__(self, events, name):
        self.events = events
        self.name = name

    def emit(self, cancelled, value):
        # Event volume is tiny (rare spawns and visibility transitions). Do not
        # silently discard an alert if the GUI briefly stalls.
        if self.name != "found":
            try:
                self.events.put((self.name, value), timeout=0.25)
            except (OSError, EOFError, ValueError, queue.Full):
                watch_logger().warning("noncritical_event_not_delivered type=%s", self.name)
            return
        # Never discard a named alert because the GUI's event queue is briefly full.
        while not cancelled.is_set():
            try:
                self.events.put((self.name, value), timeout=0.3)
                return
            except queue.Full:
                watch_logger().warning(
                    "rare_alert_waiting_for_gui type=%s item=%s", self.name, value
                )
            except (OSError, EOFError, ValueError) as exc:
                watch_logger().error(
                    "rare_alert_delivery_failed type=%s item=%s error=%s", self.name, value, exc
                )
                return


class _StandaloneDroidScanner:
    """Scanner-only host: no QApplication, widgets, or virtual controller."""

    def __init__(self, events, save_evidence=True, secondary_ocr=False):
        self.save_evidence = bool(save_evidence)
        self.secondary_ocr = bool(secondary_ocr)
        self.is_fortnite_window = identify_fortnite_for_scan
        self.found = _ProcessEventSignal(events, "found")
        self.failed = _ProcessEventSignal(events, "failed")
        self.visibility_changed = _ProcessEventSignal(events, "visible")
        self.health_changed = _ProcessEventSignal(events, "health")

    def resource(self, name):
        return asset_path(name)

    # Reuse the same tested capture and detection code, without duplication.
    def capture_frames(self, target, cancelled, finished, publish):
        return DroidAlert.capture_frames(self, target, cancelled, finished, publish)


def scan_in_separate_process(
    region, stop_event, event_queue, save_evidence=True, secondary_ocr=False
):
    """Windows spawn target. No Qt application or UI event loop is created."""
    try:
        configure_native_threads()
        worker = _StandaloneDroidScanner(event_queue, save_evidence, secondary_ocr)
        DroidAlert.watch(worker, region, stop_event)
    except BaseException as exc:
        _ProcessEventSignal(event_queue, "failed").emit(stop_event, f"{type(exc).__name__}: {exc}")


class AreaPreview(QLabel):
    selected = Signal(QRect)

    def __init__(self, pixmap):
        super().__init__()
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.band = QRubberBand(QRubberBand.Shape.Rectangle, self)
        self.origin = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.origin = event.position().toPoint()
            self.band.setGeometry(QRect(self.origin, self.origin))
            self.band.show()

    def mouseMoveEvent(self, event):
        if self.origin is not None:
            self.band.setGeometry(QRect(self.origin, event.position().toPoint()).normalized())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.origin is not None:
            box = (
                QRect(self.origin, event.position().toPoint()).normalized().intersected(self.rect())
            )
            self.origin = None
            self.band.setGeometry(box)
            self.selected.emit(box)


class DroidAlert(QObject):
    state_changed = Signal(str)
    found = Signal(object, str)
    failed = Signal(object, str)
    visibility_changed = Signal(object, bool)
    health_changed = Signal(object, object)
    history_changed = Signal(int)

    def __init__(self, parent, settings, foreground_fortnite, is_fortnite_window, resource):
        super().__init__(parent)
        self.settings = settings
        self.settings.remove("droidAlert/possible_alerts")
        self.foreground_fortnite = foreground_fortnite
        self.is_fortnite_window = is_fortnite_window
        self.resource = resource
        self.worker = None
        self.cancel = None
        self.scan_process = None
        self.process_stop = None
        self.process_events = None
        self.state = "Off"
        self.watch_visible = False
        self.last_match = ""
        self.error_dialog = None
        self.last_health_at = 0.0
        self.health_degraded = False
        self.health_watchdog = QTimer(self)
        self.health_watchdog.setInterval(2000)
        self.health_watchdog.timeout.connect(self.check_scanner_health)
        self.health_watchdog.start()
        self.enabled_pairs = {
            pair
            for pair in ALERT_CHOICES
            if settings.value(PAIR_SETTING_PREFIX + pair, pair in DEFAULT_ALERT_CHOICES, type=bool)
        }
        self.pending_alerts = deque()
        self.current_audio_pair = None
        self.alert_sequence = 0
        self.last_alert_time = 0.0
        self.last_alert_pair = ""
        # Deliberately not stored in QSettings or diagnostic files: cleared on exit.
        self.session_history = SessionAlertHistory()
        # Independent, non-modal visual channel in case Windows audio is
        # muted, delayed behind another ten-second clip, or cannot play.
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            try:
                self.tray = QSystemTrayIcon(QIcon(str(self.resource("app.ico"))), parent)
                self.tray.setToolTip("Droid Tycoon — Watch Droid")
                self.tray.show()
            except Exception as exc:
                watch_logger().warning("tray_notification_unavailable error=%s", exc)
                self.tray = None
        self.audio_timer = QTimer(self)
        self.audio_timer.setSingleShot(True)
        self.audio_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.audio_timer.timeout.connect(self.play_next_alert)
        self.found.connect(self.on_match)
        self.failed.connect(self.on_failure)
        self.visibility_changed.connect(self.on_visibility_changed)
        self.health_changed.connect(self.on_health)

    @property
    def active(self):
        return self.cancel is not None and not self.cancel.is_set()

    def saved_region(self):
        value = self.settings.value("droidAlert/region", "", type=str)
        try:
            left, top, right, bottom = map(int, value.split(","))
        except ValueError:
            return None
        if right - left >= 40 and bottom - top >= 20:
            return left, top, right, bottom
        return None

    @property
    def auto_start_enabled(self):
        return self.settings.value("droidAlert/auto_start", False, type=bool)

    def saved_target(self):
        """The preferred permanent window-relative crop; legacy pixels as fallback."""
        raw = self.settings.value("droidAlert/relative_region", "", type=str)
        if raw:
            try:
                coords = [float(x) for x in raw.split(",")]
                area = RelativeWatchArea(*coords)
                if len(coords) == 4 and 0 <= area.x0 < area.x1 <= 1 and 0 <= area.y0 < area.y1 <= 1:
                    return area
            except (ValueError, TypeError):
                pass
        return self.saved_region()

    def start_saved(self):
        target = self.saved_target()
        if target and self.enabled_pairs and not self.active:
            return self.start(target)
        return False

    def set_state(self, status):
        self.state = status
        self.state_changed.emit(status)

    def set_pair_enabled(self, pair, enabled):
        if enabled:
            self.enabled_pairs.add(pair)
        else:
            self.enabled_pairs.discard(pair)
            self.pending_alerts = deque(
                pending for pending in self.pending_alerts if pending != pair
            )
        self.settings.setValue(PAIR_SETTING_PREFIX + pair, enabled)

    def queue_alert(self, pair):
        """Queue only an explicit supported variant/rarity recording."""
        if pair not in ALERT_CHOICES:
            return False
        self.pending_alerts.append(pair)
        watch_logger().info("alert_queued pair=%s backlog=%d", pair, len(self.pending_alerts))
        if not self.audio_timer.isActive():
            self.play_next_alert()
        return True

    def play_next_alert(self):
        if not self.pending_alerts:
            self.current_audio_pair = None
            return

        import winsound

        pair = self.pending_alerts.popleft()
        self.current_audio_pair = pair
        filename = pair.lower().replace(" ", "_") + ".wav"
        path = str(self.resource(f"droid_alerts/{filename}"))
        try:
            with wave.open(path, "rb") as clip:
                duration_ms = math.ceil(1000 * clip.getnframes() / clip.getframerate())
            winsound.PlaySound(
                path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
            watch_logger().info("alert_audio_started pair=%s file=%s", pair, filename)
        except (OSError, EOFError, RuntimeError, wave.Error) as exc:
            watch_logger().error("alert_audio_failed pair=%s error=%s", pair, exc)
            self.set_state(f"Alarm could not play: {exc}")
            try:
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            except (RuntimeError, OSError):
                pass
            if self.pending_alerts:
                self.audio_timer.start(1)
        else:
            # Give asynchronous Windows playback time to start and finish the clip.
            self.audio_timer.start(duration_ms + 150)

    def test_alert(self):
        if not self.audio_timer.isActive() and self.enabled_pairs:
            sample = (
                "Kyber Mythic"
                if "Kyber Mythic" in self.enabled_pairs
                else next(pair for pair in ALERT_CHOICES if pair in self.enabled_pairs)
            )
            self.queue_alert(sample)

    def _record_history(self, name, classification):
        self.session_history.record(name, classification)
        self.history_changed.emit(len(self.session_history))

    def clear_history(self):
        self.session_history.clear()
        self.history_changed.emit(0)

    def show_history(self):
        """Display detected alerts this run only, updating as they arrive."""
        dialog = QDialog(self.parent())
        dialog.setObjectName("rareDroidAlarm")
        dialog.setStyleSheet("QDialog#rareDroidAlarm { background: #18151a; color: #f5f0f1; }")
        dialog.setWindowTitle("Watch Droid — Session Alert History")
        dialog.resize(660, 445)
        layout = QVBoxLayout(dialog)
        explanation = QLabel(
            "Alerts detected since this programme was opened. "
            "History is held in memory and cleared when the programme exits. "
            "Test Alert does not add an entry."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        count = QLabel()
        layout.addWidget(count)
        table = QTableWidget(0, 3, dialog)
        table.setHorizontalHeaderLabels(["Local time", "Droid / rarity", "Detection"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table)
        buttons = QHBoxLayout()
        clear = QPushButton("Clear Session History")
        close = QPushButton("Close")
        buttons.addWidget(clear)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)

        def refresh(_total=None):
            events = self.session_history.entries()
            count.setText(f"{len(events)} alert{'s' if len(events) != 1 else ''} this session")
            table.setRowCount(len(events))
            for row, entry in enumerate(reversed(events)):
                for col, value in enumerate((entry.timestamp, entry.droid, entry.classification)):
                    table.setItem(row, col, QTableWidgetItem(value))
            clear.setEnabled(bool(events))

        clear.clicked.connect(self.clear_history)
        close.clicked.connect(dialog.accept)
        self.history_changed.connect(refresh)
        refresh()
        try:
            dialog.exec()
        finally:
            self.history_changed.disconnect(refresh)

    def on_match(self, cancelled, pair):
        if self.active and self.cancel is cancelled and pair in self.enabled_pairs:
            self.alert_sequence += 1
            self._record_history(pair, "Confirmed")
            self.last_match = f"{pair} at {time.strftime('%H:%M:%S')}"
            self.last_alert_time = time.monotonic()
            self.last_alert_pair = pair
            watch_logger().info(
                "alert_received pair=%s alert_number=%d enabled=True", pair, self.alert_sequence
            )
            # Independently notify immediately rather than waiting behind a
            # long queued audio clip. Does not activate or steal game focus.
            try:
                if self.tray is not None:
                    self.tray.showMessage(
                        "RARE DROID DETECTED", pair, QSystemTrayIcon.MessageIcon.Information, 7000
                    )
            except (RuntimeError, OSError):
                pass
            status = "Watching" if self.watch_visible else PAUSED_STATUS
            self.set_state(f"{status}\nLast alert: {self.last_match}")
            self.queue_alert(pair)

    def on_failure(self, cancelled, error):
        if self.active and self.cancel is cancelled:
            watch_logger().error("watch_fatal_error %s", error)
            self.stop()
            self.set_state(f"ALARM ERROR — watch stopped: {error}")
            try:
                if self.tray is not None:
                    self.tray.showMessage(
                        "WATCH DROID STOPPED", str(error), QSystemTrayIcon.MessageIcon.Warning, 9000
                    )
            except (RuntimeError, OSError):
                pass

            if self.error_dialog is not None:
                self.error_dialog.close()
            message = QMessageBox(self.parent())
            message.setWindowTitle("Droid Watch stopped")
            message.setIcon(QMessageBox.Icon.Warning)
            message.setText("Droid Watch could not continue.")
            message.setInformativeText(str(error))
            message.setStandardButtons(QMessageBox.StandardButton.Ok)
            details = f"Danksy DroidOps {__version__}\nDroid Watch error: {error}"
            message.setDetailedText(details)
            copy = message.addButton("Copy error", QMessageBox.ButtonRole.ActionRole)
            copy.clicked.connect(lambda: QApplication.clipboard().setText(details))
            message.setWindowModality(Qt.WindowModality.NonModal)
            self.error_dialog = message
            message.show()

    def on_visibility_changed(self, cancelled, visible):
        if self.active and self.cancel is cancelled:
            self.watch_visible = visible
            self.last_health_at = time.monotonic()
            if not visible:
                self.health_degraded = False
            status = (
                "Watching Fortnite · other-monitor work is supported while notifications stay visible."
                if visible
                else PAUSED_STATUS
            )
            if self.last_match:
                status += f"\nLast alert: {self.last_match}"
            self.set_state(status)

    def on_health(self, cancelled, metrics):
        if not (self.active and self.cancel is cancelled):
            return
        self.last_health_at = time.monotonic()
        age_ms = float(metrics.get("frame_age_ms", 0))
        self.health_degraded = age_ms > 1500
        if self.watch_visible:
            if self.health_degraded:
                self.set_state(
                    f"WATCH ON / DELAYED — OCR {age_ms:.0f}ms behind. "
                    "Notification may be missed; reduce watched-area size."
                )
            elif self.state.startswith(("WATCH ON / DELAYED", "WATCH ON / STALLED")):
                self.set_state(
                    "Watching Fortnite · other-monitor work is supported while notifications stay visible."
                )

    def check_scanner_health(self):
        # A child process can remain alive but stop processing (e.g. OCR hang).
        if (
            self.active
            and self.watch_visible
            and self.last_health_at
            and time.monotonic() - self.last_health_at > 7.0
        ):
            if not self.state.startswith("WATCH ON / STALLED"):
                self.health_degraded = True
                self.set_state(
                    "WATCH ON / STALLED — OCR has not responded for 7 seconds. "
                    "Check the alarm and its log."
                )

    def start(self, region):
        # The OCR pipeline cannot share the GUI's Python interpreter without
        # occasionally monopolising the GIL during PIL image preparation.
        if self.worker is not None and self.worker.is_alive():
            return False
        if self.scan_process is not None and self.scan_process.is_alive():
            return False
        token = threading.Event()
        self.cancel = token
        self.watch_visible = False
        self.last_health_at = time.monotonic()
        self.health_degraded = False
        self.set_state("Starting independent droid scanner…")
        context = multiprocessing.get_context("spawn")
        self.process_stop = context.Event()
        self.process_events = context.Queue(maxsize=128)
        self.scan_process = context.Process(
            target=scan_in_separate_process,
            args=(
                region,
                self.process_stop,
                self.process_events,
                self.settings.value("droidAlert/save_evidence", False, type=bool),
                self.settings.value("droidAlert/secondary_ocr", False, type=bool),
            ),
            name="DroidAlarmOCR",
            daemon=True,
        )
        try:
            self.scan_process.start()
        except (OSError, RuntimeError, ValueError) as exc:
            token.set()
            self.set_state(f"Could not launch scanner: {exc}")
            self.process_events.close()
            self.process_events = None
            self.scan_process = None
            self.process_stop = None
            return False
        self.worker = threading.Thread(
            target=self._read_process_events,
            args=(token, self.scan_process, self.process_events, self.process_stop),
            name="DroidAlarmEvents",
            daemon=True,
        )
        self.worker.start()
        return True

    def _read_process_events(self, token, process, events, stop_event):
        """Non-blocking GUI bridge. Qt signals marshal events to the GUI thread."""
        failed = False
        try:
            while not token.is_set():
                if process.is_alive() and scanner_over_budget(process):
                    failed = True
                    stop_event.set()
                    process.terminate()
                    self.failed.emit(
                        token,
                        "Droid Watch stopped after reaching its 512 MB scanner memory limit. "
                        "Select a smaller notification area before retrying.",
                    )
                    break
                try:
                    name, value = events.get(timeout=0.20)
                except queue.Empty:
                    if not process.is_alive():
                        # Drain already queued rare alerts before reporting an exit.
                        try:
                            name, value = events.get_nowait()
                        except queue.Empty:
                            break
                    else:
                        continue
                except (EOFError, OSError, ValueError):
                    break
                if token.is_set():
                    break
                if name == "found":
                    self.found.emit(token, value)
                elif name == "visible":
                    self.visibility_changed.emit(token, bool(value))
                elif name == "health":
                    self.health_changed.emit(token, value)
                elif name == "failed":
                    failed = True
                    self.failed.emit(token, str(value))
                    break
        except Exception as exc:
            failed = True
            watch_logger().exception("scanner_bridge_error")
            self.failed.emit(token, f"Scanner supervision failed ({type(exc).__name__}): {exc}")
        finally:
            stop_event.set()
            process.join(timeout=1.5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=0.5)
            if not token.is_set() and not failed:
                self.failed.emit(
                    token, f"Droid scanner closed unexpectedly (exit {process.exitcode})."
                )
            # Queue feeder threads must not hold up application shutdown.
            events.cancel_join_thread()
            events.close()

    def stop(self):
        import winsound

        if self.active:
            self.cancel.set()
            if self.process_stop is not None:
                self.process_stop.set()
            self.set_state("Off")
        self.audio_timer.stop()
        self.pending_alerts.clear()
        self.current_audio_pair = None
        try:
            winsound.PlaySound(None, 0)
        except RuntimeError:
            pass

    def shutdown(self):
        """Stop playback, scanner processes and timers before the UI is destroyed."""
        self.health_watchdog.stop()
        self.stop()
        if self.tray is not None:
            self.tray.hide()
        worker = self.worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2.5)
        process = self.scan_process
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=0.5)

    def capture_frames(self, target, cancelled, finished, publish):
        give_background_scan_lower_priority()
        try:
            visibility = FortniteVisibility(self.is_fortnite_window)
            log = watch_logger()
            previously_visible = None
            visibility_lost_at = None
            segment = 0
            window_hint = None
            next_window_search = 0.0
            with MSS() as screen:
                while not cancelled.is_set() and not finished.is_set():
                    captured_at = time.monotonic()
                    if isinstance(target, RelativeWatchArea):
                        # Re-evaluate from the Fortnite client rect so moving
                        # the game window does not invalidate the saved area.
                        if window_hint is None or not visibility.window_drawn(window_hint):
                            window_hint = None
                            if captured_at >= next_window_search:
                                window_hint = find_game_window(self.is_fortnite_window)
                                next_window_search = captured_at + 1.0
                        bounds = client_area(window_hint) if window_hint else None
                        region = project_watch_area(bounds, target) if bounds else None
                        window = visibility.visible_window(region) if region else None
                        if window_hint and not window and not visibility.window_drawn(window_hint):
                            window_hint = None
                    else:
                        region = target
                        window = visibility.visible_window(region)
                    capture_region = region
                    if window and region:
                        validate_capture_region(region)
                        padded = padded_region(region, client_area(window))
                        try:
                            validate_capture_region(padded)
                        except ValueError:
                            padded = region
                        if padded != region and visibility.area_clear(window, padded):
                            capture_region = padded
                    if window:
                        validate_capture_region(capture_region)
                    frame = screen.grab(capture_region) if window else None
                    # A single Windows overlay/hit-test glitch must not flip
                    # the status to PAUSED. Only a sustained lack of visible
                    # game pixels is treated as a pause (OCR does not determine
                    # this status: an unchanged notification area remains ON).
                    # Region was already checked above. Do not repeat a full
                    # WindowFromPhysicalPoint / Z-order sweep after each grab.
                    visible = frame is not None and window is not None
                    if visible:
                        visibility_lost_at = None
                        if previously_visible is not True:
                            segment += 1
                            previously_visible = True
                            self.visibility_changed.emit(cancelled, True)
                            log.info("watch_area_visible region=%s hwnd=%s", capture_region, window)
                        publish((captured_at, (segment, window, capture_region), frame))
                    else:
                        if visibility_lost_at is None:
                            visibility_lost_at = captured_at
                        if previously_visible is None or captured_at - visibility_lost_at >= 0.65:
                            if previously_visible is not False:
                                segment += 1
                                previously_visible = False
                                self.visibility_changed.emit(cancelled, False)
                                log.warning(
                                    "watch_area_paused game_window=%s selected_region=%s "
                                    "hint_drawn=%s",
                                    window_hint,
                                    region,
                                    visibility.window_drawn(window_hint) if window_hint else False,
                                )
                    finished.wait(max(0, SCAN_INTERVAL - (time.monotonic() - captured_at)))
        except Exception as exc:
            publish(exc)

    def watch(self, region, cancelled):
        give_background_scan_lower_priority()
        log = watch_logger()
        log.info(
            "watch_start version=%s secondary_ocr=%s multiprocess=True target=%s",
            __version__,
            getattr(self, "secondary_ocr", False),
            region,
        )
        counts = {
            "captured": 0,
            "coalesced": 0,
            "dropped": 0,
            "read": 0,
            "confirmed_from_two_frames": 0,
            "alerts_sent": 0,
            "rapid_reads": 0,
            "visual_reads": 0,
        }
        next_report = 0.0
        frames = deque(maxlen=CAPTURE_BUFFER_SIZE)
        ready = threading.Condition()
        finished = threading.Event()

        def publish(item):
            with ready:
                if not isinstance(item, Exception):
                    counts["captured"] += 1
                    if len(frames) >= 2 and all(
                        not isinstance(old, Exception)
                        and old[1] == item[1]
                        and old[2].raw == item[2].raw
                        for old in (frames[-1], frames[-2])
                    ):
                        frames[-1] = item
                        counts["coalesced"] += 1
                        ready.notify()
                        return
                    capacity = max(
                        1, min(CAPTURE_BUFFER_SIZE, CAPTURE_BUFFER_BYTES // len(item[2].raw))
                    )
                    while len(frames) >= capacity:
                        frames.popleft()
                        counts["dropped"] += 1
                frames.append(item)
                ready.notify()

        capture = threading.Thread(
            target=self.capture_frames, args=(region, cancelled, finished, publish), daemon=True
        )
        try:
            from tesserocr import OEM, PSM, PyTessBaseAPI

            tracker = DroidTracker()
            uncertain_confirmation = UncertainMatchConfirmation()
            visual_confirmation = UncertainMatchConfirmation()
            secondary = RapidFallback(log, enabled=getattr(self, "secondary_ocr", False))
            vision = VisualLabelBank(logger=log)
            evidence = EvidenceWriter(enabled=getattr(self, "save_evidence", True), logger=log)
            last_vision_at = 0.0
            with PyTessBaseAPI(
                path=str(self.resource("tessdata")),
                lang="eng",
                oem=OEM.LSTM_ONLY,
                psm=PSM.SPARSE_TEXT,
            ) as ocr:
                capture.start()
                last_frame = None
                matches = []
                history = deque(maxlen=3)
                recent_reads = deque(maxlen=3)
                last_capture = None
                next_combat_pass = 0.0
                next_health = 0.0
                while not cancelled.is_set():
                    cooldown = 0.0
                    with ready:
                        if not ready.wait_for(
                            lambda: frames or cancelled.is_set(), timeout=SCAN_INTERVAL
                        ):
                            continue
                        if cancelled.is_set():
                            break
                        item = frames.popleft()
                    if isinstance(item, Exception):
                        raise item
                    captured_at, view, frame = item
                    segment, _, capture_region = view
                    if last_capture is not None and segment != last_capture[0][0]:
                        # The area was hidden, then reappeared. The old spawn
                        # must not suppress a newly visible Kyber Mythic.
                        tracker.reset()
                        uncertain_confirmation.reset()
                        visual_confirmation.reset()
                    elif last_capture is not None and captured_at - last_capture[1] > 0.5:
                        tracker.suspend()
                        uncertain_confirmation.reset()
                        visual_confirmation.reset()
                    if (
                        last_capture is None
                        or view != last_capture[0]
                        or captured_at - last_capture[1] > 3 * SCAN_INTERVAL
                    ):
                        history.clear()
                        recent_reads.clear()
                    last_capture = (view, captured_at)
                    snapshot = (view, frame.raw)
                    changed = snapshot != last_frame
                    if changed or not history:
                        image = frame_image(frame)
                    else:
                        image = history[-1]
                    history.append(image)

                    combat_mask = None
                    if (
                        len(history) == 3
                        and history[0] is not history[-1]
                        and captured_at >= next_combat_pass
                    ):
                        combat_mask = combat_text_mask(history)
                        next_combat_pass = captured_at + COMBAT_PASS_INTERVAL
                    if changed or combat_mask is not None:
                        began = time.monotonic()
                        matches, uncertain = recognise(
                            ocr,
                            frame,
                            capture_region[:2],
                            image=image,
                            combat_mask=combat_mask,
                            recent_reads=recent_reads,
                            captured_at=captured_at,
                            return_uncertain=True,
                        )
                        # Independently inspect difficult frames. Rate-limited
                        # to avoid a second engine overwhelming the capture queue.
                        # A secondary OCR result without a clear spawn context
                        # still needs two *distinct frames* before confirmation.
                        rapid_words = []
                        if changed and not matches:
                            rapid_words = secondary.read(
                                image, capture_region[:2], Word, cautious_label_repair, min_gap=0.50
                            )
                            if rapid_words:
                                counts["rapid_reads"] += 1
                                rapid_matches = matching_droids(rapid_words)
                                for candidate in rapid_matches:
                                    if candidate.pair not in ALERT_CHOICES:
                                        continue
                                    if spawn_context(candidate, rapid_words):
                                        if not any(
                                            duplicate_notification(candidate, old)
                                            for old in matches
                                        ):
                                            matches.append(candidate)
                                    elif not any(
                                        duplicate_notification(candidate, old) for old in uncertain
                                    ):
                                        uncertain.append(candidate)
                        # Learned visual text templates are a separate channel.
                        # They cannot alert until TWO frames agree and have
                        # acquired reliable real notification exemplars.
                        if (
                            changed
                            and vision.templates
                            and not matches
                            and time.monotonic() - last_vision_at >= 0.48
                        ):
                            last_vision_at = time.monotonic()
                            hints = visual_pair_matches(
                                vision.detect(image, capture_region[:2]), DroidMatch, Word
                            )
                            counts["visual_reads"] += 1
                            for candidate in visual_confirmation.confirm(hints, captured_at):
                                if candidate.pair in ALERT_CHOICES and not any(
                                    duplicate_notification(candidate, old) for old in matches
                                ):
                                    matches.append(candidate)
                                    log.info("visual_pair_verified pair=%s", candidate.pair)
                        # Exact-pair fallback also requires distinct
                        # screenshots; do not count variants of one frame twice.
                        additional = uncertain_confirmation.confirm(uncertain, captured_at)
                        for candidate in additional:
                            if not any(duplicate_notification(candidate, old) for old in matches):
                                matches.append(candidate)
                                counts["confirmed_from_two_frames"] += 1
                                log.info("pair_verified_from_two_frames pair=%s", candidate.pair)
                        # Reuse recognised tokens to learn only verified full labels.
                        tier_words = [*rapid_words]
                        # Reuse fast Tesseract tokens to avoid additional OCR.
                        # The recognised word cache is populated by recognise().
                        tier_words.extend(recent_reads[-1][2] if recent_reads else [])
                        # Learn non-fuzzy shapes only from context-verified OCR;
                        # never train on visual guesses, fuzzy repairs or a
                        # context-free two-frame fallback.
                        reliable = [
                            m
                            for m in matches
                            if (
                                spawn_context(m, tier_words)
                                and m.labels
                                and not any(w.approximate for w in m.labels)
                            )
                        ]
                        if reliable:
                            vision.learn(image, reliable, capture_region[:2])
                        last_frame = snapshot
                        counts["read"] += 1
                        ended = time.monotonic()
                        cooldown = min(1.0, max(0.03, ended - began))
                        if ended >= next_report:
                            log.info(
                                "scan ocr_ms=%.0f frame_age_ms=%.0f queue=%s counts=%s detected=%s",
                                1000 * (ended - began),
                                max(0, 1000 * (ended - captured_at)),
                                len(frames),
                                counts.copy(),
                                [m.pair for m in matches],
                            )
                            next_report = ended + 10.0
                    heartbeat_at = time.monotonic()
                    if heartbeat_at >= next_health:
                        self.health_changed.emit(
                            cancelled,
                            {
                                "frame_age_ms": max(0, 1000 * (heartbeat_at - captured_at)),
                                "dropped": counts["dropped"],
                            },
                        )
                        next_health = heartbeat_at + 2.0
                    for match in tracker.update(matches, captured_at, image, capture_region[:2]):
                        if cancelled.is_set():
                            break
                        log.info("new_occurrence pair=%s", match.pair)
                        evidence.submit(image, "confirmed", match.pair, captured_at, gap=0.5)
                        self.found.emit(cancelled, match.pair)
                        counts["alerts_sent"] += 1
                    if cooldown:
                        cancelled.wait(cooldown)
        except Exception as exc:
            if not cancelled.is_set():
                log.exception("scanner_exception")
                self.failed.emit(cancelled, f"{type(exc).__name__}: {exc}")
        finally:
            log.info("watch_stop counts=%s", counts)
            if "evidence" in locals():
                evidence.stop()
            finished.set()
            if capture.is_alive():
                capture.join(timeout=0.5)

    def configure(self):
        parent = self.parent()
        dialog = QDialog(parent)
        dialog.setObjectName("rareDroidAlarm")
        dialog.setStyleSheet(
            "QDialog#rareDroidAlarm { background: #18151a; color: #f5f0f1; }"
            "QDialog#rareDroidAlarm QLabel, QDialog#rareDroidAlarm QCheckBox, "
            "QDialog#rareDroidAlarm QGroupBox { color: #f5f0f1; }"
            "QWidget#droidRarityMatrix { background: #211d25; }"
            "QDialog#rareDroidAlarm QScrollArea { border: 1px solid #4a3c49; }"
            "QDialog#rareDroidAlarm QCheckBox::indicator { width: 16px; height: 16px; "
            "border: 1px solid #786777; border-radius: 3px; background: #302832; }"
            "QDialog#rareDroidAlarm QCheckBox::indicator:checked { "
            "background: #b52d50; border: 2px solid #f18ca5; }"
        )
        dialog.setWindowTitle("Rare Droid Alarm")
        dialog.setMinimumWidth(680)
        dialog.setMinimumHeight(680)
        layout = QVBoxLayout(dialog)
        instructions = QLabel(
            "Choose the droid notification and side-by-side rarity area once. "
            "The saved crop follows Fortnite when its window moves or resizes. "
            "Each alert announces the droid, rings for 7 seconds and repeats the name. "
            "Keep Fortnite visible on its monitor; you may freely use applications on your other screen. "
            "Minimising Fortnite or covering the notification pauses screen-based detection."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        filters = QGroupBox("Alert for")
        filter_layout = QVBoxLayout(filters)
        filter_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        filter_help = QLabel(
            "Tick each exact combination you want. Alerts require a recognised variant and rarity. Stella is recognised as Stellar. Default/Gold require a visible game notification."
        )
        filter_help.setWordWrap(True)
        filter_layout.addWidget(filter_help)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(265)
        scroll.setMaximumHeight(340)
        matrix = QWidget()
        matrix.setObjectName("droidRarityMatrix")
        choices = QGridLayout(matrix)
        choices.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        scroll.setWidget(matrix)
        filter_layout.addWidget(scroll)
        layout.addWidget(filters)
        status = QLabel()
        status.setWordWrap(True)
        layout.addWidget(status)
        area = QPushButton("SET NOTIFICATION WINDOW")
        toggle = QPushButton()
        test = QPushButton("Test Alert")
        history = QPushButton("ALERT HISTORY")
        close = QPushButton("Close")
        buttons = QHBoxLayout()
        for button in (area, toggle, test, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        history.setToolTip("View alerts detected during this launch; none are restored next time")
        layout.addWidget(history)
        auto_watch = QCheckBox("Automatically start Watch Droid when this programme opens")
        auto_watch.setChecked(self.auto_start_enabled)
        auto_watch.setToolTip(
            "Uses the saved position; monitoring pauses while Fortnite is hidden."
        )
        auto_watch.toggled.connect(
            lambda enabled: self.settings.setValue("droidAlert/auto_start", enabled)
        )
        layout.addWidget(auto_watch)
        evidence_toggle = QCheckBox("Keep local screenshots of detected notifications")
        evidence_toggle.setChecked(
            self.settings.value("droidAlert/save_evidence", False, type=bool)
        )
        evidence_toggle.setToolTip(
            "Stores up to 180 notification-area screenshots under %%LOCALAPPDATA%%; never uploads them."
        )
        evidence_toggle.toggled.connect(
            lambda enabled: self.settings.setValue("droidAlert/save_evidence", enabled)
        )
        layout.addWidget(evidence_toggle)
        secondary_toggle = QCheckBox("Use additional OCR (experimental; more memory)")
        secondary_toggle.setChecked(
            self.settings.value("droidAlert/secondary_ocr", False, type=bool)
        )
        secondary_toggle.setToolTip(
            "Off by default while compatibility checks continue. May improve difficult text, "
            "but its third-party runtime may contact Microsoft. Restart Droid Watch after changing."
        )
        secondary_toggle.toggled.connect(
            lambda enabled: self.settings.setValue("droidAlert/secondary_ocr", enabled)
        )
        layout.addWidget(secondary_toggle)
        capture_pending = False

        def refresh(_state=None):
            target = self.saved_target()
            saved = (
                "Notification saved — follows Fortnite window."
                if isinstance(target, RelativeWatchArea)
                else "Legacy position saved — recalibrate once to follow Fortnite."
                if target
                else "Select the notification area once to save it permanently."
            )
            details = (
                f"\nLast alert: {self.last_match}" if self.last_match and not self.active else ""
            )
            if capture_pending:
                status.setText(
                    "Switch to Fortnite now. Capturing the watch-area preview in four seconds…"
                )
            else:
                selection = "" if self.enabled_pairs else "\nTick at least one droid combination."
                status.setText(f"{saved}\n{self.state}{details}{selection}")
            area.setEnabled(not self.active and not capture_pending)
            toggle.setText("Stop Watching" if self.active else "Start Watching")
            toggle.setEnabled(
                self.active
                or bool(self.saved_target() and self.enabled_pairs and not capture_pending)
            )
            test.setEnabled(bool(self.enabled_pairs))

        def select_pair(pair, enabled):
            self.set_pair_enabled(pair, enabled)
            refresh()

        for column, rarity in enumerate(RARITY_NAMES, 1):
            choices.addWidget(QLabel(rarity), 0, column)
        for row, variant in enumerate(VARIANT_NAMES, 1):
            choices.addWidget(QLabel(variant), row, 0)
            for column, rarity in enumerate(RARITY_NAMES, 1):
                pair = f"{variant} {rarity}"
                check = QCheckBox()
                check.setAccessibleName(pair)
                check.setToolTip(pair)
                check.setChecked(pair in self.enabled_pairs)
                check.toggled.connect(lambda enabled, pair=pair: select_pair(pair, enabled))
                choices.addWidget(check, row, column, alignment=Qt.AlignmentFlag.AlignCenter)
        matrix.setMinimumSize(choices.minimumSize())

        def choose():
            nonlocal capture_pending
            capture_pending = True
            refresh()

            def capture():
                nonlocal capture_pending
                if not dialog.isVisible():
                    return
                try:
                    window = self.foreground_fortnite()
                    bounds = client_area(window) if window else None
                    if not bounds:
                        raise RuntimeError(
                            "Fortnite was not in focus. Try again and switch to it within four seconds."
                        )
                    with MSS() as screen:
                        desktop = screen.monitors[0]
                        left = max(bounds[0], desktop["left"])
                        top = max(bounds[1], desktop["top"])
                        right = min(bounds[2], desktop["left"] + desktop["width"])
                        bottom = min(bounds[3], desktop["top"] + desktop["height"])
                        if right <= left or bottom <= top:
                            raise RuntimeError(
                                "The Fortnite window is outside the visible desktop."
                            )
                        frame = screen.grab((left, top, right, bottom))
                    if self.foreground_fortnite() != window:
                        raise RuntimeError("Fortnite lost focus during capture. Try again.")
                except Exception as exc:
                    QMessageBox.warning(dialog, "Watch area capture", str(exc))
                else:
                    self.select_region(dialog, frame, left, top, bounds)
                finally:
                    capture_pending = False
                    refresh()

            QTimer.singleShot(4000, dialog, capture)

        def toggle_watch():
            if self.active:
                self.stop()
            elif region := self.saved_target():
                if self.start(region):
                    dialog.accept()
                else:
                    QMessageBox.information(
                        dialog,
                        "Rare Droid Alarm",
                        "The previous scan is finishing. Try again in a moment.",
                    )

        area.setToolTip("Switch to Fortnite within four seconds to capture the setup preview.")
        area.clicked.connect(choose)
        toggle.clicked.connect(toggle_watch)
        test.clicked.connect(self.test_alert)
        history.clicked.connect(self.show_history)
        close.clicked.connect(dialog.reject)
        self.state_changed.connect(refresh)
        refresh()
        try:
            dialog.exec()
        finally:
            self.state_changed.disconnect(refresh)

    def select_region(self, parent, frame, left, top, client_bounds):
        dialog = QDialog(parent)
        dialog.setWindowTitle("Select the droid watch area")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Drag around the droid labels and the rarities next to them."))
        picture = QImage(
            frame.rgb, frame.width, frame.height, frame.width * 3, QImage.Format.Format_RGB888
        )
        available = parent.screen().availableGeometry()
        pixmap = QPixmap.fromImage(picture).scaled(
            int(available.width() * 0.88),
            int(available.height() * 0.78),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        preview = AreaPreview(pixmap)
        layout.addWidget(preview)
        save = QPushButton("Save Watch Area")
        save.setEnabled(False)
        layout.addWidget(save)
        selection = None

        def select(box):
            nonlocal selection
            x_scale = frame.width / pixmap.width()
            y_scale = frame.height / pixmap.height()
            x0, y0 = round(box.x() * x_scale), round(box.y() * y_scale)
            x1 = round((box.x() + box.width()) * x_scale)
            y1 = round((box.y() + box.height()) * y_scale)
            selection = left + x0, top + y0, left + x1, top + y1
            save.setEnabled(x1 - x0 >= 40 and y1 - y0 >= 20)

        preview.selected.connect(select)
        save.clicked.connect(dialog.accept)
        if dialog.exec() == QDialog.DialogCode.Accepted and selection:
            normalized = anchor_watch_area(client_bounds, selection)
            self.settings.setValue(
                "droidAlert/relative_region",
                ",".join(
                    f"{value:.8f}"
                    for value in (
                        normalized.x0,
                        normalized.y0,
                        normalized.x1,
                        normalized.y1,
                    )
                ),
            )
            self.settings.setValue("droidAlert/region", ",".join(map(str, selection)))
            self.settings.sync()
