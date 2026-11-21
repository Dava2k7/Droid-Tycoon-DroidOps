import ctypes

from droidops.xinput_status import Gamepad, State, TurnObservation


def test_xinput_structures_match_windows_layout():
    assert ctypes.sizeof(Gamepad) == 12
    assert ctypes.sizeof(State) == 16


def test_new_left_axis_is_confirmed_but_preexisting_physical_axis_is_not():
    samples = iter([{0: (-32767, 0), 1: (0, 0)}, {0: (-32767, 0), 1: (-32767, 0)}])
    observer = TurnObservation(-1, read=lambda: next(samples))
    observer.sample()
    assert observer.seen == {1}
    assert "controller 2" in observer.description()
    assert "Lock Input Method as Mouse" in observer.description()


def test_neutral_or_wrong_direction_is_not_claimed_as_left():
    samples = iter([{0: (0, 0)}, {0: (32767, 0)}, {0: (0, 0)}])
    observer = TurnObservation(-1, read=lambda: next(samples))
    observer.sample()
    observer.sample()
    assert not observer.seen
    assert "did not confirm" in observer.description()


def test_unavailable_api_is_reported_without_claiming_game_movement():
    observer = TurnObservation(-1, read=lambda: None)
    observer.sample()
    assert "unavailable" in observer.description()
