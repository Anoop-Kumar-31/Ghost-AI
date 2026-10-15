"""
Controls window for Ghost Notes.
Houses the independent Blue (Ghost Mode toggle) and Red (Close) controls.
Runs in its own top-level window so it remains clickable when notes are click-through.
./controls.py
"""

from typing import Optional
from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import QWidget, QHBoxLayout, QAbstractButton
from .platform_utils import exclude_from_taskbar, set_capture_excluded


class DotButton(QAbstractButton):
    """
    A clickable control with an ~18x18 logical pixel hit target
    and an exactly 5x5 logical pixel centered colored dot.
    Strictly uses Qt.CursorShape.ArrowCursor.
    """

    def __init__(
        self,
        normal_color: str,
        hover_color: Optional[str] = None,
        active_color: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._normal_color = QColor(normal_color)
        self._hover_color = QColor(hover_color or normal_color)
        self._active_color = QColor(active_color or normal_color)
        self._is_hovered = False
        self._is_active_state = False

        self.setFixedSize(18, 18)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Requirement 13: Standard arrow pointer at all times. Never use PointingHandCursor.
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def sizeHint(self) -> QSize:
        return QSize(18, 18)

    def set_active_state(self, active: bool) -> None:
        """Update toggle state (e.g. for blue ghost mode indicator)."""
        self._is_active_state = active
        self.update()

    def enterEvent(self, event) -> None:
        self._is_hovered = True
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._is_hovered = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Subtle hover highlight on the hit target
        if self._is_hovered:
            painter.setBrush(QBrush(QColor(255, 255, 255, 24)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(1, 1, 16, 16), 3, 3)

        # Exact 5x5 logical pixel dot centered inside the 18x18 target
        dot_size = 5.0
        cx = (self.width() - dot_size) / 2.0
        cy = (self.height() - dot_size) / 2.0

        if self._is_active_state:
            color = self._active_color
        elif self._is_hovered:
            color = self._hover_color
        else:
            color = self._normal_color

        painter.setBrush(QBrush(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(cx, cy, dot_size, dot_size))


class ControlsWindow(QWidget):
    """
    Dedicated frameless, transparent, always-on-top window holding the blue and red controls.
    Maintains a distinct native HWND so it remains clickable even when the notes window
    is in click-through Ghost Mode.
    """

    toggle_ghost_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # Make this a separate top-level window so it gets its own native HWND
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Requirement 13: strictly standard arrow cursor
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # Blue dot: 5x5 px centered in 18x18 hit target
        # Blue first
        self.blue_btn = DotButton(
            normal_color="#3b82f6",
            hover_color="#60a5fa",
            active_color="#38bdf8",
            parent=self,
        )
        # self.blue_btn.setToolTip("Toggle Ghost Mode")
        self.blue_btn.clicked.connect(self.toggle_ghost_requested.emit)

        # Red dot: 5x5 px centered in 18x18 hit target
        # Red immediately beside it
        self.red_btn = DotButton(
            normal_color="#ef4444",
            hover_color="#f87171",
            active_color="#ef4444",
            parent=self,
        )
        # self.red_btn.setToolTip("Close Ghost Notes")
        self.red_btn.clicked.connect(self.close_requested.emit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.blue_btn)
        layout.addWidget(self.red_btn)

        # 18 + 2 + 18 = 38 px width, 18 px height
        self.setFixedSize(38, 18)

    def set_ghost_state(self, active: bool) -> None:
        """Reflect ghost mode state on the blue button."""
        self.blue_btn.set_active_state(active)

    def set_ghost_active(self, active: bool) -> None:
        """Alias for set_ghost_state."""
        self.set_ghost_state(active)

    def sync_position(self, parent_geo) -> None:
        """Synchronize controls position to top-right of parent window."""
        ctrl_w = self.width()
        pos_x = parent_geo.x() + parent_geo.width() - ctrl_w - 10
        pos_y = parent_geo.y() + 8
        self.move(pos_x, pos_y)
        if not self.isVisible():
            self.show()
        self.raise_()

    def show_controls(self, parent_geo) -> None:
        """Show and position controls window."""
        self.show()
        self.sync_position(parent_geo)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        hwnd = int(self.winId())
        exclude_from_taskbar(hwnd)
        set_capture_excluded(hwnd)

    def enterEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().enterEvent(event)
