"""
Unit tests for Ghost AI UI components, cursors, HWND separation, taskbar exclusion,
multi-chat navigation, and view switching.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ghost_ai.main_window import MainWindow
from ghost_ai.win32_utils import (
    is_click_through,
    is_taskbar_excluded,
    get_extended_style,
    WS_EX_TOOLWINDOW,
    WS_EX_APPWINDOW,
)


def test_ui_and_hwnd_separation(qapp):
    win = MainWindow()
    win.show_app()
    qapp.processEvents()

    # 1. Distinct HWNDs
    win_hwnd = int(win.winId())
    ctrl_hwnd = int(win.controls.winId())
    assert win_hwnd != 0
    assert ctrl_hwnd != 0
    assert win_hwnd != ctrl_hwnd

    # 2. Strict arrow cursor checks (Ghost requirement: stealth, no jarring cursor changes)
    assert win.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.history_view.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.history_view.search_edit.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.chat_view.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.chat_view.title_edit.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.chat_view.input_edit.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.controls.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.controls.blue_btn.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.controls.red_btn.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert win.resize_grip.cursor().shape() == Qt.CursorShape.ArrowCursor

    # 3. Hit targets and dot dimensions
    assert win.controls.blue_btn.width() == 18
    assert win.controls.blue_btn.height() == 18
    assert win.controls.red_btn.width() == 18
    assert win.controls.red_btn.height() == 18
    assert win.controls.blue_btn.toolTip() == ""
    assert win.controls.red_btn.toolTip() == ""

    # 4. Taskbar and Alt+Tab exclusion
    assert is_taskbar_excluded(win_hwnd) is True
    assert is_taskbar_excluded(ctrl_hwnd) is True
    win_style = get_extended_style(win_hwnd)
    ctrl_style = get_extended_style(ctrl_hwnd)
    assert bool(win_style & WS_EX_TOOLWINDOW)
    assert not bool(win_style & WS_EX_APPWINDOW)
    assert bool(ctrl_style & WS_EX_TOOLWINDOW)
    assert not bool(ctrl_style & WS_EX_APPWINDOW)

    # 5. Ghost mode toggles
    assert not is_click_through(win_hwnd)
    win.toggle_ghost_mode()
    assert is_click_through(win_hwnd)
    assert not is_click_through(ctrl_hwnd)

    win.toggle_ghost_mode()
    assert not is_click_through(win_hwnd)

    # 6. Multi-chat navigation
    initial_chat_count = len(win._chats)
    win.create_new_chat()
    assert len(win._chats) == initial_chat_count + 1
    assert win.stack.currentIndex() == 1  # In ChatView

    win.show_home()
    assert win.stack.currentIndex() == 0  # In HistoryView

    # 7. Settings dialog lifecycle: ensure closing settings dialog does NOT close the app
    from ghost_ai.settings_dialog import SettingsDialog
    dialog = SettingsDialog(win)
    dialog.show()
    qapp.processEvents()
    assert dialog.isVisible()
    dialog.accept()
    qapp.processEvents()
    # Main window must still be open and visible
    assert win.isVisible()

    win.close_application()
