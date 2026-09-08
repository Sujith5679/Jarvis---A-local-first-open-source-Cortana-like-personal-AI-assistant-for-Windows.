"""JARVIS's app icon/logo — a small glowing "AI core" orb (radial cyan-to-
indigo gradient core, thin gapped ring around it, a soft specular highlight
for a glassy feel). Same accent family as ui/theme.py's cyan/teal palette,
so the mark and the UI chrome read as one identity rather than a logo
bolted onto unrelated colors.

Drawn entirely with QPainter rather than shipping a raster/SVG asset -
no image-generation tooling is available to this codebase, and a
procedural icon stays crisp at every size Windows asks for (taskbar, tray,
alt-tab, jump list) without needing a rasterizer dependency. This replaces
the placeholder "J in a solid circle" monogram that ui/tray.py and
app/supervisor.py each drew separately (now both just call build_icon()
here instead of duplicating it).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QRadialGradient

# Same family as ui/theme.py's accent tokens - kept as its own literals
# (not imported from Theme) since the icon is theme-independent brand
# identity, not something that should shift with a light/dark toggle.
_RING_OUTER = QColor("#22D3EE")  # bright cyan
_RING_INNER = QColor("#1D4ED8")  # deep indigo-blue
_CORE_BRIGHT = QColor("#99F6E4")  # near-white cyan glow center
_CORE_MID = QColor("#14B8C4")  # teal-cyan
_CORE_DEEP = QColor("#1E3A8A")  # deep indigo edge

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _paint_icon(painter: QPainter, size: int) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    center = QPointF(size / 2, size / 2)

    # Outer ring: a gapped arc (not a full circle) - a small nod to a
    # radar/orbit sweep, enough to feel alive without being a literal
    # copy of any existing assistant's ring mark.
    ring_pen_width = max(1.0, size * 0.06)
    ring_radius = size / 2 - ring_pen_width
    ring_gradient = QRadialGradient(center, ring_radius)
    ring_gradient.setColorAt(0.0, _RING_OUTER)
    ring_gradient.setColorAt(1.0, _RING_INNER)
    pen = painter.pen()
    pen.setWidthF(ring_pen_width)
    pen.setColor(_RING_OUTER)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    ring_rect = QRectF(
        center.x() - ring_radius, center.y() - ring_radius, ring_radius * 2, ring_radius * 2
    )
    # Qt angles are in 1/16ths of a degree, counterclockwise from 3 o'clock.
    painter.drawArc(ring_rect, 40 * 16, 280 * 16)

    # Core: a glowing filled orb, offset slightly up-left so the glow reads
    # as light coming from one direction rather than a flat disc.
    core_radius = size * 0.32
    core_center = QPointF(center.x() - size * 0.03, center.y() - size * 0.03)
    core_gradient = QRadialGradient(core_center, core_radius * 1.15)
    core_gradient.setColorAt(0.0, _CORE_BRIGHT)
    core_gradient.setColorAt(0.55, _CORE_MID)
    core_gradient.setColorAt(1.0, _CORE_DEEP)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(core_gradient)
    painter.drawEllipse(core_center, core_radius, core_radius)

    # Specular highlight: small soft white ellipse, upper-left of the core.
    highlight = QColor(255, 255, 255, 110)
    painter.setBrush(highlight)
    highlight_radius = core_radius * 0.32
    highlight_center = QPointF(
        core_center.x() - core_radius * 0.35, core_center.y() - core_radius * 0.4
    )
    painter.drawEllipse(highlight_center, highlight_radius, highlight_radius)


def build_icon_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    _paint_icon(painter, size)
    painter.end()
    return pixmap


def build_icon() -> QIcon:
    """Multi-resolution app icon - each size is painted directly rather
    than scaled from one master pixmap, so thin strokes stay crisp instead
    of blurring when Windows picks a small size (tray) vs. a large one
    (alt-tab/jump list)."""
    icon = QIcon()
    for size in _ICON_SIZES:
        icon.addPixmap(build_icon_pixmap(size))
    return icon
