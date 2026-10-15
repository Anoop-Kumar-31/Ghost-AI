"""
Unified cross-platform dispatch utility.
Routes native OS window manipulation to macOS Cocoa or Windows Win32.
"""

import sys

if sys.platform == "darwin":
    from .macos_utils import (
        set_click_through,
        exclude_from_taskbar,
        set_capture_excluded,
        is_click_through,
        is_capture_excluded,
        is_taskbar_excluded,
    )
elif sys.platform == "win32":
    from .win32_utils import (
        set_click_through,
        exclude_from_taskbar,
        set_capture_excluded,
        is_click_through,
        is_capture_excluded,
        is_taskbar_excluded,
    )
else:
    # Generic Unix / Linux fallback
    def set_click_through(hwnd: int, enable: bool) -> bool:
        return False

    def exclude_from_taskbar(hwnd: int) -> bool:
        return True

    def set_capture_excluded(hwnd: int, enable: bool = True) -> bool:
        return False

    def is_click_through(hwnd: int) -> bool:
        return False

    def is_capture_excluded(hwnd: int) -> bool:
        return False

    def is_taskbar_excluded(hwnd: int) -> bool:
        return True
