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
    Qt, QRectF, QPointF, QSizeF, Signal, Slot, QProcess, QTimer
)
from PySide6.QtGui import (
    QAction, QBrush, QColor, QFont, QIcon, QPainter, QPen,
    QPixmap, QTransform, QWheelEvent
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGraphicsItem, QGraphicsPixmapItem,
    QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem,
    QGraphicsView, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSlider, QSpinBox, QSplitter, QTextEdit,
    QVBoxLayout, QWidget, QDockWidget, QFrame, QListWidget,
    QListWidgetItem, QProgressBar, QDialog, QLineEdit
)

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
OBJ_WAVEFORM = "waveform"
OBJ_PROGRESS = "progress"
OBJ_BRAND = "brand"

# --- Default layout (if preset not loaded) ---
DEFAULT_LAYOUT = {
    "background": {
        "id": "background", "type": "image", "x": 0, "y": 0,
        "w": 1920, "h": 1080, "visible": True, "opacity": 1.0,
        "source": "background.png", "z": 0
    },
    "cover": {
        "id": "cover", "type": "image", "x": 80, "y": 120,
        "w": 540, "h": 760, "visible": True, "opacity": 0.92,
        "source": "zina-cover.png", "z": 10
    },
    "bookTitle": {
        "id": "bookTitle", "type": "text", "x": 700, "y": 160,
        "w": 1100, "h": 80, "visible": True, "opacity": 1.0,
        "font_size": 56, "color": "#ffffff",
        "text": "ЗИНА", "align": "left", "z": 20
    },
    "currentChapter": {
        "id": "currentChapter", "type": "text", "x": 700, "y": 280,
        "w": 1100, "h": 60, "visible": True, "opacity": 1.0,
        "font_size": 32, "color": "#00ff88",
        "text": "Вступление от автора", "align": "left", "z": 21
    },
    "waveform": {
        "id": "waveform", "type": "waveform", "x": 700, "y": 680,
        "w": 1100, "h": 120, "visible": True, "opacity": 0.7,
        "color": "#00e5ff", "bg_color": "#1a1a3a",
        "z": 30
    },
    "progress": {
        "id": "progress", "type": "progress", "x": 700, "y": 780,
        "w": 1100, "h": 8, "visible": True, "opacity": 0.8,
        "color": "#00ff88", "bg_color": "#1a1a3a",
        "z": 31
    },
    "brand": {
        "id": "brand", "type": "text", "x": 1600, "y": 1000,
        "w": 280, "h": 40, "visible": True, "opacity": 0.5,
        "font_size": 16, "color": "#9090b0",
        "text": "Book Wunderwaffe Studio 1.0", "align": "right",
        "z": 100
    }
}


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
        f = QFont("Segoe UI", d.get("font_size", 24))
        f.setBold(True)
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
    """Custom waveform visualization."""
    def __init__(self, obj_id, obj_data, parent=None):
        super().__init__(parent)
        self.obj_id = obj_id
        self.obj_data = obj_data
        self.wave_data = []
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
        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(r)
        if self.wave_data:
            painter.setPen(QPen(fg, 2))
            n = len(self.wave_data)
            w = r.width()
            h = r.height()
            mid = h / 2
            for i, val in enumerate(self.wave_data):
                x = (i / n) * w
                amp = val * mid * 0.9
                painter.drawLine(QPointF(x, mid - amp), QPointF(x, mid + amp))
        else:
            painter.setPen(QPen(QColor(TEXT_SECONDARY), 1))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "waveform (generate first)")

    def set_waveform(self, data):
        self.wave_data = data
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
    """Progress bar item."""
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
        bw = r.width() * self.progress
        if bw > 0:
            painter.setBrush(QColor(self.obj_data.get("color", "#00ff88")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(0, 0, bw, r.height())

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
        return None

    def get_item(self, obj_id):
        return self._items_map.get(obj_id)

    def on_item_moved(self):
        self.layoutChanged.emit()


# =========================================================
#  Properties Panel
# =========================================================

class PropertiesPanel(QWidget):
    """Right panel: edit selected object properties."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_id = None
        self._updating = False
        self.setMinimumWidth(240)
        self.setMaximumWidth(320)
        self.setStyleSheet(f"background-color: {DARK_PANEL}; color: {TEXT_PRIMARY};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Object Properties")
        title.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {ACCENT_CYAN};")
        layout.addWidget(title)

        self._id_label = QLabel("(none selected)")
        self._id_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self._id_label)

        # X
        self._spin_x = self._make_spin("X", 0, 5000, layout)
        self._spin_x.valueChanged.connect(lambda v: self._set("x", v))

        # Y
        self._spin_y = self._make_spin("Y", 0, 5000, layout)
        self._spin_y.valueChanged.connect(lambda v: self._set("y", v))

        # W
        self._spin_w = self._make_spin("Width", 1, 5000, layout)
        self._spin_w.valueChanged.connect(lambda v: self._set("w", v))

        # H
        self._spin_h = self._make_spin("Height", 1, 5000, layout)
        self._spin_h.valueChanged.connect(lambda v: self._set("h", v))

        # Opacity
        self._spin_opacity = self._make_spin("Opacity", 0.0, 1.0, layout, step=0.01, decimals=2)
        self._spin_opacity.valueChanged.connect(lambda v: self._set("opacity", v))

        # Font size
        self._spin_font = self._make_spin("Font Size", 6, 200, layout)
        self._spin_font.valueChanged.connect(lambda v: self._set("font_size", v))

        # Visible
        self._cb_visible = QCheckBox("Visible")
        self._cb_visible.setStyleSheet(f"color: {TEXT_PRIMARY};")
        self._cb_visible.toggled.connect(lambda v: self._set("visible", v))
        layout.addWidget(self._cb_visible)

        layout.addStretch()

    def _make_spin(self, label, min_v, max_v, layout, step=1.0, decimals=0):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        lbl.setFixedWidth(60)
        row.addWidget(lbl)
        sp = QDoubleSpinBox()
        sp.setRange(min_v, max_v)
        sp.setSingleStep(step)
        sp.setDecimals(decimals)
        sp.setStyleSheet(f"""
            QDoubleSpinBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 2px; font-size: 11px;
            }}
        """)
        sp.setFixedHeight(24)
        row.addWidget(sp, 1)
        layout.addLayout(row)
        return sp

    def _set(self, key, value):
        if self._updating or not self._current_id:
            return
        scene = self.window().canvas_scene if hasattr(self.window(), "canvas_scene") else None
        if scene:
            item = scene.get_item(self._current_id)
            if item and hasattr(item, "obj_data"):
                item.obj_data[key] = value
                item.update_from_data(item.obj_data)
                scene.layoutChanged.emit()

    def show_properties(self, obj_id, obj_data):
        self._updating = True
        self._current_id = obj_id
        self._id_label.setText(f"ID: {obj_id}")
        self._spin_x.setValue(obj_data.get("x", 0))
        self._spin_y.setValue(obj_data.get("y", 0))
        self._spin_w.setValue(obj_data.get("w", 100))
        self._spin_h.setValue(obj_data.get("h", 100))
        self._spin_opacity.setValue(obj_data.get("opacity", 1.0))
        self._spin_font.setValue(obj_data.get("font_size", 24))
        self._cb_visible.setChecked(obj_data.get("visible", True))
        self._updating = False

    def clear_properties(self):
        self._updating = True
        self._current_id = None
        self._id_label.setText("(none selected)")
        self._spin_x.setValue(0)
        self._spin_y.setValue(0)
        self._spin_w.setValue(100)
        self._spin_h.setValue(100)
        self._spin_opacity.setValue(1.0)
        self._spin_font.setValue(24)
        self._cb_visible.setChecked(True)
        self._updating = False


# =========================================================
#  Main Window
# =========================================================

class BookWunderwaffeStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Book Wunderwaffe Studio 1.0 — La machine merveilleuse pour forger les livres")
        self.setMinimumSize(1280, 800)
        self.resize(1440, 900)
        self.setStyleSheet(f"background-color: {DARK_BG};")

        # State
        self._project_data = {}
        self._chapters = []
        self._chapters_index = 0
        self._waveform_data = None
        self._layout_data = None
        self._layout_dirty = False
        self._bg_pixmap = None
        self._cover_pixmap = None
        self._active_process = None
        self._selected_item_id = None

        # Build paths
        BUILD_DIR.mkdir(exist_ok=True)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Top bar
        self._top_bar = self._create_top_bar()
        main_layout.addWidget(self._top_bar)

        # Splitter: left / canvas / right
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self._splitter, 1)

        # Left panel
        self._left_panel = self._create_left_panel()
        self._splitter.addWidget(self._left_panel)

        # Canvas
        self._scene = CanvasScene(self)
        self._view = QGraphicsView(self._scene)
        self._view.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self._view.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        self._view.setStyleSheet("background-color: #000; border: none;")
        self._view.setSceneRect(0, 0, SCENE_W, SCENE_H)
        self._splitter.addWidget(self._view)

        # Right panel
        self._props_panel = PropertiesPanel()
        self._splitter.addWidget(self._props_panel)

        self._splitter.setSizes([260, 880, 260])

        # Bottom bar
        bottom_bar = self._create_bottom_bar()
        main_layout.addWidget(bottom_bar)

        # Log dock
        self._log_dock = QDockWidget("Log", self)
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

        # Connect scene signals
        self._scene.layoutChanged.connect(self._on_layout_changed)
        self._scene.selectionChanged.connect(self._on_selection_changed)

        # Init
        self._load_project()

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

        self._status_label = QLabel("NOT READY")
        self._status_label.setStyleSheet(f"font-size: 12px; color: #ff5555; font-weight: bold;")
        layout.addWidget(self._status_label)

        layout.addSpacing(16)

        self._audio_label = QLabel("Audio: —")
        self._audio_label.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        layout.addWidget(self._audio_label)

        layout.addSpacing(16)

        self._ch_count_label = QLabel("Ch: —")
        self._ch_count_label.setStyleSheet(f"font-size: 11px; color: {TEXT_SECONDARY};")
        layout.addWidget(self._ch_count_label)

        layout.addStretch()

        # Show log toggle
        btn_log = QPushButton("Log")
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
        info_group = QGroupBox("Project")
        info_group.setStyleSheet(f"""
            QGroupBox {{ color: {ACCENT_CYAN}; font-weight: bold; border: 1px solid {BORDER_COLOR};
                         border-radius: 6px; margin-top: 8px; padding-top: 12px; }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; }}
        """)
        info_layout = QVBoxLayout(info_group)
        info_layout.setSpacing(4)

        self._lbl_audio = QLabel("Audio: —")
        self._lbl_rpp = QLabel("RPP: —")
        self._lbl_cover = QLabel("Cover: —")
        self._lbl_bg = QLabel("Background: —")
        self._lbl_chapters = QLabel("Chapters: —")
        self._lbl_intro = QLabel("Intro: —")
        self._lbl_epilogue = QLabel("Epilogue: —")
        for lbl in [self._lbl_audio, self._lbl_rpp, self._lbl_cover,
                     self._lbl_bg, self._lbl_chapters, self._lbl_intro, self._lbl_epilogue]:
            lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 11px; padding: 2px 0;")
            info_layout.addWidget(lbl)

        layout.addWidget(info_group)

        # Buttons group
        btn_group = QGroupBox("Actions")
        btn_group.setStyleSheet(info_group.styleSheet())
        btn_layout = QVBoxLayout(btn_group)
        btn_layout.setSpacing(4)

        btn_scan = QPushButton("🔍 Scan")
        btn_scan.clicked.connect(lambda: self._run_command("scan"))
        btn_scan.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_scan)

        btn_chapters = QPushButton("📖 Extract Chapters")
        btn_chapters.clicked.connect(lambda: self._run_command("chapters"))
        btn_chapters.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_chapters)

        btn_waveform = QPushButton("🌊 Generate Waveform")
        btn_waveform.clicked.connect(lambda: self._run_command("waveform"))
        btn_waveform.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_waveform)

        btn_reset = QPushButton("🔄 Reset Layout")
        btn_reset.clicked.connect(self._reset_layout)
        btn_reset.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_reset)

        btn_save = QPushButton("💾 Save Layout")
        btn_save.clicked.connect(self._save_layout)
        btn_save.setStyleSheet(self._btn_style(ACCENT_GREEN))
        btn_layout.addWidget(btn_save)

        btn_reload = QPushButton("📂 Reload Layout")
        btn_reload.clicked.connect(self._load_layout)
        btn_reload.setStyleSheet(self._btn_style())
        btn_layout.addWidget(btn_reload)

        layout.addWidget(btn_group)
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

    # --- Bottom bar ---
    def _create_bottom_bar(self):
        bar = QWidget()
        bar.setFixedHeight(44)
        bar.setStyleSheet(f"background-color: {DARK_PANEL}; border-top: 1px solid {BORDER_COLOR};")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        lbl = QLabel("Chapter:")
        lbl.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(lbl)

        self._chapter_combo = QComboBox()
        self._chapter_combo.setMinimumWidth(320)
        self._chapter_combo.setStyleSheet(f"""
            QComboBox {{
                background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
                border: 1px solid {BORDER_COLOR}; border-radius: 4px;
                padding: 3px 8px; font-size: 11px;
            }}
            QComboBox:hover {{ border-color: {ACCENT_CYAN}; }}
            QComboBox::drop-down {{
                subcontrol-origin: padding; subcontrol-position: top right;
                width: 20px; border-left: 1px solid {BORDER_COLOR};
            }}
        """)
        self._chapter_combo.currentIndexChanged.connect(self._on_chapter_selected)
        layout.addWidget(self._chapter_combo)

        layout.addSpacing(12)

        btn_contact = QPushButton("Preview Contact")
        btn_contact.clicked.connect(lambda: self._run_command("preview_contact"))
        btn_contact.setStyleSheet(self._btn_style())
        layout.addWidget(btn_contact)

        btn_test = QPushButton("Render Test 60s")
        btn_test.clicked.connect(lambda: self._run_command("render_test"))
        btn_test.setStyleSheet(self._btn_style())
        layout.addWidget(btn_test)

        btn_full = QPushButton("⚠ Full Render")
        btn_full.clicked.connect(self._confirm_full_render)
        btn_full.setStyleSheet(self._btn_style("#ff5555"))
        layout.addWidget(btn_full)

        btn_open = QPushButton("📁 Open Build")
        btn_open.clicked.connect(lambda: os.startfile(str(BUILD_DIR)))
        btn_open.setStyleSheet(self._btn_style())
        layout.addWidget(btn_open)

        return bar

    # --- Load project ---
    def _load_project(self):
        self.log("Loading project...")
        config = load_json(PROJECT_CONFIG)
        if config:
            self._project_data = config
            self.log(f"Project config loaded: {config.get('audio_file', '?')}")
        else:
            self.log("No project config found. Run Scan first.")

        # Load chapters
        self._load_chapters()

        # Load waveform
        self._load_waveform()

        # Load layout
        self._load_layout()

        self._update_project_info()
        self._rebuild_canvas()
        self._update_status()

    def _load_chapters(self):
        ch = load_json(CHAPTERS_PATH)
        if ch and isinstance(ch, list):
            self._chapters = ch
            self.log(f"Loaded {len(ch)} chapters")
        else:
            self._chapters = []
            self.log("No chapters found. Run Extract Chapters.")

        self._chapter_combo.blockSignals(True)
        self._chapter_combo.clear()
        for i, c in enumerate(self._chapters):
            title = c.get("title", f"Segment {i}")
            start = c.get("start", "00:00:00")
            self._chapter_combo.addItem(f"{start} — {title}", i)
        self._chapter_combo.blockSignals(False)

    def _load_waveform(self):
        wf = load_json(WAVEFORM_PATH)
        if wf and isinstance(wf, list) and len(wf) > 10:
            self._waveform_data = wf
            self.log(f"Waveform loaded: {len(wf)} samples")
        else:
            self._waveform_data = None
            self.log("No waveform data. Generate waveform.")

    def _load_layout(self):
        lt = load_json(LAYOUT_PATH)
        if lt and isinstance(lt, dict):
            self._layout_data = lt
            self.log("Layout loaded from file.")
        else:
            self._layout_data = dict(DEFAULT_LAYOUT)
            self.log("Using default layout.")

    def _reset_layout(self):
        self._layout_data = dict(DEFAULT_LAYOUT)
        self._rebuild_canvas()
        self._layout_dirty = True
        self.log("Layout reset to default.")
        self._update_status()

    def _save_layout(self):
        if not self._layout_data:
            self.log("Nothing to save.")
            return
        save_json(LAYOUT_PATH, self._layout_data)
        self._layout_dirty = False
        self.log(f"Layout saved: {LAYOUT_PATH}")
        self._update_status()

    def _rebuild_canvas(self):
        self._scene.clear_canvas()
        lt = self._layout_data or DEFAULT_LAYOUT

        # Load pixmaps
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
        title_data["text"] = self._project_data.get("title", "ЗИНА")
        self._scene.add_canvas_item(OBJ_BOOK_TITLE, title_data)

        # Current chapter
        ch_data = lt.get(OBJ_CURRENT_CHAPTER, DEFAULT_LAYOUT["currentChapter"])
        if self._chapters:
            ch_data["text"] = self._chapters[0].get("title", "Вступление от автора")
        self._scene.add_canvas_item(OBJ_CURRENT_CHAPTER, ch_data)

        # Waveform
        wf_data = lt.get(OBJ_WAVEFORM, DEFAULT_LAYOUT["waveform"])
        self._scene.add_canvas_item(OBJ_WAVEFORM, wf_data, waveform_data=self._waveform_data)

        # Progress
        prog_data = lt.get(OBJ_PROGRESS, DEFAULT_LAYOUT["progress"])
        self._scene.add_canvas_item(OBJ_PROGRESS, prog_data)

        # Brand
        brand_data = lt.get(OBJ_BRAND, DEFAULT_LAYOUT["brand"])
        self._scene.add_canvas_item(OBJ_BRAND, brand_data)

        self._view.fitInView(0, 0, SCENE_W, SCENE_H, Qt.AspectRatioMode.KeepAspectRatio)
        self.log("Canvas rebuilt.")

    def _update_project_info(self):
        config = self._project_data
        audio = config.get("audio_file", "—")
        rpp = config.get("rpp_file", "—")
        cover = config.get("cover_file", "—")
        bg = config.get("background_file", "—")

        self._lbl_audio.setText(f"Audio: {Path(audio).name if audio != '—' else '—'}")
        self._lbl_rpp.setText(f"RPP: {Path(rpp).name if rpp != '—' else '—'}")
        self._lbl_cover.setText(f"Cover: {Path(cover).name if cover != '—' else '—'}")
        self._lbl_bg.setText(f"Background: {Path(bg).name if bg != '—' else '—'}")
        self._lbl_chapters.setText(f"Chapters: {len(self._chapters)}")
        self._lbl_intro.setText(f"Intro: {'YES' if self._chapters and 'Вступление' in self._chapters[0].get('title', '') else '?'}")
        self._lbl_epilogue.setText(f"Epilogue: {'YES' if any('Эпилог' in c.get('title', '') for c in self._chapters) else '?'}")

        self._audio_label.setText(f"Audio: {Path(audio).name if audio != '—' else '—'}")
        self._ch_count_label.setText(f"Ch: {len(self._chapters)}")

    def _update_status(self):
        ready = len(self._chapters) > 0
        if ready:
            self._status_label.setText("● READY")
            self._status_label.setStyleSheet("font-size: 12px; color: #00ff88; font-weight: bold;")
        else:
            self._status_label.setText("● NOT READY")
            self._status_label.setStyleSheet("font-size: 12px; color: #ff5555; font-weight: bold;")

    # --- Chapter selection ---
    def _on_chapter_selected(self, idx):
        if idx < 0 or idx >= len(self._chapters):
            return
        ch = self._chapters[idx]
        self._chapters_index = idx
        title = ch.get("title", "?")
        # Update canvas chapter text
        item = self._scene.get_item(OBJ_CURRENT_CHAPTER)
        if item and hasattr(item, "obj_data"):
            item.obj_data["text"] = title
            item.setPlainText(title)
        # Update progress
        total_s = 0.0
        if self._chapters:
            last = self._chapters[-1]
            total_s = timestr_to_seconds(last.get("end", "15:48:50.932"))
        start_s = timestr_to_seconds(ch.get("start", "0"))
        prog = start_s / total_s if total_s > 0 else 0
        prog_item = self._scene.get_item(OBJ_PROGRESS)
        if prog_item and isinstance(prog_item, ProgressItem):
            prog_item.set_progress(prog)
        self.log(f"Chapter: {title} @ {ch.get('start', '?')}")

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
            QMessageBox.warning(self, "Busy", "A command is already running. Wait for it to finish.")
            return

        cmds = {
            "scan": ["python", "bookforge.py", "scan"],
            "chapters": ["python", "bookforge.py", "chapters"],
            "waveform": ["python", "bookforge.py", "waveform"],
            "preview_contact": ["python", "bookforge.py", "preview", "--contact"],
            "render_test": ["python", "bookforge.py", "render-test", "--overwrite"],
        }
        cmd = cmds.get(cmd_name)
        if not cmd:
            self.log(f"Unknown command: {cmd_name}")
            return

        self.log(f"Running: {' '.join(cmd)}")
        self._active_process = QProcess(self)
        self._active_process.setWorkingDirectory(str(PROJECT_ROOT))
        self._active_process.readyReadStandardOutput.connect(self._on_process_output)
        self._active_process.readyReadStandardError.connect(self._on_process_error)
        self._active_process.finished.connect(lambda exit_code: self._on_process_finished(exit_code, cmd_name))
        self._active_process.start(cmd[0], cmd[1:])

    def _on_process_output(self):
        data = self._active_process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self.log(data.strip())

    def _on_process_error(self):
        data = self._active_process.readAllStandardError().data().decode("utf-8", errors="replace")
        self.log(f"[ERR] {data.strip()}")

    def _on_process_finished(self, exit_code, cmd_name):
        self.log(f"Command '{cmd_name}' finished (exit: {exit_code})")
        self._active_process = None

        # Reload data
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
            self.log("Preview contact generated. Check build folder.")

    def _confirm_full_render(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Confirm Full Render")
        dlg.setMinimumWidth(400)
        dlg.setStyleSheet(f"background-color: {DARK_PANEL}; color: {TEXT_PRIMARY};")
        layout = QVBoxLayout(dlg)
        lbl = QLabel("Full render may take a long time (>1 hour).\nType RENDER FULL to continue:")
        lbl.setStyleSheet(f"color: {TEXT_PRIMARY}; font-size: 13px;")
        layout.addWidget(lbl)
        inp = QLineEdit()
        inp.setStyleSheet(f"""
            background-color: {DARK_CARD}; color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_COLOR}; padding: 6px; font-size: 14px;
        """)
        layout.addWidget(inp)
        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Render")
        btn_ok.setStyleSheet(f"""
            QPushButton {{ background-color: #aa3333; color: white; padding: 6px 16px;
                         border: none; border-radius: 4px; font-weight: bold; }}
            QPushButton:hover {{ background-color: #cc4444; }}
        """)
        btn_cancel = QPushButton("Cancel")
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
                QMessageBox.warning(dlg, "Canceled", "Type RENDER FULL exactly.")

        btn_ok.clicked.connect(on_ok)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._run_command("render_full")
            self.log("⚠ Full render started (manual confirmation).")

    # --- Log ---
    def log(self, msg):
        self._log_widget.append(msg)
        print(msg)

    # --- Wheel zoom ---
    def wheelEvent(self, event):
        # Let the view handle zoom via Ctrl+Wheel
        pass


# =========================================================
#  Main entry
# =========================================================

def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon())
    win = BookWunderwaffeStudio()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()