"""Droid Tycoon DroidOps — automation, missions and visual droid monitoring."""

import os
import sys
import time
import math
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    Qt,
    QTimer,
    Signal,
    QObject,
    QRect,
    QRectF,
    QPoint,
    QPointF,
    QSize,
    QEvent,
    QSettings,
)
from PySide6.QtGui import (
    QColor,
    QIcon,
    QPixmap,
    QPainter,
    QPen,
    QFont,
    QFontDatabase,
    QRadialGradient,
    QLinearGradient,
    QPainterPath,
)
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QComboBox,
    QSpinBox,
    QAbstractSpinBox,
    QFrame,
    QMessageBox,
    QSizePolicy,
    QDialog,
    QFormLayout,
)

if os.name != "nt":
    raise SystemExit("This application requires Windows.")

try:
    import ctypes
    import vgamepad as vg
except Exception as exc:
    raise SystemExit(f"Unable to load the virtual-controller component: {exc}") from exc

from .droid_alert import DroidAlert
from .cb23_turn import run_right_stick_turn
from .xinput_status import TurnObservation
from .resources import asset_path


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetWindowTextW.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar), ctypes.c_int)
user32.GetWindowThreadProcessId.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
user32.mouse_event.argtypes = (
    ctypes.c_ulong,
    ctypes.c_long,
    ctypes.c_long,
    ctypes.c_ulong,
    ctypes.c_size_t,
)
user32.mouse_event.restype = None
kernel32.OpenProcess.argtypes = (ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong)
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.QueryFullProcessImageNameW.argtypes = (
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.POINTER(ctypes.c_wchar),
    ctypes.POINTER(ctypes.c_ulong),
)
kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
VK_F8 = 0x77
VK_F9 = 0x78
VK_F10 = 0x79  # Test the saved CB-23 left turn from inside Fortnite.
NUDGE_INTERVAL = 15.0
NUDGE_HOLD = 0.035
NUDGE_STRENGTH = 0.60
CB23_RESTART_DELAY = 10
CB23_FOCUS_TIMEOUT = 30
CB23_TURN_QUIET_TIME = 1.0
APP_USER_MODEL_ID = "DaneVanzino.DroidTycoonAutoClickerV1"
CONTROLS = [
    "Right Trigger",
    "Left Trigger",
    "A",
    "B",
    "X",
    "Y",
    "Right Bumper",
    "Left Bumper",
    "D-Pad Up",
    "D-Pad Down",
    "D-Pad Left",
    "D-Pad Right",
    "Start",
    "Back",
    "Left Stick Click",
    "Right Stick Click",
]
BUTTON_MAP = {
    "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
    "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
    "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
    "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
    "Left Bumper": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
    "Right Bumper": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
    "D-Pad Up": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
    "D-Pad Down": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
    "D-Pad Left": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
    "D-Pad Right": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    "Start": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
    "Back": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
    "Left Stick Click": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
    "Right Stick Click": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
}


def resource(name):
    return asset_path(name)


@dataclass(frozen=True)
class CB23Settings:
    wait_seconds: int = 1110
    turn_ms: int = 500
    down_steps: int = 6
    interact: str = "X"
    hold_ms: int = 650
    select: str = "A"
    confirm: str = "None"
    camera_input: str = "Right Stick"
    mouse_counts: int = 450
    nudge_return_ms: int = 45


def cb23_setting_key(key):
    # CB-23 is a different menu row. Keep the previous timing and controller bindings.
    if key in ("down_steps", "camera_input", "mouse_counts", "nudge_return_ms"):
        return f"cb23/{key}"
    return f"stellar/{key}"


def is_fortnite_window(window):
    if not window:
        return False
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
    process = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if process:
        try:
            path = ctypes.create_unicode_buffer(1024)
            length = ctypes.c_ulong(len(path))
            if kernel32.QueryFullProcessImageNameW(process, 0, path, ctypes.byref(length)):
                name = Path(path.value).name.casefold()
                if name.startswith("fortniteclient-"):
                    return True
        finally:
            kernel32.CloseHandle(process)
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(window, title, len(title))
    return title.value.strip().casefold() == "fortnite"


def foreground_fortnite():
    window = user32.GetForegroundWindow()
    return window if is_fortnite_window(window) else None


class MissionFocusLost(Exception):
    pass


class Events(QObject):
    count = Signal(int)
    finished = Signal(str)
    tested = Signal(str)
    error = Signal(str)
    mission_status = Signal(str)


class ArtworkWidget(QWidget):
    """The supplied droid artwork with a subtle animated chest glow."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(370)
        # Keep the original pixels; QIcon.pixmap(380, 330) would rasterise the
        # artwork at 1x and let Windows enlarge it on high-DPI monitors.
        self.pixmap = QPixmap(str(resource("hero_droid.png")))
        self.phase = 0.0
        self._started_at = time.monotonic()
        self._scaled_art = None
        self._scaled_art_key = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(90)

    def advance(self):
        if not self.isVisible() or self.window().isMinimized():
            return
        self.phase = ((time.monotonic() - self._started_at) * (0.095 / 0.055)) % (2 * math.pi)
        self.update()

    def resizeEvent(self, event):
        self._scaled_art = None
        self._scaled_art_key = None
        super().resizeEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        art_h = min(self.height(), self.width() * self.pixmap.height() / self.pixmap.width())
        art_w = art_h * self.pixmap.width() / self.pixmap.height()
        # Fit the full supplied droid without distortion and centre its image.
        x = (self.width() - art_w) / 2
        y = (self.height() - art_h) / 2
        # Resampling a multi-megapixel PNG on each 55 ms glow tick is costly.
        # Keep a single device-resolution bitmap until size or DPI changes.
        dpr = self.devicePixelRatioF()
        key = (max(1, round(art_w * dpr)), max(1, round(art_h * dpr)), round(dpr, 4))
        if self._scaled_art is None or self._scaled_art_key != key:
            self._scaled_art = self.pixmap.scaled(
                key[0],
                key[1],
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._scaled_art.setDevicePixelRatio(dpr)
            self._scaled_art_key = key
        p.drawPixmap(QPointF(x, y), self._scaled_art)
        alpha = 15 + int((math.sin(self.phase) + 1) * 8)
        centre_x = x + art_w * 0.60
        centre_y = y + art_h * 0.52
        halo = QRadialGradient(centre_x, centre_y, 44)
        halo.setColorAt(0, QColor(255, 45, 64, alpha))
        halo.setColorAt(1, QColor(255, 45, 64, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QRectF(centre_x - 44, centre_y - 44, 88, 88))
        p.end()


class ModeIndicator(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(23, 23)
        self.mode = "idle"
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)

    def advance(self):
        self.phase = (self.phase + 0.16) % (2 * math.pi)
        self.update()

    def set_mode(self, mode):
        self.mode = mode
        self.timer.start(60) if mode == "active" else self.timer.stop()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        level = 0.65 + 0.35 * math.sin(self.phase) if self.mode == "active" else 1
        color = QColor(
            "#f6475e"
            if self.mode == "active"
            else "#d65162"
            if self.mode in ("ready", "stopped")
            else "#8c858c"
        )
        color.setAlphaF(level)
        p.setPen(Qt.PenStyle.NoPen)
        bezel = QLinearGradient(0, 1, 0, 22)
        bezel.setColorAt(0, QColor("#b2a5ac"))
        bezel.setColorAt(0.5, QColor("#302c33"))
        bezel.setColorAt(1, QColor("#080a0e"))
        p.setBrush(bezel)
        p.drawEllipse(QRectF(1, 1, 21, 21))
        p.setBrush(QColor("#090b10"))
        p.drawEllipse(QRectF(3, 3, 17, 17))
        p.setPen(QPen(color, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(4, 4, 15, 15))
        p.setPen(Qt.PenStyle.NoPen)
        core = QRadialGradient(10, 9, 8)
        core.setColorAt(0, QColor("#fff5f6"))
        core.setColorAt(0.38, color)
        core.setColorAt(1, QColor("#3b0714"))
        p.setBrush(core)
        p.drawEllipse(QRectF(7, 7, 9, 9))
        p.end()


class PulseCanvas(QWidget):
    """Qt timeline: cached stationary artwork, time-based cursor animation.

    Rebuilding gradients and paths 33 times each second starves the GUI event
    loop when other animations run. Only the moving dot needs fresh painting.
    """

    def __init__(self):
        super().__init__()
        self.interval = 500
        self.pulse = 45
        self.running = False
        self.phase = 0.0
        self._cycle_started_at = time.monotonic()
        self._background = None
        self._background_key = None
        self.setFixedHeight(94)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

    def tick(self):
        if not self.isVisible() or self.window().isMinimized():
            return
        # Original motion: 0.012 / 30ms = 0.4 cycles/sec, i.e. 2.5 sec.
        # This is independent of callback jitter; no catch-up redraw bursts.
        new_phase = ((time.monotonic() - self._cycle_started_at) / 2.5) % 1.0
        if abs(new_phase - self.phase) > 0.0001:
            self.phase = new_phase
            self.update()

    def set_state(self, running):
        self.running = running
        self.phase = 0.0
        self._cycle_started_at = time.monotonic()
        self.timer.start(30) if running else self.timer.stop()
        self.update()

    def set_values(self, interval, pulse):
        if (self.interval, self.pulse) != (interval, pulse):
            self.interval, self.pulse = interval, pulse
            self._background = None
            self._background_key = None
            self.update()

    def _paint_stationary(self, p):
        """Executed only if dimensions/DPI or pulse settings change."""
        w = self.width()
        p.setPen(QColor("#998f96"))
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        p.drawText(0, 18, "PULSE TIMELINE")
        p.setPen(QColor("#ff5269"))
        p.drawText(
            QRectF(w - 150, 0, 150, 24),
            Qt.AlignmentFlag.AlignRight,
            f"{self.pulse} ms / {self.interval} ms",
        )
        left, right = 7, max(38, w - 7)
        width = right - left
        track = QRectF(1, 34, max(20, w - 2), 53)
        well = QLinearGradient(0, track.top(), 0, track.bottom())
        well.setColorAt(0, QColor("#262229"))
        well.setColorAt(0.12, QColor("#11141a"))
        well.setColorAt(0.75, QColor("#080a0f"))
        well.setColorAt(1, QColor("#1d1a21"))
        p.setPen(QPen(QColor("#3f343d"), 1))
        p.setBrush(well)
        p.drawRoundedRect(track, 3, 3)
        p.setPen(QPen(QColor(255, 224, 230, 39), 1))
        p.drawLine(QPointF(5, 36), QPointF(w - 5, 36))
        p.setPen(QPen(QColor(0, 0, 0, 225), 4))
        p.drawLine(QPointF(left, 74), QPointF(right, 74))
        p.setPen(QPen(QColor("#59323c"), 2))
        p.drawLine(QPointF(left, 72), QPointF(right, 72))
        p.setPen(QPen(QColor("#9a4a5b"), 0.8))
        p.drawLine(QPointF(left, 71), QPointF(right, 71))
        ratio = min(0.88, self.pulse / max(1, self.interval))
        cycle = width / 4
        for i in range(4):
            x = left + i * cycle
            if i:
                p.setPen(QPen(QColor(255, 255, 255, 20), 1))
                p.drawLine(QPointF(x, 42), QPointF(x, 67))
                p.setPen(QPen(QColor("#712d3d"), 1))
                p.drawLine(QPointF(x, 77), QPointF(x, 81))
            hi = min(right - 2, x + max(9, cycle * ratio))
            # Filled, bevelled pulse blocks read as raised signal hardware.
            pulse = QPainterPath()
            pulse.moveTo(x, 71)
            pulse.lineTo(x, 48)
            pulse.lineTo(x + 3, 44)
            pulse.lineTo(hi - 3, 44)
            pulse.lineTo(hi, 48)
            pulse.lineTo(hi, 71)
            pulse.closeSubpath()
            p.fillPath(pulse.translated(1.5, 2), QColor(0, 0, 0, 200))
            red = QLinearGradient(0, 44, 0, 72)
            red.setColorAt(0, QColor("#ffc2cb"))
            red.setColorAt(0.13, QColor("#ff526a"))
            red.setColorAt(0.55, QColor("#c72043"))
            red.setColorAt(1, QColor("#68152d"))
            p.fillPath(pulse, red)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#f24c64"), 1))
            p.drawPath(pulse)
            p.setPen(QPen(QColor(255, 235, 239, 110), 1))
            p.drawLine(QPointF(x + 3, 46), QPointF(hi - 3, 46))

    def paintEvent(self, _event):
        dpr = self.devicePixelRatioF()
        cache_key = (self.width(), self.height(), round(dpr, 4), self.interval, self.pulse)
        if cache_key != self._background_key or self._background is None:
            background = QPixmap(
                max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr))
            )
            background.setDevicePixelRatio(dpr)
            background.fill(Qt.GlobalColor.transparent)
            painter = QPainter(background)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._paint_stationary(painter)
            painter.end()
            self._background = background
            self._background_key = cache_key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._background)
        if self.running:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w = self.width()
            left, right = 7, max(38, w - 7)
            width = right - left
            x = left + width * self.phase
            glow = QRadialGradient(x, 72, 15)
            glow.setColorAt(0, QColor(255, 103, 126, 125))
            glow.setColorAt(1, QColor(255, 60, 90, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QRectF(x - 15, 57, 30, 30))
            bead = QRadialGradient(x - 1, 69, 6)
            bead.setColorAt(0, QColor("#ffffff"))
            bead.setColorAt(0.36, QColor("#ff98a7"))
            bead.setColorAt(1, QColor("#bd1b38"))
            p.setBrush(bead)
            p.setPen(QPen(QColor("#ff8d9e"), 1))
            p.drawEllipse(QRectF(x - 4, 68, 8, 8))
        p.end()


class MonoWalker(QWidget):
    """The user's Mono pet: stationary idle pose and a rhythmic arm-strike loop."""

    FRAME_WIDTH = 192
    FRAME_HEIGHT = 208
    CROP_X = 20
    CROP_WIDTH = 152

    def __init__(self):
        super().__init__()
        sheet = QPixmap(str(resource("mono_spritesheet.png")))
        if sheet.isNull() or sheet.width() != 1536 or sheet.height() != 2288:
            raise RuntimeError("Mono Walker animation sheet is missing or invalid.")
        self.idle = sheet.copy(QRect(self.CROP_X, 0, self.CROP_WIDTH, self.FRAME_HEIGHT))
        # Alternate the pet's left- and right-arm work poses with its high
        # waving pose. All frames come from the user's original Mono atlas.
        sequence = ((7, 0), (7, 1), (7, 2), (7, 3), (7, 4), (3, 2), (7, 5), (7, 3))
        self.whack = [
            sheet.copy(
                QRect(
                    col * self.FRAME_WIDTH + self.CROP_X,
                    row * self.FRAME_HEIGHT,
                    self.CROP_WIDTH,
                    self.FRAME_HEIGHT,
                )
            )
            for row, col in sequence
        ]
        self.frame = 0
        self.running = False
        self._animation_started_at = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.setFixedWidth(100)
        self.setAccessibleName("Mono Walker animation")

    def set_running(self, running):
        self.running = running
        self.frame = 0
        self._animation_started_at = time.monotonic()
        self.timer.start(90) if running else self.timer.stop()
        self.update()

    def advance(self):
        if not self.isVisible() or self.window().isMinimized():
            return
        # Prevent the creature slowing down if Qt misses a callback. The
        # actual 90ms frame cadence and eight authored poses are unchanged.
        frame = int((time.monotonic() - self._animation_started_at) / 0.09) % len(self.whack)
        if frame != self.frame:
            self.frame = frame
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor("#6e2535"), 1))
        p.drawLine(QPointF(1, 15), QPointF(1, max(16, h - 12)))
        p.setPen(QColor("#bfa9b1"))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        p.drawText(QRectF(5, 2, w - 10, 17), Qt.AlignmentFlag.AlignCenter, "MONO WALKER")
        frame = self.whack[self.frame] if self.running else self.idle
        available_h = max(40, h - 27)
        height = min(available_h, (w - 4) * self.FRAME_HEIGHT / self.FRAME_WIDTH)
        width = height * self.FRAME_WIDTH / self.FRAME_HEIGHT
        x = (w - width) / 2
        y = h - height - 5
        p.drawPixmap(QRectF(x, y, width, height), frame, QRectF(frame.rect()))
        if self.running and self.frame in (3, 7):
            # Brief contact sparks make the downward arm swing read as a hit.
            centre = QPointF(w * (0.32 if self.frame == 3 else 0.72), h * 0.58)
            p.setPen(QPen(QColor(255, 78, 103, 180), 1.7))
            for dx, dy in ((-11, -3), (-7, -10), (9, -8), (12, 2)):
                p.drawLine(centre + QPointF(dx * 0.48, dy * 0.48), centre + QPointF(dx, dy))
        p.setPen(QPen(QColor("#7b2738"), 1))
        p.drawLine(QPointF(w * 0.18, h - 3), QPointF(w * 0.82, h - 3))
        p.end()


