"""
Tests for Win32 window style utilities in Ghost AI.
"""

import sys
import pytest
from PySide6.QtWidgets import QWidget
from ghost_ai.win32_utils import (
    GWL_EXSTYLE,
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
    WS_EX_TOOLWINDOW,
    WS_EX_APPWINDOW,
    set_click_through,
    is_click_through,
    exclude_from_taskbar,
    is_taskbar_excluded,
    get_extended_style,
)


def test_constants():
    assert GWL_EXSTYLE == -20
    assert WS_EX_LAYERED == 0x00080000
    assert WS_EX_TRANSPARENT == 0x00000020
    assert WS_EX_TOOLWINDOW == 0x00000080
    assert WS_EX_APPWINDOW == 0x00040000


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test")
def test_win32_click_through_toggle(qapp):
    widget = QWidget()
    widget.show()
    qapp.processEvents()

    hwnd = int(widget.winId())
    assert hwnd != 0

    # Initially not click-through
    assert not is_click_through(hwnd)

    # Enable click-through
    success = set_click_through(hwnd, True)
    assert success is True
    assert is_click_through(hwnd)
    style = get_extended_style(hwnd)
    assert style & WS_EX_TRANSPARENT
    assert style & WS_EX_LAYERED
    # Preserves toolwindow exclusion
    assert style & WS_EX_TOOLWINDOW
    assert not (style & WS_EX_APPWINDOW)

    # Disable click-through
    success = set_click_through(hwnd, False)
    assert success is True
    assert not is_click_through(hwnd)
    style = get_extended_style(hwnd)
    assert not (style & WS_EX_TRANSPARENT)
    assert style & WS_EX_TOOLWINDOW
    assert not (style & WS_EX_APPWINDOW)

    widget.close()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows specific test")
def test_taskbar_exclusion(qapp):
    widget = QWidget()
    widget.show()
    qapp.processEvents()

    hwnd = int(widget.winId())
    assert hwnd != 0

    # Apply taskbar exclusion
    success = exclude_from_taskbar(hwnd)
    assert success is True
    assert is_taskbar_excluded(hwnd)

    style = get_extended_style(hwnd)
    assert bool(style & WS_EX_TOOLWINDOW)
    assert not bool(style & WS_EX_APPWINDOW)

    widget.close()
