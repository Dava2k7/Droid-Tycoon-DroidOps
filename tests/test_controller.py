import threading
import pytest
from droidops.cb23_turn import run_right_stick_turn


class Pad:
    def __init__(self, stop=None):
        self.axes = []
        self.updates = 0
        self.stop = stop

    def right_joystick_float(self, **axes):
        self.axes.append(axes)
        if self.stop is not None and axes["x_value_float"]:
            self.stop.set()

    def update(self):
        self.updates += 1


@pytest.mark.parametrize("direction", [-1, 1])
def test_turn_always_returns_to_neutral(direction):
    pad = Pad()
    stop = threading.Event()
    assert run_right_stick_turn(pad, threading.Lock(), stop, direction, 50)
    assert [x["x_value_float"] for x in pad.axes] == [0.0, float(direction), 0.0]


def test_stop_during_turn_releases_the_stick():
    stop = threading.Event()
    pad = Pad(stop)
    assert not run_right_stick_turn(pad, threading.Lock(), stop, -1, 50)
    assert pad.axes[-1] == {"x_value_float": 0.0, "y_value_float": 0.0}


def test_pre_cancelled_turn_sends_no_input():
    stop = threading.Event()
    stop.set()
    pad = Pad()
    assert not run_right_stick_turn(pad, threading.Lock(), stop, -1, 50)
    assert pad.axes == []


@pytest.mark.parametrize("direction,duration", [(0, 50), (1, 49), (1, 5001)])
def test_invalid_turn_is_rejected(direction, duration):
    with pytest.raises(ValueError):
        run_right_stick_turn(Pad(), threading.Lock(), threading.Event(), direction, duration)
