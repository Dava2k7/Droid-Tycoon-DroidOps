"""Deterministic Xbox right-stick turns for CB-23 mission camera calibration.

No Fortnite process access is involved; this module sends standard virtual
controller input through the application's existing vgamepad instance.
"""

import time


def run_right_stick_turn(pad, pad_lock, stop_event, direction, duration_ms, *, observer=None):
    """Send a distinct neutral -> left/right -> neutral sequence.

    A short neutral stage prevents repeated calibration tests from blending
    together. Always releases the stick, even if Stop is pressed mid-turn or
    a virtual-controller update fails. Returns whether the intended hold was
    completed, not whether the game reacted to the input.
    """
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 for left or +1 for right")
    if not 50 <= duration_ms <= 5000:
        raise ValueError("turn duration must be within 50–5000 milliseconds")
    if pad is None or stop_event.is_set():
        return False
    with pad_lock:
        if stop_event.is_set():
            return False
        try:
            # Reset the axis so a fresh turn produces a new input transition.
            pad.right_joystick_float(x_value_float=0.0, y_value_float=0.0)
            pad.update()
            if stop_event.wait(0.12):
                return False
            pad.right_joystick_float(x_value_float=float(direction), y_value_float=0.0)
            pad.update()
            deadline = time.monotonic() + duration_ms / 1000
            while (remaining := deadline - time.monotonic()) > 0:
                if observer is not None:
                    observer()
                if stop_event.wait(min(remaining, 0.04)):
                    return False
                if time.monotonic() < deadline:
                    pad.update()
            return True
        finally:
            pad.right_joystick_float(x_value_float=0.0, y_value_float=0.0)
            pad.update()
