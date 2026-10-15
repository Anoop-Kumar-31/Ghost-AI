"""
macOS native Cocoa utilities for managing window behavior,
enabling mouse click-through (setIgnoresMouseEvents),
excluding from screen share/screenshots (setSharingType),
and excluding from the Dock / Cmd+Tab (setActivationPolicy).
Uses standard ctypes to call the macOS Objective-C runtime with zero extra dependencies.
"""

import sys
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Cocoa Constants
NSWindowSharingNone = 0        # Window is not readable by other apps/screen sharing
NSWindowSharingReadOnly = 1    # Default: Window is captured normally

NSApplicationActivationPolicyRegular = 0    # App appears in Dock and Cmd+Tab
NSApplicationActivationPolicyAccessory = 1  # App does not appear in Dock or Cmd+Tab
NSApplicationActivationPolicyProhibited = 2

_objc = None
_msg_send = None
_sel_register = None
_get_class = None

if sys.platform == "darwin":
    try:
        import ctypes
        import ctypes.util

        objc_path = ctypes.util.find_library("objc")
        appkit_path = ctypes.util.find_library("AppKit")

        if objc_path and appkit_path:
            _objc = ctypes.cdll.LoadLibrary(objc_path)
            ctypes.cdll.LoadLibrary(appkit_path)

            _sel_register = _objc.sel_registerName
            _sel_register.argtypes = [ctypes.c_char_p]
            _sel_register.restype = ctypes.c_void_p

            _get_class = _objc.objc_getClass
            _get_class.argtypes = [ctypes.c_char_p]
            _get_class.restype = ctypes.c_void_p

            _msg_send = _objc.objc_msgSend
    except Exception as exc:
        logger.error("Failed to initialize macOS Objective-C bridge: %s", exc)


def _sel(name: str):
    if not _sel_register:
        return None
    return _sel_register(name.encode("utf-8"))


def _get_nswindow(win_id: int):
    """
    Given a Qt winId (which is an NSView* on macOS),
    traverse to the parent NSWindow*.
    """
    if sys.platform != "darwin" or not _msg_send or not win_id:
        return None

    try:
        import ctypes

        view = ctypes.c_void_p(win_id)

        # Check if view responds to -[NSView window]
        responds_to_sel = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(_msg_send)
        if responds_to_sel(view, _sel("respondsToSelector:"), _sel("window")):
            msg_get_win = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(_msg_send)
            win = msg_get_win(view, _sel("window"))
            if win:
                return ctypes.c_void_p(win)

        # Otherwise view might already be an NSWindow
        return view
    except Exception as exc:
        logger.error("Error retrieving NSWindow from winId %s: %s", win_id, exc)
        return None


def set_click_through(hwnd: int, enable: bool) -> bool:
    """
    macOS equivalent of Windows WS_EX_TRANSPARENT.
    Calls -[NSWindow setIgnoresMouseEvents:(BOOL)].
    """
    if sys.platform != "darwin" or not _msg_send:
        return False

    try:
        import ctypes

        nswindow = _get_nswindow(hwnd)
        if not nswindow:
            return False

        set_ignores = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool)(_msg_send)
        set_ignores(nswindow, _sel("setIgnoresMouseEvents:"), enable)
        return True
    except Exception as exc:
        logger.error("Exception setting click-through on macOS: %s", exc)
        return False


def is_click_through(hwnd: int) -> bool:
    """Check if NSWindow is currently ignoring mouse events."""
    if sys.platform != "darwin" or not _msg_send:
        return False

    try:
        import ctypes

        nswindow = _get_nswindow(hwnd)
        if not nswindow:
            return False

        get_ignores = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(_msg_send)
        return bool(get_ignores(nswindow, _sel("ignoresMouseEvents")))
    except Exception:
        return False


def set_capture_excluded(hwnd: int, enable: bool = True) -> bool:
    """
    macOS equivalent of Windows WDA_EXCLUDEFROMCAPTURE.
    Calls -[NSWindow setSharingType:(NSWindowSharingType)].
    NSWindowSharingNone (0) makes the window invisible to screenshots, Zoom, Teams, Discord, and OBS.
    """
    if sys.platform != "darwin" or not _msg_send:
        return False

    try:
        import ctypes

        nswindow = _get_nswindow(hwnd)
        if not nswindow:
            return False

        sharing_type = NSWindowSharingNone if enable else NSWindowSharingReadOnly
        set_sharing = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)(_msg_send)
        set_sharing(nswindow, _sel("setSharingType:"), sharing_type)
        return True
    except Exception as exc:
        logger.error("Exception setting sharing type on macOS: %s", exc)
        return False


def is_capture_excluded(hwnd: int) -> bool:
    """Check if NSWindow is currently excluded from screen sharing."""
    if sys.platform != "darwin" or not _msg_send:
        return False

    try:
        import ctypes

        nswindow = _get_nswindow(hwnd)
        if not nswindow:
            return False

        get_sharing = ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)(_msg_send)
        return get_sharing(nswindow, _sel("sharingType")) == NSWindowSharingNone
    except Exception:
        return False


def exclude_from_taskbar(hwnd: int) -> bool:
    """
    macOS equivalent of Windows WS_EX_TOOLWINDOW.
    Sets NSApp activation policy to NSApplicationActivationPolicyAccessory (1),
    excluding the app from the macOS Dock and Cmd+Tab app switcher.
    """
    if sys.platform != "darwin" or not _msg_send or not _get_class:
        return False

    try:
        import ctypes

        ns_app_cls = _get_class(b"NSApplication")
        if not ns_app_cls:
            return False

        get_shared_app = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(_msg_send)
        ns_app = get_shared_app(ctypes.c_void_p(ns_app_cls), _sel("sharedApplication"))
        if not ns_app:
            return False

        set_policy = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long)(_msg_send)
        set_policy(ctypes.c_void_p(ns_app), _sel("setActivationPolicy:"), NSApplicationActivationPolicyAccessory)
        return True
    except Exception as exc:
        logger.error("Exception excluding from Dock on macOS: %s", exc)
        return False


def is_taskbar_excluded(hwnd: int) -> bool:
    """Check if app activation policy is NSApplicationActivationPolicyAccessory on macOS."""
    if sys.platform != "darwin" or not _msg_send or not _get_class:
        return True

    try:
        import ctypes

        ns_app_cls = _get_class(b"NSApplication")
        if not ns_app_cls:
            return True

        get_shared_app = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(_msg_send)
        ns_app = get_shared_app(ctypes.c_void_p(ns_app_cls), _sel("sharedApplication"))
        if not ns_app:
            return True

        get_policy = ctypes.CFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(_msg_send)
        return get_policy(ctypes.c_void_p(ns_app), _sel("activationPolicy")) == NSApplicationActivationPolicyAccessory
    except Exception:
        return True
