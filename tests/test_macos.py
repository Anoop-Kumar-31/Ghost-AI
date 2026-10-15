"""
Tests for macOS native Cocoa utility contracts and platform dispatching in Ghost AI.
"""

import sys
import pytest
from ghost_ai import macos_utils, platform_utils


def test_macos_constants():
    assert macos_utils.NSWindowSharingNone == 0
    assert macos_utils.NSWindowSharingReadOnly == 1
    assert macos_utils.NSApplicationActivationPolicyRegular == 0
    assert macos_utils.NSApplicationActivationPolicyAccessory == 1


def test_macos_safe_fallbacks_on_non_darwin():
    """Verify that macos_utils functions do not crash and return safe values when invoked."""
    if sys.platform != "darwin":
        # On non-Darwin (Windows/Linux), functions should fail gracefully without unhandled exceptions
        assert macos_utils.set_click_through(0, True) is False
        assert macos_utils.set_capture_excluded(0, True) is False
        assert macos_utils.exclude_from_taskbar(0) is False
        assert macos_utils.is_click_through(0) is False


def test_platform_utils_dispatch():
    """Verify platform_utils exports all expected function signatures."""
    expected_funcs = [
        "set_click_through",
        "exclude_from_taskbar",
        "set_capture_excluded",
        "is_click_through",
        "is_capture_excluded",
        "is_taskbar_excluded",
    ]
    for fn_name in expected_funcs:
        assert hasattr(platform_utils, fn_name)
        assert callable(getattr(platform_utils, fn_name))
