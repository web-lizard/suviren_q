#!/usr/bin/env python3
"""
Book Wunderwaffe Studio 1.0
La machine merveilleuse pour forger les livres

Native PySide6 desktop GUI for visual canvas composition.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import (
    Qt, QRectF, QPointF, QSizeF, Signal, Slot, QProcess, QTimer,
    QUrl, QPropertyAnimation, QEasingCurve
)
from PySide6.QtGui import (
    QAction, QBrush, QColor, QFont, QIcon, QPainter, QPen,
    QPixmap, QTransform, QWheelEvent, QMouseEvent, QShortcut,
    QKeySequence, QFontDatabase, QLinearGradient
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGraphicsItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem,
    QGraphicsView, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSlider, QSpinBox, QSplitter, QTextEdit,
    QVBoxLayout, QWidget, QDockWidget, QFrame, QListWidget,
    QListWidgetItem, QProgressBar, QDialog, QLineEdit,
    QSizePolicy, QToolButton, QButtonGroup, QRadioButton,
    QGraphicsSimpleTextItem, QStatusBar, QToolTip,
    QAbstractItemView
)
try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_MULTIMEDIA = True
except ImportError:
    HAS_MULTIMEDIA = False

# --- Constants ---
PROJECT_ROOT = Path(__file__).parent.resolve()
BUILD_DIR = PROJECT_ROOT / "_suviren_q_build"
DATA_DIR = PROJECT_ROOT / "data"
LAYOUT_PATH = BUILD_DIR / "layout.json"
CHAPTERS_PATH = BUILD_DIR / "chapters.detected.json"
WAVEFORM_PATH = BUILD_DIR / "waveform.json"
WAVEFORM_LOCK = BUILD_DIR / "waveform.lock"
PROJECT_CONFIG = PROJECT_ROOT / "bookforge.project.json"

CANVAS_W = 1920
CANVAS_H = 1080
SCENE_W = 1920.0
SCENE_H = 1080.0

# --- Dark theme palette ---
DARK_BG = "#070710"
DARK_PANEL = "#0b0b16"
DARK_CARD = "#12122a"
ACCENT_CYAN = "#00e5ff"
ACCENT_GREEN = "#00ff88"
ACCENT_VIOLET = "#7c3aed"
TEXT_PRIMARY = "#e0e0e0"
TEXT_SECONDARY = "#9090b0"
BORDER_COLOR = "#2a2a4a"

# --- Object types ---
OBJ_BACKGROUND = "background"
OBJ_COVER = "cover"
OBJ_BOOK_TITLE = "bookTitle"
OBJ_CURRENT_CHAPTER = "currentChapter"
OBJ_CHAPTER_STACK = "chapterStack"
OBJ_WAVEFORM = "waveform"
OBJ_PROGRESS = "progress"
OBJ_BRAND = "brand"

# --- Default layout (Phase 9: improved clean layout) ---
DEFAULT_LAYOUT = {
    "background": {
        "id": "background", "type": "image", "x": 0, "y": 0,
        "w": 1920, "h": 1080, "visible": True, "opacity": 1.0,
        "source": "background.png", "z": 0
    },
    "cover": {
        "id": "cover", "type": "image", "x": 110, "y": 150,
        "w": 470, "h": 665, "visible": True, "opacity": 0.92,
        "source": "zina-cover.png", "z": 10
    },
    "bookTitle": {
        "id": "bookTitle", "type": "text", "x": 650, "y": 180,
        "w": 1100, "h": 90, "visible": True, "opacity": 1.0,
        "font_size": 56, "color": "#ffffff",
        "font_family": "Georgia", "bold": True, "italic": False, "align": "left",
        "text": "Интимный протокол", "z": 20
    },
    "currentChapter": {
        "id": "currentChapter", "type": "text", "x": 650, "y": 310,
        "w": 1100, "h": 160, "visible": True, "opacity": 1.0,
        "font_size": 46, "color": "#00ff88",
        "font_family": "Segoe UI", "bold": False, "italic": False, "align": "left",
        "text_source": "auto",
        "text": "Вступление от автора", "z": 21
    },
    "chapterStack": {
        "id": "chapterStack", "type": "chapter_stack", "x": 650, "y": 480,
        "w": 1100, "h": 120, "visible": True, "opacity": 1.0,
        "font_size_prev": 20, "font_size_current": 30, "font_size_next": 20,
        "color_prev": "#9090b0", "color_current": "#00ff88", "color_next": "#9090b0",
        "font_family": "Segoe UI",
        "z": 22
    },
    "waveform": {
        "id": "waveform", "type": "waveform", "x": 650, "y": 550,
        "w": 1100, "h": 170, "visible": True, "opacity": 0.7,
        "color": "#00e5ff", "played_color": "#72ffd9", "bg_color": "#1a1a3a",
        "bars": 120, "style": "bars",
        "z": 30
    },
    "progress": {
        "id": "progress", "type": "progress", "x": 110, "y": 930,
        "w": 1700, "h": 18, "visible": True, "opacity": 0.8,
        "color": "#00ff88", "bg_color": "#1a1a3a",
        "z": 31
    },
    "brand": {
        "id": "brand", "type": "text", "x": 1600, "y": 1000,
        "w": 280, "h": 40, "visible": False, "opacity": 0.5,
        "font_size": 16, "color": "#9090b0",
        "font_family": "Segoe UI", "bold": False, "italic": False, "align": "right",
        "text": "Book Wunderwaffe Studio 1.0",
        "z": 100
    }
}

# --- Audio priority list ---
AUDIO_PRIORITY_KEYWORDS = [
    "final last",
    "final",
    "master",
    "full",
    "complete",
    "version",
]


# =========================================================
#  Utility functions
# =========================================================

def load_json(path):
    """Load JSON if exists, else None."""
    p = Path(path)
    if p.exists():
        try:
            return json.loads(p.read_text("utf-8"))
        except Exception:
            return None
    return None


def save_json(path, data):
    """Save JSON with indentation."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def seconds_to_timestr(s):
    """Convert float seconds to HH:MM:SS.mmm"""
    if s < 0:
        s = 0
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}"


def timestr_to_seconds(ts):
    """HH:MM:SS.mmm or HH:MM:SS -> float seconds"""
    parts = ts.replace(",", ".").split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def get_windows_fonts():
    """Return list of common/available font families."""
    db = QFontDatabase
    families = db.families(QFontDatabase.WritingSystem.Latin)
    # Prioritize common fonts
    priority = ["Segoe UI", "Arial", "Arial Narrow", "Georgia",
                 "Times New Roman", "Impact", "Consolas", "Courier New",
                 "Verdana", "Tahoma", "Trebuchet MS", "Comic Sans MS"]
    result = []
    for p in priority:
        if p in families:
            result.append(p)
    for f in families:
        if f not in result and not f.startswith("@") and not f.startswith("."):
            result.append(f)
    return result


# =========================================================
#  Canvas Items
# =========================================================

class MovableTextItem(QGraphicsTextItem):
    """Text item that can be moved on canvas."""
    def __init__(self, obj_id, obj_data, parent=None):
        super().__init__(parent)
        self.obj_id = obj_id
        self.obj_data = obj_data
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setDefaultTextColor(QColor(obj_data.get("color", "#ffffff")))
        self.setPlainText(obj_data.get("text", ""))
        self._update_font(obj_data)
        self.setOpacity(obj_data.get("opacity", 1.0))
        self.setPos(obj_data.get("x", 0), obj_data.get("y", 0))
        self.setVisible(obj_data.get("visible", True))
        self.setZValue(obj_data.get("z", 10))

    def _update_font(self, d):
        family = d.get("font_family", "Segoe UI")
        size = d.get("font_size", 24)
        bold = d.get("bold", True)
        italic = d.get("italic", False)
        f = QFont(family, size)
        f.setBold(bold)
        f.setItalic(italic)
        self.setFont(f)

    def update_from_data(self, d):
        self.obj_data = d
        self.setDefaultTextColor(QColor(d.get("color", "#ffffff")))
        self.setPlainText(d.get("text", ""))
        self._update_font(d)
        self.setOpacity(d.get("opacity", 1.0))
        self.setPos(d.get("x", 0), d.get("y", 0))
        self.setVisible(d.get("visible", True))

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.obj_data["x"] = round(value.x(), 1)
            self.obj_data["y"] = round(value.y(), 1)
        return super().itemChange(change, value)


class MovablePixmapItem(QGraphicsPixmapItem):
    """Pixmap item that can be moved on canvas."""
    def __init__(self, obj_id, obj_data, parent=None):
        super().__init__(parent)
        self.obj_id = obj_id
        self.obj_data = obj_data
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setOpacity(obj_data.get("opacity", 1.0))
        self.setPos(obj_data.get("x", 0), obj_data.get("y", 0))
        self.setVisible(obj_data.get("visible", True))
        self.setZValue(obj_data.get("z", 0))
        self._scale_pixmap()

    def _scale_pixmap(self):
        px = self.pixmap()
        if px.isNull():
            return
        tw = self.obj_data.get("w", px.width())
        th = self.obj_data.get("h", px.height())
        scaled = px.scaled(int(tw), int(th), Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)

    def set_pixmap(self, pixmap):
        super().setPixmap(pixmap)
        self._scale_pixmap()

    def update_from_data(self, d):
        self.obj_data = d
        self.setOpacity(d.get("opacity", 1.0))
        self.setPos(d.get("x", 0), d.get("y", 0))
        self.setVisible(d.get("visible", True))
        self._scale_pixmap()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.obj_data["x"] = round(value.x(), 1)
            self.obj_data["y"] = round(value.y(), 1)
        return super().itemChange(change, value)


