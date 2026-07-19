from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .analysis import beat_grid
from .audio import waveform_peaks, write_wav
from .config import AppConfig
from .core import (
    LoadedProject,
    change_mode,
    export_project,
    load_project,
    update_loop_duration_warning,
)
from .exporter import render_reconstruction
from .models import ExportFormat, ExportSettings, Session
from .playback import (
    PlaybackContext,
    map_player_position_to_waveform,
    original_playback_context,
    reconstruct_playback_context,
    slice_playback_context,
)
from .session import (
    SessionError,
    SourceStatus,
    is_remote_path,
    load_session,
    relink_source,
    save_session,
)
from .slicing import normalize_markers, snap_marker

log = logging.getLogger(__name__)

SESSION_SUFFIX = ".chopscout.json"
SESSION_FILTER = f"ChopScout session (*{SESSION_SUFFIX});;All files (*)"
# Rewritten by save_session on every write, so they are excluded from the
# dirty-state comparison; otherwise a freshly saved session reads as modified.
VOLATILE_SESSION_FIELDS = ("schema_version", "app_version", "source_size")
MAX_DISPLAYED_PATH = 200


def display_path(value: str, limit: int = MAX_DISPLAYED_PATH) -> str:
    """Shorten a session-supplied path so it cannot flood a dialog."""
    return value if len(value) <= limit else value[:limit] + "…"


class WorkerSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class LoadWorker(QRunnable):
    def __init__(self, path: str, mode: str, sensitivity: float):
        super().__init__()
        self.path = path
        self.mode = mode
        self.sensitivity = sensitivity
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.done.emit(load_project(self.path, self.mode, self.sensitivity))
        except Exception as exc:
            log.exception("load failed")
            self.signals.failed.emit(str(exc))


class ExportWorker(QRunnable):
    def __init__(self, project: LoadedProject, output: str, settings: ExportSettings):
        super().__init__()
        self.project = project
        self.output = output
        self.settings = settings
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.done.emit(export_project(self.project, self.output, self.settings))
        except Exception as exc:
            log.exception("export failed")
            self.signals.failed.emit(str(exc))