class GlossButton(QPushButton):
    """Raised control with a clipped, slowly travelling specular highlight."""

    COLOURS = {
        "primary": ("#ff7182", "#d72240", "#7c1025", "#ff9daa"),
        "connect": ("#9e5362", "#5b2531", "#30141d", "#dc8491"),
        "secondary": ("#55535e", "#29272e", "#15161c", "#b58c98"),
        "danger": ("#794353", "#40212a", "#211419", "#ae6a7a"),
    }

    def __init__(self, text, role, parent=None):
        super().__init__(text, parent)
        self.role = role
        self.setObjectName(role)
        self.setMouseTracking(True)
        self._shine_visible = False
        self.shine_timer = QTimer(self)
        self.shine_timer.timeout.connect(self._advance_shine)
        self.shine_timer.start(80)

    def _advance_shine(self):
        phase = self._shine_phase()
        shining = phase < 0.27
        connected = self.role == "connect" and self.text() == "CONNECTED"
        if self.isVisible() and (shining or self._shine_visible or connected):
            self.update()
        self._shine_visible = shining

    def _shine_phase(self):
        offset = {"primary": 0, "connect": 1150, "secondary": 2250, "danger": 3200}[self.role]
        return (time.monotonic() * 1000 + offset) % 5700 / 5700

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        enabled, pressed = self.isEnabled(), self.isDown()
        hovering = self.underMouse() and enabled
        top, middle, bottom, edge = self.COLOURS[self.role]
        if not enabled:
            top, middle, bottom, edge = ("#363038", "#29252b", "#211e23", "#57414a")

        # Recessed shadow below the lower rim supplies the physical depth.
        shadow = QPainterPath()
        shadow.addRect(QRectF(3, 5, width - 6, height - 5))
        p.fillPath(shadow, QColor(0, 0, 0, 165 if enabled else 65))
        shift = 2 if pressed else 0
        face = QRectF(1.5, 1.5 + shift, width - 3, height - 6)
        shape = QPainterPath()
        shape.moveTo(face.left(), face.top() + 9)
        shape.lineTo(face.left() + 9, face.top())
        shape.lineTo(face.right() - 12, face.top())
        shape.lineTo(face.right(), face.top() + 12)
        shape.lineTo(face.right(), face.bottom() - 9)
        shape.lineTo(face.right() - 9, face.bottom())
        shape.lineTo(face.left() + 12, face.bottom())
        shape.lineTo(face.left(), face.bottom() - 12)
        shape.closeSubpath()
        fill = QLinearGradient(0, face.top(), 0, face.bottom())
        fill.setColorAt(0, QColor(top).lighter(118 if hovering else 100))
        fill.setColorAt(0.47, QColor(middle))
        fill.setColorAt(1, QColor(bottom))
        p.fillPath(shape, fill)

        p.save()
        p.setClipPath(shape)
        lip = QLinearGradient(0, face.top(), 0, face.top() + height * 0.46)
        lip.setColorAt(0, QColor(255, 255, 255, 61 if enabled else 14))
        lip.setColorAt(0.25, QColor(255, 255, 255, 22 if enabled else 5))
        lip.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(2, face.top() + 1, width - 4, height * 0.46), lip)
        p.setPen(QPen(QColor(255, 226, 231, 68 if enabled else 14), 1))
        p.drawLine(QPointF(12, face.top() + 2), QPointF(width - 12, face.top() + 2))

        # A short sweep, followed by a quiet pause, avoids a constant flashing UI.
        if not pressed:
            phase = self._shine_phase()
            if phase < 0.27:
                travel = phase / 0.27
                x = -width * 0.35 + travel * width * 1.7
                span = max(30, width * 0.24)
                p.save()
                p.translate(x, 0)
                p.shear(0.32, 0)
                gleam = QLinearGradient(-span, 0, span, 0)
                gleam.setColorAt(0, QColor(255, 244, 246, 0))
                gleam.setColorAt(
                    0.5, QColor(255, 244, 246, 72 if hovering else 43 if enabled else 27)
                )
                gleam.setColorAt(1, QColor(255, 244, 246, 0))
                p.fillRect(QRectF(-span, 0, span * 2, height), gleam)
                p.restore()
        p.restore()

        p.setPen(QPen(QColor(edge), 1.2))
        p.drawPath(shape)
        p.setPen(QPen(QColor(255, 255, 255, 35 if enabled else 10), 1))
        p.drawLine(QPointF(12, face.top() + 4), QPointF(width - 19, face.top() + 4))
        p.setPen(QPen(QColor("#ff5068" if enabled else "#66515b"), 2))
        p.drawLine(QPointF(14, face.top() + 2), QPointF(min(width - 26, 52), face.top() + 2))
        p.setPen(
            QPen(QColor(255, 110, 132, 185) if self.hasFocus() else QColor(21, 8, 12, 165), 1.4)
        )
        p.drawLine(QPointF(9, face.bottom() + 1.5), QPointF(width - 9, face.bottom() + 1.5))
        p.setPen(QColor("#fff8f9" if enabled else "#8e7981"))
        font = self.font()
        font.setBold(True)
        font.setPointSize(11 if self.role == "primary" else 10)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        p.setFont(font)
        text_rect = face.translated(0, 1 if pressed else 0)
        connected = self.role == "connect" and self.text() == "CONNECTED"
        if connected:
            pulse = (1 + math.sin(time.monotonic() * 2.0 * math.pi / 2.5)) / 2
            # Restrict the breathing red halo to the lettering, keeping the
            # disconnected button's normal raised styling and shine intact.
            for radius, alpha in ((5, 16), (3, 35), (1, 68)):
                p.setPen(QColor(255, 32, 62, int(alpha + alpha * pulse)))
                for dx, dy in ((-radius, 0), (radius, 0), (0, -radius), (0, radius)):
                    p.drawText(
                        text_rect.translated(dx, dy), Qt.AlignmentFlag.AlignCenter, self.text()
                    )
        p.setPen(QColor(5, 3, 8, 210))
        p.drawText(text_rect.translated(0, 2), Qt.AlignmentFlag.AlignCenter, self.text())
        p.setPen(QColor(255, 213, 221, 92 if enabled or connected else 18))
        p.drawText(text_rect.translated(0, -1), Qt.AlignmentFlag.AlignCenter, self.text())
        ink = QLinearGradient(0, text_rect.top() + 8, 0, text_rect.bottom() - 5)
        ink.setColorAt(0, QColor("#ffc8d0" if connected else "#ffffff" if enabled else "#a38c95"))
        ink.setColorAt(
            0.48, QColor("#ff5b72" if connected else "#fff0f2" if enabled else "#8e7981")
        )
        ink.setColorAt(1, QColor("#b71d38" if connected else "#cdb8c0" if enabled else "#66565e"))
        p.setPen(QPen(ink, 1))
        p.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()


class FrameControlButton(QPushButton):
    """An illuminated segment within the header's shared control housing."""

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.action = action
        self.setFixedSize(44, 30)
        self.setStyleSheet(
            "QPushButton { min-width: 0px; min-height: 0px; padding: 0px; border: none; }"
        )
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setToolTip({"min": "Minimise", "max": "Maximise or restore", "close": "Close"}[action])
        self.setAccessibleName(self.toolTip())
        self.sweep = QTimer(self)
        self.sweep.timeout.connect(self._animate)
        self.sweep.start(100)

    def _animate(self):
        t = (
            (time.monotonic() * 1000 + {"min": 0, "max": 900, "close": 1800}[self.action])
            % 6400
            / 6400
        )
        if self.isVisible() and t < 0.18:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        hover = self.underMouse()
        fill = QLinearGradient(0, 2, 0, h - 1)
        top = "#a7354b" if self.action == "close" and hover else "#65414c" if hover else "#282a32"
        bottom = (
            "#4b1020" if self.action == "close" and hover else "#222027" if hover else "#101116"
        )
        fill.setColorAt(0, QColor(top))
        fill.setColorAt(0.46, QColor("#24232b"))
        fill.setColorAt(1, QColor(bottom))
        p.fillRect(QRectF(0, 1, w, h - 2), fill)
        p.setPen(QPen(QColor(255, 255, 255, 38 if hover else 18), 1))
        p.drawLine(QPointF(2, 2), QPointF(w - 3, 2))
        if self.action != "min":
            p.setPen(QPen(QColor("#51444e"), 1))
            p.drawLine(QPointF(0, 4), QPointF(0, h - 4))
        t = (
            (time.monotonic() * 1000 + {"min": 0, "max": 900, "close": 1800}[self.action])
            % 6400
            / 6400
        )
        if t < 0.18:
            x = -20 + (w + 40) * t / 0.18
            shine = QLinearGradient(x - 10, 0, x + 10, 0)
            shine.setColorAt(0, QColor(255, 255, 255, 0))
            shine.setColorAt(0.5, QColor(255, 235, 239, 80 if hover else 35))
            shine.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(0, 2, w, h - 4), shine)
        p.setPen(
            QPen(
                QColor("#fff3f5" if hover else "#c9b9bf"),
                1.7,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.SquareCap,
                Qt.PenJoinStyle.MiterJoin,
            )
        )
        # Centre the symbols in the actual resized button, not a 44x30 slot.
        glyph_scale = min(w / 44, h / 30)
        p.translate(w / 2, h / 2)
        p.scale(glyph_scale, glyph_scale)
        p.translate(-22, -15)
        if self.action == "min":
            p.drawLine(QPointF(16, 15), QPointF(28, 15))
        elif self.action == "max":
            if self.window().isMaximized():
                p.drawRect(QRectF(17, 12, 10, 8))
                p.drawLine(QPointF(20, 10), QPointF(29, 10))
                p.drawLine(QPointF(29, 10), QPointF(29, 17))
            else:
                p.drawRect(QRectF(16, 10, 12, 10))
        else:
            p.drawLine(QPointF(16, 10), QPointF(28, 20))
            p.drawLine(QPointF(28, 10), QPointF(16, 20))
        p.end()


