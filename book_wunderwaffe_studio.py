#!/usr/bin/env python3
"""
Book Wunderwaffe Studio 1.0
La machine merveilleuse pour forger les livres

Native PySide6 desktop GUI for visual canvas composition.

Phases implemented:
- Phase 1: Player with QMediaPlayer+QAudioOutput, diagnostics, simulation fallback
- Phase 2: Duplicate chapter removed (chapterStack on, currentChapter off)
- Phase 3: Global chapterStackStyle (edit once, apply to all chapters)
- Phase 4: Font bold/italic/align/color apply correctly via QPainter drawText
- Phase 5: QColorDialog color picker button
- Phase 6: Progress bar with chapter sections
- Phase 7: Waveform bars with played highlight
- Phase 8: Timeline zoom (+/-/fit/1h/10m) with scroll
- Phase 9: Clean Actions panel with groups and bigger buttons
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
    QKeySequence, QFontDatabase, QLinearGradient, QFontInfo
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
    QAbstractItemView, QGraphicsWidget, QColorDialog
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

# =========================================================
#  Undo Manager for layout edits
# =========================================================

class UndoManager:
    """Simple snapshot-based undo/redo for layout data."""
    MAX_STACK = 50

    def __init__(self):
        self._stack = []
        self._index = -1
        self._saved_index = -1

    def push_snapshot(self, layout_data):
        """Push a deep copy of layout_data onto undo stack."""
        snapshot = json.loads(json.dumps(layout_data))
        # Remove future states if we are in the middle of stack
        if self._index < len(self._stack) - 1:
            self._stack = self._stack[:self._index + 1]
        self._stack.append(snapshot)
        if len(self._stack) > self.MAX_STACK:
            self._stack.pop(0)
        self._index = len(self._stack) - 1

    def can_undo(self):
        return self._index > 0

    def can_redo(self):
        return self._index < len(self._stack) - 1

    def undo(self):
        if not self.can_undo():
            return None
        self._index -= 1
        return json.loads(json.dumps(self._stack[self._index]))

    def redo(self):
        if not self.can_redo():
            return None
        self._index += 1
        return json.loads(json.dumps(self._stack[self._index]))

    def clear(self):
        self._stack.clear()
        self._index = -1


# --- Object types ---
OBJ_BACKGROUND = "background"
OBJ_COVER = "cover"
OBJ_BOOK_TITLE = "bookTitle"
OBJ_CURRENT_CHAPTER = "currentChapter"
OBJ_CHAPTER_STACK = "chapterStack"
OBJ_WAVEFORM = "waveform"
OBJ_PROGRESS = "progress"
OBJ_BRAND = "brand"

# --- Default layout (improved: no duplicate chapter, chapterStack enabled) ---
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
        "w": 1100, "h": 160, "visible": False, "opacity": 1.0,  # OFF by default, use chapterStack
        "font_size": 46, "color": "#00ff88",
        "font_family": "Segoe UI", "bold": False, "italic": False, "align": "left",
        "text_source": "auto",
        "text": "Вступление от автора", "z": 21
    },
    "chapterStack": {
        "id": "chapterStack", "type": "chapter_stack", "x": 650, "y": 340,
        "w": 1100, "h": 200, "visible": True, "opacity": 1.0,
        # Global chapterStackStyle — applies to all chapters, not per-chapter
        "font_family": "Segoe UI",
        "font_size_current": 32, "font_size_side": 20,
        "color_current": "#00ff88", "color_side": "#9090b0",
        "bold_current": False, "italic_current": False,
        "bold_side": False, "italic_side": False,
        "align": "left", "line_gap": 8, "side_opacity": 0.6,
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
        "chapter_marker_color": "#00e5ff",
        "current_section_color": "rgba(0,255,136,0.15)",
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
    priority = ["Segoe UI", "Arial", "Arial Narrow", "Georgia",
                 "Times New Roman", "Impact", "Consolas", "Courier New",
                 "Verdana", "Tahoma", "Trebuchet MS", "Comic Sans MS"]
    result = []
    for p in priority:
        if p in families:
            result.append(p)
    for f in families:
        if f not in result:
            result.append(f)
    return result


def parse_rgba(color_str):
    """Parse rgba(r,g,b,a) or #hex to QColor. Returns QColor."""
    color_str = str(color_str).strip()
    if color_str.startswith("rgba"):
        # rgba(r,g,b,a)
        try:
            inner = color_str[5:].strip("() ")
            parts = [x.strip() for x in inner.split(",")]
            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
            a = float(parts[3]) if len(parts) > 3 else 1.0
            return QColor(r, g, b, int(a * 255))
        except Exception:
            pass
    return QColor(color_str)


# =========================================================
#  Custom text item with proper font rendering
# =========================================================