class WaveformItem(QGraphicsItem):
    """Custom waveform visualization with played highlight."""
    def __init__(self, obj_id, obj_data, parent=None):
        super().__init__(parent)
        self.obj_id = obj_id
        self.obj_data = obj_data
        self.wave_data = []
        self._current_time = 0.0
        self._total_duration = 0.0
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setPos(obj_data.get("x", 0), obj_data.get("y", 0))
        self.setVisible(obj_data.get("visible", True))
        self.setZValue(obj_data.get("z", 30))

    def boundingRect(self):
        return QRectF(0, 0, self.obj_data.get("w", 1100), self.obj_data.get("h", 120))

    def paint(self, painter, option, widget=None):
        r = self.boundingRect()
        bg = QColor(self.obj_data.get("bg_color", "#1a1a3a"))
        fg = QColor(self.obj_data.get("color", "#00e5ff"))
        played = QColor(self.obj_data.get("played_color", "#72ffd9"))
        bars = self.obj_data.get("bars", 120)

        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(r, 6, 6)

        if self.wave_data and len(self.wave_data) > 10:
            n = len(self.wave_data)
            w = r.width()
            h = r.height()
            mid = h / 2
            bar_w = w / bars if bars > 0 else w / n
            samples_per_bar = max(1, n // bars)

            # Determine played sample index
            played_idx = n
            if self._total_duration > 0:
                played_idx = int((self._current_time / self._total_duration) * n)
                played_idx = min(played_idx, n)

            for b in range(bars):
                start_s = b * samples_per_bar
                end_s = min(start_s + samples_per_bar, n)
                if start_s >= n:
                    break
                avg = sum(abs(self.wave_data[s]) for s in range(start_s, end_s)) / samples_per_bar
                amp = avg * mid * 0.9
                x = b * bar_w + 1
                bw = max(bar_w - 2, 1)

                is_played = (end_s <= played_idx)
                if not is_played and start_s < played_idx < end_s:
                    partial_ratio = (played_idx - start_s) / samples_per_bar
                    painter.setBrush(played)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRect(x, mid - amp * partial_ratio, bw, amp * 2 * partial_ratio)
                    painter.setBrush(fg)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRect(x, mid - amp + amp * partial_ratio, bw, amp * 2 * (1 - partial_ratio))
                    continue

                painter.setBrush(played if is_played else fg)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(x, mid - amp, bw, amp * 2)
        else:
            painter.setPen(QPen(QColor(TEXT_SECONDARY), 1))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter,
                             "Сгенерируйте гистограмму (кнопка выше)")

    def set_waveform(self, data):
        self.wave_data = data
        self.update()

    def set_playback_time(self, current, total):
        self._current_time = current
        self._total_duration = total
        self.update()

    def update_from_data(self, d):
        self.obj_data = d
        self.setPos(d.get("x", 0), d.get("y", 0))
        self.setVisible(d.get("visible", True))
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.obj_data["x"] = round(value.x(), 1)
            self.obj_data["y"] = round(value.y(), 1)
        return super().itemChange(change, value)