class WaveformWidget(QWidget):
    marker_moved = Signal(int, float)
    marker_added = Signal(float)
    marker_removed = Signal(int)
    selection_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(320)
        self.setFocusPolicy(Qt.StrongFocus)
        self.peaks = np.array([], dtype=np.float32)
        self.duration = 1.0
        self.markers = []
        self.beats = []
        self.downbeat = 0.0
        self.playhead = None
        self.active_slice = None
        self.selected = 0
        self.dragging = None
        self.zoom = 1.0
        self.offset = 0.0

    def clear(self):
        self.peaks = np.array([], dtype=np.float32)
        self.duration = 1.0
        self.markers = []
        self.beats = []
        self.downbeat = 0.0
        self.selected = 0
        self.dragging = None
        self.zoom = 1.0
        self.offset = 0.0
        self.reset_playback_visuals()

    def set_project(self, project: LoadedProject):
        self.peaks = waveform_peaks(project.data)
        self.duration = project.analysis.audio.duration
        self.markers = list(project.markers)
        self.beats = list(project.analysis.beat_times)
        self.downbeat = project.analysis.downbeat
        self.zoom = 1.0
        self.offset = 0.0
        self.selected = 0
        self.reset_playback_visuals()
        self.update()

    def set_active_slices(self, markers: list[float]):
        self.markers = list(markers)
        self.selected = min(self.selected, max(0, len(self.markers) - 1))
        self.update()

    def set_playback_position(self, position: float | None):
        self.playhead = position
        self.update()

    def set_active_slice(self, index: int | None):
        self.active_slice = index
        self.update()

    def reset_playback_visuals(self):
        self.playhead = None
        self.active_slice = None
        self.update()

    def visible_span(self):
        return self.duration / self.zoom

    def x_for_time(self, value):
        return (value - self.offset) / self.visible_span() * self.width()

    def time_for_x(self, x):
        return max(
            0.0, min(self.duration, self.offset + x / max(1, self.width()) * self.visible_span())
        )

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#17191d"))
        p.setRenderHint(QPainter.Antialiasing)
        if self.peaks.size == 0:
            p.setPen(QColor("#9ca3af"))
            p.drawText(self.rect(), Qt.AlignCenter, "Drop a break here")
            return
        mid = self.height() / 2
        p.setPen(QPen(QColor("#5b6472"), 1))
        count = len(self.peaks)
        start = max(0, int(self.offset / self.duration * count))
        end = min(count, int((self.offset + self.visible_span()) / self.duration * count) + 1)
        path = QPainterPath()
        first = True
        for i in range(start, end):
            x = self.x_for_time(i / count * self.duration)
            pair = self.peaks[i]
            lo, hi = (
                (float(pair[0]), float(pair[1]))
                if np.ndim(pair)
                else (-abs(float(pair)), abs(float(pair)))
            )
            if first:
                path.moveTo(x, mid - hi * (mid - 12))
                first = False
            else:
                path.lineTo(x, mid - hi * (mid - 12))
        for i in range(end - 1, start - 1, -1):
            x = self.x_for_time(i / count * self.duration)
            pair = self.peaks[i]
            lo = float(pair[0]) if np.ndim(pair) else -abs(float(pair))
            path.lineTo(x, mid - lo * (mid - 12))
        path.closeSubpath()
        p.fillPath(path, QColor("#4f8fcf"))
        for idx, beat in enumerate(self.beats):
            x = self.x_for_time(beat)
            if 0 <= x <= self.width():
                p.setPen(QPen(QColor("#4b5563") if idx % 4 else QColor("#7c8492"), 1))
                p.drawLine(x, 0, x, self.height())
        if self.active_slice is not None and 0 <= self.active_slice < len(self.markers):
            start = self.markers[self.active_slice]
            end = (
                self.markers[self.active_slice + 1]
                if self.active_slice + 1 < len(self.markers)
                else self.duration
            )
            x1 = self.x_for_time(start)
            x2 = self.x_for_time(end)
            if x2 >= 0 and x1 <= self.width():
                p.fillRect(
                    QRectF(max(0, x1), 0, min(self.width(), x2) - max(0, x1), self.height()),
                    QColor(242, 184, 75, 45),
                )
        for idx, m in enumerate(self.markers):
            x = self.x_for_time(m)
            if 0 <= x <= self.width():
                if idx == self.selected:
                    next_m = self.markers[idx + 1] if idx + 1 < len(self.markers) else self.duration
                    p.fillRect(
                        QRectF(x, 0, self.x_for_time(next_m) - x, self.height()),
                        QColor(70, 120, 190, 35),
                    )
                p.setPen(QPen(QColor("#f2b84b") if idx != self.selected else QColor("#ffffff"), 2))
                p.drawLine(x, 0, x, self.height())
                p.drawText(QPointF(x + 4, 18), f"{idx + 1}")
        x = self.x_for_time(self.downbeat)
        p.setPen(QPen(QColor("#ef6b73"), 3, Qt.DashLine))
        p.drawLine(x, 0, x, 34)
        p.drawText(QPointF(x + 5, 32), "downbeat")
        if self.playhead is not None:
            x = self.x_for_time(self.playhead)
            p.setPen(QPen(QColor("#e5e7eb"), 2))
            p.drawLine(x, 0, x, self.height())
            p.drawText(QPointF(x + 5, self.height() - 12), "play")

    def wheelEvent(self, event):
        old = self.time_for_x(event.position().x())
        self.zoom = max(
            1.0, min(32.0, self.zoom * (1.2 if event.angleDelta().y() > 0 else 1 / 1.2))
        )
        self.offset = max(
            0.0,
            min(
                self.duration - self.visible_span(),
                old - event.position().x() / self.width() * self.visible_span(),
            ),
        )
        self.update()

    def mousePressEvent(self, event):
        t = self.time_for_x(event.position().x())
        nearest = min(range(len(self.markers)), key=lambda i: abs(self.markers[i] - t), default=0)
        if self.markers and abs(self.x_for_time(self.markers[nearest]) - event.position().x()) < 9:
            if event.button() == Qt.RightButton and nearest > 0:
                self.marker_removed.emit(nearest)
                return
            self.selected = nearest
            self.dragging = nearest
            self.selection_changed.emit(nearest)
            self.update()
        elif event.button() == Qt.LeftButton:
            self.marker_added.emit(t)

    def mouseMoveEvent(self, event):
        if self.dragging is not None:
            self.marker_moved.emit(self.dragging, self.time_for_x(event.position().x()))

    def mouseReleaseEvent(self, _event):
        self.dragging = None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChopScout")
        self.resize(1280, 760)
        self.setAcceptDrops(True)
        self.pool = QThreadPool.globalInstance()
        self.project = None
        self.config = AppConfig.load()
        self.current_session_path: Path | None = None
        # pad_map has no producer or consumer in the app yet; it is round-tripped
        # verbatim so a session written by a future build is not silently dropped.
        self.pad_map: dict[str, int] = {}
        self._clean_snapshot: dict | None = None
        self.temp_paths = []
        self._controls_enabled = False
        self._playback_context: PlaybackContext | None = None
        self._playback_generation = 0
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)
        self.player.positionChanged.connect(self.player_position_changed)
        self.player.mediaStatusChanged.connect(self.player_media_status_changed)
        self._build()
        self._set_enabled(False)

    def _build(self):
        self._build_session_menu()
        toolbar = QToolBar()
        self.addToolBar(toolbar)
        open_action = QAction("Open", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.choose_file)
        toolbar.addAction(open_action)
        self.export_action = QAction("Export MPC Package", self)
        self.export_action.setShortcut("Ctrl+E")
        self.export_action.triggered.connect(self.export)
        toolbar.addAction(self.export_action)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel(" BPM "))
        self.bpm = QDoubleSpinBox()
        self.bpm.setRange(20, 400)
        self.bpm.setDecimals(2)
        self.bpm.valueChanged.connect(self.bpm_changed)
        toolbar.addWidget(self.bpm)
        self.half = QPushButton("½×")
        self.half.clicked.connect(lambda: self.bpm.setValue(self.bpm.value() / 2))
        toolbar.addWidget(self.half)
        self.double = QPushButton("2×")
        self.double.clicked.connect(lambda: self.bpm.setValue(self.bpm.value() * 2))
        toolbar.addWidget(self.double)
        toolbar.addWidget(QLabel(" Bars "))
        self.bars = QSpinBox()
        self.bars.setRange(1, 128)
        self.bars.valueChanged.connect(self.bars_changed)
        toolbar.addWidget(self.bars)
        splitter = QSplitter()
        left = QFrame()
        form = QFormLayout(left)
        self.mode = QComboBox()
        self.mode.addItems(
            [
                "transient",
                "equal8",
                "equal16",
                "equal32",
                "equal48",
                "equal64",
                "beat",
                "eighth",
                "sixteenth",
                "hybrid",
                "manual",
            ]
        )
        self.mode.currentTextChanged.connect(self.mode_changed)
        form.addRow("Chop mode", self.mode)
        self.export_format = QComboBox()
        self.export_format.addItems([item.value for item in ExportFormat])
        self.export_format.setCurrentText(ExportFormat.BOTH.value)
        self.export_format.currentTextChanged.connect(self.export_format_changed)
        form.addRow("Export format", self.export_format)
        self.pad_count = QComboBox()
        self.pad_count.addItems(
            [
                "16 pads (Bank A)",
                "32 pads (Banks A-B)",
                "48 pads (Banks A-C)",
                "64 pads (Banks A-D)",
            ]
        )
        self.pad_count.currentIndexChanged.connect(self.pad_count_changed)
        form.addRow("MPC layout", self.pad_count)
        self.overwrite = QCheckBox("Replace an existing export with the same name")
        form.addRow("Overwrite", self.overwrite)
        self.sensitivity = QDoubleSpinBox()
        self.sensitivity.setRange(0.35, 0.9)
        self.sensitivity.setSingleStep(0.05)
        self.sensitivity.setValue(0.55)
        form.addRow("Detection sensitivity", self.sensitivity)
        self.snap = QComboBox()
        self.snap.addItems(["Transients", "Beat grid", "No snapping"])
        form.addRow("Marker snap", self.snap)
        self.start_note = QSpinBox()
        self.start_note.setRange(0, 127)
        self.start_note.setValue(36)
        self.start_note.valueChanged.connect(
            lambda _value: self.selection_changed(self.wave.selected)
        )
        form.addRow("First MIDI note", self.start_note)
        self.info = QLabel(
            "Drop a break here.\n\nExports support complete XPJ projects and standalone XPM programs across Banks A-D for MPC 3.9.0."
        )
        self.info.setWordWrap(True)
        form.addRow(self.info)
        center = QWidget()
        cv = QVBoxLayout(center)
        self.wave = WaveformWidget()
        cv.addWidget(self.wave, 1)
        self.wave.marker_moved.connect(self.marker_moved)
        self.wave.marker_added.connect(self.marker_added)
        self.wave.marker_removed.connect(self.marker_removed)
        self.wave.selection_changed.connect(self.selection_changed)
        transport = QHBoxLayout()
        for text, fn in [
            ("Play original", self.play_original),
            ("Play slice", self.play_slice),
            ("Reconstruct", self.play_reconstruction),
            ("Stop", self.stop_playback),
        ]:
            button = QPushButton(text)
            button.clicked.connect(fn)
            transport.addWidget(button)
        cv.addLayout(transport)
        right = QFrame()
        rf = QFormLayout(right)
        self.slice_label = QLabel("No slice selected")
        rf.addRow(self.slice_label)
        self.downbeat = QDoubleSpinBox()
        self.downbeat.setRange(0, 99999)
        self.downbeat.setDecimals(4)
        self.downbeat.valueChanged.connect(self.downbeat_changed)
        rf.addRow("First downbeat (s)", self.downbeat)
        self.confidence = QLabel("—")
        rf.addRow("Confidence", self.confidence)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setSizes([220, 850, 240])
        self.setCentralWidget(splitter)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Ready")

    def _build_session_menu(self):
        menu = self.menuBar().addMenu("Session")
        new_action = QAction("New", self)
        new_action.setShortcut(QKeySequence.New)
        new_action.triggered.connect(self.session_new)
        menu.addAction(new_action)
        open_action = QAction("Open Session…", self)
        open_action.setShortcut("Ctrl+Shift+O")
        open_action.triggered.connect(self.session_open)
        menu.addAction(open_action)
        menu.addSeparator()
        self.save_session_action = QAction("Save Session", self)
        self.save_session_action.setShortcut(QKeySequence.Save)
        self.save_session_action.triggered.connect(self.session_save)
        menu.addAction(self.save_session_action)
        self.save_session_as_action = QAction("Save Session As…", self)
        self.save_session_as_action.setShortcut(QKeySequence.SaveAs)
        self.save_session_as_action.triggered.connect(self.session_save_as)
        menu.addAction(self.save_session_as_action)
        menu.addSeparator()
        self.recent_menu = menu.addMenu("Recent Sessions")
        self._refresh_recent_menu()

    def _refresh_recent_menu(self):
        self.recent_menu.clear()
        if not self.config.recent_files:
            empty = self.recent_menu.addAction("No recent sessions")
            empty.setEnabled(False)
            return
        for item in self.config.recent_files:
            action = self.recent_menu.addAction(Path(item).name)
            action.setToolTip(item)
            action.triggered.connect(lambda _checked=False, path=item: self._open_session_path(path))

    def _set_enabled(self, value):
        self._controls_enabled = value
        for w in [
            self.export_action,
            self.save_session_action,
            self.save_session_as_action,
            self.bpm,
            self.half,
            self.double,
            self.bars,
            self.mode,
            self.export_format,
            self.pad_count,
            self.overwrite,
            self.sensitivity,
            self.snap,
            self.start_note,
            self.downbeat,
        ]:
            w.setEnabled(value)
        if hasattr(self, "pad_count"):
            self._sync_pad_count_to_mode(
                self.project.mode if self.project else self.mode.currentText()
            )
        if hasattr(self, "export_format"):
            self._sync_export_format_controls()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.load(urls[0].toLocalFile())

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open break",
            "",
            "Audio (*.wav *.aif *.aiff *.flac *.mp3 *.ogg *.m4a);;All files (*)",
        )
        if path:
            self.load(path)

    def load(self, path):
        if not self._confirm_discard("Open audio"):
            return
        self.stop_playback()
        # Plain audio starts an untitled session; Save must ask where to write it.
        self.current_session_path = None
        self.pad_map = {}
        self.statusBar().showMessage("Analyzing audio…")
        self._set_enabled(False)
        worker = LoadWorker(path, self.mode.currentText(), self.sensitivity.value())
        worker.signals.done.connect(self.loaded)
        worker.signals.failed.connect(self.failed)
        self.pool.start(worker)

    def loaded(self, project):
        self.project = project
        self.wave.set_project(project)
        self.mode.blockSignals(True)
        self.mode.setCurrentText(project.mode)
        self.mode.blockSignals(False)
        self.bpm.blockSignals(True)
        self.bpm.setValue(project.analysis.selected_bpm)
        self.bpm.blockSignals(False)
        self._sync_pad_count_to_mode(project.mode)
        self.bars.blockSignals(True)
        self.bars.setValue(project.analysis.estimated_bars)
        self.bars.blockSignals(False)
        self.downbeat.blockSignals(True)
        self.downbeat.setMaximum(project.analysis.audio.duration)
        self.downbeat.setValue(project.analysis.downbeat)
        self.downbeat.blockSignals(False)
        c = project.analysis.tempo_confidence
        label = "high" if c >= 0.4 else "medium" if c >= 0.15 else "low"
        self.confidence.setText(f"Tempo: {label} ({c:.2f})")
        self._update_info()
        self._set_enabled(True)
        # Freshly analyzed audio is the baseline, not unsaved work; edits from
        # here are what make the session dirty.
        self._mark_clean()
        self.statusBar().showMessage("Analysis complete")

    def failed(self, message):
        QMessageBox.critical(self, "ChopScout", message)
        self.statusBar().showMessage("Operation failed")
        self._set_enabled(self.project is not None)

    def bpm_changed(self, value):
        if not self.project:
            return
        self.project.analysis.selected_bpm = value
        self.project.analysis.beat_times = beat_grid(
            self.project.analysis.audio.duration, value, self.project.analysis.downbeat
        )
        self.wave.beats = self.project.analysis.beat_times
        update_loop_duration_warning(self.project.analysis, value, self.bars.value())
        self.wave.update()
        self._update_info()

    def bars_changed(self, value):
        if not self.project:
            return
        update_loop_duration_warning(self.project.analysis, self.bpm.value(), value)
        self._update_info()

    def downbeat_changed(self, value):
        if not self.project:
            return
        self.project.analysis.downbeat = value
        self.project.analysis.beat_times = beat_grid(
            self.project.analysis.audio.duration, self.bpm.value(), value
        )
        self.wave.downbeat = value
        self.wave.beats = self.project.analysis.beat_times
        self.wave.update()

    def mode_changed(self, mode):
        if not self.project:
            return
        self.set_chop_mode(mode)

    def set_chop_mode(self, mode):
        if not self.project:
            return
        self.stop_playback()
        change_mode(self.project, mode)
        self.wave.set_active_slices(self.project.markers)
        self.mode.blockSignals(True)
        self.mode.setCurrentText(self.project.mode)
        self.mode.blockSignals(False)
        self._sync_pad_count_to_mode(self.project.mode)
        self.selection_changed(min(self.wave.selected, max(0, len(self.project.markers) - 1)))
        self._update_info()

    def pad_count_changed(self, index):
        if not self.project:
            return
        count = (16, 32, 48, 64)[index]
        self.mode.setCurrentText(f"equal{count}")

    def export_format_changed(self, _format):
        self._sync_export_format_controls()
        if self.project:
            self.selection_changed(self.wave.selected)

    def _update_info(self):
        if not self.project:
            return
        warn = "\n".join(f"• {x}" for x in self.project.analysis.warnings) or "No major warnings."
        self.info.setText(
            f"{Path(self.project.path).name}\n{self.project.analysis.audio.duration:.2f}s · {self.project.sample_rate} Hz · {self.project.analysis.audio.channels} ch\n{len(self.project.markers)} slices · mode {self.project.mode}\n\n{warn}"
        )
        self._update_window_title()

    def _mode_pad_count(self, mode):
        return {"equal16": 16, "equal32": 32, "equal48": 48, "equal64": 64}.get(mode)

    def _sync_pad_count_to_mode(self, mode):
        count = self._mode_pad_count(mode)
        self.pad_count.blockSignals(True)
        if count is None:
            self.pad_count.setCurrentIndex(0)
            self.pad_count.setEnabled(False)
            self.pad_count.setToolTip(
                "MPC layout is explicit only for equal16, equal32, equal48, and equal64 modes."
            )
        else:
            self.pad_count.setCurrentIndex((16, 32, 48, 64).index(count))
            self.pad_count.setEnabled(self._controls_enabled)
            self.pad_count.setToolTip("")
        self.pad_count.blockSignals(False)

    def _sync_export_format_controls(self):
        export_format = ExportFormat(self.export_format.currentText())
        if export_format is ExportFormat.PORTABLE:
            self.start_note.setEnabled(self._controls_enabled)
            self.start_note.setToolTip("")
        else:
            self.start_note.blockSignals(True)
            self.start_note.setValue(36)
            self.start_note.blockSignals(False)
            self.start_note.setEnabled(False)
            self.start_note.setToolTip(
                "MPC exports use fixed drum notes 36-99. Use portable format for custom MIDI notes."
            )

    def _adopt_manual_markers(self, markers):
        if not self.project:
            return
        self.stop_playback()
        self.project.mode = "manual"
        self.project.markers = list(markers)
        self.wave.set_active_slices(self.project.markers)
        self.mode.blockSignals(True)
        self.mode.setCurrentText("manual")
        self.mode.blockSignals(False)
        self._update_info()

    def marker_moved(self, index, value):
        if not self.project:
            return
        candidates = (
            []
            if self.snap.currentText() == "No snapping"
            else (
                self.project.analysis.onset_times
                if self.snap.currentText() == "Transients"
                else self.project.analysis.beat_times
            )
        )
        value = snap_marker(value, candidates)
        marks = list(self.project.markers)
        marks[index] = value
        self._adopt_manual_markers(normalize_markers(marks, self.project.analysis.audio.duration))

    def marker_added(self, value):
        if not self.project:
            return
        self._adopt_manual_markers(
            normalize_markers(self.project.markers + [value], self.project.analysis.audio.duration)
        )

    def marker_removed(self, index):
        if not self.project or index <= 0:
            return
        marks = list(self.project.markers)
        del marks[index]
        self._adopt_manual_markers(marks)

    def selection_changed(self, index):
        if not self.project or not self.project.markers:
            return
        index = min(max(index, 0), len(self.project.markers) - 1)
        end = (
            self.project.markers[index + 1]
            if index + 1 < len(self.project.markers)
            else self.project.analysis.audio.duration
        )
        bank = chr(ord("A") + index // 16)
        pad = index % 16 + 1
        self.slice_label.setText(
            f"Bank {bank}, Pad {pad:02d} · note {self.start_note.value() + index}\n{self.project.markers[index]:.4f}s – {end:.4f}s"
        )

    def _play_array(self, data, context: PlaybackContext):
        if self.project is None:
            return
        self._playback_generation += 1
        self._playback_context = context
        path = Path(tempfile.gettempdir()) / f"chopscout-preview-{self._playback_generation}.wav"
        write_wav(path, data, self.project.sample_rate)
        self.temp_paths.append(path)
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self.player.play()

    def play_original(self):
        if self.project is not None:
            self._play_array(
                self.project.data,
                original_playback_context(
                    self.project.markers,
                    self.project.analysis.audio.duration,
                    self._playback_generation + 1,
                ),
            )

    def play_slice(self):
        if not self.project:
            return
        i = self.wave.selected
        start = self.project.markers[i]
        end = (
            self.project.markers[i + 1]
            if i + 1 < len(self.project.markers)
            else self.project.analysis.audio.duration
        )
        self._play_array(
            self.project.data[
                round(start * self.project.sample_rate) : round(end * self.project.sample_rate)
            ],
            slice_playback_context(
                self.project.markers,
                self.project.analysis.audio.duration,
                i,
                self._playback_generation + 1,
            ),
        )

    def play_reconstruction(self):
        if self.project is not None:
            self._play_array(
                render_reconstruction(
                    self.project.data,
                    self.project.sample_rate,
                    self.project.markers,
                    self.project.analysis.audio.duration,
                ),
                reconstruct_playback_context(
                    self.project.markers,
                    self.project.analysis.audio.duration,
                    self._playback_generation + 1,
                ),
            )

    def stop_playback(self):
        self._playback_generation += 1
        self._playback_context = None
        self.player.stop()
        self.wave.reset_playback_visuals()

    def player_position_changed(self, position_ms):
        context = self._playback_context
        if context is None or context.generation != self._playback_generation:
            return
        mapped = map_player_position_to_waveform(context, position_ms / 1000.0)
        self.wave.set_playback_position(mapped.position_seconds)
        self.wave.set_active_slice(mapped.active_slice)

    def player_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.stop_playback()

    def export(self):
        if not self.project:
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Choose export folder", self.config.last_export_dir or str(Path.home())
        )
        if not directory:
            return
        settings = self._export_settings()
        self.statusBar().showMessage("Exporting and validating…")
        self._set_enabled(False)
        worker = ExportWorker(self.project, directory, settings)
        worker.signals.done.connect(self.exported)
        worker.signals.failed.connect(self.failed)
        self.pool.start(worker)

    def _export_settings(self):
        return ExportSettings(
            mode=self.project.mode,
            starting_note=self.start_note.value(),
            bars=self.bars.value(),
            bpm=self.bpm.value(),
            overwrite=self.overwrite.isChecked(),
            export_format=ExportFormat(self.export_format.currentText()),
            pad_count=self._mode_pad_count(self.project.mode),
        )

    # ----- session workflow -------------------------------------------------

    def _session_from_state(self) -> Session:
        """Capture the live widget and project state as a Session."""
        analysis = self.project.analysis
        settings = self._export_settings()
        return Session(
            source_path=str(self.project.path),
            source_hash=analysis.audio.source_hash,
            detected_bpm=analysis.detected_bpm,
            selected_bpm=self.bpm.value(),
            bar_count=self.bars.value(),
            downbeat=self.downbeat.value(),
            markers=list(self.project.markers),
            chop_mode=self.project.mode,
            pad_map=dict(self.pad_map),
            export_settings={
                "mode": settings.mode,
                "starting_note": settings.starting_note,
                "bars": settings.bars,
                "bpm": settings.bpm,
                "short_fades_ms": settings.short_fades_ms,
                "overwrite": settings.overwrite,
                "export_format": str(settings.export_format),
                "pad_count": settings.pad_count,
            },
        )

    def _state_snapshot(self) -> dict | None:
        if not self.project:
            return None
        data = self._session_from_state().to_dict()
        for key in VOLATILE_SESSION_FIELDS:
            data.pop(key, None)
        return data

    def is_dirty(self) -> bool:
        """True when the live state differs from the last saved or loaded session."""
        return self._state_snapshot() != self._clean_snapshot

    def _mark_clean(self):
        self._clean_snapshot = self._state_snapshot()
        self._update_window_title()

    def _update_window_title(self):
        name = self.current_session_path.name if self.current_session_path else "Untitled"
        marker = "*" if self.is_dirty() else ""
        self.setWindowTitle(f"ChopScout — {name}{marker}")

    def _apply_session(self, session: Session):
        """Overlay a loaded session onto the freshly analyzed project.

        `loaded()` rebuilds widgets from the analysis, which cannot reproduce
        saved manual markers or the export controls it never touches, so the
        session's own values are applied on top of it here.
        """
        analysis = self.project.analysis
        duration = analysis.audio.duration
        # The session core allows far wider values than the controls do (BPM to
        # 1e5, downbeat to +/-1e6). Clamping first keeps the model and the widgets
        # in agreement and keeps beat_grid from walking billions of steps.
        bpm = min(max(session.selected_bpm, self.bpm.minimum()), self.bpm.maximum())
        downbeat = min(max(session.downbeat, 0.0), duration)
        bar_count = int(min(max(session.bar_count, self.bars.minimum()), self.bars.maximum()))
        markers = normalize_markers(session.markers, duration)
        analysis.selected_bpm = bpm
        analysis.downbeat = downbeat
        analysis.beat_times = beat_grid(duration, bpm, downbeat)
        self.project.mode = session.chop_mode
        self.project.markers = markers
        self.pad_map = dict(session.pad_map)
        for widget, value in [
            (self.bpm, bpm),
            (self.bars, bar_count),
            (self.downbeat, downbeat),
        ]:
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.mode.blockSignals(True)
        self.mode.setCurrentText(session.chop_mode)
        self.mode.blockSignals(False)
        settings = session.export_settings
        if isinstance(settings.get("export_format"), str):
            self.export_format.blockSignals(True)
            self.export_format.setCurrentText(settings["export_format"])
            self.export_format.blockSignals(False)
        if isinstance(settings.get("overwrite"), bool):
            self.overwrite.setChecked(settings["overwrite"])
        if isinstance(settings.get("starting_note"), int):
            self.start_note.blockSignals(True)
            self.start_note.setValue(settings["starting_note"])
            self.start_note.blockSignals(False)
        self._sync_pad_count_to_mode(self.project.mode)
        self._sync_export_format_controls()
        self.wave.set_active_slices(self.project.markers)
        self.wave.downbeat = downbeat
        self.wave.beats = analysis.beat_times
        self.wave.update()
        update_loop_duration_warning(analysis, bpm, bar_count)
        self.selection_changed(min(self.wave.selected, max(0, len(self.project.markers) - 1)))
        self._update_info()

    def session_new(self):
        if not self._confirm_discard("New session"):
            return
        self.stop_playback()
        self.project = None
        self.current_session_path = None
        self.pad_map = {}
        self.wave.clear()
        self._set_enabled(False)
        self.info.setText("Drop a break here.")
        self.slice_label.setText("No slice selected")
        self.confidence.setText("—")
        self._mark_clean()
        self.statusBar().showMessage("New session")

    def session_open(self):
        if not self._confirm_discard("Open session"):
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open session",
            self.config.last_session_dir or str(Path.home()),
            SESSION_FILTER,
        )
        if path:
            self._open_session_path(path, confirmed=True)

    def _open_session_path(self, path, confirmed: bool = False):
        if not confirmed and not self._confirm_discard("Open session"):
            return
        try:
            session, status = load_session(path)
        except SessionError as exc:
            self.failed(str(exc))
            return
        original_source = session.source_path
        if not self._resolve_source(session, status):
            return
        self._restore_session(session, Path(path), relinked=session.source_path != original_source)

    def _restore_session(self, session: Session, path: Path, relinked: bool = False):
        self.stop_playback()
        self.statusBar().showMessage("Restoring session…")
        self._set_enabled(False)
        worker = LoadWorker(session.source_path, session.chop_mode, self.sensitivity.value())
        worker.signals.done.connect(
            lambda project: self._session_loaded(project, session, path, relinked)
        )
        worker.signals.failed.connect(self.failed)
        self.pool.start(worker)

    def _session_loaded(self, project, session: Session, path: Path, relinked: bool):
        self.loaded(project)
        self._apply_session(session)
        # Only adopt the file once the audio actually loaded, so a failed restore
        # cannot leave Save pointed at it or advertise it as a recent session.
        self.current_session_path = path
        self._remember_session(path)
        if relinked:
            # The new source path is an unsaved edit until the user saves it.
            self.statusBar().showMessage("Session restored — relinked source is unsaved")
        else:
            self._mark_clean()
            self.statusBar().showMessage("Session restored")
        self._update_window_title()

    def _ask(self, icon, title, text, buttons, default):
        """Modal question whose body may contain untrusted, session-supplied text."""
        box = QMessageBox(icon, title, text, buttons, self)
        box.setTextFormat(Qt.PlainText)
        box.setDefaultButton(default)
        return box.exec()

    def _resolve_source(self, session: Session, status) -> bool:
        """Handle a session whose source audio is missing, changed, or unchecked.

        Returns True when the session should still be opened.
        """
        if status == SourceStatus.OK:
            return True
        shown = display_path(session.source_path)
        if status == SourceStatus.UNVERIFIED:
            # The session core refuses to probe network paths, so opening one is
            # a decision the user has to make: it contacts an arbitrary host.
            choice = self._ask(
                QMessageBox.Warning,
                "Network source",
                f"This session points at a network location:\n\n{shown}\n\n"
                "Opening it will contact that host. Continue?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            return choice == QMessageBox.Yes
        if status == SourceStatus.MISSING:
            choice = self._ask(
                QMessageBox.Warning,
                "Source audio missing",
                f"The audio this session refers to was not found:\n\n{shown}\n\n"
                "Locate the file to relink the session?",
                QMessageBox.Open | QMessageBox.Cancel,
                QMessageBox.Open,
            )
            if choice != QMessageBox.Open:
                return False
            return self._relink(session)
        choice = self._ask(
            QMessageBox.Warning,
            "Source audio changed",
            f"The audio this session refers to has changed since it was saved:\n\n"
            f"{shown}\n\nMarkers may no longer line up.",
            QMessageBox.Open | QMessageBox.Ignore | QMessageBox.Cancel,
            QMessageBox.Ignore,
        )
        if choice == QMessageBox.Cancel:
            return False
        if choice == QMessageBox.Open:
            return self._relink(session)
        return True

    def _relink(self, session: Session) -> bool:
        """Re-point a session at moved audio. The change stays in memory until saved."""
        start = Path(session.source_path).parent
        # Never seed the dialog with a network directory; browsing it reaches out.
        directory = str(Path.home()) if is_remote_path(session.source_path) else str(start)
        new_path, _ = QFileDialog.getOpenFileName(
            self,
            "Locate source audio",
            directory,
            "Audio (*.wav *.aif *.aiff *.flac *.mp3 *.ogg *.m4a);;All files (*)",
        )
        if not new_path:
            return False
        try:
            relink_source(session, new_path)
        except SessionError:
            # The replacement is different audio, so rebinding must be deliberate.
            confirm = self._ask(
                QMessageBox.Warning,
                "Different audio",
                f"{display_path(Path(new_path).name)} is not the audio this session was "
                "built from.\n\nRelink anyway? The session's markers were made for the "
                "original file.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return False
            try:
                relink_source(session, new_path, allow_changed=True)
            except SessionError as exc:
                self.failed(str(exc))
                return False
        return True

    def session_save(self) -> bool:
        if not self.project:
            return False
        if self.current_session_path is None:
            return self.session_save_as()
        return self._write_session(self.current_session_path)

    def session_save_as(self) -> bool:
        if not self.project:
            return False
        suggested = Path(self.config.last_session_dir or str(Path.home())) / (
            Path(self.project.path).stem + SESSION_SUFFIX
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save session", str(suggested), SESSION_FILTER
        )
        if not path:
            return False
        target = Path(path)
        if not target.name.endswith(SESSION_SUFFIX):
            target = target.with_name(target.stem + SESSION_SUFFIX)
        return self._write_session(target)

    def _write_session(self, path: Path) -> bool:
        try:
            save_session(path, self._session_from_state())
        except SessionError as exc:
            self.failed(str(exc))
            return False
        self.current_session_path = path
        self._remember_session(path)
        self._mark_clean()
        self.statusBar().showMessage(f"Session saved: {path}")
        return True

    def _remember_session(self, path: Path):
        self.config.add_recent_file(path)
        self.config.last_session_dir = str(path.parent)
        try:
            self.config.save()
        except OSError:
            # Recent-files bookkeeping must never fail an otherwise good save.
            log.exception("could not persist config")
        self._refresh_recent_menu()

    def _confirm_discard(self, title: str) -> bool:
        """Ask before losing unsaved work. Returns True when it is safe to continue."""
        if not self.is_dirty():
            return True
        choice = QMessageBox.warning(
            self,
            title,
            "This session has unsaved changes.",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if choice == QMessageBox.Save:
            return self.session_save()
        return choice == QMessageBox.Discard

    def closeEvent(self, event):
        if self._confirm_discard("Quit ChopScout"):
            event.accept()
        else:
            event.ignore()

    def exported(self, path):
        self._set_enabled(True)
        self.config.last_export_dir = str(Path(path).parent)
        self.config.save()
        self.statusBar().showMessage(f"Export complete: {path}")
        QMessageBox.information(
            self,
            "Export complete",
            f"Validated package created:\n\n{path}\n\nWith 16, 32, 48, or 64 slices, it also contains a generated MPC 3.9.0 XPJ project, sequence, and standalone XPM drum program with the required ProgramData folder.",
        )
