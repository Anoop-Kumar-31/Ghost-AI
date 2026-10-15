"""
Windows Win32 native API utilities for managing extended window styles,
enabling mouse click-through behavior, and excluding windows from taskbar / Alt+Tab.
./win32_utils.py
"""

import sys
import ctypes
from ctypes import wintypes
import logging

logger = logging.getLogger(__name__)

WDA_NONE = 0x00
WDA_MONITOR = 0x01             # black rectangle in captures (older Windows)
WDA_EXCLUDEFROMCAPTURE = 0x11  # omitted entirely (Windows 10 build 19041+)

# Win32 Constants
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

if sys.platform == "win32":
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # GetWindowLongPtrW and SetWindowLongPtrW for 64-bit Windows
    if hasattr(user32, "GetWindowLongPtrW"):
        _GetWindowLongPtr = user32.GetWindowLongPtrW
    else:
        _GetWindowLongPtr = user32.GetWindowLongW

    if hasattr(user32, "SetWindowLongPtrW"):
        _SetWindowLongPtr = user32.SetWindowLongPtrW
    else:
        _SetWindowLongPtr = user32.SetWindowLongW

    _GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
    _GetWindowLongPtr.restype = ctypes.c_ssize_t

    _SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _SetWindowLongPtr.restype = ctypes.c_ssize_t

    _SetWindowPos = user32.SetWindowPos
    _SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _SetWindowDisplayAffinity = user32.SetWindowDisplayAffinity
    _SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _SetWindowDisplayAffinity.restype = wintypes.BOOL

    _GetWindowDisplayAffinity = user32.GetWindowDisplayAffinity
    _GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _GetWindowDisplayAffinity.restype = wintypes.BOOL
    _SetWindowPos.restype = wintypes.BOOL
else:
    user32 = None
    kernel32 = None
    _SetWindowDisplayAffinity = None
    _GetWindowDisplayAffinity = None
    _GetWindowLongPtr = None
    _SetWindowLongPtr = None
    _SetWindowPos = None


def get_extended_style(hwnd: int) -> int:
    """Retrieve current GWL_EXSTYLE flags for HWND."""
    if sys.platform != "win32" or not _GetWindowLongPtr:
        return 0
    try:
        kernel32.SetLastError(0)
        style = _GetWindowLongPtr(wintypes.HWND(hwnd), GWL_EXSTYLE)
        err = kernel32.GetLastError()
        if style == 0 and err != 0:
            logger.warning("GetWindowLongPtrW failed with error code %d", err)
        return style
    except Exception as exc:
        logger.error("Exception getting extended window style: %s", exc)
        return 0


def exclude_from_taskbar(hwnd: int) -> bool:
    """
    Ensures WS_EX_TOOLWINDOW is set and WS_EX_APPWINDOW is cleared,
    excluding the window from the Windows taskbar and Alt+Tab switcher.
    Preserves all other extended styles.
    """
    if sys.platform != "win32" or not _SetWindowLongPtr:
        return False
    try:
        hwnd_val = wintypes.HWND(hwnd)
        kernel32.SetLastError(0)
        current_style = _GetWindowLongPtr(hwnd_val, GWL_EXSTYLE)
        err = kernel32.GetLastError()
        if current_style == 0 and err != 0:
            logger.error("Failed to read extended style for HWND %s (err %d)", hwnd, err)
            return False

        new_style = (current_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        if new_style != current_style:
            kernel32.SetLastError(0)
            res = _SetWindowLongPtr(hwnd_val, GWL_EXSTYLE, new_style)
            err = kernel32.GetLastError()
            if res == 0 and err != 0:
                logger.error("SetWindowLongPtrW failed with error code %d", err)
                return False

            _SetWindowPos(
                hwnd_val,
                None,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE,
            )
        return True
    except Exception as exc:
        logger.error("Exception excluding window from taskbar: %s", exc)
        return False


def is_taskbar_excluded(hwnd: int) -> bool:
    """Check if window has WS_EX_TOOLWINDOW and does not have WS_EX_APPWINDOW."""
    if sys.platform != "win32":
        return True
    style = get_extended_style(hwnd)
    return bool((style & WS_EX_TOOLWINDOW) and not (style & WS_EX_APPWINDOW))


def set_click_through(hwnd: int, enable: bool) -> bool:
    """
    Toggles WS_EX_TRANSPARENT on the target HWND while preserving existing styles.
    Ensures WS_EX_LAYERED is present when WS_EX_TRANSPARENT is applied.
    Ensures WS_EX_TOOLWINDOW is preserved and WS_EX_APPWINDOW is excluded.
    Returns True if the operation succeeded, False otherwise.
    """
    if sys.platform != "win32" or not _SetWindowLongPtr:
        logger.info("Non-Windows platform; native click-through skipped.")
        return False

    try:
        hwnd_val = wintypes.HWND(hwnd)
        kernel32.SetLastError(0)
        current_style = _GetWindowLongPtr(hwnd_val, GWL_EXSTYLE)
        err = kernel32.GetLastError()
        if current_style == 0 and err != 0:
            logger.error("Failed to read current extended style for HWND %s (err %d)", hwnd, err)
            return False

        if enable:
            # Add WS_EX_LAYERED, WS_EX_TRANSPARENT, and maintain taskbar exclusion
            new_style = (current_style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        else:
            # Remove only WS_EX_TRANSPARENT; preserve WS_EX_LAYERED, WS_EX_TOOLWINDOW, and avoid WS_EX_APPWINDOW
            new_style = (current_style & ~WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW

        if new_style != current_style:
            kernel32.SetLastError(0)
            res = _SetWindowLongPtr(hwnd_val, GWL_EXSTYLE, new_style)
            err = kernel32.GetLastError()
            if res == 0 and err != 0:
                logger.error("SetWindowLongPtrW failed with error code %d", err)
                return False

            # Refresh frame & styles
            _SetWindowPos(
                hwnd_val,
                None,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE,
            )
        return True
    except Exception as exc:
        logger.error("Exception setting click-through: %s", exc)
        return False


def is_click_through(hwnd: int) -> bool:
    """Check if WS_EX_TRANSPARENT is currently active on HWND."""
    if sys.platform != "win32":
        return False
    style = get_extended_style(hwnd)
    return bool(style & WS_EX_TRANSPARENT)
def set_capture_excluded(hwnd: int, enable: bool = True) -> bool:
    """
    Hide the window from screen capture/sharing (Zoom, Teams, OBS, etc.).
    Falls back to WDA_MONITOR (black box) on Windows builds older than 10 2004.
    """
    if sys.platform != "win32" or not _SetWindowDisplayAffinity:
        return False
    try:
        hwnd_val = wintypes.HWND(hwnd)
        if not enable:
            return bool(_SetWindowDisplayAffinity(hwnd_val, WDA_NONE))
        if _SetWindowDisplayAffinity(hwnd_val, WDA_EXCLUDEFROMCAPTURE):
            return True
        logger.warning("WDA_EXCLUDEFROMCAPTURE unsupported; falling back to WDA_MONITOR")
        return bool(_SetWindowDisplayAffinity(hwnd_val, WDA_MONITOR))
    except Exception as exc:
        logger.error("Exception setting display affinity: %s", exc)
        return False


def is_capture_excluded(hwnd: int) -> bool:
    if sys.platform != "win32" or not _GetWindowDisplayAffinity:
        return False
    out = wintypes.DWORD(0)
    ok = _GetWindowDisplayAffinity(wintypes.HWND(hwnd), ctypes.byref(out))
    return bool(ok) and out.value != WDA_NONE