class FrameControlBar(QWidget):
    """Three seamless controls nested in the header's top-right dock."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(140, 34)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        border = QPainterPath()
        border.moveTo(1, 7)
        border.lineTo(7, 1)
        border.lineTo(w - 9, 1)
        border.lineTo(w - 1, 9)
        border.lineTo(w - 1, h - 6)
        border.lineTo(w - 7, h - 1)
        border.lineTo(7, h - 1)
        border.lineTo(1, h - 7)
        border.closeSubpath()
        metal = QLinearGradient(0, 1, 0, h - 1)
        metal.setColorAt(0, QColor("#78757e"))
        metal.setColorAt(0.22, QColor("#3c3d47"))
        metal.setColorAt(1, QColor("#15151b"))
        p.fillPath(border, metal)
        p.setPen(QPen(QColor("#9b727e"), 1))
        p.drawPath(border)
        p.end()


class RootSurface(QWidget):
    """A continuous metallic perimeter that contains the whole interface."""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        base = QLinearGradient(0, 0, w, h)
        base.setColorAt(0, QColor("#12151a"))
        base.setColorAt(0.35, QColor("#050609"))
        base.setColorAt(1, QColor("#0d0d12"))
        p.fillRect(self.rect(), base)
        p.setPen(QPen(QColor("#60616b"), 2))
        p.drawRect(QRectF(1.5, 1.5, w - 3, h - 3))
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.drawLine(QPointF(6, 3), QPointF(w - 7, 3))
        p.drawLine(QPointF(3, 6), QPointF(3, h - 8))
        p.setPen(QPen(QColor(0, 0, 0, 210), 2))
        p.drawLine(QPointF(6, h - 5), QPointF(w - 7, h - 5))
        p.end()


class FooterRail(QWidget):
    """A shallow footer housing for keyboard guidance and product identity."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        shape = QPainterPath()
        shape.moveTo(1, 7)
        shape.lineTo(7, 1)
        shape.lineTo(w - 8, 1)
        shape.lineTo(w - 1, 8)
        shape.lineTo(w - 1, h - 7)
        shape.lineTo(w - 7, h - 1)
        shape.lineTo(7, h - 1)
        shape.lineTo(1, h - 7)
        shape.closeSubpath()
        fill = QLinearGradient(0, 1, 0, h - 1)
        fill.setColorAt(0, QColor("#393943"))
        fill.setColorAt(0.16, QColor("#17191f"))
        fill.setColorAt(1, QColor("#090b10"))
        p.fillPath(shape, fill)
        p.setPen(QPen(QColor("#565660"), 1))
        p.drawPath(shape)
        p.setPen(QPen(QColor(255, 255, 255, 42), 1))
        p.drawLine(QPointF(12, 3), QPointF(w - 15, 3))
        p.setPen(QPen(QColor("#e12d49"), 1.5))
        s = self.height() / 30
        p.drawLine(QPointF(8 * s, h - 4 * s), QPointF(75 * s, h - 4 * s))
        p.drawLine(QPointF(w - 75 * s, h - 4 * s), QPointF(w - 10 * s, h - 4 * s))
        p.end()


class ChromePanel(QFrame):
    """Native, resolution-independent instrument housing with cut corners."""

    def __init__(self, kind="module", parent=None):
        super().__init__(parent)
        self.kind = kind
        self._static_panel = None
        self._static_key = None
        self.scan_phase = {"header": 0.0, "config": 0.38, "monitor": 0.68}.get(kind, 0.3)
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self.advance_scan)
        if kind in ("header", "config", "monitor"):
            self.scan_timer.start(90)

    def advance_scan(self):
        previous = self.scan_phase
        self.scan_phase = (self.scan_phase + 0.012) % 1.0
        if self.isVisible() and (self.scan_phase < 0.2 or previous < 0.2):
            # Only the first 9px of the rail animates. Avoid repainting the
            # whole gradient panel (up to thousands of pixels wide).
            self.update(QRect(0, 0, self.width(), 18))

    def resizeEvent(self, event):
        self._static_panel = None
        self._static_key = None
        super().resizeEvent(event)
        if self.kind == "header" and hasattr(self, "window_controls"):
            right = self.window_controls.property("dock_right") or 28
            top = self.window_controls.property("dock_top") or 13
            self.window_controls.move(self.width() - self.window_controls.width() - right, top)

    def _paint_static(self, p):
        """Complex bevels, gradients and markings never change between frames."""
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cut = 15 if self.kind != "header" else 11
        shape = QPainterPath()
        shape.moveTo(1, cut)
        shape.lineTo(cut, 1)
        shape.lineTo(w - 34, 1)
        shape.lineTo(w - 19, cut)
        shape.lineTo(w - 1, cut)
        shape.lineTo(w - 1, h - cut)
        shape.lineTo(w - cut, h - 1)
        shape.lineTo(18, h - 1)
        shape.lineTo(1, h - 18)
        shape.closeSubpath()
        body = QLinearGradient(0, 0, w, h)
        body.setColorAt(0, QColor("#70737a"))
        body.setColorAt(0.09, QColor("#2d3138"))
        body.setColorAt(0.6, QColor("#14171d"))
        body.setColorAt(1, QColor("#44404a"))
        p.fillPath(shape, body)
        p.setPen(QPen(QColor("#535860"), 1.4))
        p.drawPath(shape)

        well = QPainterPath()
        well.moveTo(8, cut + 3)
        well.lineTo(cut + 3, 8)
        well.lineTo(w - 38, 8)
        well.lineTo(w - 25, cut + 3)
        well.lineTo(w - 8, cut + 3)
        well.lineTo(w - 8, h - cut - 2)
        well.lineTo(w - cut - 2, h - 8)
        well.lineTo(22, h - 8)
        well.lineTo(8, h - 22)
        well.closeSubpath()
        inset = QLinearGradient(0, 8, w, h)
        inset.setColorAt(0, QColor("#11151b"))
        inset.setColorAt(0.46, QColor("#080a0e"))
        inset.setColorAt(1, QColor("#040508"))
        p.fillPath(well, inset)
        p.setPen(QPen(QColor("#090b0f"), 2))
        p.drawPath(well)
        p.save()
        p.setClipPath(well)
        ambient = QRadialGradient(w * 0.1, h * 0.08, max(w, h) * 0.8)
        ambient.setColorAt(0, QColor(147, 22, 41, 29))
        ambient.setColorAt(1, QColor(147, 22, 41, 0))
        p.fillRect(QRectF(8, 8, w - 16, h - 16), ambient)
        p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 39), 1))
        rail_end = (
            max(21, self.window_controls.x() - 30)
            if self.kind == "header" and hasattr(self, "window_controls")
            else max(21, w - 39)
        )
        p.drawLine(QPoint(21, 3), QPoint(rail_end, 3))
        p.setPen(QPen(QColor(0, 0, 0, 130), 2))
        p.drawLine(QPoint(12, h - 10), QPoint(w - 26, h - 10))

        # Layered industrial lip and broken neon tracer, inspired by the
        # reference's hardware language rather than using its bitmap parts.
        p.setPen(QPen(QColor("#71737a"), 2))
        p.drawLine(QPoint(20, 5), QPoint(rail_end, 5))
        p.setPen(QPen(QColor("#20262c"), 5))
        p.drawLine(QPoint(19, 12), QPoint(rail_end + 3, 12))
        if self.kind == "header":
            # The upper rail descends into a full-width right-hand control dock.
            p.setPen(QPen(QColor("#74717a"), 2))
            p.drawLine(QPoint(rail_end, 5), QPoint(rail_end + 15, 17))
        # Reference-image accent anchors, independent of the content layouts.
        scale = min(1.0, max(0.66, self.window().width() / 1618))
        p.setPen(QPen(QColor("#e21d38"), 2 * scale))
        top = 36 if self.kind == "header" else 32
        if self.kind != "header":
            p.drawLine(QPointF(29 * scale, top * scale), QPointF(162 * scale, top * scale))
        if self.kind != "header":
            p.drawLine(QPointF(w - 40 * scale, 36 * scale), QPointF(w - 17 * scale, 36 * scale))
            p.drawLine(QPointF(w - 17 * scale, 36 * scale), QPointF(w - 17 * scale, 67 * scale))
            left = 19 if self.kind == "art" else 27
            lower = 27 if self.kind == "monitor" else 25
            p.drawLine(
                QPointF(left * scale, h - (lower + 27) * scale),
                QPointF(left * scale, h - lower * scale),
            )
            p.drawLine(
                QPointF(left * scale, h - lower * scale),
                QPointF((left + 52) * scale, h - lower * scale),
            )
            right_lower = 18 if self.kind == "config" else 24
            p.drawLine(
                QPointF(w - 190 * scale, h - right_lower * scale),
                QPointF(w - 43 * scale, h - right_lower * scale),
            )

    def paintEvent(self, event):
        dpr = self.devicePixelRatioF()
        rail_x = (
            self.window_controls.x()
            if self.kind == "header" and hasattr(self, "window_controls")
            else None
        )
        key = (self.width(), self.height(), round(dpr, 4), self.window().width(), rail_x)
        if self._static_panel is None or self._static_key != key:
            base = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
            base.setDevicePixelRatio(dpr)
            base.fill(Qt.GlobalColor.transparent)
            offscreen = QPainter(base)
            self._paint_static(offscreen)
            offscreen.end()
            self._static_panel = base
            self._static_key = key
        p = QPainter(self)
        p.drawPixmap(0, 0, self._static_panel)
        if self.scan_phase < 0.2 and self.kind in ("header", "config", "monitor"):
            # The strip is the only changing part of ChromePanel; its cached
            # static panel is shared across all cosmetic timer callbacks.
            w = self.width()
            rail_end = (
                max(21, self.window_controls.x() - 30)
                if self.kind == "header" and hasattr(self, "window_controls")
                else max(21, w - 39)
            )
            progress = self.scan_phase / 0.2
            # Begin and end inside the straight rail; fade before the bevel.
            x = 60 + max(0, rail_end - 100) * progress
            strength = int(130 * math.sin(math.pi * progress))
            shine = QLinearGradient(x - 40, 0, x + 40, 0)
            shine.setColorAt(0, QColor(255, 230, 235, 0))
            shine.setColorAt(0.5, QColor(255, 230, 235, strength))
            shine.setColorAt(1, QColor(255, 230, 235, 0))
            p.save()
            p.setClipRect(QRectF(20, 3, max(1, rail_end - 20), 6))
            p.fillRect(QRectF(x - 40, 3, 80, 6), shine)
            p.restore()
        p.end()


