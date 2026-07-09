from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
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
from .core import LoadedProject, change_mode, export_project, load_project
from .exporter import render_reconstruction
from .models import ExportSettings
from .slicing import normalize_markers, snap_marker

log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class LoadWorker(QRunnable):
    def __init__(self, path: str):
        super().__init__(); self.path = path; self.signals = WorkerSignals()
    @Slot()
    def run(self):
        try: self.signals.done.emit(load_project(self.path))
        except Exception as exc: log.exception("load failed"); self.signals.failed.emit(str(exc))


class ExportWorker(QRunnable):
    def __init__(self, project: LoadedProject, output: str, settings: ExportSettings):
        super().__init__(); self.project = project; self.output = output; self.settings = settings; self.signals = WorkerSignals()
    @Slot()
    def run(self):
        try: self.signals.done.emit(export_project(self.project, self.output, self.settings))
        except Exception as exc: log.exception("export failed"); self.signals.failed.emit(str(exc))


class WaveformWidget(QWidget):
    marker_moved = Signal(int, float)
    marker_added = Signal(float)
    marker_removed = Signal(int)
    selection_changed = Signal(int)

    def __init__(self):
        super().__init__(); self.setMinimumHeight(320); self.setFocusPolicy(Qt.StrongFocus)
        self.peaks = np.array([], dtype=np.float32); self.duration = 1.0; self.markers=[]; self.beats=[]
        self.downbeat=0.0; self.playhead=0.0; self.selected=0; self.dragging=None; self.zoom=1.0; self.offset=0.0

    def set_project(self, project: LoadedProject):
        self.peaks = waveform_peaks(project.data); self.duration=project.analysis.audio.duration
        self.markers=list(project.markers); self.beats=list(project.analysis.beat_times); self.downbeat=project.analysis.downbeat
        self.zoom=1.0; self.offset=0.0; self.selected=0; self.update()

    def visible_span(self): return self.duration / self.zoom
    def x_for_time(self, value): return (value-self.offset)/self.visible_span()*self.width()
    def time_for_x(self, x): return max(0.0, min(self.duration, self.offset+x/max(1,self.width())*self.visible_span()))

    def paintEvent(self, _event):
        p=QPainter(self); p.fillRect(self.rect(), QColor("#17191d")); p.setRenderHint(QPainter.Antialiasing)
        if self.peaks.size == 0:
            p.setPen(QColor("#9ca3af")); p.drawText(self.rect(), Qt.AlignCenter, "Drop a break here") ; return
        mid=self.height()/2; p.setPen(QPen(QColor("#5b6472"),1))
        count=len(self.peaks); start=max(0,int(self.offset/self.duration*count)); end=min(count,int((self.offset+self.visible_span())/self.duration*count)+1)
        path=QPainterPath(); first=True
        for i in range(start,end):
            x=self.x_for_time(i/count*self.duration); pair=self.peaks[i]
            lo,hi=(float(pair[0]),float(pair[1])) if np.ndim(pair) else (-abs(float(pair)),abs(float(pair)))
            if first: path.moveTo(x,mid-hi*(mid-12)); first=False
            else: path.lineTo(x,mid-hi*(mid-12))
        for i in range(end-1,start-1,-1):
            x=self.x_for_time(i/count*self.duration); pair=self.peaks[i]
            lo=float(pair[0]) if np.ndim(pair) else -abs(float(pair)); path.lineTo(x,mid-lo*(mid-12))
        path.closeSubpath(); p.fillPath(path,QColor("#4f8fcf"))
        for idx,beat in enumerate(self.beats):
            x=self.x_for_time(beat)
            if 0<=x<=self.width(): p.setPen(QPen(QColor("#4b5563") if idx%4 else QColor("#7c8492"),1)); p.drawLine(x,0,x,self.height())
        for idx,m in enumerate(self.markers):
            x=self.x_for_time(m)
            if 0<=x<=self.width():
                if idx==self.selected:
                    next_m=self.markers[idx+1] if idx+1<len(self.markers) else self.duration
                    p.fillRect(QRectF(x,0,self.x_for_time(next_m)-x,self.height()),QColor(70,120,190,35))
                p.setPen(QPen(QColor("#f2b84b") if idx!=self.selected else QColor("#ffffff"),2)); p.drawLine(x,0,x,self.height()); p.drawText(QPointF(x+4,18), f"{idx+1}")
        x=self.x_for_time(self.downbeat); p.setPen(QPen(QColor("#ef6b73"),3)); p.drawLine(x,0,x,28)
        x=self.x_for_time(self.playhead); p.setPen(QPen(QColor("#e5e7eb"),1)); p.drawLine(x,0,x,self.height())

    def wheelEvent(self,event):
        old=self.time_for_x(event.position().x()); self.zoom=max(1.0,min(32.0,self.zoom*(1.2 if event.angleDelta().y()>0 else 1/1.2)))
        self.offset=max(0.0,min(self.duration-self.visible_span(),old-event.position().x()/self.width()*self.visible_span())); self.update()
    def mousePressEvent(self,event):
        t=self.time_for_x(event.position().x()); nearest=min(range(len(self.markers)),key=lambda i:abs(self.markers[i]-t),default=0)
        if self.markers and abs(self.x_for_time(self.markers[nearest])-event.position().x())<9:
            if event.button()==Qt.RightButton and nearest>0: self.marker_removed.emit(nearest); return
            self.selected=nearest; self.dragging=nearest; self.selection_changed.emit(nearest); self.update()
        elif event.button()==Qt.LeftButton: self.marker_added.emit(t)
    def mouseMoveEvent(self,event):
        if self.dragging is not None: self.marker_moved.emit(self.dragging,self.time_for_x(event.position().x()))
    def mouseReleaseEvent(self,_event): self.dragging=None


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("ChopScout"); self.resize(1280,760); self.setAcceptDrops(True)
        self.pool=QThreadPool.globalInstance(); self.project=None; self.config=AppConfig.load(); self.temp_paths=[]
        self.player=QMediaPlayer(self); self.audio_output=QAudioOutput(self); self.player.setAudioOutput(self.audio_output); self.audio_output.setVolume(0.8)
        self._build(); self._set_enabled(False)

    def _build(self):
        toolbar=QToolBar(); self.addToolBar(toolbar)
        open_action=QAction("Open",self); open_action.setShortcut(QKeySequence.Open); open_action.triggered.connect(self.choose_file); toolbar.addAction(open_action)
        self.export_action=QAction("Export MPC Package",self); self.export_action.setShortcut("Ctrl+E"); self.export_action.triggered.connect(self.export); toolbar.addAction(self.export_action)
        toolbar.addSeparator(); toolbar.addWidget(QLabel(" BPM "))
        self.bpm=QDoubleSpinBox(); self.bpm.setRange(20,400); self.bpm.setDecimals(2); self.bpm.valueChanged.connect(self.bpm_changed); toolbar.addWidget(self.bpm)
        self.half=QPushButton("½×"); self.half.clicked.connect(lambda:self.bpm.setValue(self.bpm.value()/2)); toolbar.addWidget(self.half)
        self.double=QPushButton("2×"); self.double.clicked.connect(lambda:self.bpm.setValue(self.bpm.value()*2)); toolbar.addWidget(self.double)
        toolbar.addWidget(QLabel(" Bars ")); self.bars=QSpinBox(); self.bars.setRange(1,128); toolbar.addWidget(self.bars)
        splitter=QSplitter()
        left=QFrame(); form=QFormLayout(left)
        self.mode=QComboBox(); self.mode.addItems(["transient","equal8","equal16","equal32","equal48","equal64","beat","eighth","sixteenth","hybrid","manual"]); self.mode.currentTextChanged.connect(self.mode_changed); form.addRow("Chop mode",self.mode)
        self.pad_count=QComboBox(); self.pad_count.addItems(["16 pads (Bank A)","32 pads (Banks A-B)","48 pads (Banks A-C)","64 pads (Banks A-D)"]); self.pad_count.currentIndexChanged.connect(self.pad_count_changed); form.addRow("MPC layout",self.pad_count)
        self.sensitivity=QDoubleSpinBox(); self.sensitivity.setRange(.35,.9); self.sensitivity.setSingleStep(.05); self.sensitivity.setValue(.55); form.addRow("Detection sensitivity",self.sensitivity)
        self.snap=QComboBox(); self.snap.addItems(["Transients","Beat grid","No snapping"]); form.addRow("Marker snap",self.snap)
        self.start_note=QSpinBox(); self.start_note.setRange(0,127); self.start_note.setValue(36); form.addRow("First MIDI note",self.start_note)
        self.info=QLabel("Drop a break here.\n\nExports support complete XPJ projects and standalone XPM programs across Banks A-D for MPC 3.9.0."); self.info.setWordWrap(True); form.addRow(self.info)
        center=QWidget(); cv=QVBoxLayout(center); self.wave=WaveformWidget(); cv.addWidget(self.wave,1)
        self.wave.marker_moved.connect(self.marker_moved); self.wave.marker_added.connect(self.marker_added); self.wave.marker_removed.connect(self.marker_removed); self.wave.selection_changed.connect(self.selection_changed)
        transport=QHBoxLayout()
        for text,fn in [("Play original",self.play_original),("Play slice",self.play_slice),("Reconstruct",self.play_reconstruction),("Stop",self.player.stop)]:
            button=QPushButton(text); button.clicked.connect(fn); transport.addWidget(button)
        cv.addLayout(transport)
        right=QFrame(); rf=QFormLayout(right); self.slice_label=QLabel("No slice selected"); rf.addRow(self.slice_label)
        self.downbeat=QDoubleSpinBox(); self.downbeat.setRange(0,99999); self.downbeat.setDecimals(4); self.downbeat.valueChanged.connect(self.downbeat_changed); rf.addRow("First downbeat (s)",self.downbeat)
        self.confidence=QLabel("—"); rf.addRow("Confidence",self.confidence)
        splitter.addWidget(left); splitter.addWidget(center); splitter.addWidget(right); splitter.setSizes([220,850,240]); self.setCentralWidget(splitter)
        self.setStatusBar(QStatusBar()); self.statusBar().showMessage("Ready")

    def _set_enabled(self,value):
        for w in [self.export_action,self.bpm,self.half,self.double,self.bars,self.mode,self.pad_count,self.sensitivity,self.snap,self.start_note,self.downbeat]: w.setEnabled(value)
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self,e):
        urls=e.mimeData().urls()
        if urls: self.load(urls[0].toLocalFile())
    def choose_file(self):
        path,_=QFileDialog.getOpenFileName(self,"Open break","","Audio (*.wav *.aif *.aiff *.flac *.mp3 *.ogg *.m4a);;All files (*)")
        if path:self.load(path)
    def load(self,path):
        self.statusBar().showMessage("Analyzing audio…"); self._set_enabled(False); worker=LoadWorker(path); worker.signals.done.connect(self.loaded); worker.signals.failed.connect(self.failed); self.pool.start(worker)
    def loaded(self,project):
        self.project=project; self.wave.set_project(project); self.bpm.blockSignals(True); self.bpm.setValue(project.analysis.selected_bpm); self.bpm.blockSignals(False)
        self.bars.setValue(project.analysis.estimated_bars); self.downbeat.blockSignals(True); self.downbeat.setMaximum(project.analysis.audio.duration); self.downbeat.setValue(project.analysis.downbeat); self.downbeat.blockSignals(False)
        c=project.analysis.tempo_confidence; label="high" if c>=.4 else "medium" if c>=.15 else "low"; self.confidence.setText(f"Tempo: {label} ({c:.2f})")
        warn="\n".join(f"• {x}" for x in project.analysis.warnings) or "No major warnings."
        self.info.setText(f"{Path(project.path).name}\n{project.analysis.audio.duration:.2f}s · {project.sample_rate} Hz · {project.analysis.audio.channels} ch\n{len(project.markers)} slices\n\n{warn}")
        self._set_enabled(True); self.statusBar().showMessage("Analysis complete")
    def failed(self,message): QMessageBox.critical(self,"ChopScout",message); self.statusBar().showMessage("Operation failed"); self._set_enabled(self.project is not None)
    def bpm_changed(self,value):
        if not self.project:return
        self.project.analysis.selected_bpm=value; self.project.analysis.beat_times=beat_grid(self.project.analysis.audio.duration,value,self.project.analysis.downbeat); self.wave.beats=self.project.analysis.beat_times; self.wave.update()
    def downbeat_changed(self,value):
        if not self.project:return
        self.project.analysis.downbeat=value; self.project.analysis.beat_times=beat_grid(self.project.analysis.audio.duration,self.bpm.value(),value); self.wave.downbeat=value; self.wave.beats=self.project.analysis.beat_times; self.wave.update()
    def mode_changed(self,mode):
        if not self.project:return
        change_mode(self.project,mode); self.wave.markers=list(self.project.markers); self.wave.update(); self.info.setText(self.info.text().split("\n\n")[0]+f"\n{len(self.project.markers)} slices")
    def pad_count_changed(self,index):
        if not self.project:return
        count=(16,32,48,64)[index]
        self.mode.setCurrentText(f"equal{count}")

    def marker_moved(self,index,value):
        if not self.project:return
        candidates=[] if self.snap.currentText()=="No snapping" else (self.project.analysis.onset_times if self.snap.currentText()=="Transients" else self.project.analysis.beat_times)
        value=snap_marker(value,candidates); marks=list(self.project.markers); marks[index]=value; marks=normalize_markers(marks,self.project.analysis.audio.duration); self.project.markers=marks; self.wave.markers=marks; self.wave.update()
    def marker_added(self,value):
        if not self.project:return
        self.project.markers=normalize_markers(self.project.markers+[value],self.project.analysis.audio.duration); self.wave.markers=self.project.markers; self.wave.update()
    def marker_removed(self,index):
        if not self.project or index<=0:return
        del self.project.markers[index]; self.wave.markers=self.project.markers; self.wave.update()
    def selection_changed(self,index):
        if not self.project:return
        end=self.project.markers[index+1] if index+1<len(self.project.markers) else self.project.analysis.audio.duration
        bank=chr(ord("A")+index//16); pad=index%16+1
        self.slice_label.setText(f"Bank {bank}, Pad {pad:02d} · note {36+index}\n{self.project.markers[index]:.4f}s – {end:.4f}s")
    def _play_array(self,data):
        path=Path(tempfile.gettempdir())/"chopscout-preview.wav"; write_wav(path,data,self.project.sample_rate); self.temp_paths.append(path); self.player.setSource(QUrl.fromLocalFile(str(path))); self.player.play()
    def play_original(self):
        if self.project is not None:self._play_array(self.project.data)
    def play_slice(self):
        if not self.project:return
        i=self.wave.selected; start=self.project.markers[i]; end=self.project.markers[i+1] if i+1<len(self.project.markers) else self.project.analysis.audio.duration; self._play_array(self.project.data[round(start*self.project.sample_rate):round(end*self.project.sample_rate)])
    def play_reconstruction(self):
        if self.project is not None:self._play_array(render_reconstruction(self.project.data,self.project.sample_rate,self.project.markers,self.project.analysis.audio.duration))
    def export(self):
        if not self.project:return
        directory=QFileDialog.getExistingDirectory(self,"Choose export folder",self.config.last_export_dir or str(Path.home()))
        if not directory:return
        settings=ExportSettings(mode=self.mode.currentText(),starting_note=36,bars=self.bars.value(),bpm=self.bpm.value(),pad_count=(16,32,48,64)[self.pad_count.currentIndex()])
        self.statusBar().showMessage("Exporting and validating…"); self._set_enabled(False); worker=ExportWorker(self.project,directory,settings); worker.signals.done.connect(self.exported); worker.signals.failed.connect(self.failed); self.pool.start(worker)
    def exported(self,path):
        self._set_enabled(True); self.config.last_export_dir=str(Path(path).parent); self.config.save(); self.statusBar().showMessage(f"Export complete: {path}")
        QMessageBox.information(self,"Export complete",f"Validated package created:\n\n{path}\n\nWith 16, 32, 48, or 64 slices, it also contains a generated MPC 3.9.0 XPJ project, sequence, and standalone XPM drum program with the required ProgramData folder.")
