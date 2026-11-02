"""
Centralized Lucide icon manager for Ghost AI.

Provides consistent SVG icon loading, recoloring, caching, and
high-DPI rendering for all application widgets.
"""

from __future__ import annotations
from pathlib import Path
from functools import lru_cache
from typing import Optional

from PySide6.QtCore import Qt, QByteArray, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QPushButton, QWidget

# ── Color tokens ──────────────────────────────────────────────────────────────
COLOR_DEFAULT  = "#9292A2"
COLOR_HOVER    = "#E5D9FF"
COLOR_ACTIVE   = "#B99AFF"
COLOR_DISABLED = "#555563"

# ── Icon asset root ───────────────────────────────────────────────────────────
_ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons"


def _svg_with_color(name: str, color: str) -> Optional[bytes]:
    """Return SVG bytes for *name* with stroke recolored to *color*."""
    path = _ICONS_DIR / f"{name}.svg"
    if not path.is_file():
        return None
    raw = path.read_text(encoding="utf-8")
    # Replace currentColor tokens so Qt renders in the requested color
    raw = raw.replace('stroke="currentColor"', f'stroke="{color}"')
    raw = raw.replace('fill="currentColor"',   f'fill="{color}"')
    return raw.encode("utf-8")


@lru_cache(maxsize=256)
def _render_pixmap(name: str, size: int, color: str) -> QPixmap:
    """Render *name* at *size*×*size* px with *color* and return a QPixmap."""
    svg_bytes = _svg_with_color(name, color)
    if svg_bytes is None:
        return QPixmap()
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return pixmap


def get_pixmap(name: str, size: int = 18, color: str = COLOR_DEFAULT) -> QPixmap:
    """Return a QPixmap for the named Lucide icon."""
    return _render_pixmap(name, size, color)


def get_icon(name: str, size: int = 18, color: str = COLOR_DEFAULT) -> QIcon:
    """Return a QIcon for the named Lucide icon."""
    return QIcon(get_pixmap(name, size, color))


class IconButton(QPushButton):
    """
    A QPushButton that renders a Lucide SVG icon.

    Preserves ArrowCursor and updates icon color on hover / press.
    Pass *checkable=True* to get toggle behaviour with the active color.
    """

    def __init__(
        self,
        icon_name: str,
        size: int = 18,
        btn_size: int = 28,
        color_default: str = COLOR_DEFAULT,
        color_hover: str = COLOR_HOVER,
        color_active: str = COLOR_ACTIVE,
        tooltip: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._icon_name     = icon_name
        self._icon_size     = size
        self._c_default     = color_default
        self._c_hover       = color_hover
        self._c_active      = color_active
        self._hovered       = False
        self._is_active     = False

        self.setFixedSize(btn_size, btn_size)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setIconSize(QSize(size, size))
        self.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 6px;
                padding: 0;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.07);
            }
            QPushButton:pressed {
                background: rgba(139, 92, 246, 0.15);
            }
            """
        )
        if tooltip:
            self.setToolTip(tooltip)
        self._refresh_icon(self._c_default)

    def _refresh_icon(self, color: str) -> None:
        self.setIcon(get_icon(self._icon_name, self._icon_size, color))

    def enterEvent(self, event) -> None:
        self._hovered = True
        if not self._is_active and not self.isChecked():
            self._refresh_icon(self._c_hover)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        if not self._is_active and not self.isChecked():
            self._refresh_icon(self._c_default)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        self._refresh_icon(self._c_active)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        color = self._c_active if (self._is_active or self.isChecked()) else (
            self._c_hover if self._hovered else self._c_default
        )
        self._refresh_icon(color)
        super().mouseReleaseEvent(event)

    def set_active_color(self, active: bool) -> None:
        """Manually force active or default color (used for stateful buttons)."""
        self._is_active = active
        self._refresh_icon(self._c_active if active else self._c_default)

    def set_icon_name(self, icon_name: str) -> None:
        """Change the rendered icon."""
        self._icon_name = icon_name
        color = self._c_active if (self._is_active or self.isChecked()) else (
            self._c_hover if self._hovered else self._c_default
        )
        self._refresh_icon(color)