class ProgressItem(QGraphicsRectItem):
    """Progress bar item with fill."""
    def __init__(self, obj_id, obj_data, parent=None):
        w = obj_data.get("w", 1100)
        h = obj_data.get("h", 8)
        super().__init__(0, 0, w, h, parent)
        self.obj_id = obj_id
        self.obj_data = obj_data
        self.progress = 0.0
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setPos(obj_data.get("x", 0), obj_data.get("y", 0))
        self.setVisible(obj_data.get("visible", True))
        self.setZValue(obj_data.get("z", 31))
        self.setBrush(QColor(obj_data.get("bg_color", "#1a1a3a")))
        self.setPen(Qt.PenStyle.NoPen)

    def paint(self, painter, option, widget=None):
        super().paint(painter, option, widget)
        r = self.rect()
        painter.setBrush(QColor(self.obj_data.get("bg_color", "#1a1a3a")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        bw = r.width() * self.progress
        if bw > 0:
            painter.setBrush(QColor(self.obj_data.get("color", "#00ff88")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(0, 0, bw, r.height(), r.height() / 2, r.height() / 2)

    def set_progress(self, p):
        self.progress = max(0.0, min(1.0, p))
        self.update()

    def update_from_data(self, d):
        self.obj_data = d
        self.setPos(d.get("x", 0), d.get("y", 0))
        self.setVisible(d.get("visible", True))
        w = d.get("w", 1100)
        self.setRect(0, 0, w, d.get("h", 8))
        self.setBrush(QColor(d.get("bg_color", "#1a1a3a")))
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.obj_data["x"] = round(value.x(), 1)
            self.obj_data["y"] = round(value.y(), 1)
        return super().itemChange(change, value)


class ChapterStackItem(QGraphicsItem):
    """Item showing prev/current/next chapters."""
    def __init__(self, obj_id, obj_data, parent=None):
        super().__init__(parent)
        self.obj_id = obj_id
        self.obj_data = obj_data
        self._prev_text = ""
        self._current_text = ""
        self._next_text = ""
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setPos(obj_data.get("x", 0), obj_data.get("y", 0))
        self.setVisible(obj_data.get("visible", True))
        self.setZValue(obj_data.get("z", 22))

    def boundingRect(self):
        return QRectF(0, 0, self.obj_data.get("w", 1100), self.obj_data.get("h", 120))

    def paint(self, painter, option, widget=None):
        r = self.boundingRect()
        d = self.obj_data
        family = d.get("font_family", "Segoe UI")
        color_prev = QColor(d.get("color_prev", "#9090b0"))
        color_cur = QColor(d.get("color_current", "#00ff88"))
        color_next = QColor(d.get("color_next", "#9090b0"))
        fs_prev = d.get("font_size_prev", 20)
        fs_cur = d.get("font_size_current", 30)
        fs_next = d.get("font_size_next", 20)

        # Previous chapter (top, smaller, dim)
        if self._prev_text:
            f_prev = QFont(family, fs_prev)
            f_prev.setBold(False)
            painter.setFont(f_prev)
            painter.setPen(QPen(color_prev))
            painter.setOpacity(0.55)
            painter.drawText(QRectF(0, 0, r.width(), fs_prev + 6),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             self._prev_text)
            painter.setOpacity(1.0)

        # Current chapter (middle, larger, bright)
        f_cur = QFont(family, fs_cur)
        f_cur.setBold(True)
        painter.setFont(f_cur)
        painter.setPen(QPen(color_cur))
        y_cur = fs_prev + 10 if self._prev_text else 0
        painter.drawText(QRectF(0, y_cur, r.width(), fs_cur + 8),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self._current_text)

        # Next chapter (bottom, smaller, dim)
        if self._next_text:
            f_next = QFont(family, fs_next)
            f_next.setBold(False)
            painter.setFont(f_next)
            painter.setPen(QPen(color_next))
            y_next = y_cur + fs_cur + 10
            painter.setOpacity(0.55)
            painter.drawText(QRectF(0, y_next, r.width(), fs_next + 6),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             self._next_text)
            painter.setOpacity(1.0)

    def set_chapters(self, prev, current, nxt):
        self._prev_text = prev or ""
        self._current_text = current or ""
        self._next_text = nxt or ""
        self.update()

    def update_from_data(self, d):
        self.obj_data = d
        self.setPos(d.get("x", 0), d.get("y", 0))
        self.setVisible(d.get("visible", True))
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.obj_data["x"] = round(value.x(), 1)
            self.obj_data["y"] = round(value.y(), 1)
        return super().itemChange(change, value)


# =========================================================
#  Zoomable QGraphicsView
# =========================================================

class ZoomableView(QGraphicsView):
    """QGraphicsView with zoom/pan support."""
    zoomChanged = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._zoom = 1.0
        self._min_zoom = 0.1
        self._max_zoom = 5.0
        self._panning = False
        self._pan_start = QPointF()
        self.setRenderHints(QPainter.RenderHint.Antialiasing |
                            QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("background-color: #000; border: none;")
        self.setSceneRect(0, 0, SCENE_W, SCENE_H)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def zoom_to(self, factor):
        """Set zoom to specific factor."""
        factor = max(self._min_zoom, min(self._max_zoom, factor))
        if abs(factor - self._zoom) < 0.001:
            return
        self._zoom = factor
        tr = QTransform()
        tr.scale(factor, factor)
        self.setTransform(tr)
        self.zoomChanged.emit(factor)

    def zoom_in(self):
        self.zoom_to(self._zoom * 1.2)

    def zoom_out(self):
        self.zoom_to(self._zoom / 1.2)

    def zoom_fit(self):
        """Fit scene into view."""
        self.fitInView(0, 0, SCENE_W, SCENE_H, Qt.AspectRatioMode.KeepAspectRatio)
        t = self.transform()
        self._zoom = t.m11()
        self.zoomChanged.emit(self._zoom)

    def zoom_50(self):
        self.zoom_to(0.5)

    def zoom_100(self):
        self.zoom_to(1.0)

    def zoom_150(self):
        self.zoom_to(1.5)

    def zoom_200(self):
        self.zoom_to(2.0)

    def wheelEvent(self, event: QWheelEvent):
        modifiers = event.modifiers()
        if modifiers == Qt.KeyboardModifier.ControlModifier or True:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def get_zoom_percent(self):
        return self._zoom * 100.0


# =========================================================
#  Scene
# =========================================================

class CanvasScene(QGraphicsScene):
    """Main canvas scene at 1920x1080."""
    layoutChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(0, 0, SCENE_W, SCENE_H)
        self._items_map = {}
        self._bg_item = None

    def clear_canvas(self):
        self._items_map.clear()
        self._bg_item = None
        self.clear()

    def add_canvas_item(self, obj_id, obj_data, pixmap=None, waveform_data=None):
        obj_type = obj_data.get("type", "text")
        if obj_type == "image":
            item = MovablePixmapItem(obj_id, obj_data)
            if pixmap and not pixmap.isNull():
                item.set_pixmap(pixmap)
            self.addItem(item)
            if obj_id == OBJ_BACKGROUND:
                self._bg_item = item
            self._items_map[obj_id] = item
            return item
        elif obj_type == "text":
            item = MovableTextItem(obj_id, obj_data)
            self.addItem(item)
            self._items_map[obj_id] = item
            return item
        elif obj_type == "waveform":
            item = WaveformItem(obj_id, obj_data)
            if waveform_data:
                item.set_waveform(waveform_data)
            self.addItem(item)
            self._items_map[obj_id] = item
            return item
        elif obj_type == "progress":
            item = ProgressItem(obj_id, obj_data)
            self.addItem(item)
            self._items_map[obj_id] = item
            return item
        elif obj_type == "chapter_stack":
            item = ChapterStackItem(obj_id, obj_data)
            self.addItem(item)
            self._items_map[obj_id] = item
            return item
        return None

    def get_item(self, obj_id):
        return self._items_map.get(obj_id)

    def on_item_moved(self):
        self.layoutChanged.emit()


# =========================================================
#  Timeline Widget
# =========================================================

class BookTimelineWidget(QWidget):
    """Horizontal timeline showing book chapters as segments."""
    chapterClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chapters = []
        self._current_index = -1
        self._playhead_pos = 0.0
        self.setMinimumHeight(60)
        self.setMaximumHeight(80)
        self.setMouseTracking(True)
        self._hover_idx = -1
        self.setStyleSheet(f"background-color: {DARK_PANEL};")

    def set_chapters(self, chapters):
        self._chapters = chapters
        self.update()

    def set_current_index(self, idx):
        self._current_index = idx
        self.update()

    def set_playhead(self, fraction):
        self._playhead_pos = fraction
        self.update()

    def paintEvent(self, event):
        if not self._chapters:
            return
        painter = QPainter(self)
        w = self.width()
        h = self.height()
        margin = 8
        bar_h = h - 16
        bar_y = 8
        usable_w = w - margin * 2

        # Calculate total duration
        last_ch = self._chapters[-1]
        total_s = timestr_to_seconds(last_ch.get("end", "15:48:50"))

        # Draw segments
        x = margin
        for i, ch in enumerate(self._chapters):
            start_s = timestr_to_seconds(ch.get("start", "0"))
            ch_end_s = timestr_to_seconds(ch.get("end", "0"))
            dur = ch_end_s - start_s if ch_end_s > start_s else total_s / len(self._chapters)
            seg_w = max(6, (dur / total_s) * usable_w)

            # Determine color
            if i == self._current_index:
                bg = QColor(ACCENT_GREEN)
                fg = QColor("#000000")
            elif self._hover_idx == i:
                bg = QColor("#2a4a6a")
                fg = QColor(TEXT_PRIMARY)
            else:
                bg = QColor(DARK_CARD)
                fg = QColor(TEXT_SECONDARY)

            painter.setBrush(bg)
            painter.setPen(QPen(QColor(BORDER_COLOR), 1))
            rect = QRectF(x, bar_y, seg_w, bar_h)
            painter.drawRoundedRect(rect, 4, 4)

            # Label (truncate)
            title = ch.get("title", f"#{i}")
            if seg_w > 60:
                painter.setPen(fg)
                font = QFont("Segoe UI", 8)
                painter.setFont(font)
                painter.drawText(QRectF(x + 2, bar_y, seg_w - 4, bar_h),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                 title[:20])

            x += seg_w

        # Playhead line
        ph_x = margin + self._playhead_pos * usable_w
        painter.setPen(QPen(QColor(ACCENT_CYAN), 2))
        painter.drawLine(int(ph_x), bar_y, int(ph_x), bar_y + bar_h)

    def mouseMoveEvent(self, event):
        x = event.position().x()
        self._find_hover(x)
        if self._hover_idx >= 0 and self._hover_idx < len(self._chapters):
            ch = self._chapters[self._hover_idx]
            tip = f"{ch.get('title', '?')} @ {ch.get('start', '?')}"
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            x = event.position().x()
            idx = self._find_segment(x)
            if idx >= 0:
                self.chapterClicked.emit(idx)
        super().mousePressEvent(event)

    def _find_segment(self, mx):
        if not self._chapters:
            return -1
        margin = 8
        w = self.width()
        usable_w = w - margin * 2
        last_ch = self._chapters[-1]
        total_s = timestr_to_seconds(last_ch.get("end", "15:48:50"))
        x = margin
        for i, ch in enumerate(self._chapters):
            start_s = timestr_to_seconds(ch.get("start", "0"))
            ch_end_s = timestr_to_seconds(ch.get("end", "0"))
            dur = ch_end_s - start_s if ch_end_s > start_s else total_s / len(self._chapters)
            seg_w = max(6, (dur / total_s) * usable_w)
            if x <= mx <= x + seg_w:
                return i
            x += seg_w
        return -1

    def _find_hover(self, mx):
        self._hover_idx = self._find_segment(mx)
        self.update()

    def leaveEvent(self, event):
        self._hover_idx = -1
        self.update()
        super().leaveEvent(event)


# =========================================================
#  Properties Panel
# =========================================================

class PropertiesPanel(QWidget):
    """Right panel: edit selected object properties."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_id = None
        self._updating = False
        self._main_window = parent
        self.setMinimumWidth(240)
        self.setMaximumWidth(320)
        self.setStyleSheet(f"background-color: {DARK_PANEL}; color: {TEXT_PRIMARY};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Свойства объекта")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {ACCENT_CYAN};")
        layout.addWidget(title)

        self._hint_label = QLabel("Выбери объект на сцене, чтобы изменить текст, шрифт и позицию.")
        self._hint_label.setWordWrap(True)
        self._hint_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px; padding: 2px 0;")
        layout.addWidget(self._hint_label)

        self._id_label = QLabel("(ничего не выбрано)")
        self._id_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._id_label)

        # --- Text editing (for text objects) ---
        self._text_group = QGroupBox("Текст")
        self._text_group.setStyleSheet(f"""
            QGroupBox {{ color: {ACCENT_CYAN}; font-weight: bold; border: 1px solid {BORDER_COLOR};
                         border-radius: 4px; margin-top: 6px; padding-top: 10px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 6px; padding: 0 4px; }}
        """)
        text_layout = QVBoxLayout(self._text_group)
        text_layout.setSpacing(4)

        # Text source mode (for currentChapter)
        self._source_row = QHBoxLayout()
        self._source_label = QLabel("Источник:")
        self._source_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        self._source_row.addWidget(self._source_label)
        self._source_combo = QComboBox()
        self._source_combo.addItems(["Auto (из главы)", "Свой текст"])
        self._source_combo.setStyleSheet(f"""
            QComboBox {{ background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                         border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                         padding: 2px 4px; font-size: 10px; }}
        """)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        self._source_row.addWidget(self._source_combo, 1)
        text_layout.addLayout(self._source_row)

        # Text content / editable
        self._text_edit = QLineEdit()
        self._text_edit.setPlaceholderText("Текст...")
        self._text_edit.setStyleSheet(f"""
            QLineEdit {{ background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                         border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                         padding: 3px 6px; font-size: 11px; }}
        """)
        self._text_edit.textChanged.connect(self._on_text_changed)
        text_layout.addWidget(self._text_edit)

        layout.addWidget(self._text_group)

        # --- Font settings ---
        self._font_group = QGroupBox("Шрифт")
        self._font_group.setStyleSheet(self._text_group.styleSheet())
        font_layout = QVBoxLayout(self._font_group)
        font_layout.setSpacing(4)

        # Font family
        ff_row = QHBoxLayout()
        ff_lbl = QLabel("Семейство:")
        ff_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        ff_lbl.setFixedWidth(65)
        ff_row.addWidget(ff_lbl)
        self._font_family = QComboBox()
        self._font_family.setEditable(True)
        self._font_family.setStyleSheet(f"""
            QComboBox {{ background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                         border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                         padding: 2px 4px; font-size: 10px; }}
        """)
        self._font_family.currentTextChanged.connect(lambda v: self._set("font_family", v))
        ff_row.addWidget(self._font_family, 1)
        font_layout.addLayout(ff_row)

        # Font size
        fs_row = QHBoxLayout()
        fs_lbl = QLabel("Размер:")
        fs_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        fs_lbl.setFixedWidth(65)
        fs_row.addWidget(fs_lbl)
        self._fs_spin = QSpinBox()
        self._fs_spin.setRange(6, 200)
        self._fs_spin.setValue(24)
        self._fs_spin.setStyleSheet(f"""
            QSpinBox {{ background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                        border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                        padding: 2px; font-size: 10px; }}
        """)
        self._fs_spin.valueChanged.connect(lambda v: self._set("font_size", v))
        fs_row.addWidget(self._fs_spin, 1)
        font_layout.addLayout(fs_row)

        # Bold + Italic
        bi_row = QHBoxLayout()
        self._cb_bold = QCheckBox("Жирный")
        self._cb_bold.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 10px;")
        self._cb_bold.toggled.connect(lambda v: self._set("bold", v))
        bi_row.addWidget(self._cb_bold)
        self._cb_italic = QCheckBox("Курсив")
        self._cb_italic.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 10px;")
        self._cb_italic.toggled.connect(lambda v: self._set("italic", v))
        bi_row.addWidget(self._cb_italic)
        font_layout.addLayout(bi_row)

        # Color
        color_row = QHBoxLayout()
        color_lbl = QLabel("Цвет:")
        color_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        color_lbl.setFixedWidth(65)
        color_row.addWidget(color_lbl)
        self._color_input = QLineEdit("#FFFFFF")
        self._color_input.setMaxLength(7)
        self._color_input.setStyleSheet(f"""
            QLineEdit {{ background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                         border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                         padding: 2px 4px; font-size: 10px;
                         font-family: Consolas; }}
        """)
        self._color_input.textChanged.connect(lambda v: self._set("color", v.upper()))
        color_row.addWidget(self._color_input, 1)
        # Color swatch
        self._color_swatch = QFrame()
        self._color_swatch.setFixedSize(18, 18)
        self._color_swatch.setStyleSheet(f"background-color: #ffffff; border: 1px solid {BORDER_COLOR}; border-radius: 3px;")
        color_row.addWidget(self._color_swatch)
        font_layout.addLayout(color_row)

        # Alignment
        align_row = QHBoxLayout()
        align_lbl = QLabel("Выравн.:")
        align_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        align_lbl.setFixedWidth(65)
        align_row.addWidget(align_lbl)
        self._align_combo = QComboBox()
        self._align_combo.addItems(["left", "center", "right"])
        self._align_combo.setStyleSheet(f"""
            QComboBox {{ background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                         border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                         padding: 2px 4px; font-size: 10px; }}
        """)
        self._align_combo.currentTextChanged.connect(lambda v: self._set("align", v))
        align_row.addWidget(self._align_combo, 1)
        font_layout.addLayout(align_row)

        layout.addWidget(self._font_group)

        # --- Geometry ---
        self._geo_group = QGroupBox("Геометрия")
        self._geo_group.setStyleSheet(self._text_group.styleSheet())
        geo_layout = QVBoxLayout(self._geo_group)
        geo_layout.setSpacing(4)

        self._spin_x = self._make_spin("X", 0, 5000, geo_layout)
        self._spin_x.valueChanged.connect(lambda v: self._set("x", v))

        self._spin_y = self._make_spin("Y", 0, 5000, geo_layout)
        self._spin_y.valueChanged.connect(lambda v: self._set("y", v))

        self._spin_w = self._make_spin("Ширина", 1, 5000, geo_layout)
        self._spin_w.valueChanged.connect(lambda v: self._set("w", v))

        self._spin_h = self._make_spin("Высота", 1, 5000, geo_layout)
        self._spin_h.valueChanged.connect(lambda v: self._set("h", v))

        layout.addWidget(self._geo_group)

        # Opacity + Visible
        op_row = QHBoxLayout()
        self._spin_opacity = self._make_spin_inline("Прозрачность:", 0.0, 1.0, op_row, step=0.01, decimals=2)
        self._spin_opacity.valueChanged.connect(lambda v: self._set("opacity", v))
        layout.addLayout(op_row)

        self._cb_visible = QCheckBox("Видимый")
        self._cb_visible.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11px;")
        self._cb_visible.toggled.connect(lambda v: self._set("visible", v))
        layout.addWidget(self._cb_visible)

        layout.addStretch()

    def _make_spin(self, label, min_v, max_v, layout, step=1.0, decimals=0):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        lbl.setFixedWidth(65)
        row.addWidget(lbl)
        sp = QDoubleSpinBox()
        sp.setRange(min_v, max_v)
        sp.setSingleStep(step)
        sp.setDecimals(decimals)
        sp.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 2px; font-size: 10px;
            }}
        """)
        sp.setFixedHeight(22)
        row.addWidget(sp, 1)
        layout.addLayout(row)
        return sp

    def _make_spin_inline(self, label, min_v, max_v, layout, step=1.0, decimals=0):
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        layout.addWidget(lbl)
        sp = QDoubleSpinBox()
        sp.setRange(min_v, max_v)
        sp.setSingleStep(step)
        sp.setDecimals(decimals)
        sp.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 2px; font-size: 10px;
            }}
        """)
        sp.setFixedHeight(22)
        layout.addWidget(sp, 1)
        return sp

    def _set(self, key, value):
        if self._updating or not self._current_id:
            return
        mw = self._get_main_window()
        if mw and hasattr(mw, 'canvas_scene'):
            scene = mw.canvas_scene
            item = scene.get_item(self._current_id)
            if item and hasattr(item, "obj_data"):
                item.obj_data[key] = value
                item.update_from_data(item.obj_data)
                scene.layoutChanged.emit()

    def _on_text_changed(self, text):
        if self._updating or not self._current_id:
            return
        # Only save if in custom mode or the object isn't currentChapter
        obj_id = self._current_id
        if obj_id == OBJ_CURRENT_CHAPTER:
            source_idx = self._source_combo.currentIndex()
            if source_idx == 0:
                return  # Auto mode, don't save manual edits
        self._set("text", text)

    def _on_source_changed(self, idx):
        if self._updating or not self._current_id:
            return
        obj_id = self._current_id
        if obj_id != OBJ_CURRENT_CHAPTER:
            return
        mw = self._get_main_window()
        if mw:
            source = "auto" if idx == 0 else "custom"
            mw._set_chapter_source(source)

    def _get_main_window(self):
        return self._main_window

    def populate_font_families(self):
        """Fill the font family combo box with available Windows fonts."""
        try:
            families = get_windows_fonts()
            self._font_family.clear()
            self._font_family.addItems(families)
            self._font_family.setCurrentText("Segoe UI")
        except Exception as e:
            # Fallback to common fonts
            self._font_family.clear()
            fallback = [
                "Segoe UI", "Arial", "Arial Narrow", "Georgia",
                "Times New Roman", "Impact", "Consolas", "Courier New",
                "Verdana", "Tahoma", "Trebuchet MS", "Comic Sans MS"
            ]
            self._font_family.addItems(fallback)
            self._font_family.setCurrentText("Segoe UI")

    def show_properties(self, obj_id, obj_data):
        self._updating = True
        self._current_id = obj_id
        self._id_label.setText(f"ID: {obj_id}")

        # Show/hide text editing group based on object type
        is_text = obj_data.get("type") in ("text", "chapter_stack")
        self._text_group.setVisible(is_text)
        self._font_group.setVisible(is_text or obj_data.get("type") == "chapter_stack")

        if is_text:
            self._text_edit.setText(obj_data.get("text", ""))
            self._text_edit.setVisible(True)
            text_source = obj_data.get("text_source", "auto")
            is_chapter = (obj_id == OBJ_CURRENT_CHAPTER)
            self._source_row.setVisible(is_chapter)
            if is_chapter:
                self._source_combo.setCurrentIndex(0 if text_source == "auto" else 1)
                self._text_edit.setReadOnly(text_source == "auto")
            else:
                self._text_edit.setReadOnly(False)

            # Font family
            ff = obj_data.get("font_family", "Segoe UI")
            idx = self._font_family.findText(ff)
            if idx >= 0:
                self._font_family.setCurrentIndex(idx)
            else:
                self._font_family.setCurrentText(ff)

            self._fs_spin.setValue(obj_data.get("font_size", 24))
            self._cb_bold.setChecked(obj_data.get("bold", False))
            self._cb_italic.setChecked(obj_data.get("italic", False))

            color = obj_data.get("color", "#ffffff")
            self._color_input.setText(color)
            self._color_swatch.setStyleSheet(f"background-color: {color}; border: 1px solid {BORDER_COLOR}; border-radius: 3px;")

            align = obj_data.get("align", "left")
            align_idx = self._align_combo.findText(align)
            if align_idx >= 0:
                self._align_combo.setCurrentIndex(align_idx)
        else:
            self._text_group.setVisible(False)
            self._font_group.setVisible(False)

        # Geometry
        self._spin_x.setValue(obj_data.get("x", 0))
        self._spin_y.setValue(obj_data.get("y", 0))
        self._spin_w.setValue(obj_data.get("w", 100))
        self._spin_h.setValue(obj_data.get("h", 100))
        self._spin_opacity.setValue(obj_data.get("opacity", 1.0))
        self._cb_visible.setChecked(obj_data.get("visible", True))

        self._hint_label.setVisible(False)
        self._updating = False

    def clear_properties(self):
        self._updating = True
        self._current_id = None
        self._id_label.setText("(ничего не выбрано)")
        self._hint_label.setVisible(True)

        self._text_group.setVisible(True)
        self._text_edit.setText("")
        self._source_row.setVisible(False)

        self._spin_x.setValue(0)
        self._spin_y.setValue(0)
        self._spin_w.setValue(100)
        self._spin_h.setValue(100)
        self._spin_opacity.setValue(1.0)
        self._cb_visible.setChecked(True)
        self._fs_spin.setValue(24)
        self._color_input.setText("#FFFFFF")
        self._color_swatch.setStyleSheet(f"background-color: #ffffff; border: 1px solid {BORDER_COLOR}; border-radius: 3px;")

        self._updating = False


# =========================================================
#  ChapterList Widget (left panel)
# =========================================================

class ChapterListPanel(QWidget):
    """List of chapters with current highlighted."""
    chapterSelected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("Главы")
        title.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {ACCENT_CYAN}; padding: 6px 8px;")
        layout.addWidget(title)

        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: none; font-size: 11px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 4px 8px; border-bottom: 1px solid {BORDER_COLOR};
            }}
            QListWidget::item:hover {{
                background-color: #1a1a3a;
            }}
            QListWidget::item:selected {{
                background-color: transparent;
                color: {TEXT_PRIMARY};
            }}
        """)
        self._list.itemDoubleClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, 1)

        self._current_index = -1
        self._chapters = []

    def set_chapters(self, chapters):
        self._chapters = chapters
        self._list.clear()
        for i, ch in enumerate(chapters):
            title = ch.get("title", f"#{i}")
            start = ch.get("start", "00:00:00")
            label = f"{start[:8]}  {title}"
            item = QListWidgetItem(label)
            self._list.addItem(item)
        self._update_highlight()

    def set_current_index(self, idx):
        self._current_index = idx
        self._update_highlight()

    def _update_highlight(self):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if i == self._current_index:
                item.setForeground(QColor(ACCENT_GREEN))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
                item.setBackground(QColor("#1a3a2a"))
            else:
                item.setForeground(QColor(TEXT_SECONDARY))
                font = item.font()
                font.setBold(False)
                item.setFont(font)
                item.setBackground(QColor(DARK_CARD))

    def _on_item_clicked(self, item):
        idx = self._list.row(item)
        if 0 <= idx < len(self._chapters):
            self.chapterSelected.emit(idx)

    def scroll_to_current(self):
        if self._current_index >= 0:
            self._list.scrollToItem(self._list.item(self._current_index),
                                     QAbstractItemView.ScrollHint.EnsureVisible)