class DutyDial(QWidget):
    """Segmented duty-cycle instrument, drawn at the screen's pixel density."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(108, 108)
        self.percent = 9.0
        self.running = False
        self.phase = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)

    def advance(self):
        self.phase = (self.phase + 1) % 32
        self.update()

    def set_values(self, interval, pulse):
        self.percent = min(100, 100 * pulse / max(1, interval))
        self.update()

    def set_state(self, running):
        self.running = running
        self.timer.start(70) if running else self.timer.stop()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.width() / 108, self.height() / 108)
        cx = cy = 54
        p.setPen(Qt.PenStyle.NoPen)
        outer = QRadialGradient(42, 34, 58)
        outer.setColorAt(0, QColor("#393d46"))
        outer.setColorAt(0.68, QColor("#151820"))
        outer.setColorAt(1, QColor("#030407"))
        p.setBrush(outer)
        p.drawEllipse(QRectF(11, 11, 86, 86))
        p.setPen(QPen(QColor("#666b74"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(12, 12, 84, 84), 42 * 16, 102 * 16)
        p.setPen(QPen(QColor("#2d101b"), 2))
        p.drawEllipse(QRectF(21, 21, 66, 66))
        active = max(1, round(32 * self.percent / 100))
        for i in range(32):
            angle = math.radians(-225 + i * 270 / 31)
            inner, outer = 39, 48
            colour = QColor("#f53049" if i < active else "#31343b")
            if self.running and i == self.phase:
                colour = QColor("#ffc5ca")
            p.setPen(
                QPen(colour, 4 if i < active else 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
            )
            p.drawLine(
                QPointF(cx + inner * math.cos(angle), cy + inner * math.sin(angle)),
                QPointF(cx + outer * math.cos(angle), cy + outer * math.sin(angle)),
            )
        glass = QLinearGradient(24, 27, 85, 86)
        glass.setColorAt(0, QColor("#262a32"))
        glass.setColorAt(0.45, QColor("#0c0e14"))
        glass.setColorAt(1, QColor("#030407"))
        p.setPen(QPen(QColor("#8b283d"), 1))
        p.setBrush(glass)
        p.drawEllipse(QRectF(27, 27, 54, 54))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawArc(QRectF(29, 29, 50, 50), 38 * 16, 100 * 16)
        p.setPen(QColor("#10050a"))
        p.setFont(QFont("Bahnschrift SemiCondensed", 15, QFont.Weight.Bold))
        p.drawText(QRectF(18, 37, 72, 27), Qt.AlignmentFlag.AlignCenter, f"{self.percent:.0f}%")
        p.setPen(QColor("#fff5f6"))
        p.drawText(QRectF(18, 35, 72, 27), Qt.AlignmentFlag.AlignCenter, f"{self.percent:.0f}%")
        p.setPen(QColor("#b3828d"))
        p.setFont(QFont("Consolas", 7, QFont.Weight.Bold))
        p.drawText(QRectF(18, 62, 72, 20), Qt.AlignmentFlag.AlignCenter, "DUTY")
        p.end()


class ChevronRail(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(34)
        self.phase = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(330)

    def advance(self):
        self.phase = (self.phase + 1) % 12
        if self.isVisible():
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(self.height() / 34, self.height() / 34)
        for i in range(3):
            x = 4 + i * 35
            path = QPainterPath()
            path.moveTo(x, 5)
            path.lineTo(x + 13, 5)
            path.lineTo(x + 25, 17)
            path.lineTo(x + 13, 29)
            path.lineTo(x, 29)
            path.lineTo(x + 12, 17)
            path.closeSubpath()
            bright = (self.phase // 4) == i
            p.fillPath(path, QColor("#ed2944" if bright else "#591627"))
            p.setPen(QPen(QColor("#ff8190" if bright else "#9d293c"), 1))
            p.drawPath(path)
        p.setPen(QPen(QColor("#6e2230"), 1))
        p.drawLine(
            QPoint(120, 17), QPoint(max(121, int(self.width() * 34 / self.height()) - 8), 17)
        )
        p.end()


class DepthLabel(QLabel):
    """Extruded display lettering with a quiet, clipped specular pass."""

    DISPLAY = {"headerTitle", "brandLine", "moduleTitle", "section", "statusTitle", "count"}

    def __init__(self, text):
        super().__init__(text)
        self.phase = 0.0
        self.sweep = QTimer(self)
        self.sweep.timeout.connect(self.advance)

    def advance(self):
        old = self.phase
        self.phase = (self.phase + 0.016875) % 1.0
        if self.isVisible() and (self.phase < 0.29 or old < 0.29):
            self.update()

    def setObjectName(self, name):
        super().setObjectName(name)
        if name in ("headerTitle", "brandLine", "moduleTitle"):
            self.sweep.start(90)

    def sizeHint(self):
        size = super().sizeHint()
        if self.objectName() in self.DISPLAY:
            return QSize(size.width() + int(len(self.text()) * 1.5) + 6, size.height() + 3)
        return size

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, event):
        if self.objectName() not in self.DISPLAY or self.wordWrap():
            # Small captions retain their native shaping and line wrapping.
            p = QPainter(self)
            p.setPen(QColor(0, 0, 0, 175))
            flags = self.alignment() | (
                Qt.TextFlag.TextWordWrap if self.wordWrap() else Qt.TextFlag(0)
            )
            p.setFont(self.font())
            p.drawText(self.contentsRect().translated(0, 1), flags, self.text())
            p.end()
            super().paintEvent(event)
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self.font()
        if self.property("reference_condensed"):
            font.setStretch(78)
        font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, 1.25 if self.objectName() != "count" else 0.2
        )
        path = QPainterPath()
        path.addText(0, 0, font, self.text())
        bounds = path.boundingRect()
        area = self.contentsRect()
        align = self.alignment()
        if align & Qt.AlignmentFlag.AlignHCenter:
            x = area.center().x() - bounds.width() / 2 - bounds.left()
        elif align & Qt.AlignmentFlag.AlignRight:
            x = area.right() - bounds.right() - 3
        else:
            x = area.left() - bounds.left() + 1
        if align & Qt.AlignmentFlag.AlignVCenter:
            y = area.center().y() - bounds.height() / 2 - bounds.top()
        elif align & Qt.AlignmentFlag.AlignBottom:
            y = area.bottom() - bounds.bottom() - 3
        else:
            y = area.top() - bounds.top() + 2
        path.translate(x, y)
        if self.objectName() == "count":
            top, mid, low = "#ffc1c8", "#ff405a", "#821629"
        elif self.objectName() == "brandLine":
            top, mid, low = "#ffc9d1", "#ed6a7d", "#82253a"
        else:
            top, mid, low = "#ffffff", "#e5dce1", "#9b939c"
        p.fillPath(path.translated(2, 3), QColor(0, 0, 0, 205))
        p.fillPath(path.translated(1, 2), QColor(101, 14, 31, 145))
        metal = QLinearGradient(0, path.boundingRect().top(), 0, path.boundingRect().bottom())
        metal.setColorAt(0, QColor(top))
        metal.setColorAt(0.34, QColor(mid))
        metal.setColorAt(0.5, QColor(low))
        metal.setColorAt(0.56, QColor(mid))
        metal.setColorAt(1, QColor(low))
        p.fillPath(path, metal)
        p.setPen(QPen(QColor(255, 241, 244, 65), 0.65))
        p.drawPath(path)
        if self.phase < 0.29 and self.objectName() in ("headerTitle", "brandLine", "moduleTitle"):
            rect = path.boundingRect()
            pos = rect.left() + (rect.width() + 40) * self.phase / 0.29 - 20
            light = QLinearGradient(pos - 20, 0, pos + 20, 0)
            light.setColorAt(0, QColor(255, 255, 255, 0))
            light.setColorAt(0.5, QColor(255, 255, 255, 120))
            light.setColorAt(1, QColor(255, 255, 255, 0))
            p.save()
            p.setClipPath(path)
            p.fillRect(rect, light)
            p.restore()
        p.end()


class CreatorCredit(DepthLabel):
    """Reveal the creator's name after fifty deliberate clicks on the credit."""

    SECRET = "亗--DムNKラY--亗"
    REVEALED = "Created by Dane V"

    def __init__(self):
        super().__init__(self.SECRET)
        self.setObjectName("creatorCredit")
        font_id = QFontDatabase.addApplicationFont(str(resource("credit_font.ttf")))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        self.font_family = families[0] if families else "Segoe UI Symbol"
        self.setFont(QFont(self.font_family))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.click_count = 0
        self.reveal_timer = QTimer(self)
        self.reveal_timer.setSingleShot(True)
        self.reveal_timer.timeout.connect(self._hide_credit)

    def _hide_credit(self):
        self.setText(self.SECRET)
        self.click_count = 0
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            if self.click_count < 50:
                self.click_count += 1
                if self.click_count == 50:
                    self.setText(self.REVEALED)
                    self.setCursor(Qt.CursorShape.ArrowCursor)
                    self.reveal_timer.start(5000)
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DepthComboBox(QComboBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QPen(QColor(255, 255, 255, 48), 1))
        p.drawLine(5, 2, self.width() - 38, 2)
        p.setPen(QPen(QColor(0, 0, 0, 180), 2))
        p.drawLine(4, self.height() - 2, self.width() - 3, self.height() - 2)
        p.end()


class DepthSpinBox(QSpinBox):
    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.Type.StyleChange, QEvent.Type.PolishRequest):
            QTimer.singleShot(0, self, self._fit_editor)
        return result

    def _fit_editor(self):
        # Some native styles collapse SC_SpinBoxEditField to one pixel when
        # buttons are hidden and custom padding is applied. Size the editor
        # explicitly so the visible value is also the mouse/keyboard target.
        self.lineEdit().setGeometry(self.rect().adjusted(18, 4, -12, -4))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_editor()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit_editor()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setPen(QPen(QColor(255, 255, 255, 48), 1))
        p.drawLine(5, 2, self.width() - 5, 2)
        p.setPen(QPen(QColor(0, 0, 0, 180), 2))
        p.drawLine(4, self.height() - 2, self.width() - 3, self.height() - 2)
        p.end()


STYLE = """
QWidget { color: #f5f0f1; font-family: 'Bahnschrift', 'Segoe UI'; font-size: 14px; }
QMainWindow { background: #050609; }
QLabel { background: transparent; }
QLabel#headerTitle { color: #fff7f8; font-family: 'Bahnschrift SemiCondensed', 'Segoe UI'; font-size: 29px; font-weight: 800; }
QLabel#brandLine { color: #f28091; font-family: 'Bahnschrift SemiCondensed', 'Segoe UI'; font-size: 15px; font-weight: 800; }
QLabel#micro { color: #d7384d; font-family: 'Consolas'; font-size: 11px; font-weight: 700; }
QLabel#code { color: #8d8e98; font-family: 'Consolas'; font-size: 11px; }
QLabel#moduleTitle { color: #f4eff1; font-family: 'Bahnschrift SemiCondensed', 'Segoe UI'; font-size: 19px; font-weight: 700; }
QLabel#section { color: #f8f3f4; font-family: 'Bahnschrift SemiCondensed', 'Segoe UI'; font-size: 21px; font-weight: 700; }
QLabel#fieldLabel { color: #d09aa6; font-family: 'Consolas'; font-size: 11px; font-weight: 700; }
QLabel#hint { color: #8d8990; font-size: 12px; }
QLabel#statusTitle { color: #fff7f8; font-family: 'Bahnschrift SemiCondensed', 'Segoe UI'; font-size: 27px; font-weight: 700; }
QLabel#detail { color: #aaa5ae; font-size: 12px; }
QLabel#badge { color: #ff5870; font-family: 'Consolas'; font-size: 11px; font-weight: 700; }
QLabel#count { color: #ff344f; font-family: 'Bahnschrift SemiCondensed', 'Segoe UI'; font-size: 42px; font-weight: 700; }
QLabel#monitorValue { color: #f8e8eb; font-family: 'Consolas'; font-size: 12px; font-weight: 700; }
QLabel#footer { color: #b8aab2; font-family: 'Consolas'; font-size: 10px; }
/* Explicit affordances: interactive footer captions should look like buttons. */
QPushButton#footerInfoText, QPushButton#footerAction {
    color: #f0c1cb;
    font-family: 'Consolas'; font-size: 10px; font-weight: 700;
    border: 1px solid #833447; border-radius: 5px;
    background: #28171e; padding: 0px 9px; min-height: 0px;
}
QPushButton#footerInfoText:hover, QPushButton#footerAction:hover {
    color: #fff3f5; border-color: #ef617b; background: #502331;
}
QPushButton#footerInfoText:pressed, QPushButton#footerAction:pressed {
    background: #742b42;
}
QPushButton#footerInfoText:focus, QPushButton#footerAction:focus {
    border-color: #ff8396;
}
QPushButton#footerAction:disabled { color: #826e75; border-color: #402d34; background: #1a1518; }
/* Settings, selection and history dialogues use visually obvious controls. */
QDialog QPushButton {
    color: #ffe8ed; font-size: 12px; font-weight: 700;
    background: #502130; border: 1px solid #b54860;
    border-radius: 5px; min-height: 23px; padding: 6px 11px;
}
QDialog QPushButton:hover { background: #802d46; border-color: #ff7189; }
QDialog QPushButton:pressed { background: #982f4a; }
QDialog QPushButton:disabled { color: #86727b; background: #272027; border-color: #493641; }
QLabel#creatorCredit { color: #df9fac; font-family: 'Droid Credit Symbols'; font-size: 13px; }
QLabel#artCaption { color: #bb9ca5; font-family: 'Consolas'; font-size: 10px; font-weight: 700; }
QPushButton { background: transparent; border: none; min-height: 25px; padding: 9px 12px; font-size: 14px; font-weight: 700; }
QComboBox, QSpinBox { color: #f8f0f2; font-family: 'Bahnschrift SemiCondensed', 'Bahnschrift', 'Segoe UI'; font-size: 15px; font-weight: 600; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #4b444d,stop:.07 #272a32,stop:.38 #191b22,stop:.62 #0e1016,stop:1 #07090c); border: 1px solid #5e5b64; border-left: 3px solid #bd2039; border-bottom: 2px solid #040408; border-radius: 0px; padding: 8px 12px; min-height: 25px; }
QComboBox:hover, QSpinBox:hover { border-color: #ed4159; }
QComboBox:focus, QSpinBox:focus { border-color: #ff657b; }
QComboBox:disabled, QSpinBox:disabled { color: #897e86; background: #18191e; border-color: #343039; }
QComboBox::drop-down { border: none; width: 32px; background: #18191e; }
QComboBox QAbstractItemView { background: #15171c; color: #f9edf0; border: 1px solid #923046; selection-background-color: #9f1d35; }
QToolTip { color: #fff7f8; background: #281820; border: 1px solid #a7364a; }
"""