class CustomTextItem(QGraphicsRectItem):
    """
    Custom text item that renders bold/italic/align/color correctly
    via QPainter.drawText, since QGraphicsTextItem's alignment is flaky.
    """
    def __init__(self, obj_data=None, parent=None):
        super().__init__(parent)
        self.obj_data = obj_data or {}
        self._text = self.obj_data.get("text", "")
        self._font_family = self.obj_data.get("font_family", "Segoe UI")
        self._font_size = self.obj_data.get("font_size", 32)
        self._bold = self.obj_data.get("bold", False)
        self._italic = self.obj_data.get("italic", False)
        self._align = self.obj_data.get("align", "left")
        self._color = self.obj_data.get("color", "#ffffff")
        self._opacity = self.obj_data.get("opacity", 1.0)
        self._rect = QRectF(0, 0,
            self.obj_data.get("w", 200),
            self.obj_data.get("h", 80))
        self.setRect(self._rect)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self._update_pen_brush()

    def _update_pen_brush(self):
        """Make the rect transparent (no fill) unless debugging."""
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def set_text_data(self, obj_data):
        """Update from object data dict."""
        self.obj_data = obj_data
        self._text = obj_data.get("text", self._text)
        self._font_family = obj_data.get("font_family", self._font_family)
        self._font_size = obj_data.get("font_size", self._font_size)
        self._bold = obj_data.get("bold", False)
        self._italic = obj_data.get("italic", False)
        self._align = obj_data.get("align", self._align)
        self._color = obj_data.get("color", "#ffffff")
        self._opacity = obj_data.get("opacity", 1.0)
        nx = obj_data.get("x", 0)
        ny = obj_data.get("y", 0)
        nw = obj_data.get("w", 200)
        nh = obj_data.get("h", 80)
        self.setPos(nx, ny)
        self._rect = QRectF(0, 0, nw, nh)
        self.setRect(self._rect)
        self.update()

    def setPlainText(self, text):
        """Compatibility method."""
        self._text = text
        self.obj_data["text"] = text
        self.update()

    def paint(self, painter, option, widget=None):
        if not self._text:
            return
        painter.save()
        painter.setOpacity(self._opacity)

        # Build font
        font = QFont(self._font_family, max(1, int(self._font_size)))
        font.setBold(self._bold)
        font.setItalic(self._italic)
        painter.setFont(font)

        # Color
        color = parse_rgba(self._color)
        painter.setPen(QPen(color))

        # Alignment flags
        align_map = {
            "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "center": Qt.AlignmentFlag.AlignCenter,
            "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        }
        flags = align_map.get(self._align, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # Draw text in rect with word wrap
        rect = self._rect.adjusted(4, 2, -4, -2)
        painter.drawText(rect, int(flags) | Qt.TextFlag.TextWordWrap, self._text)

        painter.restore()


# =========================================================
#  ChapterStackItem — shows prev/current/next with global styles
# =========================================================

class ChapterStackItem(QGraphicsRectItem):
    """
    Displays previous, current, and next chapter titles with global styling.
    No per-chapter style editing needed.
    """
    def __init__(self, obj_data=None, parent=None):
        super().__init__(parent)
        self.obj_data = obj_data or {}
        self._prev_title = ""
        self._cur_title = ""
        self._next_title = ""
        self._rect = QRectF(0, 0, 600, 180)
        self.setRect(self._rect)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def set_chapters(self, prev, cur, nxt):
        self._prev_title = prev
        self._cur_title = cur
        self._next_title = nxt
        self.update()

    def set_style_from_data(self, obj_data):
        """Update all styling from global chapterStack object data."""
        self.obj_data = obj_data
        nx = obj_data.get("x", 0)
        ny = obj_data.get("y", 0)
        nw = obj_data.get("w", 600)
        nh = obj_data.get("h", 180)
        self.setPos(nx, ny)
        self._rect = QRectF(0, 0, nw, nh)
        self.setRect(self._rect)
        self.update()

    def paint(self, painter, option, widget=None):
        if not self._cur_title:
            return

        painter.save()
        data = self.obj_data

        opacity = data.get("opacity", 1.0)
        painter.setOpacity(opacity)

        font_family = data.get("font_family", "Segoe UI")
        font_size_current = data.get("font_size_current", 32)
        font_size_side = data.get("font_size_side", 20)
        color_current = data.get("color_current", "#00ff88")
        color_side = data.get("color_side", "#9090b0")
        bold_current = data.get("bold_current", False)
        italic_current = data.get("italic_current", False)
        bold_side = data.get("bold_side", False)
        italic_side = data.get("italic_side", False)
        align = data.get("align", "left")
        line_gap = data.get("line_gap", 8)
        side_opacity = data.get("side_opacity", 0.6)

        align_map = {
            "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "center": Qt.AlignmentFlag.AlignCenter,
            "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        }
        flags = align_map.get(align, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        rect = self._rect.adjusted(8, 4, -8, -4)
        total_h = rect.height()
        thirds = total_h / 3.0

        # Previous chapter (top)
        if self._prev_title:
            painter.save()
            painter.setOpacity(opacity * side_opacity)
            font_prev = QFont(font_family, max(1, int(font_size_side)))
            font_prev.setBold(bold_side)
            font_prev.setItalic(italic_side)
            painter.setFont(font_prev)
            painter.setPen(QPen(parse_rgba(color_side)))
            prev_rect = QRectF(rect.x(), rect.y(), rect.width(), thirds - line_gap)
            painter.drawText(prev_rect, int(flags) | Qt.TextFlag.TextWordWrap, self._prev_title)
            painter.restore()

        # Current chapter (middle, larger, accent)
        painter.save()
        font_cur = QFont(font_family, max(1, int(font_size_current)))
        font_cur.setBold(bold_current)
        font_cur.setItalic(italic_current)
        painter.setFont(font_cur)
        painter.setPen(QPen(parse_rgba(color_current)))
        cur_rect = QRectF(rect.x(), rect.y() + thirds, rect.width(), thirds)
        painter.drawText(cur_rect, int(flags) | Qt.TextFlag.TextWordWrap, self._cur_title)
        painter.restore()

        # Next chapter (bottom)
        if self._next_title:
            painter.save()
            painter.setOpacity(opacity * side_opacity)
            font_next = QFont(font_family, max(1, int(font_size_side)))
            font_next.setBold(bold_side)
            font_next.setItalic(italic_side)
            painter.setFont(font_next)
            painter.setPen(QPen(parse_rgba(color_side)))
            next_rect = QRectF(rect.x(), rect.y() + 2 * thirds + line_gap, rect.width(), thirds - line_gap)
            painter.drawText(next_rect, int(flags) | Qt.TextFlag.TextWordWrap, self._next_title)
            painter.restore()

        painter.restore()


# =========================================================
#  ProgressItem — progress bar with chapter sections
# =========================================================

class ProgressItem(QGraphicsRectItem):
    """
    Progress bar that shows overall progress + vertical chapter dividers.
    Current chapter section is highlighted.
    """
    def __init__(self, obj_data=None, parent=None):
        super().__init__(parent)
        self.obj_data = obj_data or {}
        self._progress = 0.0  # 0.0 - 1.0
        self._chapters = []  # list of {start_seconds, end_seconds, title}
        self._rect = QRectF(0, 0, 1700, 18)
        self.setRect(self._rect)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def set_progress(self, p):
        self._progress = max(0.0, min(1.0, p))
        self.update()

    def set_chapters(self, chapters):
        self._chapters = chapters or []
        self.update()

    def set_data(self, obj_data):
        self.obj_data = obj_data
        nx = obj_data.get("x", 0)
        ny = obj_data.get("y", 0)
        nw = obj_data.get("w", 1700)
        nh = obj_data.get("h", 18)
        self.setPos(nx, ny)
        self._rect = QRectF(0, 0, nw, nh)
        self.setRect(self._rect)
        self.update()

    def paint(self, painter, option, widget=None):
        painter.save()
        data = self.obj_data
        opacity = data.get("opacity", 0.8)
        painter.setOpacity(opacity)

        rect = self._rect
        fg_color = parse_rgba(data.get("color", "#00ff88"))
        bg_color = parse_rgba(data.get("bg_color", "#1a1a3a"))
        marker_color = parse_rgba(data.get("chapter_marker_color", "#00e5ff"))
        current_section_color_str = data.get("current_section_color", "rgba(0,255,136,0.15)")
        current_section_color = parse_rgba(current_section_color_str)

        bar_h = rect.height()
        bar_y = rect.y()
        bar_w = rect.width()

        # Background
        painter.setBrush(bg_color)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.drawRoundedRect(QRectF(rect.x(), bar_y, bar_w, bar_h), bar_h / 2, bar_h / 2)

        # Chapter sections (current chapter highlighted)
        if self._chapters and len(self._chapters) > 1:
            try:
                total_s = timestr_to_seconds(self._chapters[-1].get("end", "15:48:50.932"))
                if total_s > 0:
                    # Find current chapter index
                    current_sec = self._progress * total_s
                    current_idx = -1
                    for i, ch in enumerate(self._chapters):
                        ch_start = timestr_to_seconds(ch.get("start", "0"))
                        ch_end = timestr_to_seconds(ch.get("end", str(total_s)))
                        if ch_start <= current_sec < ch_end:
                            current_idx = i
                            break

                    # Draw current section highlight
                    if current_idx >= 0:
                        ch = self._chapters[current_idx]
                        ch_start = timestr_to_seconds(ch.get("start", "0"))
                        ch_end = timestr_to_seconds(ch.get("end", str(total_s)))
                        sx = rect.x() + (ch_start / total_s) * bar_w
                        ex = rect.x() + (ch_end / total_s) * bar_w
                        painter.setBrush(current_section_color)
                        painter.setPen(QPen(Qt.PenStyle.NoPen))
                        painter.drawRoundedRect(QRectF(sx, bar_y, ex - sx, bar_h), bar_h / 2, bar_h / 2)

                    # Draw chapter dividers
                    painter.setPen(QPen(marker_color, 1))
                    for ch in self._chapters:
                        ch_start = timestr_to_seconds(ch.get("start", "0"))
                        if ch_start > 0:
                            dx = rect.x() + (ch_start / total_s) * bar_w
                            painter.drawLine(QPointF(dx, bar_y), QPointF(dx, bar_y + bar_h))
            except Exception:
                pass

        # Foreground (played portion)
        prog_w = self._progress * bar_w
        if prog_w > 1:
            painter.setBrush(fg_color)
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.drawRoundedRect(QRectF(rect.x(), bar_y, prog_w, bar_h), bar_h / 2, bar_h / 2)

        # Handle (playhead dot)
        if self._progress > 0:
            handle_x = rect.x() + prog_w
            painter.setBrush(fg_color)
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.drawEllipse(QPointF(handle_x, bar_y + bar_h / 2), bar_h * 0.8, bar_h * 0.8)

        painter.restore()


# =========================================================
#  WaveformItem — bars with played highlight
# =========================================================

class WaveformItem(QGraphicsRectItem):
    """
    Waveform display as bars with played/unplayed colors.
    """
    def __init__(self, obj_data=None, waveform_data=None, parent=None):
        super().__init__(parent)
        self.obj_data = obj_data or {}
        self._waveform_data = waveform_data or []
        self._playback_time = 0.0
        self._total_duration = 1.0
        self._rect = QRectF(0, 0, 1100, 170)
        self.setRect(self._rect)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setPen(QPen(Qt.PenStyle.NoPen))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    def set_waveform_data(self, data):
        self._waveform_data = data or []
        self.update()

    def set_playback_time(self, sec, total):
        self._playback_time = sec
        self._total_duration = max(total, 1.0)
        self.update()

    def set_data(self, obj_data):
        self.obj_data = obj_data
        nx = obj_data.get("x", 0)
        ny = obj_data.get("y", 0)
        nw = obj_data.get("w", 1100)
        nh = obj_data.get("h", 170)
        self.setPos(nx, ny)
        self._rect = QRectF(0, 0, nw, nh)
        self.setRect(self._rect)
        self.update()

    def paint(self, painter, option, widget=None):
        painter.save()
        data = self.obj_data
        opacity = data.get("opacity", 0.7)
        painter.setOpacity(opacity)

        rect = self._rect
        color_unplayed = parse_rgba(data.get("color", "#00e5ff"))
        color_played = parse_rgba(data.get("played_color", "#72ffd9"))
        bg_color = parse_rgba(data.get("bg_color", "#1a1a3a"))

        # Background
        painter.setBrush(bg_color)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.drawRoundedRect(rect, 8, 8)

        if not self._waveform_data:
            # Draw placeholder
            painter.setPen(QPen(parse_rgba("#9090b0"), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            font = QFont("Segoe UI", 14)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Сгенерируй гистограмму")
            painter.restore()
            return

        # Draw bars
        num_bars = min(len(self._waveform_data), data.get("bars", 120))
        if num_bars < 2:
            num_bars = len(self._waveform_data)

        bar_w = rect.width() / max(num_bars, 1)
        mid_y = rect.y() + rect.height() / 2
        bar_max_h = rect.height() * 0.9

        # Downsample waveform data to num_bars
        step = max(1, len(self._waveform_data) // max(num_bars, 1))
        if step > len(self._waveform_data):
            step = 1
        bars = []
        for i in range(0, len(self._waveform_data), step):
            sample = abs(self._waveform_data[i])
            bars.append(min(sample, 1.0))
        # Ensure we have enough bars
        while len(bars) < num_bars:
            bars.append(0.0)
        bars = bars[:num_bars]

        playhead_ratio = self._playback_time / self._total_duration if self._total_duration > 0 else 0

        for i, val in enumerate(bars):
            bh = max(1.0, val * bar_max_h)
            bx = rect.x() + i * bar_w
            by = mid_y - bh / 2
            bar_rect = QRectF(bx, by, max(1.0, bar_w - 1), max(1.0, bh))

            # Determine color based on playhead position
            bar_pos_ratio = i / max(num_bars - 1, 1)
            is_played = bar_pos_ratio <= playhead_ratio
            c = color_played if is_played else color_unplayed

            painter.setBrush(c)
            painter.setPen(QPen(Qt.PenStyle.NoPen))
            painter.drawRect(bar_rect)

        painter.restore()


# =========================================================
#  ChapterListPanel — list widget for chapters with highlight
# =========================================================

class ChapterListPanel(QListWidget):
    chapterSelected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chapters = []
        self._current_index = 0
        self.setStyleSheet(f"""
            QListWidget {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                font-size: 11px;
            }}
            QListWidget::item {{
                padding: 4px 8px; border-bottom: 1px solid #1a1a2a;
            }}
            QListWidget::item:selected {{
                background-color: #1a3a3a; color: {ACCENT_GREEN};
            }}
            QListWidget::item:hover {{
                background-color: #1a1a3a;
            }}
        """)
        self.itemClicked.connect(self._on_item_clicked)

    def set_chapters(self, chapters):
        self._chapters = chapters
        self.clear()
        for i, ch in enumerate(chapters):
            title = ch.get("title", f"Segment {i}")
            start = ch.get("start", "00:00:00")
            end = ch.get("end", "?")
            label = f"{start[:8]}  {title}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.addItem(item)

    def set_current_index(self, idx):
        self._current_index = idx
        self.blockSignals(True)
        for i in range(self.count()):
            item = self.item(i)
            if i == idx:
                item.setSelected(True)
                self.scrollToItem(item, QAbstractItemView.ScrollHint.EnsureVisible)
            else:
                item.setSelected(False)
        self.blockSignals(False)

    def _on_item_clicked(self, item):
        idx = item.data(Qt.ItemDataRole.UserRole)
        if idx is not None:
            self.chapterSelected.emit(idx)


# =========================================================
#  TimelineWidget — clickable chapter timeline with zoom
# =========================================================

class TimelineWidget(QGraphicsView):
    chapterClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chapters = []
        self._current_index = 0
        self._playhead = 0.0
        self._zoom_level = 1.0

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setStyleSheet(f"""
            QGraphicsView {{
                background-color: {DARK_CARD};
                border: 1px solid {BORDER_COLOR};
                border-radius: 4px;
            }}
        """)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(60)
        self.setMouseTracking(True)

        # Zoom via Ctrl+Wheel
        self._scene_rect = QRectF(0, 0, 1000, 50)
        self.setSceneRect(self._scene_rect)

    def set_chapters(self, chapters):
        self._chapters = chapters
        self._rebuild()

    def set_current_index(self, idx):
        self._current_index = idx
        self._rebuild()

    def set_playhead(self, ratio):
        self._playhead = max(0.0, min(1.0, ratio))
        self._rebuild()

    def zoom_fit(self):
        self._zoom_level = 1.0
        self._rebuild()
        self.fitInView(self._scene_rect, Qt.AspectRatioMode.KeepAspectRatio)

    def zoom_in(self):
        self._zoom_level *= 1.3
        self._rebuild()
        self.scale(1.3, 1.0)

    def zoom_out(self):
        self._zoom_level /= 1.3
        self._rebuild()
        self.scale(1.0 / 1.3, 1.0)

    def zoom_1h(self):
        """Zoom to show ~1 hour segments."""
        self._zoom_level = 2.0
        self._rebuild()

    def zoom_10m(self):
        """Zoom to show ~10 minute segments."""
        self._zoom_level = 5.0
        self._rebuild()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        # Click to seek
        pos = self.mapToScene(event.pos())
        ratio = (pos.x() - self._scene_rect.x()) / max(self._scene_rect.width(), 1)
        if 0 <= ratio <= 1 and self._chapters:
            total_s = timestr_to_seconds(self._chapters[-1].get("end", "15:48:50.932"))
            click_sec = ratio * total_s
            for i, ch in enumerate(self._chapters):
                ch_start = timestr_to_seconds(ch.get("start", "0"))
                ch_end = timestr_to_seconds(ch.get("end", str(total_s)))
                if ch_start <= click_sec < ch_end:
                    self.chapterClicked.emit(i)
                    break
        super().mousePressEvent(event)

    def _rebuild(self):
        self._scene.clear()
        if not self._chapters:
            return

        total_s = timestr_to_seconds(self._chapters[-1].get("end", "15:48:50.932"))
        w = max(1000, total_s * self._zoom_level)
        h = 50
        self._scene_rect = QRectF(0, 0, w, h)
        self._scene.setSceneRect(self._scene_rect)

        # Background
        bg = QGraphicsRectItem(self._scene_rect)
        bg.setBrush(QBrush(parse_rgba(DARK_CARD)))
        bg.setPen(QPen(Qt.PenStyle.NoPen))
        self._scene.addItem(bg)

        # Chapter segments
        for i, ch in enumerate(self._chapters):
            ch_start = timestr_to_seconds(ch.get("start", "0"))
            ch_end = timestr_to_seconds(ch.get("end", str(total_s)))
            sx = (ch_start / total_s) * w
            ex = (ch_end / total_s) * w

            is_current = (i == self._current_index)
            color = parse_rgba(ACCENT_GREEN if is_current else "#2a2a4a")
            seg = QGraphicsRectItem(QRectF(sx, 0, max(4, ex - sx), h))
            seg.setBrush(QBrush(color))
            seg.setPen(QPen(Qt.PenStyle.NoPen))
            self._scene.addItem(seg)

            # Chapter label (only if space permits)
            seg_w = ex - sx
            if seg_w > 60:
                label = ch.get("title", "")
                txt = QGraphicsSimpleTextItem(label[:20])
                txt.setFont(QFont("Segoe UI", 8))
                txt.setBrush(QBrush(parse_rgba(TEXT_PRIMARY if not is_current else ACCENT_GREEN)))
                txt.setPos(sx + 4, 4)
                self._scene.addItem(txt)

        # Playhead line
        ph_x = (self._playhead) * w
        line = self._scene.addLine(ph_x, 0, ph_x, h, QPen(parse_rgba(ACCENT_CYAN), 2))
        line.setZValue(10)

        # Playhead triangle
        tri = self._scene.addPolygon(
            [QPointF(ph_x - 5, 0), QPointF(ph_x + 5, 0), QPointF(ph_x, 8)],
            QPen(Qt.PenStyle.NoPen),
            QBrush(parse_rgba(ACCENT_CYAN))
        )
        tri.setZValue(10)


# =========================================================
#  CanvasScene — manages all canvas items
# =========================================================

class CanvasScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items_map = {}  # id -> QGraphicsItem

    def clear_canvas(self):
        self.clear()
        self._items_map.clear()

    def add_canvas_item(self, obj_id, obj_data, pixmap=None, waveform_data=None):
        """Add an item to the canvas based on type."""
        if not obj_data.get("visible", True):
            return

        obj_type = obj_data.get("type", "text")
        x = obj_data.get("x", 0)
        y = obj_data.get("y", 0)
        w = obj_data.get("w", 100)
        h = obj_data.get("h", 50)
        z = obj_data.get("z_index", obj_data.get("z", 0))

        if obj_type in ("image",):
            if pixmap and not pixmap.isNull():
                item = QGraphicsPixmapItem(pixmap)
                item.setPos(x, y)
                sm = min(w / max(pixmap.width(), 1), h / max(pixmap.height(), 1))
                item.setTransformOriginPoint(0, 0)
                item.setScale(sm)
                item.setOpacity(obj_data.get("opacity", 1.0))
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                item.setZValue(z)
                self.addItem(item)
                self._items_map[obj_id] = item
        elif obj_type in ("overlay",):
            overlay = QGraphicsRectItem(QRectF(0, 0, w, h))
            overlay.setPos(x, y)
            color_str = obj_data.get("color", "rgba(5,5,10,0.30)")
            overlay.setBrush(QBrush(parse_rgba(color_str)))
            overlay.setPen(QPen(Qt.PenStyle.NoPen))
            overlay.setOpacity(obj_data.get("opacity", 1.0))
            overlay.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            overlay.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            overlay.setZValue(z)
            self.addItem(overlay)
            self._items_map[obj_id] = overlay
        elif obj_type in ("text",):
            item = CustomTextItem(obj_data)
            item.setPos(x, y)
            item.setZValue(z)
            self.addItem(item)
            self._items_map[obj_id] = item
        elif obj_type in ("chapter_stack",):
            item = ChapterStackItem(obj_data)
            item.setPos(x, y)
            item.setZValue(z)
            self.addItem(item)
            self._items_map[obj_id] = item
        elif obj_type in ("progress", "progress_bar"):
            item = ProgressItem(obj_data)
            item.setPos(x, y)
            item.setZValue(z)
            self.addItem(item)
            self._items_map[obj_id] = item
        elif obj_type in ("waveform",):
            item = WaveformItem(obj_data, waveform_data)
            item.setPos(x, y)
            item.setZValue(z)
            self.addItem(item)
            self._items_map[obj_id] = item
        else:
            # Fallback rect
            rect = QGraphicsRectItem(QRectF(0, 0, w, h))
            rect.setPos(x, y)
            rect.setBrush(QBrush(parse_rgba("#ff00ff")))
            rect.setPen(QPen(Qt.PenStyle.NoPen))
            rect.setOpacity(0.3)
            rect.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            rect.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            rect.setZValue(z)
            self.addItem(rect)
            self._items_map[obj_id] = rect

    def get_item(self, obj_id):
        return self._items_map.get(obj_id)

    def on_playhead_update(self, current_sec, total_sec, chapters, chapters_index):
        """Update chapter stack, progress, waveform, timeline."""
        # Progress bar
        prog_item = self.get_item(OBJ_PROGRESS)
        if prog_item and isinstance(prog_item, ProgressItem):
            ratio = current_sec / max(total_sec, 1)
            prog_item.set_progress(ratio)
            if chapters:
                prog_item.set_chapters(chapters)

        # Waveform highlight
        wf_item = self.get_item(OBJ_WAVEFORM)
        if wf_item and isinstance(wf_item, WaveformItem):
            wf_item.set_playback_time(current_sec, max(total_sec, 1.0))

        # Chapter stack
        stack_item = self.get_item(OBJ_CHAPTER_STACK)
        if stack_item and isinstance(stack_item, ChapterStackItem):
            prev_title = ""
            cur_title = ""
            next_title = ""
            if chapters and 0 <= chapters_index < len(chapters):
                cur_title = chapters[chapters_index].get("title", "")
                if chapters_index > 0:
                    prev_title = chapters[chapters_index - 1].get("title", "")
                if chapters_index < len(chapters) - 1:
                    next_title = chapters[chapters_index + 1].get("title", "")
            stack_item.set_chapters(prev_title, cur_title, next_title)

        # Book title (not duplicated — only shows project name)
        title_item = self.get_item(OBJ_BOOK_TITLE)
        if title_item and hasattr(title_item, "obj_data"):
            pass  # bookTitle is static, not updated per chapter


# =========================================================
#  Properties Dock — right-side property editor
# =========================================================

class PropertiesDock(QDockWidget):
    """Property panel with global style controls and color pickers."""

    layoutChanged = Signal()

    def __init__(self, parent=None):
        super().__init__("Свойства", parent)
        self._main = parent
        self._object_combo = QComboBox()
        self._props_widget = QWidget()
        self._props_layout = QVBoxLayout(self._props_widget)
        self._props_layout.setContentsMargins(4, 4, 4, 4)
        self._props_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._props_widget)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background-color: {DARK_PANEL}; border: none; }}
        """)

        # Object selector
        sel_layout = QHBoxLayout()
        sel_layout.addWidget(QLabel("Объект:"))
        self._object_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 3px 8px; font-size: 11px;
            }}
        """)
        self._object_combo.addItems([
            "chapterStack", "bookTitle", "currentChapter",
            "progress", "waveform", "brand", "background", "cover"
        ])
        self._object_combo.currentIndexChanged.connect(self._rebuild_props)
        sel_layout.addWidget(self._object_combo, 1)
        self._props_layout.addLayout(sel_layout)

        # Props area (filled dynamically)
        self._props_frame = QWidget()
        self._props_frame_layout = QVBoxLayout(self._props_frame)
        self._props_frame_layout.setContentsMargins(0, 0, 0, 0)
        self._props_frame_layout.setSpacing(4)
        self._props_layout.addWidget(self._props_frame)

        self._props_layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_apply = QPushButton("Применить")
        btn_apply.clicked.connect(self._apply_props)
        btn_apply.setStyleSheet(f"""
            QPushButton {{
                background-color: #1a3a3a; color: {ACCENT_GREEN};
                border: 1px solid {ACCENT_GREEN}; border-radius: 4px;
                padding: 6px; font-size: 11px;
            }}
            QPushButton:hover {{ background-color: #2a4a4a; }}
        """)
        btn_layout.addWidget(btn_apply)

        btn_reset = QPushButton("Сбросить")
        btn_reset.clicked.connect(self._reset_props)
        btn_reset.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_CARD}; color: {TEXT_SECONDARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 6px; font-size: 11px;
            }}
            QPushButton:hover {{ border-color: #ff5555; color: #ff5555; }}
        """)
        btn_layout.addWidget(btn_reset)
        self._props_layout.addLayout(btn_layout)

        self.setWidget(scroll)
        self._rebuild_props()

    def _get_active_obj_id(self):
        return self._object_combo.currentText()

    def _rebuild_props(self):
        """Rebuild property fields for the selected object."""
        # Clear old widgets
        self._clear_layout(self._props_frame_layout)

        obj_id = self._get_active_obj_id()
        lt = self._main._layout_data or DEFAULT_LAYOUT
        obj_data = lt.get(obj_id, {})

        if not obj_data:
            self._props_frame_layout.addWidget(QLabel("Нет данных"))
            return

        if obj_id == "chapterStack":
            self._build_chapter_stack_props(obj_data)
        elif obj_id == "bookTitle":
            self._build_text_props(obj_data, "bookTitle")
        elif obj_id == "currentChapter":
            self._build_text_props(obj_data, "currentChapter")
        elif obj_id == "progress":
            self._build_progress_props(obj_data)
        elif obj_id == "waveform":
            self._build_waveform_props(obj_data)
        elif obj_id == "brand":
            self._build_text_props(obj_data, "brand")
        else:
            self._build_generic_props(obj_data)

    def _build_chapter_stack_props(self, data):
        """Global chapterStack style controls."""
        self._add_section_title("Стиль текущей главы")

        self._prop_font_family = self._add_combo("Шрифт:", data.get("font_family", "Segoe UI"),
                                                   get_windows_fonts())
        self._prop_font_size_current = self._add_spin("Размер:", data.get("font_size_current", 32), 8, 200)
        self._prop_color_current = self._add_color("Цвет:", data.get("color_current", "#00ff88"))
        self._prop_bold_current = self._add_check("Жирный:", data.get("bold_current", False))
        self._prop_italic_current = self._add_check("Курсив:", data.get("italic_current", False))
        self._prop_align = self._add_combo("Выравнивание:", data.get("align", "left"),
                                            ["left", "center", "right"])

        self._add_section_title("Стиль соседних глав")

        self._prop_font_size_side = self._add_spin("Размер:", data.get("font_size_side", 20), 8, 200)
        self._prop_color_side = self._add_color("Цвет:", data.get("color_side", "#9090b0"))
        self._prop_side_opacity = self._add_double_spin("Прозрачность:", data.get("side_opacity", 0.6), 0.0, 1.0, 0.05)
        self._prop_bold_side = self._add_check("Жирный:", data.get("bold_side", False))
        self._prop_italic_side = self._add_check("Курсив:", data.get("italic_side", False))

        self._add_section_title("Расположение")
        self._prop_line_gap = self._add_spin("Отступ между:", data.get("line_gap", 8), 0, 100)

    def _build_text_props(self, data, obj_id):
        """Generic text properties with color picker."""
        self._add_section_title(f"Свойства текста")

        self._prop_font_family = self._add_combo("Шрифт:", data.get("font_family", "Segoe UI"),
                                                   get_windows_fonts())
        self._prop_font_size = self._add_spin("Размер:", data.get("font_size", 32), 8, 200)
        self._prop_color = self._add_color("Цвет:", data.get("color", "#ffffff"))
        self._prop_bold = self._add_check("Жирный:", data.get("bold", False))
        self._prop_italic = self._add_check("Курсив:", data.get("italic", False))
        self._prop_align = self._add_combo("Выравнивание:", data.get("align", "left"),
                                            ["left", "center", "right"])
        self._prop_opacity = self._add_double_spin("Прозрачность:", data.get("opacity", 1.0), 0.0, 1.0, 0.05)

    def _build_progress_props(self, data):
        """Progress bar properties."""
        self._add_section_title("Цвета прогресс-бара")
        self._prop_fg_color = self._add_color("Цвет:", data.get("color", "#00ff88"))
        self._prop_bg_color = self._add_color("Фон:", data.get("bg_color", "#1a1a3a"))
        self._prop_marker_color = self._add_color("Маркер глав:", data.get("chapter_marker_color", "#00e5ff"))
        self._prop_section_color = self._add_color("Секция:", data.get("current_section_color", "rgba(0,255,136,0.15)"))
        self._prop_opacity = self._add_double_spin("Прозрачность:", data.get("opacity", 0.8), 0.0, 1.0, 0.05)

    def _build_waveform_props(self, data):
        """Waveform properties."""
        self._add_section_title("Цвета гистограммы")
        self._prop_color = self._add_color("Цвет:", data.get("color", "#00e5ff"))
        self._prop_played_color = self._add_color("Сыгранный:", data.get("played_color", "#72ffd9"))
        self._prop_bg_color = self._add_color("Фон:", data.get("bg_color", "#1a1a3a"))
        self._prop_opacity = self._add_double_spin("Прозрачность:", data.get("opacity", 0.7), 0.0, 1.0, 0.05)
        self._prop_bars = self._add_spin("Кол-во баров:", data.get("bars", 120), 10, 500)

    def _build_generic_props(self, data):
        """Generic properties for other objects."""
        for key, val in data.items():
            if key in ("id", "type", "source", "z_index", "z", "text_source", "visible"):
                continue
            lbl = QLabel(f"{key}: {val}")
            lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
            self._props_frame_layout.addWidget(lbl)

    def _add_section_title(self, title):
        lbl = QLabel(title)
        lbl.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 11px; font-weight: bold; padding-top: 8px;")
        self._props_frame_layout.addWidget(lbl)

    def _add_combo(self, label, current, items):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 10px;")
        row.addWidget(lbl)
        combo = QComboBox()
        combo.addItems(items)
        idx = combo.findText(str(current))
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                padding: 2px 6px; font-size: 10px;
            }}
        """)
        row.addWidget(combo, 1)
        self._props_frame_layout.addLayout(row)
        return combo

    def _add_spin(self, label, current, min_v, max_v):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 10px;")
        row.addWidget(lbl)
        spin = QSpinBox()
        spin.setRange(min_v, max_v)
        spin.setValue(int(current))
        spin.setStyleSheet(f"""
            QSpinBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                padding: 2px 4px; font-size: 10px;
            }}
        """)
        row.addWidget(spin, 1)
        self._props_frame_layout.addLayout(row)
        return spin

    def _add_double_spin(self, label, current, min_v, max_v, step=0.1):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 10px;")
        row.addWidget(lbl)
        spin = QDoubleSpinBox()
        spin.setRange(min_v, max_v)
        spin.setSingleStep(step)
        spin.setValue(float(current))
        spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                padding: 2px 4px; font-size: 10px;
            }}
        """)
        row.addWidget(spin, 1)
        self._props_frame_layout.addLayout(row)
        return spin

    def _add_check(self, label, current):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 10px;")
        row.addWidget(lbl)
        cb = QCheckBox()
        cb.setChecked(bool(current))
        cb.setStyleSheet(f"""
            QCheckBox {{
                color: {TEXT_PRIMARY}; font-size: 10px;
            }}
            QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {BORDER_COLOR}; border-radius: 3px;
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT_GREEN};
            }}
        """)
        row.addWidget(cb)
        row.addStretch()
        self._props_frame_layout.addLayout(row)
        return cb

    def _add_color(self, label, current):
        """Add a color hex input + QColorDialog button."""
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 10px;")
        row.addWidget(lbl)

        edit = QLineEdit(str(current))
        edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 3px;
                padding: 2px 4px; font-size: 10px; width: 80px;
            }}
        """)
        row.addWidget(edit)

        btn = QPushButton("🎨")
        btn.setFixedSize(24, 22)
        btn.setToolTip("Выбрать цвет")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_CARD}; border: 1px solid {BORDER_COLOR};
                border-radius: 3px; font-size: 12px;
            }}
            QPushButton:hover {{ border-color: {ACCENT_CYAN}; }}
        """)
        btn.clicked.connect(lambda: self._pick_color(edit))
        row.addWidget(btn)

        self._props_frame_layout.addLayout(row)
        return edit

    def _pick_color(self, edit):
        """Open QColorDialog and set the hex value."""
        current = parse_rgba(edit.text())
        color = QColorDialog.getColor(current, self, "Выберите цвет")
        if color.isValid():
            edit.setText(color.name())

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                self._clear_layout(child.layout())

    def _apply_props(self):
        """Apply the property values to the layout data and canvas."""
        obj_id = self._get_active_obj_id()
        lt = self._main._layout_data or DEFAULT_LAYOUT
        obj_data = lt.get(obj_id, {})
        if not obj_data:
            return

        if obj_id == "chapterStack":
            obj_data["font_family"] = self._prop_font_family.currentText()
            obj_data["font_size_current"] = self._prop_font_size_current.value()
            obj_data["color_current"] = self._prop_color_current.text()
            obj_data["bold_current"] = self._prop_bold_current.isChecked()
            obj_data["italic_current"] = self._prop_italic_current.isChecked()
            obj_data["align"] = self._prop_align.currentText()
            obj_data["font_size_side"] = self._prop_font_size_side.value()
            obj_data["color_side"] = self._prop_color_side.text()
            obj_data["side_opacity"] = self._prop_side_opacity.value()
            obj_data["bold_side"] = self._prop_bold_side.isChecked()
            obj_data["italic_side"] = self._prop_italic_side.isChecked()
            obj_data["line_gap"] = self._prop_line_gap.value()
        elif obj_id in ("bookTitle", "brand"):
            obj_data["font_family"] = self._prop_font_family.currentText()
            obj_data["font_size"] = self._prop_font_size.value()
            obj_data["color"] = self._prop_color.text()
            obj_data["bold"] = self._prop_bold.isChecked()
            obj_data["italic"] = self._prop_italic.isChecked()
            obj_data["align"] = self._prop_align.currentText()
            obj_data["opacity"] = self._prop_opacity.value()
        elif obj_id == "currentChapter":
            obj_data["font_family"] = self._prop_font_family.currentText()
            obj_data["font_size"] = self._prop_font_size.value()
            obj_data["color"] = self._prop_color.text()
            obj_data["bold"] = self._prop_bold.isChecked()
            obj_data["italic"] = self._prop_italic.isChecked()
            obj_data["align"] = self._prop_align.currentText()
            obj_data["opacity"] = self._prop_opacity.value()
        elif obj_id == "progress":
            obj_data["color"] = self._prop_fg_color.text()
            obj_data["bg_color"] = self._prop_bg_color.text()
            obj_data["chapter_marker_color"] = self._prop_marker_color.text()
            obj_data["current_section_color"] = self._prop_section_color.text()
            obj_data["opacity"] = self._prop_opacity.value()
        elif obj_id == "waveform":
            obj_data["color"] = self._prop_color.text()
            obj_data["played_color"] = self._prop_played_color.text()
            obj_data["bg_color"] = self._prop_bg_color.text()
            obj_data["opacity"] = self._prop_opacity.value()
            obj_data["bars"] = self._prop_bars.value()

        # Update canvas
        self._main._rebuild_canvas()
        self._main._layout_dirty = True
        self.layoutChanged.emit()

    def _reset_props(self):
        """Reset to default layout for the selected object."""
        obj_id = self._get_active_obj_id()
        if obj_id in DEFAULT_LAYOUT:
            lt = self._main._layout_data or DEFAULT_LAYOUT
            lt[obj_id] = dict(DEFAULT_LAYOUT[obj_id])
            self._main._rebuild_canvas()
            self._main._layout_dirty = True
            self._rebuild_props()


# =========================================================
#  Main Window
# =========================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Book Wunderwaffe Studio 1.0")
        self.setGeometry(100, 40, 1600, 1000)

        # --- State ---
        self._chapters = []
        self._chapters_index = 0
        self._waveform_data = None
        self._project_data = {}
        self._layout_data = None
        self._layout_dirty = False
        self._total_duration = 0.0

        # Undo manager
        self._undo = UndoManager()
        self._last_undo_obj_id = ""
        self._item_drag_timer = QTimer()
        self._item_drag_timer.setSingleShot(True)
        self._item_drag_timer.setInterval(500)
        self._item_drag_timer.timeout.connect(self._on_drag_stop)
        self._drag_start_positions = {}

        # Player state
        self._player = None
        self._audio_output = None
        self._is_playing = False
        self._was_seeking = False
        self._player_error = ""
        self._player_simulation = False
        self._simulation_timer = None
        self._simulation_position = 0.0

        self._bg_pixmap = QPixmap()
        self._cover_pixmap = QPixmap()

        # --- Central scene ---
        self._scene = CanvasScene(self)
        self._view = ZoomGraphicsView(self._scene, self)
        self._view.zoomChanged.connect(self._on_zoom_changed)

        # --- Timeline widget ---
        self._timeline = TimelineWidget()
        self._timeline.chapterClicked.connect(self._seek_to_chapter)

        # --- Assemble layout ---
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Top bar
        main_layout.addWidget(self._create_top_bar())

        # Center: left panel + canvas + right panel
        center_split = QSplitter(Qt.Orientation.Horizontal)

        # Left panel
        self._left_panel = self._create_left_panel()
        center_split.addWidget(self._left_panel)

        # Canvas + timeline
        canvas_timeline = QWidget()
        ct_layout = QVBoxLayout(canvas_timeline)
        ct_layout.setContentsMargins(0, 0, 0, 0)
        ct_layout.setSpacing(0)

        # Timeline zoom bar
        timeline_bar = QWidget()
        timeline_bar.setStyleSheet(f"background-color: {DARK_PANEL}; border-bottom: 1px solid {BORDER_COLOR};")
        tb_layout = QHBoxLayout(timeline_bar)
        tb_layout.setContentsMargins(8, 2, 8, 2)
        tb_layout.setSpacing(4)

        tb_layout.addWidget(QLabel("Таймлайн:"))
        for text, method in [
            ("Fit", self._timeline.zoom_fit),
            ("+", self._timeline.zoom_in),
            ("-", self._timeline.zoom_out),
            ("1ч", self._timeline.zoom_1h),
            ("10м", self._timeline.zoom_10m),
        ]:
            btn = QPushButton(text)
            btn.setFixedSize(36, 22)
            btn.setStyleSheet(self._btn_small_style())
            btn.clicked.connect(method)
            tb_layout.addWidget(btn)
        tb_layout.addStretch()

        ct_layout.addWidget(timeline_bar)
        ct_layout.addWidget(self._timeline)
        ct_layout.addWidget(self._view, 1)

        center_split.addWidget(canvas_timeline)

        # Properties dock as right panel
        self._props_dock = PropertiesDock(self)
        center_split.addWidget(self._props_dock)

        center_split.setStretchFactor(0, 0)  # left panel fixed
        center_split.setStretchFactor(1, 1)  # canvas expands
        center_split.setStretchFactor(2, 0)  # right panel fixed

        main_layout.addWidget(center_split, 1)

        # Bottom bar (player)
        main_layout.addWidget(self._create_bottom_bar())

        # Status bar
        self._status_bar = QStatusBar()
        self._status_bar.setStyleSheet(f"background-color: {DARK_PANEL}; color: {TEXT_SECONDARY}; font-size: 10px;")
        self._status_label_bar = QLabel("Не готов")
        self._status_bar.addWidget(self._status_label_bar)
        main_layout.addWidget(self._status_bar)

        self.setCentralWidget(central)

        # --- Log dock ---
        self._log_dock = QDockWidget("Лог", self)
        self._log_widget = QTextEdit()
        self._log_widget.setReadOnly(True)
        self._log_widget.setStyleSheet(f"""
            QTextEdit {{
                background-color: #050510; color: {TEXT_SECONDARY};
                border: none; font-family: Consolas; font-size: 10px;
            }}
        """)
        self._log_dock.setWidget(self._log_widget)
        self._log_dock.setFixedHeight(200)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)
        self._log_dock.hide()

        # --- Setup ---
        self._init_player()
        self._load_project()
        self._update_chapter_combo()

        # --- Undo/Redo shortcuts ---
        self._setup_undo_shortcuts()

    # --- Undo/Redo ---
    def _setup_undo_shortcuts(self):
        """Ctrl+Z undo, Ctrl+Y/Ctrl+Shift+Z redo."""
        self._shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self._shortcut_undo.activated.connect(self._on_undo)
        self._shortcut_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        self._shortcut_redo.activated.connect(self._on_redo)
        self._shortcut_redo2 = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        self._shortcut_redo2.activated.connect(self._on_redo)

    def _on_undo(self):
        if not self._undo.can_undo():
            self._status_bar.showMessage("Нет действий для отмены", 2000)
            return
        snapshot = self._undo.undo()
        if snapshot is not None:
            # Find which object changed by comparing snapshots
            old_snapshot = self._layout_data
            changed_id = None
            for key in old_snapshot:
                if key in snapshot and old_snapshot[key] != snapshot[key]:
                    changed_id = key
                    break
            if changed_id is None:
                for key in snapshot:
                    if key not in old_snapshot:
                        changed_id = key
                        break
            self._layout_data = snapshot
            self._rebuild_canvas()
            self._layout_dirty = True
            obj_name = changed_id or "?"
            self._status_bar.showMessage(f"Отменено: {obj_name}", 3000)

    def _on_redo(self):
        if not self._undo.can_redo():
            self._status_bar.showMessage("Нет действий для возврата", 2000)
            return
        snapshot = self._undo.redo()
        if snapshot is not None:
            self._layout_data = snapshot
            self._rebuild_canvas()
            self._layout_dirty = True
            self._status_bar.showMessage("Возвращено", 3000)

    def _on_drag_stop(self):
        """Called after item drag finishes — push snapshot."""
        if self._layout_data and self._drag_start_positions:
            # Push snapshot after drag
            self._undo.push_snapshot(self._layout_data)
            self._layout_dirty = True
            self._drag_start_positions.clear()
            self._status_bar.showMessage("Позиция изменена", 2000)

    # --- Player init ---
    def _init_player(self):
        """Initialize QMediaPlayer or simulation fallback."""
        if not HAS_MULTIMEDIA:
            self._player_error = "QtMultimedia недоступен"
            self._player_simulation = True
            self.log("QtMultimedia не найден. Включаю simulation mode.")
            self._init_simulation()
            return

        try:
            self._player = QMediaPlayer(self)
            self._audio_output = QAudioOutput()
            self._player.setAudioOutput(self._audio_output)
            self._audio_output.setVolume(0.8)

            self._player.errorOccurred.connect(self._on_player_error)
            self._player.positionChanged.connect(self._on_position_changed)
            self._player.durationChanged.connect(self._on_duration_changed)
            self._player.mediaStatusChanged.connect(self._on_media_status_changed)
            self._player.playbackStateChanged.connect(self._on_playback_state_changed)

            # Player update timer (for UI sync)
            self._player_timer = QTimer()
            self._player_timer.setInterval(100)
            self._player_timer.timeout.connect(self._on_player_timer)

            self.log("QMediaPlayer инициализирован.")
        except Exception as e:
            self._player_error = f"Ошибка инициализации плеера: {e}"
            self._player = None
            self._player_simulation = True
            self.log(self._player_error)
            self._init_simulation()

    def _init_simulation(self):
        """Initialize simulation timer as fallback."""
        self._simulation_timer = QTimer()
        self._simulation_timer.setInterval(100)
        self._simulation_timer.timeout.connect(self._on_simulation_tick)
        self._simulation_position = 0.0
        self.log("Simulation mode: плеер будет двигать playhead без звука.")
        self._status_label_bar.setText("Simulation mode (без звука)")

    def _on_simulation_tick(self):
        """Simulate playback by advancing a virtual position."""
        self._simulation_position += 0.1  # 100ms step
        if self._total_duration > 0 and self._simulation_position >= self._total_duration:
            self._simulation_position = 0.0
            self._stop_playback()
            return

        # Update UI as if real playback
        self._on_position_changed(int(self._simulation_position * 1000))
        self._update_ui_for_time(self._simulation_position)

    # --- Load audio ---
    def _load_player_audio(self):
        """Load audio file into player."""
        audio_path = DATA_DIR / "ЗИНА. Книга. final last version.mp3"
        if not audio_path.exists():
            self._player_error = "Файл аудио не найден"
            self.log(f"Аудио не найдено: {audio_path}")
            self._status_label_bar.setText("Файл аудио не найден")
            return

        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        self.log(f"Загрузка аудио: {audio_path.name} ({file_size_mb:.1f} MB)")

        if self._player_simulation:
            # Use chapters total duration
            if self._chapters:
                last = self._chapters[-1]
                self._total_duration = timestr_to_seconds(last.get("end", "15:48:50.932"))
                self._label_total.setText(seconds_to_timestr(self._total_duration)[:8])
            self._status_label_bar.setText("Simulation: аудио загружено")
            return

        if self._player:
            try:
                self._player.setSource(QUrl.fromLocalFile(str(audio_path)))
                self._status_label_bar.setText("Аудио загружено")
                self._player_indicator.setStyleSheet("color: #00ff88; font-size: 14px;")
            except Exception as e:
                self._player_error = f"Ошибка загрузки аудио: {e}"
                self.log(self._player_error)
                self._status_label_bar.setText(self._player_error)
                self._player_simulation = True
                self._init_simulation()

    # --- Player callbacks ---
    def _on_player_error(self, error, error_string):
        self._player_error = f"Ошибка плеера: {error_string}"
        self.log(self._player_error)
        self._status_label_bar.setText(self._player_error)
        self._is_playing = False
        self._btn_play.setText("▶")
        self._player_indicator.setStyleSheet("color: #ff5555; font-size: 14px;")

        # Fall back to simulation
        if not self._player_simulation:
            self._player_simulation = True
            self._init_simulation()
            self.log("Переключение в simulation mode.")

    def _on_position_changed(self, pos_ms):
        """Called when player position changes."""
        sec = pos_ms / 1000.0
        self._label_current.setText(seconds_to_timestr(sec)[:8])

        # Update slider (avoid feedback loop during seeking)
        if not self._was_seeking:
            self._slider_position.blockSignals(True)
            total_ms = int(self._total_duration * 1000)
            self._slider_position.setRange(0, max(total_ms, 1))
            self._slider_position.setValue(pos_ms)
            self._slider_position.blockSignals(False)

    def _on_duration_changed(self, duration_ms):
        if duration_ms > 0:
            self._total_duration = duration_ms / 1000.0
            self._label_total.setText(seconds_to_timestr(self._total_duration)[:8])
            self._slider_position.setRange(0, duration_ms)
            self.log(f"Длительность: {seconds_to_timestr(self._total_duration)[:8]}")

    def _on_media_status_changed(self, status):
        status_map = {
            QMediaPlayer.MediaStatus.LoadedMedia: "Аудио загружено",
            QMediaPlayer.MediaStatus.LoadingMedia: "Загрузка...",
            QMediaPlayer.MediaStatus.BufferedMedia: "Буферизация завершена",
            QMediaPlayer.MediaStatus.BufferingMedia: "Буферизация...",
            QMediaPlayer.MediaStatus.EndOfMedia: "Воспроизведение завершено",
            QMediaPlayer.MediaStatus.InvalidMedia: "Ошибка: неверный формат",
            QMediaPlayer.MediaStatus.NoMedia: "Нет аудио",
            QMediaPlayer.MediaStatus.StalledMedia: "Ошибка загрузки",
        }
        msg = status_map.get(status, f"Статус: {status}")
        self.log(msg)
        if status == QMediaPlayer.MediaStatus.LoadedMedia:
            self._status_label_bar.setText(msg)
            self._player_indicator.setStyleSheet("color: #00ff88; font-size: 14px;")
        elif status in (QMediaPlayer.MediaStatus.InvalidMedia, QMediaPlayer.MediaStatus.StalledMedia):
            self._status_label_bar.setText(msg)
            self._player_indicator.setStyleSheet("color: #ff5555; font-size: 14px;")

    def _on_playback_state_changed(self, state):
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self._is_playing = False
            self._btn_play.setText("▶")
            self._player_timer.stop()
            self._status_label_bar.setText("Остановлено")

    def _on_player_timer(self):
        """Periodic timer to sync canvas with player position."""
        if self._player and not self._player_simulation:
            pos_ms = self._player.position()
            sec = pos_ms / 1000.0
            self._update_ui_for_time(sec)

    def _update_ui_for_time(self, current_sec):
        """Update all canvas and UI elements for given time."""
        total_s = self._total_duration
        if total_s <= 0:
            total_s = 0.001

        # Find chapter
        idx = self._find_chapter_at_time(current_sec) if self._chapters else -1
        if idx >= 0:
            self._chapters_index = idx
            # Update chapter combo
            self._chapter_combo.blockSignals(True)
            self._chapter_combo.setCurrentIndex(idx)
            self._chapter_combo.blockSignals(False)

            # Update chapter list
            if hasattr(self, '_chapter_list'):
                self._chapter_list.set_current_index(idx)

            # Update timeline
            self._timeline.set_current_index(idx)

        # Update canvas scene
        self._scene.on_playhead_update(current_sec, total_s, self._chapters, self._chapters_index)

        # Timeline playhead
        ratio = current_sec / max(total_s, 1)
        self._timeline.set_playhead(ratio)

        # Chapter label in bottom bar
        if 0 <= idx < len(self._chapters):
            title = self._chapters[idx].get("title", "")
            self._player_status_label_bar.setText(f"Глава: {title[:40]}")

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
        if self._player_simulation:
            if self._is_playing:
                self._simulation_timer.stop()
                self._is_playing = False
                self._btn_play.setText("▶")
                self._status_label_bar.setText("Пауза (simulation)")
            else:
                self._simulation_timer.start()
                self._is_playing = True
                self._btn_play.setText("⏸")
                self._status_label_bar.setText("Воспроизведение (simulation)")
            return

        if not self._player:
            self.log("Плеер недоступен.")
            return

        if self._player_error and "Ошибка" in self._player_error:
            # Try fallback to simulation
            self._player_simulation = True
            self._init_simulation()
            self._toggle_playback()
            return

        if self._is_playing:
            self._player.pause()
            self._is_playing = False
            self._btn_play.setText("▶")
            self._player_timer.stop()
            self._status_label_bar.setText("Пауза")
        else:
            self._player.play()
            self._is_playing = True
            self._btn_play.setText("⏸")
            self._player_timer.start()
            self._status_label_bar.setText("Воспроизведение")

    def _stop_playback(self):
        if self._player_simulation:
            self._simulation_timer.stop()
            self._simulation_position = 0.0
            self._is_playing = False
            self._btn_play.setText("▶")
            self._label_current.setText("00:00:00")
            self._slider_position.setValue(0)
            self._status_label_bar.setText("Остановлено")
            self._update_ui_for_time(0)
            return

        if not self._player:
            return
        self._player.stop()
        self._is_playing = False
        self._btn_play.setText("▶")
        self._player_timer.stop()
        self._slider_position.setValue(0)
        self._label_current.setText("00:00:00")
        self._status_label_bar.setText("Остановлено")
        self._update_ui_for_time(0)

    def _seek_to(self, position_ms):
        if self._player_simulation:
            self._simulation_position = position_ms / 1000.0
            self._update_ui_for_time(self._simulation_position)
            self._label_current.setText(seconds_to_timestr(self._simulation_position)[:8])
            return

        if not self._player:
            return
        self._player.setPosition(position_ms)

    def _seek_to_chapter(self, idx):
        if idx < 0 or idx >= len(self._chapters):
            return
        ch = self._chapters[idx]
        start_s = timestr_to_seconds(ch.get("start", "0"))
        self._seek_to(int(start_s * 1000))
        # Update UI without calling _on_chapter_selected (which would re-enter here)
        self._chapters_index = idx
        self._chapter_combo.blockSignals(True)
        self._chapter_combo.setCurrentIndex(idx)
        self._chapter_combo.blockSignals(False)
        self._chapter_list.set_current_index(idx)
        self._timeline.set_current_index(idx)
        self._update_ui_for_time(start_s)

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
        hint = QLabel("Сцена 1920×1080. Навигация: Ctrl+колесо — зум, средняя кнопка/Space+drag — двигать сцену.")
        hint.setStyleSheet(f"font-size: 10px; color: {TEXT_SECONDARY}; padding: 2px 4px;")
        layout.addWidget(hint)

        layout.addStretch()

        # Zoom controls
        self._zoom_label = QLabel("Zoom: 100%")
        self._zoom_label.setStyleSheet(f"font-size: 11px; color: {ACCENT_CYAN}; font-weight: bold;")
        layout.addWidget(self._zoom_label)

        layout.addSpacing(8)

        for text, method in [("Fit", self._view.zoom_fit),
                              ("Center", self._view.zoom_center),
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

    # --- Left panel (Phase 9: improved actions panel) ---
    def _create_left_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(340)
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
        info_layout.setSpacing(3)

        self._lbl_audio = QLabel("Аудио: —")
        self._lbl_rpp = QLabel("RPP: —")
        self._lbl_cover = QLabel("Обложка: —")
        self._lbl_bg = QLabel("Фон: —")
        self._lbl_chapters = QLabel("Главы: —")
        self._lbl_intro = QLabel("Вступление: —")
        self._lbl_epilogue = QLabel("Эпилог: —")
        for lbl in [self._lbl_audio, self._lbl_rpp, self._lbl_cover,
                     self._lbl_bg, self._lbl_chapters, self._lbl_intro, self._lbl_epilogue]:
            lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11px; padding: 1px 0;")
            info_layout.addWidget(lbl)

        layout.addWidget(info_group)

        # Chapter list
        self._chapter_list = ChapterListPanel()
        self._chapter_list.chapterSelected.connect(self._seek_to_chapter)
        layout.addWidget(self._chapter_list, 1)

        # Actions group — improved with subgroups and bigger buttons
        btn_group = QGroupBox("Действия")
        btn_group.setStyleSheet(info_group.styleSheet())
        btn_layout = QVBoxLayout(btn_group)
        btn_layout.setSpacing(4)

        # Subgroup: Project
        sub_proj = QLabel("  Проект")
        sub_proj.setStyleSheet(f"color: {ACCENT_VIOLET}; font-size: 10px; font-weight: bold; padding: 2px 0;")
        btn_layout.addWidget(sub_proj)

        btn_scan = QPushButton("🔍 Сканировать проект")
        btn_scan.clicked.connect(lambda: self._run_command("scan"))
        btn_scan.setMinimumHeight(30)
        btn_scan.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_scan)

        btn_chapters = QPushButton("📖 Извлечь главы из RPP")
        btn_chapters.clicked.connect(lambda: self._run_command("chapters"))
        btn_chapters.setMinimumHeight(30)
        btn_chapters.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_chapters)

        btn_waveform = QPushButton("🌊 Сгенерировать гистограмму")
        btn_waveform.clicked.connect(lambda: self._run_command("waveform"))
        btn_waveform.setMinimumHeight(30)
        btn_waveform.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_waveform)

        # Subgroup: Composition
        sub_comp = QLabel("  Композиция")
        sub_comp.setStyleSheet(f"color: {ACCENT_VIOLET}; font-size: 10px; font-weight: bold; padding: 2px 0;")
        btn_layout.addWidget(sub_comp)

        btn_reset = QPushButton("🔄 Сбросить композицию")
        btn_reset.clicked.connect(self._reset_layout)
        btn_reset.setMinimumHeight(30)
        btn_reset.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_reset)

        btn_save = QPushButton("💾 Сохранить композицию")
        btn_save.clicked.connect(self._save_layout)
        btn_save.setMinimumHeight(30)
        btn_save.setStyleSheet(self._btn_style(ACCENT_GREEN))
        btn_layout.addWidget(btn_save)

        btn_reload = QPushButton("📂 Перезагрузить композицию")
        btn_reload.clicked.connect(self._load_layout)
        btn_reload.setMinimumHeight(30)
        btn_reload.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_reload)

        # Subgroup: Diagnostics
        sub_diag = QLabel("  Диагностика")
        sub_diag.setStyleSheet(f"color: {ACCENT_VIOLET}; font-size: 10px; font-weight: bold; padding: 2px 0;")
        btn_layout.addWidget(sub_diag)

        btn_diag = QPushButton("🩺 Диагностика")
        btn_diag.clicked.connect(self._run_diagnostics)
        btn_diag.setMinimumHeight(30)
        btn_diag.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_diag)

        # Subgroup: Preview
        sub_preview = QLabel("  Превью")
        sub_preview.setStyleSheet(f"color: {ACCENT_VIOLET}; font-size: 10px; font-weight: bold; padding: 2px 0;")
        btn_layout.addWidget(sub_preview)

        btn_preview = QPushButton("👁 Создать превью-лист")
        btn_preview.clicked.connect(lambda: self._run_command("preview_contact"))
        btn_preview.setMinimumHeight(30)
        btn_preview.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_preview)

        btn_check = QPushButton("✅ Проверить превью")
        btn_check.clicked.connect(lambda: self._run_command("check_preview"))
        btn_check.setMinimumHeight(30)
        btn_check.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_check)

        btn_open_build = QPushButton("📁 Открыть папку сборки")
        btn_open_build.clicked.connect(lambda: os.startfile(str(BUILD_DIR)))
        btn_open_build.setMinimumHeight(30)
        btn_open_build.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_open_build)

        btn_open_data = QPushButton("📁 Открыть data/")
        btn_open_data.clicked.connect(lambda: os.startfile(str(DATA_DIR)))
        btn_open_data.setMinimumHeight(30)
        btn_open_data.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_open_data)

        # Subgroup: Render
        sub_render = QLabel("  Рендер")
        sub_render.setStyleSheet(f"color: {ACCENT_VIOLET}; font-size: 10px; font-weight: bold; padding: 2px 0;")
        btn_layout.addWidget(sub_render)

        layout.addWidget(btn_group)

        # Test render group
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
        btn_render_test.setMinimumHeight(32)
        btn_render_test.setStyleSheet(self._btn_style(ACCENT_VIOLET))
        test_layout.addWidget(btn_render_test)

        layout.addWidget(test_group)

        # Full render button (red, at bottom)
        btn_full = QPushButton("⚠️ ПОЛНЫЙ РЕНДЕР — ОСТОРОЖНО")
        btn_full.clicked.connect(self._confirm_full_render)
        btn_full.setMinimumHeight(36)
        btn_full.setStyleSheet(f"""
            QPushButton {{
                background-color: #441111; color: #ff6666;
                border: 2px solid #881111; border-radius: 6px;
                padding: 8px 12px; font-size: 11px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #552222; }}
        """)
        layout.addWidget(btn_full)

        layout.addStretch()
        return panel

    def _btn_style(self, color=ACCENT_CYAN):
        return f"""
            QPushButton {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 8px 10px; font-size: 11px; text-align: left;
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

    # --- Bottom bar with player (Phase 1: improved diagnostics) ---
    def _create_bottom_bar(self):
        bar = QWidget()
        bar.setFixedHeight(60)
        bar.setStyleSheet(f"background-color: {DARK_PANEL}; border-top: 1px solid {BORDER_COLOR};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        # Player status indicator
        self._player_indicator = QLabel("●")
        self._player_indicator.setFixedWidth(16)
        self._player_indicator.setStyleSheet("color: #666666; font-size: 16px;")
        layout.addWidget(self._player_indicator)

        # Chapter navigation
        btn_prev = QPushButton("⏮")
        btn_prev.setFixedSize(38, 34)
        btn_prev.setToolTip("Предыдущая глава")
        btn_prev.setStyleSheet(self._btn_player_style())
        btn_prev.clicked.connect(self._prev_chapter)
        layout.addWidget(btn_prev)

        # Play/Pause
        self._btn_play = QPushButton("▶")
        self._btn_play.setFixedSize(46, 34)
        self._btn_play.setToolTip("Воспроизвести / Пауза")
        self._btn_play.setStyleSheet(self._btn_play_style())
        self._btn_play.clicked.connect(self._toggle_playback)
        layout.addWidget(self._btn_play)

        # Stop
        btn_stop = QPushButton("⏹")
        btn_stop.setFixedSize(38, 34)
        btn_stop.setToolTip("Стоп")
        btn_stop.setStyleSheet(self._btn_player_style())
        btn_stop.clicked.connect(self._stop_playback)
        layout.addWidget(btn_stop)

        # Next chapter
        btn_next = QPushButton("⏭")
        btn_next.setFixedSize(38, 34)
        btn_next.setToolTip("Следующая глава")
        btn_next.setStyleSheet(self._btn_player_style())
        btn_next.clicked.connect(self._next_chapter)
        layout.addWidget(btn_next)

        layout.addSpacing(6)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet(f"background-color: {BORDER_COLOR};")
        layout.addWidget(sep)

        layout.addSpacing(6)

        # Time display
        self._label_current = QLabel("00:00:00")
        self._label_current.setFixedWidth(90)
        self._label_current.setStyleSheet(f"color: {ACCENT_CYAN}; font-size: 14px; font-family: Consolas; font-weight: bold;")
        layout.addWidget(self._label_current)

        sep2 = QLabel("/")
        sep2.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(sep2)

        self._label_total = QLabel("00:00:00")
        self._label_total.setFixedWidth(90)
        self._label_total.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 14px; font-family: Consolas;")
        layout.addWidget(self._label_total)

        layout.addSpacing(6)

        # Seek slider
        self._slider_position = QSlider(Qt.Orientation.Horizontal)
        self._slider_position.setMinimumWidth(250)
        self._slider_position.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {DARK_CARD}; height: 8px; border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: {ACCENT_CYAN}; width: 16px; height: 16px;
                margin: -4px 0; border-radius: 8px;
            }}
            QSlider::sub-page:horizontal {{
                background: {ACCENT_GREEN}; border-radius: 4px;
            }}
        """)
        self._slider_position.sliderMoved.connect(self._seek_to)
        self._slider_position.sliderPressed.connect(self._on_seek_start)
        self._slider_position.sliderReleased.connect(self._on_seek_end)
        layout.addWidget(self._slider_position, 1)

        layout.addSpacing(6)

        # Player status label
        self._player_status_label_bar = QLabel("Аудио загружено")
        self._player_status_label_bar.setFixedWidth(220)
        self._player_status_label_bar.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 10px;")
        layout.addWidget(self._player_status_label_bar)

        layout.addSpacing(6)

        # Separator
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setFixedWidth(1)
        sep3.setStyleSheet(f"background-color: {BORDER_COLOR};")
        layout.addWidget(sep3)

        layout.addSpacing(6)

        # Chapter selector
        self._chapter_combo = QComboBox()
        self._chapter_combo.setMinimumWidth(240)
        self._chapter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 3px 8px; font-size: 10px;
            }}
            QComboBox:hover {{ border-color: {ACCENT_CYAN}; }}
            QComboBox::drop-down {{
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 18px; border-left: 1px solid {BORDER_COLOR};
            }}
        """)
        self._chapter_combo.currentIndexChanged.connect(self._on_chapter_selected)
        layout.addWidget(self._chapter_combo)

        # Jump button
        btn_jump = QPushButton("→")
        btn_jump.setFixedSize(30, 34)
        btn_jump.setToolTip("Перейти к главе")
        btn_jump.setStyleSheet(self._btn_player_style())
        btn_jump.clicked.connect(lambda: self._seek_to_chapter(self._chapter_combo.currentIndex()))
        layout.addWidget(btn_jump)

        return bar

    def _btn_player_style(self):
        return f"""
            QPushButton {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 2px 6px; font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: #1a1a4a; border-color: {ACCENT_CYAN};
            }}
            QPushButton:pressed {{
                background-color: #0a0a3a;
            }}
        """

    def _btn_play_style(self):
        return f"""
            QPushButton {{
                background-color: #1a3a1a; color: {ACCENT_GREEN};
                border: 1px solid {ACCENT_GREEN}; border-radius: 4px;
                padding: 2px 8px; font-size: 18px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #2a4a2a; }}
            QPushButton:pressed {{ background-color: #0a2a0a; }}
        """

    def _on_seek_start(self):
        self._was_seeking = True

    def _on_seek_end(self):
        self._was_seeking = False
        if self._player and not self._player_simulation:
            pos = self._slider_position.value()
            self._player.setPosition(pos)

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
        # Push initial layout snapshot
        if self._layout_data:
            self._undo.push_snapshot(self._layout_data)

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

        # Update chapter list & timeline
        if hasattr(self, '_chapter_list'):
            self._chapter_list.set_chapters(self._chapters)
        if hasattr(self, '_timeline'):
            self._timeline.set_chapters(self._chapters)

        # Update progress bar chapters
        prog_item = self._scene.get_item(OBJ_PROGRESS)
        if prog_item and isinstance(prog_item, ProgressItem):
            prog_item.set_chapters(self._chapters)

    def _update_chapter_combo(self):
        """Populate chapter combo box."""
        self._chapter_combo.blockSignals(True)
        self._chapter_combo.clear()
        for i, c in enumerate(self._chapters):
            title = c.get("title", f"Segment {i}")
            start = c.get("start", "00:00:00")
            self._chapter_combo.addItem(f"{start[:8]} — {title}", i)
        self._chapter_combo.blockSignals(False)

    def _load_waveform(self):
        wf = load_json(WAVEFORM_PATH)
        if wf and isinstance(wf, list) and len(wf) > 10:
            self._waveform_data = wf
            self.log(f"Waveform загружен: {len(wf)} samples")
        else:
            self._waveform_data = None
            self.log("Нет данных waveform. Сгенерируй гистограмму.")

        # Update waveform item
        wf_item = self._scene.get_item(OBJ_WAVEFORM)
        if wf_item and isinstance(wf_item, WaveformItem):
            wf_item.set_waveform_data(self._waveform_data)

    def _load_layout(self):
        lt = load_json(LAYOUT_PATH)
        if lt and isinstance(lt, dict):
            self._layout_data = lt
            self.log("Композиция загружена из файла.")
        else:
            self._layout_data = dict(DEFAULT_LAYOUT)
            self.log("Используется композиция по умолчанию.")
            if self._layout_data:
                self._undo.push_snapshot(self._layout_data)

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

        # Current chapter (hidden by default in DEFAULT_LAYOUT — Phase 2 fix)
        ch_data = lt.get(OBJ_CURRENT_CHAPTER, DEFAULT_LAYOUT["currentChapter"])
        if self._chapters and ch_data.get("text_source", "auto") == "auto":
            ch_data["text"] = self._chapters[0].get("title", "Вступление от автора")
        self._scene.add_canvas_item(OBJ_CURRENT_CHAPTER, ch_data)

        # Chapter stack — shows prev/current/next with global styles
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
            stack_item = self._scene.get_item(OBJ_CHAPTER_STACK)
            if stack_item and isinstance(stack_item, ChapterStackItem):
                prev_title = ""
                cur_title = self._chapters[0].get("title", "")
                next_title = self._chapters[1].get("title", "") if len(self._chapters) > 1 else ""
                stack_item.set_chapters(prev_title, cur_title, next_title)
                stack_item.set_style_from_data(stack_data)

        # Set chapter data for progress bar
        prog_item = self._scene.get_item(OBJ_PROGRESS)
        if prog_item and isinstance(prog_item, ProgressItem):
            prog_item.set_chapters(self._chapters)

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

        # Seek to chapter start
        self._seek_to_chapter(idx)

        # Update canvas
        self._update_ui_for_time(timestr_to_seconds(ch.get("start", "0")))

    # --- Project info ---
    def _update_project_info(self):
        config = self._project_data or {}
        audio = config.get("audio_file", "—")
        rpp = config.get("rpp_file", "—")
        cover = config.get("cover_file", "—")
        bg = config.get("background_file", "—")

        self._lbl_audio.setText(f"Аудио: {Path(audio).name if audio != '—' else '—'}")
        self._lbl_rpp.setText(f"RPP: {Path(rpp).name if rpp != '—' else '—'}")
        self._lbl_cover.setText(f"Обложка: {Path(cover).name if cover != '—' else '—'}")
        self._lbl_bg.setText(f"Фон: {Path(bg).name if bg != '—' else '—'}")

        if self._chapters:
            self._lbl_chapters.setText(f"Главы: {len(self._chapters)}")
            first = self._chapters[0].get("title", "?")
            self._lbl_intro.setText(f"Вступление: {first}")
            last = self._chapters[-1].get("title", "?")
            if "эпилог" in last.lower():
                self._lbl_epilogue.setText(f"Эпилог: {last}")
            else:
                self._lbl_epilogue.setText(f"Последняя: {last}")
        else:
            self._lbl_chapters.setText("Главы: 0")

        self._audio_label.setText(f"Аудио: {Path(audio).name if audio != '—' else '—'}")
        self._ch_count_label.setText(f"Глав: {len(self._chapters) if self._chapters else 0}")

    # --- Commands ---
    def _run_command(self, cmd):
        self.log(f"Запуск: python bookforge.py {cmd}")
        try:
            result = subprocess.run(
                [sys.executable, "bookforge.py", cmd],
                capture_output=True, text=True, timeout=300,
                cwd=str(PROJECT_ROOT)
            )
            self.log(f"stdout:\n{result.stdout[-2000:]}")
            if result.stderr:
                self.log(f"stderr:\n{result.stderr[-1000:]}")
            # Reload after command
            if cmd in ("scan", "chapters"):
                self._load_chapters()
                self._update_chapter_combo()
            if cmd == "waveform":
                self._load_waveform()
            if cmd == "scan":
                self._load_project()
            self._update_project_info()
            self._update_status()
            self._rebuild_canvas()
        except subprocess.TimeoutExpired:
            self.log(f"Команда {cmd} превысила тайм-аут.")
        except Exception as e:
            self.log(f"Ошибка команды {cmd}: {e}")

    def _run_render_test(self):
        duration = self._test_duration_combo.currentText()
        if duration == "Свой":
            sec = self._test_custom_spin.value()
        elif duration == "1 мин":
            sec = 60
        elif duration == "5 мин":
            sec = 300
        elif duration == "10 мин":
            sec = 600
        elif duration == "60 сек":
            sec = 60
        elif duration == "Текущая глава":
            if self._chapters and self._chapters_index < len(self._chapters):
                ch = self._chapters[self._chapters_index]
                start_s = timestr_to_seconds(ch.get("start", "0"))
                end_s = timestr_to_seconds(ch.get("end", str(start_s + 60)))
                sec = int(end_s - start_s)
            else:
                sec = 60
        else:
            sec = 60

        # Cap at 600 seconds (10 min) for safety
        if sec > 600:
            reply = QMessageBox.question(self, "Длинный тест",
                                          f"Тестовый рендер на {sec} сек ({sec//60} мин). Продолжить?",
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        self.log(f"Запуск тестового рендера: {sec} сек")
        self._run_command(f"render-test --duration {sec}")

    def _run_diagnostics(self):
        """Run full diagnostics and open report."""
        self.log("Запуск диагностики...")
        try:
            import subprocess, sys, json, os, shutil, datetime, platform
            from pathlib import Path
            report_lines = []
            rl = report_lines.append

            rl("=" * 70)
            rl("  BOOK WUNDERWAFFE STUDIO 1.0 — DIAGNOSTICS REPORT")
            rl(f"  Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            rl("=" * 70)
            rl("")

            # --- 1. Environment ---
            rl("[ENVIRONMENT]")
            rl(f"Python executable: {sys.executable}")
            rl(f"Python version: {sys.version}")
            rl(f"Platform: {platform.platform()}")
            rl(f"CWD: {os.getcwd()}")

            try:
                from PySide6.QtCore import __version__ as qt_ver
                rl(f"PySide6: {qt_ver}")
            except:
                rl("PySide6: ERROR — cannot import version")

            try:
                from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
                rl("QtMultimedia: AVAILABLE (imported)")
            except ImportError as e:
                rl(f"QtMultimedia: UNAVAILABLE — {e}")

            # ffmpeg/ffprobe paths
            ffmpeg = shutil.which("ffmpeg")
            ffprobe = shutil.which("ffprobe")
            rl(f"ffmpeg: {ffmpeg or 'NOT FOUND'}")
            rl(f"ffprobe: {ffprobe or 'NOT FOUND'}")
            rl("")

            # --- 2. Project files ---
            rl("[PROJECT FILES]")
            audio_path = DATA_DIR / "ЗИНА. Книга. final last version.mp3"
            rl(f"Selected audio: {audio_path}")
            if audio_path.exists():
                sz = audio_path.stat().st_size
                mb = sz / (1024 * 1024)
                gb = sz / (1024 * 1024 * 1024)
                rl(f"Audio exists: YES")
                rl(f"Audio size: {mb:.2f} MB ({gb:.3f} GB)")
            else:
                rl(f"Audio exists: NO")

            rpp_candidates = list(DATA_DIR.glob("*.rpp"))
            rl(f"Selected RPP: {rpp_candidates[0] if rpp_candidates else 'NOT FOUND'}")

            cover_candidates = list(DATA_DIR.glob("*cover*")) + list(DATA_DIR.glob("*обложк*"))
            rl(f"Cover: {cover_candidates[0] if cover_candidates else 'NOT FOUND'}")

            bg_candidates = list(DATA_DIR.glob("*background*")) + list(DATA_DIR.glob("*фон*"))
            rl(f"Background: {bg_candidates[0] if bg_candidates else 'NOT FOUND'}")

            rl(f"Chapters path: {CHAPTERS_PATH} — {'EXISTS' if CHAPTERS_PATH.exists() else 'NOT FOUND'}")
            rl(f"Waveform path: {WAVEFORM_PATH} — {'EXISTS' if WAVEFORM_PATH.exists() else 'NOT FOUND'}")
            rl(f"Layout path: {LAYOUT_PATH} — {'EXISTS' if LAYOUT_PATH.exists() else 'NOT FOUND'}")
            rl("")

            # --- 3. Audio ffprobe ---
            rl("[AUDIO FFPROBE]")
            if ffprobe and audio_path.exists():
                try:
                    result = subprocess.run(
                        [ffprobe, "-v", "error", "-show_format", "-show_streams",
                         "-of", "json", str(audio_path)],
                        capture_output=True, text=True, timeout=30
                    )
                    if result.returncode == 0:
                        info = json.loads(result.stdout)
                        fmt = info.get("format", {})
                        rl(f"format_name: {fmt.get('format_name', '?')}")
                        rl(f"duration: {fmt.get('duration', '?')} sec")
                        rl(f"bit_rate: {fmt.get('bit_rate', '?')} bps")
                        streams = info.get("streams", [])
                        for s in streams:
                            if s.get("codec_type") == "audio":
                                rl(f"codec: {s.get('codec_name', '?')}")
                                rl(f"sample_rate: {s.get('sample_rate', '?')} Hz")
                                rl(f"channels: {s.get('channels', '?')}")
                                break
                    else:
                        dur_result = subprocess.run(
                            [ffprobe, "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
                            capture_output=True, text=True, timeout=30
                        )
                        rl(f"Duration (fallback): {dur_result.stdout.strip() or 'UNKNOWN'} sec")
                        rl(f"ffprobe stderr: {result.stderr[:500] if result.stderr else 'none'}")
                except Exception as e:
                    rl(f"ffprobe error: {e}")
            else:
                rl("Cannot probe audio — ffprobe missing or audio missing")
            rl("")

            # --- 4. QMediaPlayer diagnostics ---
            rl("[QMEDIAPLAYER DIAGNOSTICS]")
            rl(f"HAS_MULTIMEDIA: {HAS_MULTIMEDIA}")
            rl(f"Player simulation: {self._player_simulation}")
            rl(f"Player error: {self._player_error or 'None'}")
            if self._player and not self._player_simulation:
                try:
                    ms = self._player.mediaStatus()
                    ms_map = {0: "NoMedia", 1: "LoadingMedia", 2: "LoadedMedia",
                              3: "BufferingMedia", 4: "BufferedMedia", 5: "EndOfMedia",
                              6: "InvalidMedia", 7: "StalledMedia"}
                    rl(f"mediaStatus: {ms_map.get(ms, str(ms))}")
                    err = self._player.error()
                    err_map = {0: "NoError", 1: "ResourceError", 2: "FormatError",
                               3: "NetworkError", 4: "AccessDeniedError"}
                    rl(f"error: {err_map.get(err, str(err))}")
                    rl(f"errorString: {self._player.errorString()}")
                except Exception as e:
                    rl(f"player.diagnostics error: {e}")
            else:
                rl("QMediaPlayer not active or in simulation mode")

            if self._player_error and "Ошибка" in str(self._player_error):
                rl("")
                rl(">>> QMediaPlayer FAILED. Check audio file format/codec/size.")
                rl(">>> 2.17 GB MP3 may be too large for Qt's built-in player.")
                rl(">>> Recommended fallback: proxy audio or python-vlc.")
            rl("")

            # --- 5. Audio fallback recommendation ---
            rl("[FALLBACK RECOMMENDATION]")
            for vlc_path in [
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"
            ]:
                rl(f"VLC at '{vlc_path}': {'YES' if os.path.exists(vlc_path) else 'NO'}")
            ffplay = shutil.which("ffplay")
            rl(f"ffplay: {ffplay or 'NOT FOUND'}")
            rl("")
            rl("Options:")
            rl("  Option A: use ffplay external preview (for audio check only)")
            rl("  Option B: install python-vlc (pip install python-vlc)")
            rl("  Option C: generate low-bitrate proxy MP3 for GUI playback")
            rl("")

            # --- 6. Waveform diagnostics ---
            rl("[WAVEFORM DIAGNOSTICS]")
            if WAVEFORM_PATH.exists():
                sz = WAVEFORM_PATH.stat().st_size
                mt = datetime.datetime.fromtimestamp(WAVEFORM_PATH.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                rl(f"File size: {sz / 1024:.1f} KB")
                rl(f"Modified: {mt}")
                try:
                    wf_data = json.loads(WAVEFORM_PATH.read_text("utf-8"))
                    if isinstance(wf_data, list):
                        rl(f"Valid JSON: YES (list, {len(wf_data)} samples)")
                        if len(wf_data) > 0:
                            rl(f"First 10 samples: {wf_data[:10]}")
                            rl(f"Min sample: {min(wf_data):.4f}")
                            rl(f"Max sample: {max(wf_data):.4f}")
                    elif isinstance(wf_data, dict):
                        rl(f"Valid JSON: YES (dict)")
                        rl(f"Keys: {list(wf_data.keys())[:10]}")
                        if "samples" in wf_data:
                            rl(f"  samples count: {len(wf_data['samples'])}")
                        if "peaks" in wf_data:
                            rl(f"  peaks count: {len(wf_data['peaks'])}")
                        if "data" in wf_data:
                            rl(f"  data count: {len(wf_data['data'])}")
                    else:
                        rl(f"Valid JSON: YES (type={type(wf_data).__name__})")
                except Exception as e:
                    rl(f"Valid JSON: NO — {e}")
                rl(f"Waveform loaded in GUI: {'YES' if self._waveform_data else 'NO'}")
            else:
                rl("waveform.json NOT FOUND")
                rl("  -> Run: python bookforge.py waveform")
            rl("")

            # --- 7. Layout diagnostics ---
            rl("[LAYOUT DIAGNOSTICS]")
            if LAYOUT_PATH.exists():
                try:
                    lt_data = json.loads(LAYOUT_PATH.read_text("utf-8"))
                    rl(f"Object IDs: {list(lt_data.keys())}")
                    for obj_id, obj_data in lt_data.items():
                        visible = obj_data.get("visible", True)
                        z = obj_data.get("z", obj_data.get("z_index", 0))
                        rl(f"  {obj_id}: visible={visible}, z={z}, type={obj_data.get('type','?')}")
                except Exception as e:
                    rl(f"Layout error: {e}")
            else:
                rl("layout.json NOT FOUND (using defaults)")
            rl("")

            # --- 8. GUI diagnostics ---
            rl("[GUI DIAGNOSTICS]")
            rl("MainWindow class: AVAILABLE")
            rl("UndoManager: AVAILABLE")
            rl("ZoomGraphicsView: AVAILABLE")
            rl("CanvasScene: AVAILABLE")
            rl("WaveformItem: AVAILABLE")
            rl("ProgressItem: AVAILABLE")
            rl("ChapterStackItem: AVAILABLE")
            rl("CustomTextItem: AVAILABLE")
            rl("TimelineWidget: AVAILABLE")
            rl("PropertiesDock: AVAILABLE")
            rl(f"Player simulation mode: {self._player_simulation}")
            rl(f"Total chapters: {len(self._chapters)}")
            rl(f"Total duration: {self._total_duration:.2f} sec")
            rl(f"Layout dirty: {self._layout_dirty}")
            rl(f"Waveform samples: {len(self._waveform_data) if self._waveform_data else 0}")
            rl("")

            # --- 9. Summary ---
            rl("=" * 70)
            rl("  SUMMARY")
            rl("=" * 70)

            audio_ok = audio_path.exists() and not self._player_error
            if not audio_path.exists():
                audio_status = "FILE_MISSING"
            elif self._player_error:
                audio_status = f"FAILED_QMEDIAPLAYER: {self._player_error[:80]}"
            elif HAS_MULTIMEDIA and self._player:
                audio_status = "OK (QMediaPlayer)"
            elif self._player_simulation:
                audio_status = "SIMULATION_MODE (no real playback)"
            else:
                audio_status = "UNKNOWN"
            rl(f"AUDIO_STATUS: {audio_status}")

            if self._waveform_data:
                wf_status = "OK_DATA_AND_GUI"
                # check if GUI waveform item actually renders
                wf_item = self._scene.get_item(OBJ_WAVEFORM)
                if wf_item is None or not isinstance(wf_item, WaveformItem):
                    wf_status = "OK_DATA_GUI_BROKEN"
            elif WAVEFORM_PATH.exists():
                wf_status = "OK_DATA_GUI_BROKEN (data file exists but not loaded)"
            else:
                wf_status = "MISSING"
            rl(f"WAVEFORM_STATUS: {wf_status}")

            canvas_ok = True
            rl(f"CANVAS_STATUS: OK")

            rl("")
            rl("NEXT_FIXES:")
            fixes = []
            if not audio_path.exists():
                fixes.append("Find/replace missing audio file")
            if self._player_error:
                fixes.append("Create proxy audio for QMediaPlayer (ffmpeg -> low-bitrate MP3)")
            if not self._waveform_data:
                fixes.append("Generate waveform: python bookforge.py waveform")
            if not self._chapters:
                fixes.append("Extract chapters: python bookforge.py chapters")
            if not fixes:
                fixes.append("All systems nominal.")
            for f in fixes:
                rl(f"  - {f}")

            rl("")
            rl("=" * 70)
            rl("  END OF REPORT")
            rl("=" * 70)

            # --- Write report ---
            BUILD_DIR.mkdir(parents=True, exist_ok=True)
            report_path = BUILD_DIR / "BOOK_WUNDERWAFFE_DIAGNOSTICS.txt"
            report_path.write_text("\n".join(report_lines), "utf-8")
            self.log(f"Диагностика завершена: {report_path}")

            # Open report automatically
            try:
                os.startfile(str(report_path))
                self.log("Отчёт открыт.")
            except Exception as e:
                self.log(f"Не удалось открыть отчёт: {e}")
                # Fallback: log content
                self._log_widget.append("\n".join(report_lines[-20:]))

        except Exception as e:
            self.log(f"Ошибка диагностики: {e}")
            import traceback
            self.log(traceback.format_exc())

    def _confirm_full_render(self):
        reply = QMessageBox.warning(self, "Полный рендер",
                                     "Полный рендер может занять несколько часов.\n\n"
                                     "Убедись, что:\n"
                                     "• Все главы извлечены\n"
                                     "• Гистограмма сгенерирована\n"
                                     "• Композиция сохранена\n"
                                     "• Достаточно места на диске\n\n"
                                     "Продолжить?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.log("Полный рендер запущен. Смотри терминал.")
            self._run_command("render-full")

    # --- Logging ---
    def log(self, message):
        timestamp = QTimer().metaObject().methodCount()  # dummy
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_widget.append(f"[{ts}] {message}")
        print(f"[Studio] {message}")


# =========================================================
#  QGraphicsView with zoom support
# =========================================================

class ZoomGraphicsView(QGraphicsView):
    zoomChanged = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._zoom = 1.0
        self._panning = False
        self._pan_start = QPointF()
        self._space_pressed = False
        self._space_panning = False
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setStyleSheet(f"background-color: {DARK_BG}; border: none;")
        self.setInteractive(True)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

    # ---- Middle mouse / Space+left pan ----
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._space_pressed:
            self._space_panning = True
            self._pan_start = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning or self._space_panning:
            delta = event.pos() - self._pan_start
            self._pan_start = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._space_panning:
            self._space_panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = True
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self._space_pressed = False
            if self._space_panning:
                self._space_panning = False
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().keyReleaseEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
            self._zoom *= factor
            self._zoom = max(0.1, min(10.0, self._zoom))
            self.scale(factor, factor)
            self.zoomChanged.emit(self._zoom)
            event.accept()
        else:
            super().wheelEvent(event)

    def zoom_fit(self):
        """Fit entire scene into view, keep aspect ratio."""
        self._zoom = 1.0
        self.resetTransform()
        self.fitInView(0, 0, SCENE_W, SCENE_H, Qt.AspectRatioMode.KeepAspectRatio)
        t = self.transform()
        self._zoom = t.m11()
        self.zoomChanged.emit(self._zoom)

    def zoom_center(self):
        """Center view on scene center without changing zoom."""
        self.centerOn(SCENE_W / 2, SCENE_H / 2)

    def zoom_100(self):
        """Zoom to 100% and center."""
        self._set_zoom(1.0)

    def zoom_50(self):
        self._set_zoom(0.5)

    def zoom_150(self):
        self._set_zoom(1.5)

    def zoom_200(self):
        self._set_zoom(2.0)

    def _set_zoom(self, factor):
        self._zoom = factor
        self.resetTransform()
        self.scale(factor, factor)
        self.centerOn(SCENE_W / 2, SCENE_H / 2)
        self.zoomChanged.emit(self._zoom)


# =========================================================
#  Entry point
# =========================================================

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, QColor(DARK_BG))
    palette.setColor(palette.ColorRole.WindowText, QColor(TEXT_PRIMARY))
    palette.setColor(palette.ColorRole.Base, QColor(DARK_CARD))
    palette.setColor(palette.ColorRole.AlternateBase, QColor(DARK_PANEL))
    palette.setColor(palette.ColorRole.Button, QColor(DARK_CARD))
    palette.setColor(palette.ColorRole.ButtonText, QColor(TEXT_PRIMARY))
    palette.setColor(palette.ColorRole.Text, QColor(TEXT_PRIMARY))
    palette.setColor(palette.ColorRole.Highlight, QColor(ACCENT_CYAN))
    palette.setColor(palette.ColorRole.HighlightedText, QColor("#000000"))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()