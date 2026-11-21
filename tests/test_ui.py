import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QSize, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QCheckBox, QScrollArea
from ui_support import load_view
import sys
import types
import threading


@pytest.fixture(scope="module")
def qt():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt, tmp_path, monkeypatch):
    view = load_view()
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("droidAlert/possible_alerts", True)
    monkeypatch.setattr(view, "QSettings", lambda *args: settings)
    poll_impl = view.Clicker.poll_hotkey
    monkeypatch.setattr(view.Clicker, "poll_hotkey", lambda self: None)
    qt.setStyleSheet(view.STYLE)
    window = view.Clicker()
    window._test_poll_impl = poll_impl
    window.show()
    qt.processEvents()
    yield window
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt.processEvents()


def test_window_is_fixed_and_frame_controls_fit(window, qt):
    expected = QSize(1080, 780)
    window.resize(1600, 1100)
    qt.processEvents()
    assert window.size() == expected == window.minimumSize() == window.maximumSize()
    window.toggle_maximize()
    assert not window.isMaximized()
    controls = window.header.window_controls
    assert window.header.width() - controls.x() - controls.width() == 28
    for button in controls.findChildren(type(controls.layout().itemAt(0).widget())):
        assert controls.rect().contains(button.geometry())
        if button.action == "max":
            assert not button.isEnabled()


def test_footer_has_clearance_and_credit_is_centred(window):
    footer = window.footer_bar
    for button in [
        window.watch_status_info_text_btn,
        window.watch_status_info_btn,
        window.input_test_btn,
        window.alert_history_btn,
    ]:
        assert button.y() >= 5
        assert button.geometry().bottom() <= footer.height() - 6
    assert window.creator_credit.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert window.creator_credit.text() == window.creator_credit.SECRET


def test_creator_easter_egg_reveals_dane_v_after_fifty_clicks(window):
    from PySide6.QtTest import QTest

    credit = window.creator_credit
    for _ in range(49):
        QTest.mouseClick(credit, Qt.MouseButton.LeftButton)
    assert credit.text() == credit.SECRET
    QTest.mouseClick(credit, Qt.MouseButton.LeftButton)
    assert credit.text() == "Created by Dane V"
    assert credit.reveal_timer.isActive()
    credit.reveal_timer.timeout.emit()
    assert credit.text() == credit.SECRET
    assert credit.click_count == 0


def test_timing_boxes_have_clickable_editors_and_accept_typed_values(window, qt):
    from PySide6.QtTest import QTest

    for field, value in [(window.interval, 850), (window.pulse, 60)]:
        editor = field.lineEdit()
        assert editor.width() >= field.width() - 40
        assert window.childAt(editor.mapTo(window, editor.rect().center())) is editor
        QTest.mouseClick(editor, Qt.MouseButton.LeftButton)
        QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(editor, str(value))
        QTest.keyClick(editor, Qt.Key.Key_Return)
        qt.processEvents()
        assert field.value() == value
    assert window.settings.value("timing/interval_ms", type=int) == 850
    assert window.settings.value("timing/pulse_ms", type=int) == 60


def test_shutdown_stops_watcher_watchdog(window):
    window.droid_alert.shutdown()
    assert not window.droid_alert.health_watchdog.isActive()
    assert not window.droid_alert.audio_timer.isActive()


