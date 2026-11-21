"""Read Windows' controller state to distinguish a sent axis from game response."""

import ctypes
from functools import lru_cache
import os


class Gamepad(ctypes.Structure):
    _fields_ = [
        ("buttons", ctypes.c_uint16),
        ("left_trigger", ctypes.c_uint8),
        ("right_trigger", ctypes.c_uint8),
        ("left_x", ctypes.c_int16),
        ("left_y", ctypes.c_int16),
        ("right_x", ctypes.c_int16),
        ("right_y", ctypes.c_int16),
    ]


class State(ctypes.Structure):
    _fields_ = [("packet", ctypes.c_uint32), ("gamepad", Gamepad)]


@lru_cache(maxsize=1)
def _reader():
    if os.name != "nt":
        return None
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "xinput1_4.dll")
    try:
        function = ctypes.WinDLL(path).XInputGetState
        function.argtypes = [ctypes.c_uint32, ctypes.POINTER(State)]
        function.restype = ctypes.c_uint32
        return function
    except (OSError, AttributeError):
        return None


def right_sticks():
    read = _reader()
    if read is None:
        return None
    result = {}
    for slot in range(4):
        state = State()
        if read(slot, ctypes.byref(state)) == 0:
            result[slot] = (state.gamepad.right_x, state.gamepad.right_y)
    return result


class TurnObservation:
    def __init__(self, direction, read=right_sticks):
        self.direction = direction
        self.read = read
        self.before = read()
        self.seen = set()

    def sample(self):
        current = self.read()
        if current is None or self.before is None:
            return
        for slot, (x, y) in current.items():
            if self.direction * x >= 25000 and abs(y) <= 5000 and self.before.get(slot) != (x, y):
                self.seen.add(slot)

    def description(self):
        if self.seen:
            slots = ", ".join(str(slot + 1) for slot in sorted(self.seen))
            return (
                f"Windows confirmed right-stick left on controller {slots}. "
                "If the camera stayed still, turn Fortnite's Lock Input Method as Mouse off; "
                "check look sensitivity or select Mouse camera input for a foreground test."
            )
        if self.before is None:
            return "Turn input sent; Windows axis confirmation was unavailable. Check the camera in Fortnite."
        return (
            "Windows did not confirm the right-stick movement. Reconnect the virtual controller "
            "and test again; Test Input alone does not verify the camera axis."
        )