def label(text, name=None, wrap=False):
    w = DepthLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(wrap)
    return w


class Clicker(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.MSWindowsFixedSizeDialogHint
        )
        self.setWindowTitle("Droid Tycoon DroidOps")
        self.setWindowIcon(QIcon(str(resource("app.ico"))))
        self.setFixedSize(1080, 780)
        self.pad = None
        self.pad_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker = None
        self.running = False
        self.f8_down = False
        self.f9_down = False
        self.f10_down = False
        self._manual_drag = None
        self._manual_resize = None
        self.events = Events()
        self.events.count.connect(self.on_count)
        self.events.finished.connect(self.on_finished)
        self.events.tested.connect(self.on_tested)
        self.events.error.connect(self.on_error)
        self.events.mission_status.connect(self.on_mission_status)
        self.settings = QSettings("Dane Vanzino", "Droid Tycoon Auto Clicker V1")
        self.droid_alert = DroidAlert(
            self, self.settings, foreground_fortnite, is_fortnite_window, resource
        )
        self.build_ui()
        # Optional per-user preference. A remembered notification crop follows
        # the Fortnite client and never needs to be redrawn after installation.
        if (
            not os.environ.get("DROIDOPS_HEALTH_CHECK")
            and self.droid_alert.auto_start_enabled
            and self.droid_alert.saved_target()
        ):
            QTimer.singleShot(700, self.droid_alert.start_saved)
        self._install_frame_watchdog()
        QApplication.instance().installEventFilter(self)
        self.hotkey_timer = QTimer(self)
        self.hotkey_timer.timeout.connect(self.poll_hotkey)
        self.hotkey_timer.start(40)

    def build_ui(self):
        base = RootSurface()
        base.setObjectName("root")
        self.setCentralWidget(base)
        outer = QVBoxLayout(base)
        self.outer_layout = outer
        outer.setContentsMargins(9, 9, 9, 8)
        outer.setSpacing(8)

        header = ChromePanel("header")
        header.setFixedHeight(91)
        hb = QHBoxLayout(header)
        hb.setContentsMargins(25, 22, 23, 11)
        hb.setSpacing(14)
        self.header_layout = hb
        brand = QVBoxLayout()
        brand.setSpacing(0)
        self.brand_line = label("DROID TYCOON", "brandLine")
        self.brand_line.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.product_title = label("DROIDOPS", "headerTitle")
        self.product_title.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        brand.addWidget(self.brand_line)
        brand.addWidget(self.product_title)
        hb.addLayout(brand)
        hb.addStretch()
        hb.addWidget(
            label("VIRTUAL INPUT   //   XBOX 360", "code"), 0, Qt.AlignmentFlag.AlignBottom
        )
        hb.addSpacing(16)
        self.orb = ModeIndicator()
        hb.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignBottom)
        self.badge = label("OFFLINE", "badge")
        hb.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignBottom)
        self.header = header
        controls = FrameControlBar(header)
        row = controls.layout()
        for action, handler in (
            ("min", self.showMinimized),
            ("max", self.toggle_maximize),
            ("close", self.close),
        ):
            button = FrameControlButton(action, controls)
            if action == "max":
                button.setEnabled(False)
                button.setToolTip("Window size is fixed")
                button.setAccessibleName("Window size is fixed")
            button.clicked.connect(handler)
            row.addWidget(button)
        header.window_controls = controls
        controls.move(header.width() - controls.width() - 28, 13)
        controls.raise_()
        outer.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(11)
        self.body_layout = body
        identity = ChromePanel("art")
        identity.setFixedWidth(375)
        self.identity_panel = identity
        iv = QVBoxLayout(identity)
        self.identity_layout = iv
        iv.setContentsMargins(24, 37, 24, 35)
        iv.setSpacing(8)
        iv.addStretch(1)
        self.art = ArtworkWidget()
        iv.addWidget(self.art)
        iv.addSpacing(10)
        self.creator_credit = CreatorCredit()
        self.creator_credit.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.creator_credit.setFixedHeight(36)
        iv.addWidget(self.creator_credit)
        iv.addStretch(1)
        iv.addWidget(ChevronRail())
        # Share the right instrument column's full height: its lower border
        # must line up precisely with the Live Telemetry lower border.
        identity.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        body.addWidget(identity, 0)

        right = QVBoxLayout()
        right.setSpacing(0)
        self.right_layout = right
        statusPanel = ChromePanel("status")
        statusPanel.setFixedHeight(103)
        self.status_panel = statusPanel
        sr = QHBoxLayout(statusPanel)
        sr.setContentsMargins(23, 35, 22, 21)
        sr.setSpacing(12)
        self.status_layout = sr
        st = QVBoxLayout()
        st.setSpacing(1)
        self.status = label("Not connected", "statusTitle")
        self.detail = label("Connect the virtual controller to begin.", "detail", True)
        st.addWidget(self.status)
        st.addWidget(self.detail)
        sr.addLayout(st, 1)
        self.connect_btn = GlossButton("CONNECT", "connect")
        self.connect_btn.setMinimumWidth(126)
        self.connect_btn.clicked.connect(self.connect_pad)
        sr.addWidget(self.connect_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        right.addWidget(statusPanel)
        right.addSpacing(9)
        self.after_status = right.itemAt(right.count() - 1).spacerItem()

        config = ChromePanel("config")
        config.setFixedHeight(252)
        self.config_panel = config
        cv = QVBoxLayout(config)
        cv.setContentsMargins(22, 33, 22, 23)
        cv.setSpacing(0)
        self.config_layout = cv
        titleRow = QHBoxLayout()
        self.config_title = label("SIGNAL CONFIGURATION", "micro")
        titleRow.addWidget(self.config_title)
        titleRow.addStretch()
        self.config_manual = label("MANUAL OVERRIDE", "code")
        titleRow.addWidget(self.config_manual)
        cv.addLayout(titleRow)
        cv.addSpacing(8)
        self.config_gap_1 = cv.itemAt(cv.count() - 1).spacerItem()
        self.input_label = label("CONTROLLER INPUT", "fieldLabel")
        cv.addWidget(self.input_label)
        cv.addSpacing(6)
        self.config_gap_2 = cv.itemAt(cv.count() - 1).spacerItem()
        self.control = DepthComboBox()
        self.control.addItems(CONTROLS)
        self.control.setStyleSheet(
            f'QComboBox::down-arrow {{ image: url("{resource("chevron.png").as_posix()}"); width: 16px; height: 16px; }}'
        )
        cv.addWidget(self.control)
        cv.addSpacing(6)
        self.config_gap_3 = cv.itemAt(cv.count() - 1).spacerItem()
        timing = QHBoxLayout()
        timing.setSpacing(14)
        self.timing_layout = timing
        c1 = QVBoxLayout()
        c1.setSpacing(5)
        self.interval_label = label("INTERVAL  /  MS", "fieldLabel")
        c1.addWidget(self.interval_label)
        self.interval = DepthSpinBox()
        self.interval.setRange(75, 60000)
        self.interval.setSingleStep(25)
        self.interval.setValue(self.settings.value("timing/interval_ms", 500, type=int))
        self.interval.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.interval.setKeyboardTracking(False)
        self.interval.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        c1.addWidget(self.interval)
        timing.addLayout(c1, 1)
        c2 = QVBoxLayout()
        c2.setSpacing(5)
        self.pulse_label = label("PULSE  /  MS", "fieldLabel")
        c2.addWidget(self.pulse_label)
        self.pulse = DepthSpinBox()
        self.pulse.setRange(10, 59999)
        self.pulse.setSingleStep(5)
        self.pulse.setValue(self.settings.value("timing/pulse_ms", 45, type=int))
        self.pulse.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.pulse.setKeyboardTracking(False)
        self.pulse.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        c2.addWidget(self.pulse)
        timing.addLayout(c2, 1)
        cv.addLayout(timing)
        self.timing_left = c1
        self.timing_right = c2
        cv.addSpacing(6)
        self.config_gap_4 = cv.itemAt(cv.count() - 1).spacerItem()
        self.hint_label = label("PULSE DURATION MUST BE SHORTER THAN INTERVAL", "hint")
        cv.addWidget(self.hint_label)
        cv.addStretch()
        right.addWidget(config)
        right.addSpacing(9)
        self.after_config = right.itemAt(right.count() - 1).spacerItem()

        monitor = ChromePanel("monitor")
        self.monitor_panel = monitor
        mv = QVBoxLayout(monitor)
        mv.setContentsMargins(22, 26, 22, 17)
        mv.setSpacing(0)
        self.monitor_layout = mv
        mh = QHBoxLayout()
        mh.addWidget(label("LIVE TELEMETRY", "micro"))
        mh.addStretch()
        self.control_readout = label("Right Trigger", "monitorValue")
        mh.addWidget(self.control_readout)
        mv.addLayout(mh)
        signal = QHBoxLayout()
        signal.setSpacing(9)
        countcol = QVBoxLayout()
        countcol.setSpacing(0)
        self.count = label("0", "count")
        countcol.addWidget(self.count)
        self.count_label = label("PULSES SENT", "fieldLabel")
        countcol.addWidget(self.count_label)
        countcol.addStretch()
        signal.addLayout(countcol)
        self.dial = DutyDial()
        signal.addWidget(self.dial)
        linecol = QVBoxLayout()
        linecol.setSpacing(0)
        self.visual = PulseCanvas()
        linecol.addWidget(self.visual)
        signal.addLayout(linecol, 1)
        self.mono = MonoWalker()
        signal.addWidget(self.mono, 0, Qt.AlignmentFlag.AlignVCenter)
        mv.addLayout(signal)
        # No trailing spacer: it previously placed Live Telemetry 9px above
        # the matching Actuation Device frame despite sharing one body row.
        right.addWidget(monitor, 1)
        self.interval.valueChanged.connect(self.update_visual)
        self.pulse.valueChanged.connect(self.update_visual)
        self.control.currentTextChanged.connect(self.update_visual)

        # Main actions span the complete window beneath both instrument panels.
        # The Watch button configures the alarm, not a controller test.
        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.actions_layout = actions
        self.watch_btn = GlossButton("DROID WATCH", "secondary")
        self.watch_btn.setToolTip("Configure rare droid monitoring and selected notifications")
        self.watch_btn.clicked.connect(self.droid_alert.configure)
        self.droid_alert.state_changed.connect(self.update_alarm_button)
        self.start_btn = GlossButton("▶   AUTO SCRAP", "primary")
        self.start_btn.clicked.connect(self.start)
        self.cb23_btn = GlossButton("CB-23 LOOP", "secondary")
        self.cb23_btn.clicked.connect(self.configure_cb23)
        self.stop_btn = GlossButton("■   STOP", "danger")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        for button in (self.watch_btn, self.start_btn, self.cb23_btn, self.stop_btn):
            actions.addWidget(button, 1)
        body.addLayout(right, 1)
        outer.addLayout(body, 1)
        outer.addLayout(actions)

        footerBar = FooterRail()
        self.footer_bar = footerBar
        footer = QHBoxLayout(footerBar)
        footer.setContentsMargins(17, 5, 17, 5)
        # Document the F10 shortcut, then show a proper footer action button
        # and red circled-i info control; no redundant live ON/OFF label.
        footer.addWidget(
            label("F8  /  STOP     F9  /  CB-23 LOOP     F10  /  TEST LEFT TURN", "footer")
        )
        footer.addSpacing(10)
        # The label itself is an actionable button; both this and the red
        # circled-i control open the same guide. No duplicate live status here.
        self.watch_status_info_text_btn = QPushButton("DROID WATCH INFO")
        self.watch_status_info_text_btn.setObjectName("footerInfoText")
        self.watch_status_info_text_btn.setAccessibleName("Open Droid Watch status guide")
        self.watch_status_info_text_btn.setToolTip("Open the complete Droid Watch status guide")
        self.watch_status_info_text_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.watch_status_info_text_btn.clicked.connect(self.show_watch_status_info)
        footer.addWidget(self.watch_status_info_text_btn)
        self.watch_status_info_btn = QPushButton("i")
        self.watch_status_info_btn.setObjectName("watchStatusInfo")
        self.watch_status_info_btn.setAccessibleName("Droid Watch status information")
        self.watch_status_info_btn.setToolTip("Open the complete Droid Watch status guide")
        self.watch_status_info_btn.setFixedSize(20, 20)
        self.watch_status_info_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.watch_status_info_btn.setStyleSheet(
            "QPushButton#watchStatusInfo { color: #ffe4e8; font-family: 'Segoe UI'; "
            "font-size: 12px; font-weight: 800; border: 1px solid #dc415b; "
            "border-radius: 10px; background: #a22642; padding: 0px; min-height: 0px; } "
            "QPushButton#watchStatusInfo:hover { background: #cb3e5b; border-color: #ffa0b0; } "
            "QPushButton#watchStatusInfo:pressed { background: #7a1a2f; }"
        )
        self.watch_status_info_btn.clicked.connect(self.show_watch_status_info)
        footer.addWidget(self.watch_status_info_btn)
        # Keep the state available for the full info popup, but show its live
        # status only once: on the primary Droid Watch action button.
        self._watch_footer_state = "OFF"
        footer.addStretch()
        # Retain the original one-shot controller test without making it the
        # primary Watch Droid action; this is used by the controller routines.
        self.input_test_btn = QPushButton("TEST INPUT")
        self.input_test_btn.setToolTip("Send one test controller pulse and a short anti-idle nudge")
        self.input_test_btn.setObjectName("footerAction")
        self.input_test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.input_test_btn.clicked.connect(self.test_pulse)
        footer.addWidget(self.input_test_btn)
        self.alert_history_btn = QPushButton("HISTORY  0")
        self.alert_history_btn.setToolTip("View time-stamped droid alarms in this session only")
        self.alert_history_btn.setObjectName("footerAction")
        self.alert_history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.alert_history_btn.clicked.connect(self.droid_alert.show_history)
        self.droid_alert.history_changed.connect(
            lambda count: self.alert_history_btn.setText(f"HISTORY  {count}")
        )
        footer.addWidget(self.alert_history_btn)
        for button in (
            self.watch_status_info_text_btn,
            self.input_test_btn,
            self.alert_history_btn,
        ):
            button.setFixedHeight(18)
        outer.addWidget(footerBar)
        self.update_visual()
        self.update_alarm_button(self.droid_alert.state)
        self.apply_reference_layout()

    def _install_frame_watchdog(self):
        """Log real GUI-thread stalls without inserting extra paints or blocking IO."""
        import logging
        from logging.handlers import RotatingFileHandler
        import tempfile

        self._gui_lag_log = logging.getLogger("droid_ui_stalls")
        if not self._gui_lag_log.handlers:
            self._gui_lag_log.setLevel(logging.INFO)
            self._gui_lag_log.propagate = False
            try:
                folder = (
                    Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
                    / "DroidTycoonAutoClicker"
                )
                folder.mkdir(parents=True, exist_ok=True)
                handler = RotatingFileHandler(
                    folder / "ui-stalls.log", maxBytes=256 * 1024, backupCount=1, encoding="utf-8"
                )
                handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
                self._gui_lag_log.addHandler(handler)
            except OSError:
                self._gui_lag_log.addHandler(logging.NullHandler())
        self._gui_watch_interval = 100
        self._gui_last_tick = time.monotonic()
        self._gui_last_report = 0.0
        self._gui_lag_timer = QTimer(self)
        self._gui_lag_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._gui_lag_timer.timeout.connect(self._check_frame_stalls)
        self._gui_lag_timer.start(self._gui_watch_interval)

    def _check_frame_stalls(self):
        now = time.monotonic()
        elapsed_ms = (now - self._gui_last_tick) * 1000
        self._gui_last_tick = now
        if elapsed_ms > 220 and not self.isMinimized() and now - self._gui_last_report >= 1.0:
            self._gui_last_report = now
            self._gui_lag_log.info(
                "GUI callback gap=%.0fms watcher_active=%s clicker_running=%s",
                elapsed_ms,
                self.droid_alert.active,
                self.running,
            )

    def apply_reference_layout(self):
        """Keep the supplied compact layout at the fixed 1080 × 780 size."""
        s = max(1.0, min(self.width() / 1200, self.height() / 780, 1.38))
        if getattr(self, "_layout_scale", None) == round(s, 2):
            return
        self._layout_scale = round(s, 2)
        n = lambda value: round(value * s)
        t = s - 1
        self.outer_layout.setContentsMargins(
            round(9 + 11.5 * t), round(9 + 11.5 * t), 9, round(8 + 6 * t)
        )
        self.outer_layout.setSpacing(round(8 + 14 * t))
        self.header.setFixedHeight(round(91 + 141 * t))
        self.header_layout.setContentsMargins(
            round(25 + 46 * t), round(22 + 20 * t), 23, round(11 + 29 * t)
        )
        brand_width = round(266 + 172 * t)
        self.brand_line.setFixedWidth(brand_width)
        self.product_title.setFixedWidth(brand_width)
        self.body_layout.setSpacing(round(11 + 6 * t))
        self.identity_panel.setFixedWidth(round(375 + 548 * t))
        # The droid panel fills the full body row, matching the bottom of
        # Live Telemetry. A stretch above its bottom caption absorbs height.
        self.identity_layout.setContentsMargins(
            round(24 + 34 * t), round(24 + 65 * t), round(24 + 20 * t), round(22 + 52 * t)
        )
        self.identity_layout.setSpacing(round(6 + 17 * t))
        self.art.setFixedHeight(420)
        self.status_panel.setFixedHeight(round(103 + 143 * t))
        self.status_layout.setContentsMargins(
            round(23 + 43 * t), round(35 + 34 * t), round(22 + 35 * t), round(21 + 14 * t)
        )
        self.after_status.changeSize(0, round(9 + 20 * t))
        self.config_panel.setFixedHeight(round(245 + 359 * t))
        self.config_layout.setContentsMargins(
            round(22 + 46 * t), round(33 + 66 * t), round(22 + 31 * t), round(23 + 32 * t)
        )
        for label_widget, height in (
            (self.config_title, 20),
            (self.config_manual, 20),
            (self.input_label, 18),
            (self.interval_label, 18),
            (self.pulse_label, 18),
            (self.hint_label, 20),
        ):
            label_widget.setFixedHeight(round(height if s > 1.1 else max(16, height - 2)))
        for spacer, small, large in (
            (self.config_gap_1, 8, 22),
            (self.config_gap_2, 6, 17),
            (self.config_gap_3, 6, 10),
            (self.config_gap_4, 6, 16),
        ):
            spacer.changeSize(0, round(small + (large - small) * min(1, t / 0.348)))
        self.timing_left.setSpacing(round(5 + 12 * t))
        self.timing_right.setSpacing(round(5 + 12 * t))
        self.timing_layout.setSpacing(round(14 + 17 * t))
        self.config_layout.invalidate()
        self.after_config.changeSize(0, round(9 - 9 * t))
        self.monitor_layout.setContentsMargins(
            round(22 + 44 * t), round(26 + 40 * t), round(22 + 23 * t), round(17 + 10 * t)
        )
        self.dial.setFixedSize(n(108), n(108))
        self.visual.setFixedHeight(round(94 + 40 * t))
        self.count.setMinimumWidth(round(74 + 67 * t))
        self.mono.setFixedSize(round(100 + 100 * t), round(125 + 85 * t))
        self.right_layout.invalidate()
        self.actions_layout.setSpacing(round(9 + 12 * t))
        self.footer_bar.setFixedHeight(round(30 + 43 * t))
        for button in (self.watch_btn, self.start_btn, self.cb23_btn, self.stop_btn):
            button.setFixedHeight(round(40 + 63 * t))
        self.connect_btn.setFixedSize(round(126 + 172 * t), round(43 + 40 * t))
        self.control.setFixedHeight(round(43 + 63 * t))
        self.interval.setFixedHeight(round(43 + 63 * t))
        self.pulse.setFixedHeight(round(43 + 63 * t))
        control_min = round(25 + 60 * t)
        self.control.setStyleSheet(
            f"QComboBox {{ min-height: {control_min}px; }} "
            f'QComboBox::down-arrow {{ image: url("{resource("chevron.png").as_posix()}"); width: 16px; height: 16px; }}'
        )
        for spin in (self.interval, self.pulse):
            spin.setStyleSheet(f"QSpinBox {{ min-height: {control_min}px; }}")
        button_min = round(25 + 55 * t)
        for button in (
            self.watch_btn,
            self.start_btn,
            self.cb23_btn,
            self.stop_btn,
            self.connect_btn,
        ):
            button.setStyleSheet(f"QPushButton {{ min-height: {button_min}px; }}")
        self.header.window_controls.setFixedSize(round(140 + 201 * t), round(34 + 57 * t))
        dock_right = round(28 + 78 * t)
        dock_top = round(13 + 37 * t)
        self.header.window_controls.setProperty("dock_right", dock_right)
        self.header.window_controls.setProperty("dock_top", dock_top)
        self.header.window_controls.layout().setContentsMargins(
            round(4 + 1 * t), round(2 + 5 * t), round(4 + 1 * t), round(2 + 5 * t)
        )
        for button in self.header.window_controls.findChildren(FrameControlButton):
            button.setFixedSize(round(44 + 69 * t), round(30 + 40 * t))
        self.header.window_controls.move(
            self.header.width() - self.header.window_controls.width() - dock_right, dock_top
        )
        # Keep typography aligned with the fixed panel and control geometry.
        ratio = min(1.0, t / 0.348)
        target_sizes = {
            "headerTitle": (29, 39),
            "brandLine": (20, 27),
            "moduleTitle": (19, 24),
            "statusTitle": (27, 35),
            "count": (42, 56),
            "micro": (11, 15),
            "code": (11, 14),
            "fieldLabel": (11, 14),
            "hint": (12, 16),
            "detail": (12, 16),
            "footer": (10, 13),
            "creatorCredit": (25, 25),
            "artCaption": (10, 13),
            "badge": (11, 14),
            "monitorValue": (12, 15),
        }
        for field in self.findChildren(DepthLabel):
            sizes = target_sizes.get(field.objectName())
            if sizes:
                family = (
                    f'font-family: "{field.font_family}";'
                    if isinstance(field, CreatorCredit)
                    else ""
                )
                font_size = round(sizes[0] + (sizes[1] - sizes[0]) * ratio)
                field.setStyleSheet(f"{family} font-size: {font_size}px;")
                field.setProperty(
                    "reference_condensed",
                    field.objectName()
                    in ("headerTitle", "brandLine", "moduleTitle", "statusTitle"),
                )
                field.update()
        value_font = round(15 + 5 * ratio)
        self.control.setStyleSheet(
            f"QComboBox {{ min-height: {control_min}px; font-size: {value_font}px; }} "
            f'QComboBox::down-arrow {{ image: url("{resource("chevron.png").as_posix()}"); width: 16px; height: 16px; }}'
        )
        for spin in (self.interval, self.pulse):
            spin.setStyleSheet(
                f"QSpinBox {{ min-height: {control_min}px; font-size: {value_font}px; }}"
            )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "outer_layout") and hasattr(self, "footer_bar"):
            self.apply_reference_layout()

    def toggle_maximize(self):
        # Retain the title-bar symbol without allowing a larger window.
        if self.isMaximized():
            self.showNormal()
        self.header.window_controls.update()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "header"):
            for button in self.header.window_controls.findChildren(FrameControlButton):
                button.update()

    def _resize_edges(self, pos):
        return Qt.Edge(0)  # The compact window cannot be resized.

    def eventFilter(self, obj, event):
        if not isinstance(obj, QWidget) or not (obj is self or self.isAncestorOf(obj)):
            return super().eventFilter(obj, event)
        kind = event.type()
        mouse = (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        )
        if kind not in mouse:
            return super().eventFilter(obj, event)
        global_pos = event.globalPosition().toPoint()
        if kind == QEvent.Type.MouseMove:
            if self._manual_drag and event.buttons() & Qt.MouseButton.LeftButton:
                self.move(global_pos - self._manual_drag)
                return True
            self.unsetCursor()
        elif kind == QEvent.Type.MouseButtonRelease:
            self._manual_drag = None
            self._manual_resize = None
        elif event.button() == Qt.MouseButton.LeftButton:
            in_header = hasattr(self, "header") and (
                obj is self.header or self.header.isAncestorOf(obj)
            )
            if in_header and not isinstance(obj, FrameControlButton):
                if kind == QEvent.Type.MouseButtonDblClick:
                    return True  # Double-click does not maximise the fixed window.
                if kind == QEvent.Type.MouseButtonPress:
                    if self.isMaximized():
                        fraction = max(
                            0.1,
                            min(
                                0.9, self.header.mapFromGlobal(global_pos).x() / self.header.width()
                            ),
                        )
                        self.showNormal()
                        self.move(
                            global_pos.x() - int(self.width() * fraction), global_pos.y() - 20
                        )
                    if not (self.windowHandle() and self.windowHandle().startSystemMove()):
                        self._manual_drag = global_pos - self.pos()
                    return True
        return super().eventFilter(obj, event)

    def update_visual(self):
        self.visual.set_values(self.interval.value(), self.pulse.value())
        self.dial.set_values(self.interval.value(), self.pulse.value())
        self.control_readout.setText(self.control.currentText())
        self.settings.setValue("timing/interval_ms", self.interval.value())
        self.settings.setValue("timing/pulse_ms", self.pulse.value())

    def show_error(self, title, details):
        QMessageBox.critical(self, title, details)

    def connect_pad(self):
        if self.pad is not None:
            return True
        try:
            with self.pad_lock:
                pad = vg.VX360Gamepad()
                pad.reset()
                pad.update()
                self.pad = pad
        except Exception as exc:
            self.status.setText("Connection failed")
            self.orb.set_mode("idle")
            self.badge.setText("OFFLINE")
            self.detail.setText("Check that ViGEmBus is installed, then restart Windows if needed.")
            self.show_error(
                "Controller connection failed",
                f"The virtual controller could not be created.\n\nInstall ViGEmBus 1.22.0 and retry.\n\nDetails: {exc}",
            )
            return False
        self.status.setText("Controller connected")
        self.orb.set_mode("ready")
        self.badge.setText("CONNECTED")
        self.detail.setText("Virtual Xbox 360 device is ready to pulse.")
        self.connect_btn.setText("CONNECTED")
        self.connect_btn.setEnabled(False)
        # The connected halo remains visible without a separate FX mode.
        return True

    def get_timing(self):
        interval, pulse = self.interval.value(), self.pulse.value()
        if pulse >= interval:
            QMessageBox.warning(
                self, "Check pulse timing", "The pulse must be shorter than the interval."
            )
            return None
        return interval / 1000, pulse / 1000

    def press(self, control):
        if control == "Right Trigger":
            self.pad.right_trigger(value=255)
        elif control == "Left Trigger":
            self.pad.left_trigger(value=255)
        else:
            self.pad.press_button(button=BUTTON_MAP[control])
        self.pad.update()

    def release(self, control):
        if control == "Right Trigger":
            self.pad.right_trigger(value=0)
        elif control == "Left Trigger":
            self.pad.left_trigger(value=0)
        else:
            self.pad.release_button(button=BUTTON_MAP[control])
        self.pad.update()

    def move_stick(self, vertical):
        self.pad.left_joystick_float(x_value_float=0.0, y_value_float=vertical)
        self.pad.update()

    def nudge_cb23(self, return_hold):
        with self.pad_lock:
            if self.stop_event.is_set():
                return
            try:
                self.move_stick(NUDGE_STRENGTH)
                if not self.stop_event.wait(NUDGE_HOLD):
                    self.move_stick(-NUDGE_STRENGTH)
                    self.stop_event.wait(return_hold)
            finally:
                self.move_stick(0.0)

    def pulse_once(self, control, duration, *, nudge=False):
        with self.pad_lock:
            if self.stop_event.is_set():
                return

            pressed = control is not None
            moving = False
            try:
                changes = []
                if pressed:
                    self.press(control)
                    changes.append((time.perf_counter() + duration, None))
                if nudge:
                    moving = True
                    self.move_stick(NUDGE_STRENGTH)
                    moved_at = time.perf_counter()
                    # Merge the stick and button deadlines so the hit keeps its own duration.
                    changes.extend(
                        [
                            (moved_at + NUDGE_HOLD, -NUDGE_STRENGTH),
                            (moved_at + 2 * NUDGE_HOLD, 0.0),
                        ]
                    )
                    changes.sort(key=lambda change: change[0])

                for deadline, vertical in changes:
                    if self.stop_event.wait(max(0, deadline - time.perf_counter())):
                        break
                    if vertical is None:
                        self.release(control)
                        pressed = False
                    else:
                        self.move_stick(vertical)
                        moving = vertical != 0.0
            finally:
                try:
                    if moving:
                        self.move_stick(0.0)
                finally:
                    if pressed:
                        self.release(control)

    def test_pulse(self):
        if self.running or not self.connect_pad():
            return
        timing = self.get_timing()
        if timing is None:
            return
        control = self.control.currentText()
        duration = timing[1]
        self.input_test_btn.setEnabled(False)
        self.cb23_btn.setEnabled(False)
        self.stop_event.clear()

        def work():
            try:
                self.pulse_once(control, duration, nudge=True)
                self.events.tested.emit(control)
            except Exception as exc:
                self.events.error.emit(str(exc))

        threading.Thread(target=work, daemon=True).start()

    def on_tested(self, control):
        self.input_test_btn.setEnabled(True)
        self.cb23_btn.setEnabled(True)
        self.detail.setText(f"One {control} pulse sent successfully.")

    def on_error(self, error):
        self.input_test_btn.setEnabled(not self.running)
        self.cb23_btn.setEnabled(not self.running)
        self.show_error("Controller input failed", error)

    def start(self):
        if self.running or not self.connect_pad():
            return
        timing = self.get_timing()
        if timing is None:
            return
        if not self.input_test_btn.isEnabled():
            return
        interval, duration = timing
        control = self.control.currentText()
        self.begin_session(
            "Auto Scrap active",
            f"Sending {control} every {self.interval.value()} ms.",
            "PULSES SENT",
        )
        self.visual.set_state(True)
        self.dial.set_state(True)
        self.mono.set_running(True)
        self.worker = threading.Thread(
            target=self.loop, args=(control, interval, duration), daemon=True
        )
        self.worker.start()

    def begin_session(self, status, detail, count_label):
        self.stop_event.clear()
        self.running = True
        self.count.setText("0")
        self.count_label.setText(count_label)
        self.status.setText(status)
        self.detail.setText(detail)
        for control in (
            self.start_btn,
            self.input_test_btn,
            self.cb23_btn,
            self.control,
            self.interval,
            self.pulse,
        ):
            control.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.orb.set_mode("active")
        self.badge.setText("ACTIVE")

    def configure_cb23(self):
        if self.running or not self.input_test_btn.isEnabled() or not self.connect_pad():
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("CB-23 Mission Loop")
        form = QFormLayout(dialog)
        instructions = QLabel(
            "Stand facing the Astromech terminal with the claim point 90° to your left. "
            "Check the menu starts at the top, then use Test Left Turn to calibrate your camera. "
            "Right Stick uses Xbox inputs and can run in the background. Mouse needs Fortnite in focus. "
            "If buttons work but the camera does not, turn Fortnite's Lock Input Method as Mouse off. "
            "Press F9 to start with saved settings, or F10 from inside Fortnite "
            "to test your saved left turn while the game has focus. "
            "F8 stops the loop."
        )
        instructions.setWordWrap(True)
        form.addRow(instructions)
        saved = self.saved_cb23_settings()
        fields = {}
        for key, title, minimum, maximum, suffix in (
            ("wait_seconds", "Mission wait", 5, 7200, " s"),
            ("turn_ms", "Right-stick turn duration", 50, 5000, " ms"),
            ("mouse_counts", "Mouse turn distance", 8, 12000, ""),
            ("down_steps", "D-Pad Down presses to CB-23", 0, 20, ""),
            ("hold_ms", "Interact / claim hold", 40, 2500, " ms"),
            ("nudge_return_ms", "Backward nudge duration", 20, 85, " ms"),
        ):
            spin = DepthSpinBox()
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.setKeyboardTracking(False)
            spin.setRange(minimum, maximum)
            spin.setSuffix(suffix)
            spin.setValue(getattr(saved, key))
            if key == "nudge_return_ms":
                spin.setSingleStep(5)
                spin.setToolTip(
                    "Increase slightly for forward drift, or decrease for backward drift."
                )
            fields[key] = spin
            form.addRow(title, spin)
        for key, title, buttons in (
            ("camera_input", "Camera input", ["Right Stick", "Mouse"]),
            ("interact", "Interact and claim button", CONTROLS),
            ("select", "Select CB-23 button", CONTROLS),
            ("confirm", "Extra launch / confirm button", ["None", *CONTROLS]),
        ):
            combo = QComboBox()
            combo.addItems(buttons)
            combo.setCurrentText(getattr(saved, key))
            fields[key] = combo
            form.addRow(title, combo)

        def save_settings():
            values = {
                key: widget.value() if isinstance(widget, QSpinBox) else widget.currentText()
                for key, widget in fields.items()
            }
            for key, value in values.items():
                self.settings.setValue(cb23_setting_key(key), value)
            dialog.accept()
            return CB23Settings(**values)

        def launch(test_turn):
            settings = save_settings()
            # Do not send the stick movement while the modal settings dialog is
            # still tearing down: launch after its event loop has unwound.
            QTimer.singleShot(180, lambda: self.launch_saved_cb23(settings, test_turn))

        actions = QHBoxLayout()
        for title, action in (
            ("Test Left Turn", lambda: launch(True)),
            ("Start Loop", lambda: launch(False)),
            ("Save Settings", save_settings),
            ("Cancel", dialog.reject),
        ):
            button = QPushButton(title)
            button.clicked.connect(action)
            actions.addWidget(button)
        form.addRow(actions)
        dialog.setMinimumWidth(490)
        dialog.exec()

    def launch_saved_cb23(self, settings, test_turn):
        """Start a dialog-requested CB-23 run only after the dialog has closed."""
        if self.running or not self.input_test_btn.isEnabled():
            return
        self.start_cb23(settings, test_turn)

    def saved_cb23_settings(self):
        return CB23Settings(
            **{
                key: self.settings.value(cb23_setting_key(key), default, type=type(default))
                for key, default in vars(CB23Settings()).items()
            }
        )

    def start_cb23(self, settings, test_turn, game_window=None):
        status = "Turn test" if test_turn else "CB-23 loop active"
        detail = (
            "Switch to Fortnite to begin."
            if test_turn or (settings.camera_input == "Mouse" and not game_window)
            else "Starting…"
        )
        self.begin_session(status, detail, "CLAIM ATTEMPTS")
        self.worker = threading.Thread(
            target=self.cb23_loop,
            args=(settings, test_turn, game_window),
            daemon=True,
        )
        self.worker.start()

    def cb23_loop(self, settings, test_turn, game_window):
        reason = "Stopped"
        mouse_camera = settings.camera_input == "Mouse"
        turn_observation = None
        try:

            def can_send_input():
                return not mouse_camera or (
                    game_window is not None and user32.GetForegroundWindow() == game_window
                )

            def wait_for_fortnite():
                nonlocal game_window
                if can_send_input():
                    return not self.stop_event.is_set()
                deadline = time.monotonic() + CB23_FOCUS_TIMEOUT
                self.events.mission_status.emit(
                    "Waiting for Fortnite. Switch back to the game to continue."
                )
                while not self.stop_event.is_set():
                    game_window = foreground_fortnite()
                    if game_window:
                        return True
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise MissionFocusLost(
                            "Fortnite was not in focus for 30 seconds. Return to the terminal and press F9."
                        )
                    self.stop_event.wait(min(0.05, remaining))
                return False

            def check_focus():
                if not can_send_input():
                    raise MissionFocusLost(
                        "Fortnite lost focus during an input sequence. Face the terminal and press F9."
                    )

            def send(control, *, hold=0.08, settle=0.2):
                if self.stop_event.is_set():
                    return False
                check_focus()
                self.pulse_once(control, hold)
                return not self.stop_event.wait(settle)

            def turn(direction, settle):
                if self.stop_event.is_set():
                    return False
                check_focus()
                if mouse_camera:
                    # Mouse mode is intentionally foreground-only.
                    step, extra = divmod(settings.mouse_counts, 8)
                    for index in range(8):
                        check_focus()
                        distance = direction * (step + int(index < extra))
                        user32.mouse_event(
                            0x2001, distance, 0, 0, 0
                        )  # Relative move, no coalescing.
                        if self.stop_event.wait(0.02):
                            return False
                elif not run_right_stick_turn(
                    self.pad,
                    self.pad_lock,
                    self.stop_event,
                    direction,
                    settings.turn_ms,
                    observer=turn_observation.sample if turn_observation else None,
                ):
                    return False
                return not self.stop_event.wait(settle)

            interact_hold = settings.hold_ms / 1000
            return_hold = settings.nudge_return_ms / 1000
            if test_turn:
                units = (
                    f"{settings.turn_ms} ms on Xbox right stick"
                    if not mouse_camera
                    else f"{settings.mouse_counts} mouse counts"
                )
                self.events.mission_status.emit(
                    "Switch to Fortnite within 30 seconds to test the left turn. F8 cancels."
                )
                deadline = time.monotonic() + CB23_FOCUS_TIMEOUT
                ready_at = None
                while not self.stop_event.is_set():
                    active = foreground_fortnite()
                    now = time.monotonic()
                    if active:
                        game_window = active
                        if ready_at is None:
                            # Let Windows enumerate a newly connected pad and let
                            # the game switch away from the mouse used for the dialog.
                            ready_at = now + 1.0
                        if now >= ready_at:
                            if not mouse_camera:
                                turn_observation = TurnObservation(-1)
                            self.events.mission_status.emit(f"Testing left turn — {units}.")
                            if turn(-1, settle=0.2):
                                self.turn_test_report = (
                                    turn_observation.description()
                                    if turn_observation
                                    else "Mouse left-turn input sent. Check the camera in Fortnite."
                                )
                                reason = "Turn sent"
                            break
                    else:
                        ready_at = None
                    if now >= deadline:
                        raise MissionFocusLost(
                            "Turn test timed out. Open Fortnite, close its menus, then press F10."
                        )
                    self.stop_event.wait(0.05)
                return

            count = 0
            while not self.stop_event.is_set():
                if not wait_for_fortnite():
                    return
                self.events.mission_status.emit("Opening Astromech terminal and selecting CB-23…")
                if not send(settings.interact, hold=interact_hold, settle=0.9):
                    return
                for _ in range(settings.down_steps):
                    if not send("D-Pad Down"):
                        return
                if not send(settings.select, settle=0.9):
                    return
                if settings.confirm != "None" and not send(settings.confirm):
                    return

                minutes, seconds = divmod(settings.wait_seconds, 60)
                self.events.mission_status.emit(f"Waiting {minutes}:{seconds:02d} before claiming.")
                claim_at = time.monotonic() + settings.wait_seconds
                nudge_settled_at = 0.0
                while (remaining := claim_at - time.monotonic()) > 0:
                    if self.stop_event.wait(min(remaining, NUDGE_INTERVAL)):
                        return
                    time_needed = NUDGE_HOLD + return_hold + CB23_TURN_QUIET_TIME
                    if claim_at - time.monotonic() >= time_needed and can_send_input():
                        self.nudge_cb23(return_hold)
                        nudge_settled_at = time.monotonic() + CB23_TURN_QUIET_TIME
                settle_remaining = nudge_settled_at - time.monotonic()
                if settle_remaining > 0 and self.stop_event.wait(settle_remaining):
                    return
                if not wait_for_fortnite():
                    return
                self.events.mission_status.emit("Turning left to claim the reward…")
                if not turn(-1, settle=0.45):
                    return
                self.events.mission_status.emit(f"Pressing {settings.interact} to open the crate…")
                if not send(settings.interact, hold=interact_hold, settle=1.25):
                    return
                count += 1
                self.events.count.emit(count)
                self.events.mission_status.emit("Turning right to face the terminal…")
                if not turn(1, settle=0):
                    return
                self.events.mission_status.emit("Waiting 10 seconds before restarting the mission.")
                if self.stop_event.wait(CB23_RESTART_DELAY):
                    return
        except MissionFocusLost as exc:
            reason = "CB-23 loop stopped"
            self.events.mission_status.emit(str(exc))
        except Exception as exc:
            reason = "CB-23 loop failed"
            self.events.mission_status.emit(f"Controller input failed: {exc}")
        finally:
            try:
                with self.pad_lock:
                    self.pad.reset()
                    self.pad.update()
            except Exception as exc:
                reason = "Controller reset failed"
                self.events.mission_status.emit(f"Controller reset failed: {exc}")
            self.events.finished.emit(reason)

    def loop(self, control, interval, duration):
        count = 0
        next_tick = time.perf_counter()
        reason = "Stopped"
        next_nudge = next_tick
        try:
            while not self.stop_event.is_set():
                now = time.perf_counter()
                nudge = now >= next_nudge
                self.pulse_once(control, duration, nudge=nudge)
                if self.stop_event.is_set():
                    break
                if nudge:
                    next_nudge = now + NUDGE_INTERVAL
                count += 1
                if count == 1 or count % 5 == 0:
                    self.events.count.emit(count)
                next_tick += interval
                delay = next_tick - time.perf_counter()
                if delay > 0:
                    self.stop_event.wait(delay)
                else:
                    next_tick = time.perf_counter()
        except Exception as exc:
            reason = "Pulse failed"
            self.events.error.emit(str(exc))
        finally:
            try:
                with self.pad_lock:
                    self.pad.reset()
                    self.pad.update()
            except Exception:
                pass
            self.events.count.emit(count)
            self.events.finished.emit(reason)

    def update_alarm_button(self, status):
        # Do not conceal scanner failures or paused monitoring behind an
        # apparently healthy "ALARM ON" button.
        if status.startswith("ALARM ERROR") or status.startswith("Alarm could not play"):
            text = "DROID WATCH / ERROR"
            footer_state = "ERROR"
        elif self.droid_alert.active and self.droid_alert.state.startswith("WATCH ON / STALLED"):
            text = "DROID WATCH / ON (STALLED)"
            footer_state = "ON (STALLED)"
        elif self.droid_alert.active and self.droid_alert.health_degraded:
            # DELAYED means the scanner is still enabled, not switched off.
            # Keep this visible even if a rare-droid alert was just received.
            text = "DROID WATCH / ON (DELAYED)"
            footer_state = "ON (DELAYED)"
        elif self.droid_alert.active and not self.droid_alert.watch_visible:
            text = "DROID WATCH / ON (PAUSED)"
            footer_state = "ON (PAUSED)"
        elif (
            self.droid_alert.active
            and self.droid_alert.last_alert_pair
            and (time.monotonic() - self.droid_alert.last_alert_time < 8.0)
        ):
            text = f"DROID WATCH / {self.droid_alert.last_alert_pair.upper()}"
            footer_state = "ON"
            QTimer.singleShot(8100, self, lambda: self.update_alarm_button(self.droid_alert.state))
        elif self.droid_alert.active:
            text = "DROID WATCH / ON"
            footer_state = "ON"
        else:
            text = "DROID WATCH"
            footer_state = "OFF"
        self.watch_btn.setText(text)
        self.watch_btn.setToolTip(status or "Configure rare droid monitoring")
        # Track the state for the information popup, but never create a second
        # live footer readout. The primary Droid Watch button is authoritative.
        if footer_state != self._watch_footer_state:
            self._watch_footer_state = footer_state
            tooltip = f"Open Droid Watch status guide (current: {footer_state})"
            self.watch_status_info_btn.setToolTip(tooltip)
            self.watch_status_info_text_btn.setToolTip(tooltip)

    def show_watch_status_info(self):
        """Display every scanner status without changing monitoring or focus."""
        guide = QDialog(self)
        guide.setObjectName("droidWatchStatusGuide")
        guide.setWindowTitle("Droid Watch — Status Information")
        guide.setModal(True)
        guide.setMinimumWidth(660)
        guide.setStyleSheet("""
            QDialog#droidWatchStatusGuide {
                background-color: #101218;
                border: 1px solid #90394d;
                color: #f5f0f1;
            }
            QLabel#watchGuideTitle {
                color: #ff7990; font-size: 19px; font-weight: 800;
                font-family: 'Bahnschrift', 'Segoe UI';
            }
            QLabel#watchGuideSubtitle, QLabel#watchGuideDetail {
                color: #bfb1bb; font-size: 11px;
            }
            QLabel#watchGuideCurrent {
                color: #f4dde3; font-size: 12px; font-weight: 700;
            }
            QLabel#watchGuideColumn {
                color: #e98da0; font-size: 10px; font-weight: 800;
            }
            QFrame#watchGuideRow {
                background-color: #1b1c25;
                border: 1px solid #44313b;
                border-left: 3px solid #ae4258;
                border-radius: 4px;
            }
            QLabel#watchGuideStatus {
                color: #f3a2b2; font: bold 11px 'Consolas';
            }
            QLabel#watchGuideMeaning {
                color: #f2e9ec; font-size: 12px;
            }
            QPushButton#watchGuideClose {
                color: #fff7f8; background-color: #74263c;
                border: 1px solid #dc4762; border-radius: 5px;
                padding: 8px 22px; font-weight: 700;
            }
            QPushButton#watchGuideClose:hover { background-color: #a53550; }
        """)
        root = QVBoxLayout(guide)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(9)

        heading = QLabel("DROID WATCH / STATUS GUIDE", guide)
        heading.setObjectName("watchGuideTitle")
        root.addWidget(heading)
        subtitle = QLabel("What the live scanner indicator means", guide)
        subtitle.setObjectName("watchGuideSubtitle")
        root.addWidget(subtitle)

        current = QLabel(
            f"CURRENT STATUS: DROID WATCH / {getattr(self, '_watch_footer_state', 'OFF')}", guide
        )
        current.setObjectName("watchGuideCurrent")
        root.addWidget(current)

        columns = QHBoxLayout()
        first = QLabel("STATUS DISPLAYED", guide)
        first.setObjectName("watchGuideColumn")
        first.setMinimumWidth(230)
        second = QLabel("MEANING", guide)
        second.setObjectName("watchGuideColumn")
        columns.addWidget(first)
        columns.addWidget(second, 1)
        root.addLayout(columns)

        statuses = (
            ("DROID WATCH / ON", "Monitoring normally"),
            ("DROID WATCH / ON (DELAYED)", "Still enabled, but recognition is running behind"),
            ("DROID WATCH / ON (STALLED)", "Enabled, but the scanner has stopped responding"),
            ("DROID WATCH / ON (PAUSED)", "Enabled, but the notification area is not visible"),
            ("DROID WATCH / ERROR", "Scanner or alarm failure"),
            ("DROID WATCH / OFF", "Monitoring is switched off"),
        )
        for status_name, meaning in statuses:
            item = QFrame(guide)
            item.setObjectName("watchGuideRow")
            content = QHBoxLayout(item)
            content.setContentsMargins(12, 9, 12, 9)
            content.setSpacing(10)
            name = QLabel(status_name, item)
            name.setObjectName("watchGuideStatus")
            name.setMinimumWidth(230)
            explanation = QLabel(meaning, item)
            explanation.setObjectName("watchGuideMeaning")
            explanation.setWordWrap(True)
            content.addWidget(name)
            content.addWidget(explanation, 1)
            root.addWidget(item)

        diagnostic = QLabel(
            f"LATEST SCANNER MESSAGE: {self.droid_alert.state or 'No scanner message'}", guide
        )
        diagnostic.setObjectName("watchGuideDetail")
        diagnostic.setWordWrap(True)
        root.addWidget(diagnostic)
        close_row = QHBoxLayout()
        close_row.addStretch()
        close = QPushButton("CLOSE", guide)
        close.setObjectName("watchGuideClose")
        close.clicked.connect(guide.accept)
        close_row.addWidget(close)
        root.addLayout(close_row)
        guide.exec()

    def stop(self):
        self.stop_event.set()
        self.mono.set_running(False)
        if self.running:
            self.status.setText("Stopping…")
            self.stop_btn.setEnabled(False)

    def on_count(self, number):
        self.count.setText(f"{number:,}")

    def on_mission_status(self, status):
        self.detail.setText(status)

    def on_finished(self, reason):
        self.running = False
        self.visual.set_state(False)
        self.dial.set_state(False)
        self.mono.set_running(False)
        self.orb.set_mode("stopped")
        self.badge.setText("READY")
        self.status.setText(reason)
        if reason == "Turn sent":
            report = getattr(
                self, "turn_test_report", "Left-turn input sent. Check the camera in Fortnite."
            )
            self.detail.setText(report)
            self.detail.setToolTip(report)
        elif reason not in ("CB-23 loop stopped", "CB-23 loop failed", "Controller reset failed"):
            self.detail.setText("Controller connected and ready for another session.")
        self.start_btn.setEnabled(True)
        self.input_test_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.cb23_btn.setEnabled(True)
        self.control.setEnabled(True)
        self.interval.setEnabled(True)
        self.pulse.setEnabled(True)

    def poll_hotkey(self):
        stop_pressed = bool(user32.GetAsyncKeyState(VK_F8) & 0x8000)
        start_pressed = bool(user32.GetAsyncKeyState(VK_F9) & 0x8000)
        test_pressed = bool(user32.GetAsyncKeyState(VK_F10) & 0x8000)
        start_requested = start_pressed and not self.f9_down
        test_requested = test_pressed and not self.f10_down
        if stop_pressed and not self.f8_down:
            self.stop()
        self.f8_down = stop_pressed
        self.f9_down = start_pressed
        self.f10_down = test_pressed
        if (
            not stop_pressed
            and not self.running
            and self.input_test_btn.isEnabled()
            and QApplication.activeModalWidget() is None
            and (start_requested or test_requested)
        ):
            if self.connect_pad():
                settings = self.saved_cb23_settings()
                game_window = foreground_fortnite() if settings.camera_input == "Mouse" else None
                self.start_cb23(settings, test_requested, game_window)

    def closeEvent(self, event):
        self.hotkey_timer.stop()
        self.stop_event.set()
        self.droid_alert.shutdown()
        self._gui_lag_timer.stop()
        QApplication.instance().removeEventFilter(self)
        # The in-app history is session-only; never write it to settings or disk.
        self.droid_alert.clear_history()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=1.0)
        try:
            with self.pad_lock:
                if self.pad:
                    self.pad.reset()
                    self.pad.update()
        except Exception:
            pass
        event.accept()


def main():
    # Match the installer shortcuts so Windows associates the running window
    # with this app's icon instead of a previously pinned executable.
    shell32 = ctypes.windll.shell32
    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [ctypes.c_wchar_p]
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.c_long
    shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    app = QApplication(sys.argv)
    app.setApplicationName("Droid Tycoon DroidOps")
    app.setOrganizationName("Dane Vanzino")
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(str(resource("app.ico"))))
    window = Clicker()
    window.show()
    sys.exit(app.exec())