def test_turn_duration_editor_can_be_clicked_typed_and_saved(window, qt, monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QSpinBox, QPushButton

    monkeypatch.setattr(window, "connect_pad", lambda: True)
    errors = []

    def edit():
        dialog = next(w for w in qt.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible())
        try:
            field = next(
                w
                for w in dialog.findChildren(QSpinBox)
                if dialog.layout().labelForField(w).text() == "Right-stick turn duration"
            )
            editor = field.lineEdit()
            assert editor.width() >= field.width() - 40
            assert dialog.childAt(editor.mapTo(dialog, editor.rect().center())) is editor
            QTest.mouseClick(editor, Qt.MouseButton.LeftButton)
            QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            QTest.keyClicks(editor, "800")
            QTest.keyClick(editor, Qt.Key.Key_Tab)
            next(w for w in dialog.findChildren(QPushButton) if w.text() == "Save Settings").click()
        except Exception as error:
            errors.append(error)
            dialog.reject()

    QTimer.singleShot(80, edit)
    window.configure_cb23()
    if errors:
        raise errors[0]
    assert window.saved_cb23_settings().turn_ms == 800


def test_watch_failure_shows_full_error_and_can_copy_it(window, qt):
    from PySide6.QtWidgets import QMessageBox

    alert = window.droid_alert
    token = threading.Event()
    alert.cancel = token
    error = "ValueError: notification region is outside the allowed capture area"
    alert.on_failure(token, error)
    qt.processEvents()
    assert token.is_set()
    assert error in alert.state
    box = alert.error_dialog
    assert isinstance(box, QMessageBox) and box.isVisible()
    assert error == box.informativeText()
    copy = next(button for button in box.buttons() if button.text() == "Copy error")
    copy.click()
    assert error in QApplication.clipboard().text()
    box.close()


def prepare_turn_test(window, monkeypatch, foreground):
    view = sys.modules[window.__class__.__module__]
    monkeypatch.setattr(view, "foreground_fortnite", foreground)
    window.pad = types.SimpleNamespace(reset=lambda: None, update=lambda: None)
    window.pad_lock = threading.Lock()
    monkeypatch.setattr(view, "CB23_FOCUS_TIMEOUT", 2, raising=False)
    return view


def test_left_turn_waits_for_game_before_using_saved_duration(window, monkeypatch):
    active = iter([None, 41])
    view = prepare_turn_test(window, monkeypatch, lambda: next(active, 41))
    turns = []
    monkeypatch.setattr(
        view, "run_right_stick_turn", lambda *args, **kwargs: turns.append(args[3:]) or True
    )
    settings = view.CB23Settings(turn_ms=800)
    window.cb23_loop(settings, True, None)
    assert turns == [(-1, 800)]


def test_left_turn_does_not_send_input_when_fortnite_never_active(window, monkeypatch):
    view = prepare_turn_test(window, monkeypatch, lambda: None)
    monkeypatch.setattr(view, "CB23_FOCUS_TIMEOUT", 0)
    turns = []
    monkeypatch.setattr(
        view, "run_right_stick_turn", lambda *args, **kwargs: turns.append(args) or True
    )
    window.cb23_loop(view.CB23Settings(), True, None)
    assert turns == []
    assert "timed out" in window.detail.text()


def test_cancelled_left_turn_sends_no_movement(window, monkeypatch):
    view = prepare_turn_test(window, monkeypatch, lambda: 41)
    turns = []
    monkeypatch.setattr(
        view, "run_right_stick_turn", lambda *args, **kwargs: turns.append(args) or True
    )
    window.stop_event.set()
    window.cb23_loop(view.CB23Settings(), True, None)
    assert turns == []


def test_dialog_start_keeps_window_visible_and_routes_test_flag(window, monkeypatch):
    view = sys.modules[window.__class__.__module__]
    calls = []
    monkeypatch.setattr(window, "start_cb23", lambda *args: calls.append(args))
    settings = view.CB23Settings(camera_input="Mouse", turn_ms=900)
    window.launch_saved_cb23(settings, True)
    assert calls == [(settings, True)]
    assert not window.isMinimized()


def test_f10_uses_saved_turn_and_triggers_once_per_keypress(window, monkeypatch):
    view = sys.modules[window.__class__.__module__]
    calls = []
    window.settings.setValue(view.cb23_setting_key("turn_ms"), 850)
    monkeypatch.setattr(
        view,
        "user32",
        types.SimpleNamespace(GetAsyncKeyState=lambda key: 0x8000 if key == view.VK_F10 else 0),
        raising=False,
    )
    monkeypatch.setattr(window, "connect_pad", lambda: True)
    monkeypatch.setattr(window, "start_cb23", lambda *args: calls.append(args))
    window._test_poll_impl(window)
    window._test_poll_impl(window)
    assert len(calls) == 1
    assert calls[0][0].turn_ms == 850
    assert calls[0][1:] == (True, None)


def test_memory_guard_stops_only_scanner_and_reports_reason(window, monkeypatch):
    from droidops import droid_alert as scanner

    alive, messages, closed = [True], [], []

    def terminate():
        alive[0] = False
        closed.append("scanner")

    process = types.SimpleNamespace(
        is_alive=lambda: alive[0], terminate=terminate, join=lambda **kw: None, exitcode=-15
    )
    queue = types.SimpleNamespace(
        cancel_join_thread=lambda: None, close=lambda: closed.append("queue")
    )
    monkeypatch.setattr(scanner, "scanner_over_budget", lambda p: p is process)
    token, stop = threading.Event(), threading.Event()
    window.droid_alert.failed.connect(lambda _, message: messages.append(message))
    window.droid_alert._read_process_events(token, process, queue, stop)
    assert stop.is_set()
    assert closed == ["scanner", "queue"]
    assert len(messages) == 1 and "512 MB" in messages[0]


def test_duplicate_watcher_start_is_rejected(window):
    window.droid_alert.worker = types.SimpleNamespace(is_alive=lambda: True, join=lambda **kw: None)
    assert not window.droid_alert.start((0, 0, 1000, 100))


@pytest.mark.parametrize(
    "name", ["Possible Mythic", "Possible Legendary", "Mythic", "Legendary", "Unknown Mythic"]
)
def test_incomplete_or_generic_alert_cannot_play(window, monkeypatch, name):
    plays = []
    monkeypatch.setattr(window.droid_alert, "play_next_alert", lambda: plays.append(True))
    assert not window.droid_alert.queue_alert(name)
    assert not window.droid_alert.pending_alerts
    assert plays == []


def test_upgrade_discards_old_warning_preference(window):
    assert not window.settings.contains("droidAlert/possible_alerts")


def test_only_selected_named_pairs_alert_and_enter_history(window, monkeypatch):
    alert = window.droid_alert
    token = threading.Event()
    alert.cancel = token
    alert.enabled_pairs = {"Diamond Mythic"}
    played = []
    monkeypatch.setattr(alert, "queue_alert", lambda pair: played.append(pair))
    alert.on_match(token, "Kyber Mythic")
    alert.on_match(token, "Diamond Mythic")
    assert played == ["Diamond Mythic"]
    assert [entry.droid for entry in alert.session_history.entries()] == ["Diamond Mythic"]


def test_filter_matrix_keeps_saved_preferences_and_all_rows_accessible(window, qt):
    alert = window.droid_alert
    alert.set_pair_enabled("Diamond Mythic", True)
    errors = []

    def inspect():
        dialog = next(w for w in qt.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible())
        try:
            from PySide6.QtWidgets import QPushButton

            assert not any(
                "possible" in w.text().casefold()
                for w in [*dialog.findChildren(QCheckBox), *dialog.findChildren(QPushButton)]
            )
            choices = [c for c in dialog.findChildren(QCheckBox) if c.accessibleName()]
            assert len(choices) == 45
            scroll_parent = dialog.findChild(QScrollArea)
            filters = scroll_parent.parentWidget()
            assert scroll_parent.geometry().bottom() < filters.height()
            assert filters.geometry().bottom() < dialog.layout().itemAt(2).widget().y()
            assert next(c for c in choices if c.accessibleName() == "Diamond Mythic").isChecked()
            gold = next(c for c in choices if c.accessibleName() == "Gold Common")
            gold.click()
            assert "Gold Common" in alert.enabled_pairs
            scroll = dialog.findChild(QScrollArea)
            last = next(c for c in choices if c.accessibleName() == "Scourge Mythic")
            scroll.ensureWidgetVisible(last)
            qt.processEvents()
            assert not last.visibleRegion().isEmpty()
        except Exception as exc:
            errors.append(exc)
        finally:
            dialog.accept()

    QTimer.singleShot(50, inspect)
    alert.configure()
    if errors:
        raise errors[0]