# =========================================================
#  Main Window
# =========================================================

class BookWunderwaffeStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Book Wunderwaffe Studio 1.0 — La machine merveilleuse pour forger les livres")
        self.setMinimumSize(1280, 800)
        self.resize(1600, 1000)
        self.setStyleSheet(f"background-color: {DARK_BG};")

        # State
        self._project_data = {}
        self._chapters = []
        self._chapters_index = 0
        self._chapters_source_mode = {}  # chapter text source per-chapter
        self._waveform_data = None
        self._layout_data = None
        self._layout_dirty = False
        self._bg_pixmap = None
        self._cover_pixmap = None
        self._active_process = None
        self._selected_item_id = None

        # Player state
        self._player = None
        self._audio_output = None
        self._is_playing = False
        self._total_duration = 0.0
        self._player_timer = QTimer(self)
        self._player_timer.setInterval(100)  # 100ms update
        self._player_timer.timeout.connect(self._on_player_tick)

        # Build paths
        BUILD_DIR.mkdir(exist_ok=True)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Top bar
        # Canvas with zoomable view (must be before top_bar)
        self._scene = CanvasScene(self)
        self._view = ZoomableView(self._scene)

        self._top_bar = self._create_top_bar()
        main_layout.addWidget(self._top_bar)

        # Splitter: left / canvas / right
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self._splitter, 1)

        # Left panel (chapters + project info)
        self._left_panel = self._create_left_panel()
        self._splitter.addWidget(self._left_panel)

        self._splitter.addWidget(self._view)

        # Right panel
        self._props_panel = PropertiesPanel(self)
        # Populate font family combo
        self._props_panel.populate_font_families()
        self._splitter.addWidget(self._props_panel)

        self._splitter.setSizes([260, 880, 260])

        # Timeline bar (between canvas and player)
        self._timeline_label = QLabel("Таймлайн книги")
        self._timeline_label.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY}; padding: 2px 8px; background: {DARK_PANEL};")
        main_layout.addWidget(self._timeline_label)
        self._timeline = BookTimelineWidget()
        self._timeline.chapterClicked.connect(self._on_timeline_chapter_clicked)
        main_layout.addWidget(self._timeline)

        # Player bar label
        player_label = QLabel("Плеер предпросмотра")
        player_label.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY}; padding: 2px 8px; background: {DARK_PANEL};")
        main_layout.addWidget(player_label)

        # Bottom bar (player)
        bottom_bar = self._create_bottom_bar()
        main_layout.addWidget(bottom_bar)

        # Log dock
        self._log_dock = QDockWidget("Лог", self)
        self._log_dock.setStyleSheet(f"color: {TEXT_SECONDARY}; background: {DARK_PANEL};")
        self._log_widget = QTextEdit()
        self._log_widget.setReadOnly(True)
        self._log_widget.document().setMaximumBlockCount(500)
        self._log_widget.setStyleSheet(f"""
            background-color: {DARK_CARD}; color: {ACCENT_GREEN};
            font-family: Consolas, monospace; font-size: 10px;
            border: 1px solid {BORDER_COLOR};
        """)
        self._log_dock.setWidget(self._log_widget)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)
        self._log_dock.hide()

        # Status bar
        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet(f"background-color: {DARK_PANEL}; color: {TEXT_SECONDARY}; font-size: 10px;")
        self._status_label_bar = QLabel("Готово")
        self._status_label_bar.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 10px;")
        self._status_bar.addWidget(self._status_label_bar)
        self._player_status_label = QLabel("")
        self._player_status_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        self._status_bar.addPermanentWidget(self._player_status_label)
        self.setStatusBar(self._status_bar)

        # Connect scene signals
        self._scene.layoutChanged.connect(self._on_layout_changed)
        self._scene.selectionChanged.connect(self._on_selection_changed)
        self._view.zoomChanged.connect(self._on_zoom_changed)

        # Init
        self._init_player()
        self._load_project()

    # --- Player init ---
    def _init_player(self):
        if not HAS_MULTIMEDIA:
            self.log("PySide6 QtMultimedia не доступен. Плеер отключён.")
            self._player_status_label.setText("⚠ QtMultimedia недоступен")
            self._player_status_label.setStyleSheet("color: #ff5555; font-size: 10px;")
            return
        try:
            self._player = QMediaPlayer(self)
            self._audio_output = QAudioOutput(self)
            self._player.setAudioOutput(self._audio_output)
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)
            self._player.mediaStatusChanged.connect(self._on_media_status_changed)
            self._player.errorOccurred.connect(self._on_player_error)
            self.log("Аудио плеер инициализирован.")
            self._player_status_label.setText("Плеер: готов")
            self._player_status_label.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 10px;")
        except Exception as e:
            self.log(f"Ошибка инициализации плеера: {e}")
            self._player = None
            self._player_status_label.setText("⚠ Ошибка плеера")
            self._player_status_label.setStyleSheet("color: #ff5555; font-size: 10px;")

    def _on_player_error(self, error, error_string):
        self.log(f"Плеер: ошибка — {error_string}")
        self._player_status_label.setText(f"⚠ {error_string[:40]}")
        self._player_status_label.setStyleSheet("color: #ff5555; font-size: 10px;")

    def _load_player_audio(self):
        """Load the selected audio file into player."""
        if not self._player:
            return
        audio_file = self._get_config_path("audio", "")
        if not audio_file:
            self.log("Нет аудиофайла для загрузки в плеер.")
            self._player_status_label.setText("⚠ Аудио не найдено")
            return
        audio_path = Path(audio_file)
        if not audio_path.exists():
            audio_path = DATA_DIR / Path(audio_file).name
        if not audio_path.exists():
            self.log(f"Аудиофайл не найден: {audio_path}")
            self._player_status_label.setText("⚠ Аудиофайл не найден")
            self._player_status_label.setStyleSheet("color: #ff5555; font-size: 10px;")
            return
        url = QUrl.fromLocalFile(str(audio_path.resolve()))
        self._player.setSource(url)
        self.log(f"Плеер: загружено {Path(audio_file).name}")
        self._player_status_label.setText(f"Загружено: {Path(audio_file).name}")
        self._player_status_label.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 10px;")
        self._status_label_bar.setText("Плеер: загружено")

    def _get_config_path(self, key, default=""):
        """Get a path from config, supporting both flat and nested formats."""
        val = self._project_data.get(key, default)
        if val:
            return val
        legacy_key = key + "_file"
        val = self._project_data.get(legacy_key, default)
        if val:
            return val
        return default

    def _update_project_info(self):
        config = self._project_data
        audio = self._get_config_path("audio", "—")
        rpp = self._get_config_path("rpp", "—")
        cover = self._get_config_path("cover", "—")
        bg = self._get_config_path("background", "—")
        self._lbl_audio.setText(f"Аудио: {Path(audio).name if audio != '—' else '—'}")
        self._lbl_rpp.setText(f"RPP: {Path(rpp).name if rpp != '—' else '—'}")
        self._lbl_cover.setText(f"Обложка: {Path(cover).name if cover != '—' else '—'}")
        self._lbl_bg.setText(f"Фон: {Path(bg).name if bg != '—' else '—'}")
        self._lbl_chapters.setText(f"Главы: {len(self._chapters)}")
        has_intro = bool(self._chapters and 'Вступление' in self._chapters[0].get('title', ''))
        has_epilogue = bool(any('Эпилог' in c.get('title', '') for c in self._chapters))
        self._lbl_intro.setText(f"Вступление: {'ДА' if has_intro else '?'}")
        self._lbl_epilogue.setText(f"Эпилог: {'ДА' if has_epilogue else '?'}")
        self._audio_label.setText(f"Аудио: {Path(audio).name if audio != '—' else '—'}")
        self._ch_count_label.setText(f"Глав: {len(self._chapters)}")

    def _on_position_changed(self, pos_ms):
        """Update slider and canvas based on playback position."""
        if self._player_timer.isActive():
            return  # timer handles updates
        self._update_playback_ui(pos_ms / 1000.0)

    def _on_duration_changed(self, dur_ms):
        self._total_duration = dur_ms / 1000.0
        self._slider_position.setMaximum(int(dur_ms))
        total_str = seconds_to_timestr(self._total_duration)
        self._label_total.setText(total_str)
        self.log(f"Длительность: {total_str}")

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self.log("Медиа загружено.")
            self._player_status_label.setText("Плеер: готов")
        elif status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._is_playing = False
            self._btn_play.setText("▶ Играть")
            self._player_timer.stop()
            self._status_label_bar.setText("Готово")
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            self.log("⚠ Плеер не смог загрузить аудио. Проверь PySide6 QtMultimedia.")
            self._player_status_label.setText("⚠ Не удалось загрузить аудио")
            self._player_status_label.setStyleSheet("color: #ff5555; font-size: 10px;")

    def _on_player_tick(self):
        """Timer tick for smooth UI updates."""
        if self._player and self._is_playing:
            pos = self._player.position()
            self._update_playback_ui(pos / 1000.0)

    def _update_playback_ui(self, current_sec):
        """Update all UI elements based on current time."""
        # Slider
        slider_ms = int(current_sec * 1000)
        self._slider_position.blockSignals(True)
        self._slider_position.setValue(slider_ms)
        self._slider_position.blockSignals(False)

        # Time label
        self._label_current.setText(seconds_to_timestr(current_sec))

        # Find active chapter
        active_idx = self._find_chapter_at_time(current_sec)
        if active_idx >= 0 and active_idx < len(self._chapters):
            ch = self._chapters[active_idx]
            title = ch.get("title", "?")
            self._chapters_index = active_idx

            # Update chapterStack
            self._update_chapter_stack(active_idx)

            # Update chapter text on canvas (only if source is auto)
            item = self._scene.get_item(OBJ_CURRENT_CHAPTER)
            if item and hasattr(item, "obj_data"):
                text_source = item.obj_data.get("text_source", "auto")
                if text_source == "auto":
                    item.obj_data["text"] = title
                    item.setPlainText(title)

            # Update chapter combo (don't trigger signal)
            self._chapter_combo.blockSignals(True)
            self._chapter_combo.setCurrentIndex(active_idx)
            self._chapter_combo.blockSignals(False)

            # Update chapter list
            if hasattr(self, '_chapter_list'):
                self._chapter_list.set_current_index(active_idx)

            # Update timeline
            self._timeline.set_current_index(active_idx)

        # Progress bar
        total_s = self._total_duration
        if total_s > 0 and self._chapters:
            prog = current_sec / total_s if total_s > 0 else 0
        else:
            if self._chapters:
                last = self._chapters[-1]
                total_s = timestr_to_seconds(last.get("end", "15:48:50.932"))
                prog = current_sec / total_s if total_s > 0 else 0
            else:
                prog = 0

        prog_item = self._scene.get_item(OBJ_PROGRESS)
        if prog_item and isinstance(prog_item, ProgressItem):
            prog_item.set_progress(prog)

        # Waveform highlight
        wf_item = self._scene.get_item(OBJ_WAVEFORM)
        if wf_item and isinstance(wf_item, WaveformItem):
            wf_item.set_playback_time(current_sec, total_s if total_s > 0 else 1.0)

        # Timeline playhead
        if total_s > 0:
            self._timeline.set_playhead(current_sec / total_s)

    def _update_chapter_stack(self, idx):
        """Update chapterStack with prev/current/next chapters."""
        stack_item = self._scene.get_item(OBJ_CHAPTER_STACK)
        if not stack_item or not isinstance(stack_item, ChapterStackItem):
            return
        prev_title = ""
        cur_title = self._chapters[idx].get("title", "") if idx < len(self._chapters) else ""
        next_title = ""
        if idx > 0:
            prev_title = self._chapters[idx - 1].get("title", "")
        if idx < len(self._chapters) - 1:
            next_title = self._chapters[idx + 1].get("title", "")
        stack_item.set_chapters(prev_title, cur_title, next_title)

    def _find_chapter_at_time(self, sec):
        """Find chapter index by time in seconds."""
        if not self._chapters:
            return -1
        for i, ch in enumerate(self._chapters):
            ch_start = timestr_to_seconds(ch.get("start", "0"))
            ch_end = timestr_to_seconds(ch.get("end", str(sec + 1)))
            if ch_start <= sec < ch_end:
                return i
        return len(self._chapters) - 1

    def _toggle_playback(self):
        if not self._player:
            self.log("Плеер недоступен.")
            return
        if self._is_playing:
            self._player.pause()
            self._is_playing = False
            self._btn_play.setText("▶ Играть")
            self._player_timer.stop()
            self._status_label_bar.setText("Готово")
        else:
            self._player.play()
            self._is_playing = True
            self._btn_play.setText("⏸ Пауза")
            self._player_timer.start()
            self._status_label_bar.setText("Воспроизведение...")

    def _stop_playback(self):
        if not self._player:
            return
        self._player.stop()
        self._is_playing = False
        self._btn_play.setText("▶ Играть")
        self._player_timer.stop()
        self._slider_position.setValue(0)
        self._label_current.setText("00:00:00.000")
        self._status_label_bar.setText("Готово")

    def _seek_to(self, position_ms):
        if not self._player:
            return
        self._player.setPosition(position_ms)

    def _seek_to_chapter(self, idx):
        if idx < 0 or idx >= len(self._chapters):
            return
        ch = self._chapters[idx]
        start_s = timestr_to_seconds(ch.get("start", "0"))
        self._seek_to(int(start_s * 1000))
        self._on_chapter_selected(idx)

    def _prev_chapter(self):
        idx = self._chapters_index - 1
        if idx < 0:
            idx = 0
        self._seek_to_chapter(idx)

    def _next_chapter(self):
        idx = self._chapters_index + 1
        if idx >= len(self._chapters):
            idx = len(self._chapters) - 1
        self._seek_to_chapter(idx)

    def _on_timeline_chapter_clicked(self, idx):
        self._seek_to_chapter(idx)

    # --- Top bar ---
    def _create_top_bar(self):
        bar = QWidget()
        bar.setFixedHeight(40)
        bar.setStyleSheet(f"background-color: {DARK_PANEL}; border-bottom: 1px solid {BORDER_COLOR};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 0, 12, 0)

        self._app_title = QLabel("Book Wunderwaffe Studio 1.0")
        self._app_title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {ACCENT_CYAN};")
        layout.addWidget(self._app_title)

        layout.addSpacing(16)

        self._status_label = QLabel("НЕ ГОТОВ")
        self._status_label.setStyleSheet(f"font-size: 12px; color: #ff5555; font-weight: bold;")
        layout.addWidget(self._status_label)

        layout.addSpacing(16)

        self._audio_label = QLabel("Аудио: —")
        self._audio_label.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        layout.addWidget(self._audio_label)

        layout.addSpacing(16)

        self._ch_count_label = QLabel("Глав: —")
        self._ch_count_label.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        layout.addWidget(self._ch_count_label)

        layout.addSpacing(16)

        # Canvas hint
        hint = QLabel("Сцена 1920×1080. Перетаскивай элементы мышкой. Колесо/кнопки — зум.")
        hint.setStyleSheet(f"font-size: 10px; color: {TEXT_SECONDARY}; padding: 2px 4px;")
        layout.addWidget(hint)

        layout.addStretch()

        # Zoom controls
        self._zoom_label = QLabel("Zoom: 100%")
        self._zoom_label.setStyleSheet(f"font-size: 11px; color: {ACCENT_CYAN}; font-weight: bold;")
        layout.addWidget(self._zoom_label)

        layout.addSpacing(8)

        for text, method in [("Fit", self._view.zoom_fit),
                              ("50%", self._view.zoom_50),
                              ("100%", self._view.zoom_100),
                              ("150%", self._view.zoom_150),
                              ("200%", self._view.zoom_200)]:
            btn = QPushButton(text)
            btn.setFixedSize(42, 24)
            btn.setStyleSheet(self._btn_small_style())
            btn.clicked.connect(method)
            layout.addWidget(btn)

        layout.addSpacing(8)

        # Show log toggle
        btn_log = QPushButton("Лог")
        btn_log.setFixedSize(50, 26)
        btn_log.setStyleSheet(self._btn_small_style())
        btn_log.clicked.connect(lambda: self._log_dock.show())
        layout.addWidget(btn_log)

        return bar

    # --- Left panel ---
    def _create_left_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(320)
        panel.setStyleSheet(f"background-color: {DARK_PANEL};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Project info group
        info_group = QGroupBox("Проект")
        info_group.setStyleSheet(f"""
            QGroupBox {{ color: {ACCENT_CYAN}; font-weight: bold; border: 1px solid {BORDER_COLOR};
                         border-radius: 6px; margin-top: 8px; padding-top: 12px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
        """)
        info_layout = QVBoxLayout(info_group)
        info_layout.setSpacing(4)

        self._lbl_audio = QLabel("Аудио: —")
        self._lbl_rpp = QLabel("RPP: —")
        self._lbl_cover = QLabel("Обложка: —")
        self._lbl_bg = QLabel("Фон: —")
        self._lbl_chapters = QLabel("Главы: —")
        self._lbl_intro = QLabel("Вступление: —")
        self._lbl_epilogue = QLabel("Эпилог: —")
        for lbl in [self._lbl_audio, self._lbl_rpp, self._lbl_cover,
                     self._lbl_bg, self._lbl_chapters, self._lbl_intro, self._lbl_epilogue]:
            lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11px; padding: 2px 0;")
            info_layout.addWidget(lbl)

        layout.addWidget(info_group)

        # Chapter list
        self._chapter_list = ChapterListPanel()
        self._chapter_list.chapterSelected.connect(self._seek_to_chapter)
        layout.addWidget(self._chapter_list, 1)

        # Buttons group
        btn_group = QGroupBox("Действия")
        btn_group.setStyleSheet(info_group.styleSheet())
        btn_layout = QVBoxLayout(btn_group)
        btn_layout.setSpacing(4)

        btn_scan = QPushButton("🔍 Сканировать")
        btn_scan.clicked.connect(lambda: self._run_command("scan"))
        btn_scan.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_scan)

        btn_chapters = QPushButton("📖 Извлечь главы")
        btn_chapters.clicked.connect(lambda: self._run_command("chapters"))
        btn_chapters.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_chapters)

        btn_waveform = QPushButton("🌊 Сгенерировать гистограмму")
        btn_waveform.clicked.connect(lambda: self._run_command("waveform"))
        btn_waveform.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_waveform)

        btn_layout.addSpacing(4)

        btn_reset = QPushButton("🔄 Сбросить композицию")
        btn_reset.clicked.connect(self._reset_layout)
        btn_reset.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_reset)

        btn_save = QPushButton("💾 Сохранить композицию")
        btn_save.clicked.connect(self._save_layout)
        btn_save.setStyleSheet(self._btn_style(ACCENT_GREEN))
        btn_layout.addWidget(btn_save)

        btn_reload = QPushButton("📂 Перезагрузить композицию")
        btn_reload.clicked.connect(self._load_layout)
        btn_reload.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_reload)

        btn_layout.addSpacing(4)

        btn_preview = QPushButton("👁 Превью-лист")
        btn_preview.clicked.connect(lambda: self._run_command("preview_contact"))
        btn_preview.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_preview)

        btn_check = QPushButton("✅ Проверить превью")
        btn_check.clicked.connect(lambda: self._run_command("check_preview"))
        btn_check.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_check)

        btn_open_build = QPushButton("📁 Открыть папку сборки")
        btn_open_build.clicked.connect(lambda: os.startfile(str(BUILD_DIR)))
        btn_open_build.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_open_build)

        btn_open_layout = QPushButton("📄 Открыть layout.json")
        btn_open_layout.clicked.connect(lambda: os.startfile(str(LAYOUT_PATH)))
        btn_open_layout.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_open_layout)

        btn_open_data = QPushButton("📁 Открыть data")
        btn_open_data.clicked.connect(lambda: os.startfile(str(DATA_DIR)))
        btn_open_data.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_open_data)

        layout.addWidget(btn_group)

        # Render test group
        test_group = QGroupBox("Тестовый рендер")
        test_group.setStyleSheet(info_group.styleSheet())
        test_layout = QVBoxLayout(test_group)
        test_layout.setSpacing(4)

        dur_row = QHBoxLayout()
        dur_lbl = QLabel("Длительность:")
        dur_lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        dur_row.addWidget(dur_lbl)
        self._test_duration_combo = QComboBox()
        self._test_duration_combo.addItems([
            "1 мин",
            "5 мин",
            "10 мин",
            "60 сек",
            "Текущая глава",
            "Свой"
        ])
        self._test_duration_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 3px 8px; font-size: 11px;
            }}
        """)
        dur_row.addWidget(self._test_duration_combo, 1)
        test_layout.addLayout(dur_row)

        custom_row = QHBoxLayout()
        self._test_custom_spin = QSpinBox()
        self._test_custom_spin.setRange(60, 36000)
        self._test_custom_spin.setValue(600)
        self._test_custom_spin.setSuffix(" сек")
        self._test_custom_spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 3px; font-size: 11px;
            }}
        """)
        self._test_custom_spin.hide()
        custom_row.addWidget(self._test_custom_spin, 1)
        self._test_duration_combo.currentTextChanged.connect(
            lambda t: self._test_custom_spin.setVisible(t == "Свой"))
        test_layout.addLayout(custom_row)

        btn_render_test = QPushButton("🎬 Тестовый рендер")
        btn_render_test.clicked.connect(self._run_render_test)
        btn_render_test.setStyleSheet(self._btn_style(ACCENT_VIOLET))
        test_layout.addWidget(btn_render_test)

        layout.addWidget(test_group)

        # Full render button
        btn_full = QPushButton("⚠️ Полный рендер")
        btn_full.clicked.connect(self._confirm_full_render)
        btn_full.setStyleSheet(f"""
            QPushButton {{
                background-color: #331111; color: #ff6666;
                border: 1px solid #661111; border-radius: 4px;
                padding: 6px 10px; font-size: 10px; text-align: left;
            }}
            QPushButton:hover {{ background-color: #442222; }}
        """)
        layout.addWidget(btn_full)

        layout.addStretch()
        return panel

    def _btn_style(self, color=ACCENT_CYAN):
        return f"""
            QPushButton {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 6px 10px; font-size: 11px; text-align: left;
            }}
            QPushButton:hover {{
                background-color: #1a1a4a; border-color: {color};
            }}
            QPushButton:pressed {{
                background-color: #0a0a3a;
            }}
        """

    def _btn_small_style(self):
        return f"""
            QPushButton {{
                background-color: {DARK_CARD}; color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                padding: 2px 6px; font-size: 10px;
            }}
            QPushButton:hover {{ background-color: #1a1a4a; color: {ACCENT_CYAN}; }}
        """

    # --- Bottom bar with player ---
    def _create_bottom_bar(self):
        bar = QWidget()
        bar.setFixedHeight(48)
        bar.setStyleSheet(f"background-color: {DARK_PANEL}; border-top: 1px solid {BORDER_COLOR};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        # Chapter navigation
        btn_prev = QPushButton("⏮")
        btn_prev.setFixedSize(30, 28)
        btn_prev.setStyleSheet(self._btn_small_style())
        btn_prev.clicked.connect(self._prev_chapter)
        layout.addWidget(btn_prev)

        # Play/Pause
        self._btn_play = QPushButton("▶ Играть")
        self._btn_play.setFixedSize(70, 28)
        self._btn_play.setStyleSheet(f"""
            QPushButton {{
                background-color: #1a3a1a; color: {ACCENT_GREEN};
                border: 1px solid {ACCENT_GREEN}; border-radius: 4px;
                padding: 3px 10px; font-size: 11px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #2a4a2a; }}
        """)
        self._btn_play.clicked.connect(self._toggle_playback)
        layout.addWidget(self._btn_play)

        # Stop
        btn_stop = QPushButton("⏹")
        btn_stop.setFixedSize(30, 28)
        btn_stop.setStyleSheet(self._btn_small_style())
        btn_stop.clicked.connect(self._stop_playback)
        layout.addWidget(btn_stop)

        # Next chapter
        btn_next = QPushButton("⏭")
        btn_next.setFixedSize(30, 28)
        btn_next.setStyleSheet(self._btn_small_style())
        btn_next.clicked.connect(self._next_chapter)
        layout.addWidget(btn_next)

        layout.addSpacing(8)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {BORDER_COLOR};")
        layout.addWidget(sep)

        layout.addSpacing(8)

        # Time display
        self._label_current = QLabel("00:00:00")
        self._label_current.setFixedWidth(70)
        self._label_current.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 11px; font-family: Consolas;")
        layout.addWidget(self._label_current)

        self._label_sep = QLabel("/")
        self._label_sep.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(self._label_sep)

        self._label_total = QLabel("00:00:00")
        self._label_total.setFixedWidth(70)
        self._label_total.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px; font-family: Consolas;")
        layout.addWidget(self._label_total)

        layout.addSpacing(8)

        # Seek slider
        self._slider_position = QSlider(Qt.Orientation.Horizontal)
        self._slider_position.setMinimumWidth(200)
        self._slider_position.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {DARK_CARD}; height: 6px; border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {ACCENT_CYAN}; width: 12px; height: 12px;
                margin: -3px 0; border-radius: 6px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT_CYAN}; border-radius: 3px;
            }}
        """)
        self._slider_position.sliderMoved.connect(self._seek_to)
        layout.addWidget(self._slider_position, 1)

        layout.addSpacing(8)

        # Chapter dropdown
        lbl_ch = QLabel("Глава:")
        lbl_ch.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        layout.addWidget(lbl_ch)

        self._chapter_combo = QComboBox()
        self._chapter_combo.setMinimumWidth(200)
        self._chapter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 3px 8px; font-size: 10px;
            }}
            QComboBox:hover {{ border-color: {ACCENT_CYAN}; }}
            QComboBox::drop-down {{
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 16px; border-left: 1px solid {BORDER_COLOR};
            }}
        """)
        self._chapter_combo.currentIndexChanged.connect(self._on_chapter_selected)
        layout.addWidget(self._chapter_combo)

        # Jump to chapter
        btn_jump = QPushButton("→")
        btn_jump.setFixedSize(24, 28)
        btn_jump.setStyleSheet(self._btn_small_style())
        btn_jump.clicked.connect(lambda: self._seek_to_chapter(self._chapter_combo.currentIndex()))
        layout.addWidget(btn_jump)

        layout.addSpacing(8)

        # Contact preview
        self._btn_contact = QPushButton("👁 Контакт")
        self._btn_contact.setStyleSheet(self._btn_small_style())
        self._btn_contact.clicked.connect(lambda: self._run_command("preview_contact"))
        layout.addWidget(self._btn_contact)

        return bar

    # --- Load project ---
    def _load_project(self):
        self.log("Загрузка проекта...")
        config = load_json(PROJECT_CONFIG)
        if config:
            self._project_data = config
            self.log(f"Конфиг проекта загружен: {config.get('audio_file', '?')}")
        else:
            self.log("Конфиг проекта не найден. Запусти Сканировать.")

        self._load_chapters()
        self._load_waveform()
        self._load_layout()

        self._update_project_info()
        self._rebuild_canvas()
        self._update_status()

        self._load_player_audio()

    def _load_chapters(self):
        ch = load_json(CHAPTERS_PATH)
        if ch and isinstance(ch, list):
            self._chapters = ch
            self.log(f"Загружено {len(ch)} глав")
        else:
            self._chapters = []
            self.log("Главы не найдены. Запусти Извлечь главы.")

        self._chapter_combo.blockSignals(True)
        self._chapter_combo.clear()
        for i, c in enumerate(self._chapters):
            title = c.get("title", f"Segment {i}")
            start = c.get("start", "00:00:00")
            self._chapter_combo.addItem(f"{start[:8]} — {title}", i)
        self._chapter_combo.blockSignals(False)

        # Update chapter list
        if hasattr(self, '_chapter_list'):
            self._chapter_list.set_chapters(self._chapters)

        # Update timeline
        if hasattr(self, '_timeline'):
            self._timeline.set_chapters(self._chapters)

    def _load_waveform(self):
        wf = load_json(WAVEFORM_PATH)
        if wf and isinstance(wf, list) and len(wf) > 10:
            self._waveform_data = wf
            self.log(f"Waveform загружен: {len(wf)} samples")
        else:
            self._waveform_data = None
            self.log("Нет данных waveform. Сгенерируй гистограмму.")

    def _load_layout(self):
        lt = load_json(LAYOUT_PATH)
        if lt and isinstance(lt, dict):
            self._layout_data = lt
            self.log("Композиция загружена из файла.")
        else:
            self._layout_data = dict(DEFAULT_LAYOUT)
            self.log("Используется композиция по умолчанию.")

    def _reset_layout(self):
        self._layout_data = dict(DEFAULT_LAYOUT)
        self._rebuild_canvas()
        self._layout_dirty = True
        self.log("Композиция сброшена до стандартной.")
        self._update_status()

    def _save_layout(self):
        if not self._layout_data:
            self.log("Нечего сохранять.")
            return
        # Ensure current text is saved
        self._sync_layout_from_canvas()
        save_json(LAYOUT_PATH, self._layout_data)
        self._layout_dirty = False
        self.log(f"Композиция сохранена: {LAYOUT_PATH}")
        self._status_bar.showMessage("Layout saved", 3000)
        self._update_status()

    def _sync_layout_from_canvas(self):
        """Sync layout data from canvas items."""
        if not self._layout_data:
            return
        for obj_id, item in self._scene._items_map.items():
            if hasattr(item, "obj_data"):
                self._layout_data[obj_id] = dict(item.obj_data)

    def _rebuild_canvas(self):
        self._scene.clear_canvas()
        lt = self._layout_data or DEFAULT_LAYOUT

        bg_path = DATA_DIR / "background.png"
        cover_path = DATA_DIR / "zina-cover.png"
        self._bg_pixmap = QPixmap(str(bg_path)) if bg_path.exists() else QPixmap()
        self._cover_pixmap = QPixmap(str(cover_path)) if cover_path.exists() else QPixmap()

        # Background
        bg_data = lt.get(OBJ_BACKGROUND, DEFAULT_LAYOUT["background"])
        self._scene.add_canvas_item(OBJ_BACKGROUND, bg_data, pixmap=self._bg_pixmap)

        # Cover
        cover_data = lt.get(OBJ_COVER, DEFAULT_LAYOUT["cover"])
        self._scene.add_canvas_item(OBJ_COVER, cover_data, pixmap=self._cover_pixmap)

        # Book title
        title_data = lt.get(OBJ_BOOK_TITLE, DEFAULT_LAYOUT["bookTitle"])
        if "text" not in title_data or not title_data.get("text"):
            title_data["text"] = self._project_data.get("title", "Интимный протокол")
        self._scene.add_canvas_item(OBJ_BOOK_TITLE, title_data)

        # Current chapter
        ch_data = lt.get(OBJ_CURRENT_CHAPTER, DEFAULT_LAYOUT["currentChapter"])
        if self._chapters and ch_data.get("text_source", "auto") == "auto":
            ch_data["text"] = self._chapters[0].get("title", "Вступление от автора")
        self._scene.add_canvas_item(OBJ_CURRENT_CHAPTER, ch_data)

        # Chapter stack
        stack_data = lt.get(OBJ_CHAPTER_STACK, DEFAULT_LAYOUT["chapterStack"])
        self._scene.add_canvas_item(OBJ_CHAPTER_STACK, stack_data)

        # Waveform
        wf_data = lt.get(OBJ_WAVEFORM, DEFAULT_LAYOUT["waveform"])
        self._scene.add_canvas_item(OBJ_WAVEFORM, wf_data, waveform_data=self._waveform_data)

        # Progress
        prog_data = lt.get(OBJ_PROGRESS, DEFAULT_LAYOUT["progress"])
        self._scene.add_canvas_item(OBJ_PROGRESS, prog_data)

        # Brand
        brand_data = lt.get(OBJ_BRAND, DEFAULT_LAYOUT["brand"])
        self._scene.add_canvas_item(OBJ_BRAND, brand_data)

        # Initialize chapterStack with current chapter
        if self._chapters:
            self._update_chapter_stack(0)

        self._view.zoom_fit()
        self.log("Сцена перестроена.")

    def _update_status(self):
        ready = len(self._chapters) > 0
        if ready:
            self._status_label.setText("● ГОТОВ")
            self._status_label.setStyleSheet("font-size: 12px; color: #00ff88; font-weight: bold;")
            self._status_label_bar.setText("Готово")
        else:
            self._status_label.setText("● НЕ ГОТОВ")
            self._status_label.setStyleSheet("font-size: 12px; color: #ff5555; font-weight: bold;")
            self._status_label_bar.setText("Не готов")

    def _set_chapter_source(self, source):
        """Set text source for currentChapter (auto/custom)."""
        item = self._scene.get_item(OBJ_CURRENT_CHAPTER)
        if item and hasattr(item, "obj_data"):
            item.obj_data["text_source"] = source
            if source == "auto":
                # Reset to chapter title
                if self._chapters and self._chapters_index < len(self._chapters):
                    title = self._chapters[self._chapters_index].get("title", "")
                    item.obj_data["text"] = title
                    item.setPlainText(title)
            self._layout_dirty = True

    # --- Zoom change ---
    def _on_zoom_changed(self, factor):
        pct = factor * 100.0
        self._zoom_label.setText(f"Zoom: {pct:.0f}%")

    # --- Chapter selection ---
    def _on_chapter_selected(self, idx):
        if idx < 0 or idx >= len(self._chapters):
            return
        ch = self._chapters[idx]
        self._chapters_index = idx
        title = ch.get("title", "?")
        # Update canvas chapter text (only if auto mode)
        item = self._scene.get_item(OBJ_CURRENT_CHAPTER)
        if item and hasattr(item, "obj_data"):
            text_source = item.obj_data.get("text_source", "auto")
            if text_source == "auto":
                item.obj_data["text"] = title
                item.setPlainText(title)
        # Update chapterStack
        self._update_chapter_stack(idx)
        # Update chapter list
        if hasattr(self, '_chapter_list'):
            self._chapter_list.set_current_index(idx)
        # Update timeline
        self._timeline.set_current_index(idx)
        self.log(f"Глава: {title} @ {ch.get('start', '?')}")

    # --- Selection change ---
    def _on_selection_changed(self):
        items = self._scene.selectedItems()
        if items:
            item = items[0]
            if hasattr(item, "obj_id") and hasattr(item, "obj_data"):
                self._selected_item_id = item.obj_id
                self._props_panel.show_properties(item.obj_id, item.obj_data)
                return
        self._selected_item_id = None
        self._props_panel.clear_properties()

    # --- Layout changed ---
    def _on_layout_changed(self):
        self._layout_dirty = True

    # --- Engine commands via QProcess ---
    def _run_command(self, cmd_name):
        if self._active_process:
            QMessageBox.warning(self, "Занято", "Команда уже выполняется. Дождитесь завершения.")
            return

        cmds = {
            "scan": ["python", "bookforge.py", "scan"],
            "chapters": ["python", "bookforge.py", "chapters"],
            "waveform": ["python", "bookforge.py", "waveform"],
            "preview_contact": ["python", "bookforge.py", "preview", "--contact"],
            "check_preview": ["python", "bookforge.py", "check-preview"],
        }
        cmd = cmds.get(cmd_name)
        if not cmd:
            self.log(f"Неизвестная команда: {cmd_name}")
            return

        self.log(f"Запуск: {' '.join(cmd)}")
        self._active_process = QProcess(self)
        self._active_process.setWorkingDirectory(str(PROJECT_ROOT))
        self._active_process.readyReadStandardOutput.connect(self._on_process_output)
        self._active_process.readyReadStandardError.connect(self._on_process_error)
        self._active_process.finished.connect(lambda exit_code: self._on_process_finished(exit_code, cmd_name))
        self._active_process.start(cmd[0], cmd[1:])
        self._status_label_bar.setText("Выполняется процесс...")

    def _run_render_test(self):
        """Run render-test with selected duration."""
        if self._active_process:
            QMessageBox.warning(self, "Занято", "Команда уже выполняется. Дождитесь завершения.")
            return

        duration_text = self._test_duration_combo.currentText()
        if duration_text == "Текущая глава":
            if self._chapters and self._chapters_index < len(self._chapters):
                ch = self._chapters[self._chapters_index]
                start_s = timestr_to_seconds(ch.get("start", "0"))
                end_s = timestr_to_seconds(ch.get("end", str(start_s + 60)))
                seconds = int(end_s - start_s)
                if seconds < 10:
                    seconds = 60
            else:
                seconds = 60
                self.log("Глава не выбрана, используется 60 сек.")
        elif duration_text == "Свой":
            seconds = self._test_custom_spin.value()
        elif duration_text == "60 сек":
            seconds = 60
        else:
            minutes = int(duration_text.split()[0])
            seconds = minutes * 60

        cmd = ["python", "bookforge.py", "render-test", "--seconds", str(seconds), "--overwrite"]
        self.log(f"Запуск: {' '.join(cmd)}")

        self._active_process = QProcess(self)
        self._active_process.setWorkingDirectory(str(PROJECT_ROOT))
        self._active_process.readyReadStandardOutput.connect(self._on_process_output)
        self._active_process.readyReadStandardError.connect(self._on_process_error)
        self._active_process.finished.connect(lambda exit_code: self._on_render_test_finished(exit_code, seconds))
        self._active_process.start(cmd[0], cmd[1:])
        self._status_label_bar.setText("Тестовый рендер запущен...")

    def _on_render_test_finished(self, exit_code, seconds):
        self._on_process_finished(exit_code, f"render_test_{seconds}s")
        minutes = seconds // 60
        remainder = seconds % 60
        if remainder == 0:
            test_file = BUILD_DIR / f"test_{minutes}min.mp4"
        else:
            test_file = BUILD_DIR / f"test_{seconds}sec.mp4"
        if test_file.exists():
            self.log(f"✅ Результат тестового рендера: {test_file}")
        else:
            self.log("Файл тестового рендера не найден.")

    def _on_process_output(self):
        data = self._active_process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self.log(data.strip())

    def _on_process_error(self):
        data = self._active_process.readAllStandardError().data().decode("utf-8", errors="replace")
        self.log(f"[ERR] {data.strip()}")

    def _on_process_finished(self, exit_code, cmd_name):
        self.log(f"Команда '{cmd_name}' завершена (exit: {exit_code})")
        self._active_process = None
        self._status_label_bar.setText("Готово")

        if cmd_name in ("scan",):
            self._load_project()
        elif cmd_name == "chapters":
            self._load_chapters()
            self._update_project_info()
            self._rebuild_canvas()
            self._update_status()
        elif cmd_name == "waveform":
            self._load_waveform()
            self._rebuild_canvas()
        elif cmd_name == "preview_contact":
            self.log("Превью-лист сгенерирован. Проверьте папку сборки.")

    def _confirm_full_render(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("⚠️ Подтвердите полный рендер")
        dlg.setMinimumWidth(400)
        dlg.setStyleSheet(f"background-color: {DARK_PANEL}; color: {TEXT_PRIMARY};")
        layout = QVBoxLayout(dlg)
        lbl = QLabel(
            "⚠️  ПОЛНЫЙ РЕНДЕР  ⚠️\n\n"
            "Это займёт ОЧЕНЬ много времени (>1 часа).\n"
            "Приложение может зависнуть.\n\n"
            "Напишите RENDER FULL для подтверждения:")
        lbl.setStyleSheet(f"color: #ff6666; font-size: 13px; font-weight: bold;")
        layout.addWidget(lbl)
        inp = QLineEdit()
        inp.setStyleSheet(f"""
            background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
            border: 1px solid #661111; padding: 6px; font-size: 14px;
        """)
        layout.addWidget(inp)
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("⚠️ ПОДТВЕРДИТЬ РЕНДЕР")
        btn_ok.setStyleSheet(f"""
            QPushButton {{ background-color: #aa2222; color: white; padding: 8px 20px;
                         border: none; border-radius: 4px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #cc3333; }}
        """)
        btn_cancel = QPushButton("Отмена")
        btn_cancel.setStyleSheet(f"""
            QPushButton {{ background-color: {DARK_CARD}; color: {TEXT_SECONDARY};
                         border: 1px solid {BORDER_COLOR}; padding: 6px 16px; border-radius: 4px; }}
        """)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        def on_ok():
            if inp.text().strip() == "RENDER FULL":
                dlg.accept()
            else:
                QMessageBox.warning(dlg, "Отменено", "Напишите RENDER FULL точно.")

        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._run_command("render_full")
            self.log("⚠️ Полный рендер запущен (ручное подтверждение).")

    # --- Log ---
    def log(self, msg):
        self._log_widget.append(msg)
        print(msg)

    @property
    def canvas_scene(self):
        return self._scene


# =========================================================
#  Main entry
# =========================================================

def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon())
    # Load available fonts for the font family combo
    _ = get_windows_fonts()  # seed font database
    win = BookWunderwaffeStudio()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()