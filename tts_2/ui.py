import os
import sys
import tempfile
import threading
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QProgressBar, QSystemTrayIcon, QMenu,
    QMessageBox, QCheckBox, QListWidget, QListWidgetItem, QFileDialog,
    QInputDialog, QFrame, QScrollArea
)
from PySide6.QtCore import Qt, Signal, QObject, QPointF
from PySide6.QtGui import QIcon, QAction, QColor, QPixmap, QPainter, QPen
from audio_manager import AudioRouter
from config import load_config
from pipeline import VoicePipelineController
from llm_engine import PERSONA_PROMPTS
# Absolute path to your application icon
ICON_PATH = r"E:**\t**ts**\t**ts_2\soundboard.ico"
# ==============================================================================
# DESIGN TOKENS
# ==============================================================================
BG = "#17181B"          # window
SURFACE = "#1F2125"     # inputs, list, raised areas
SURFACE_HI = "#282B30"  # hover
LINE = "#30333A"        # hairlines
TEXT = "#ECEDEF"
MUTED = "#979CA5"
DIM = "#6E747E"
ACCENT = "#9BBBEA"      # focus, selection, meter
DANGER = "#E5645F"
STATE_COLORS = {
    "READY": "#5FCB8F",
    "LISTENING": "#F0B45A",
    "PROCESSING": "#8CB8F0",
    "SPEAKING": "#E58AB8",
}
UI_FONT = "'Segoe UI Variable Text', 'Segoe UI', system-ui, sans-serif"
def _build_assets() -> dict:
    """Paint the small glyphs (dropdown chevron, checkmark) the stylesheet needs."""
    folder = os.path.join(tempfile.gettempdir(), "game_voice_tts_ui")
    os.makedirs(folder, exist_ok=True)
    def paint(name, size, color, points, width):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(color), width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        for a, b in zip(points, points[1:]):
            p.drawLine(QPointF(*a), QPointF(*b))
        p.end()
        path = os.path.join(folder, name).replace("\\\\", "/")
        pm.save(path)
        return path
    return {
        "chevron": paint("chevron.png", 16, MUTED, [(4, 6.5), (8, 10.5), (12, 6.5)], 1.6),
        "check": paint("check.png", 14, BG, [(3, 7.5), (5.8, 10.2), (11, 4.2)], 2.0),
    }
def build_stylesheet(assets: dict) -> str:
    qss = """
QMainWindow, QScrollArea, QWidget#root { background-color: @BG@; }
QScrollArea { border: none; }
QWidget {
    font-family: @FONT@;
    font-size: 13px;
    color: @TEXT@;
}
QLabel { background: transparent; }
QScrollBar:vertical { border: none; background: transparent; width: 8px; margin: 3px; }
QScrollBar::handle:vertical { background: @LINE@; min-height: 28px; border-radius: 4px; }
QScrollBar::handle:vertical:hover { background: @DIM@; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
/* ---- Typography roles ---- */
QLabel#appEyebrow { font-size: 10px; font-weight: 700; letter-spacing: 1.3px; color: @DIM@; }
QLabel#appTitle { font-size: 20px; font-weight: 650; letter-spacing: -0.3px; }
QLabel#appSubtitle { font-size: 12px; color: @MUTED@; }
QLabel[role="section"] { font-size: 13px; font-weight: 650; color: @TEXT@; }
QLabel[role="hint"] { font-size: 12px; color: @MUTED@; }
QLabel[role="field"] { font-size: 11px; font-weight: 600; color: @DIM@; }
QLabel[role="statValue"] { font-size: 19px; font-weight: 650; }
QLabel[role="statName"] { font-size: 11px; color: @MUTED@; }
QLabel#emptyState { color: @MUTED@; font-size: 12px; padding: 24px 0px; }
/* ---- Structure ---- */
QFrame[role="rule"] { background-color: @LINE@; border: none; max-height: 1px; min-height: 1px; }
QFrame#statusPill { background-color: transparent; border: 1px solid @LINE@; border-radius: 13px; }
QFrame#soundboardPanel, QFrame#monitorPanel {
    background-color: @SURFACE@;
    border: 1px solid @LINE@;
    border-radius: 10px;
}
QFrame#meterWell {
    background-color: @BG@;
    border: 1px solid @LINE@;
    border-radius: 6px;
}
QFrame#personaRow {
    background-color: @SURFACE@;
    border: 1px solid @LINE@;
    border-radius: 8px;
}
/* ---- Inputs ---- */
QComboBox {
    background-color: @SURFACE@;
    border: 1px solid @LINE@;
    border-radius: 7px;
    padding: 8px 10px;
    min-height: 18px;
}
QComboBox:hover { background-color: @SURFACE_HI@; border-color: @DIM@; }
QComboBox:focus, QComboBox:on { border-color: @ACCENT@; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox::down-arrow { image: url(@CHEVRON@); width: 16px; height: 16px; }
QComboBox QAbstractItemView {
    background-color: @SURFACE@;
    border: 1px solid @LINE@;
    padding: 4px;
    outline: none;
    selection-background-color: @SURFACE_HI@;
    selection-color: @ACCENT@;
}
QCheckBox { spacing: 9px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 5px;
    border: 1px solid @DIM@;
    background-color: transparent;
}
QCheckBox::indicator:hover { border-color: @TEXT@; }
QCheckBox::indicator:checked {
    background-color: @ACCENT@;
    border-color: @ACCENT@;
    image: url(@CHECK@);
}
/* ---- Soundboard list ---- */
QListWidget {
    background-color: @BG@;
    border: none;
    border-radius: 7px;
    padding: 4px;
    outline: none;
}
QListWidget::item { padding: 9px 11px; border-radius: 6px; border-left: 2px solid transparent; }
QListWidget::item:hover { background-color: @SURFACE_HI@; }
QListWidget::item:selected { background-color: @SURFACE_HI@; color: @TEXT@; border-left: 2px solid @ACCENT@; }
/* ---- Buttons ---- */
QPushButton {
    background-color: transparent;
    border: 1px solid @LINE@;
    border-radius: 7px;
    padding: 8px 14px;
    font-weight: 550;
}
QPushButton:hover { background-color: @SURFACE_HI@; border-color: @DIM@; }
QPushButton:pressed { background-color: @SURFACE@; }
QPushButton:focus { border-color: @ACCENT@; }
QPushButton#primaryBtn {
    background-color: @TEXT@;
    color: @BG@;
    border: 1px solid @TEXT@;
    font-weight: 650;
}
QPushButton#primaryBtn:hover { background-color: #FFFFFF; border-color: #FFFFFF; }
QPushButton#primaryBtn:pressed { background-color: #C9CBD0; }
QPushButton#silenceBtn { padding: 10px 14px; font-weight: 650; }
QPushButton#quitBtn { border: none; color: @MUTED@; padding: 10px 12px; }
QPushButton#quitBtn:hover { color: @DANGER@; background-color: transparent; }
/* ---- Level meter ---- */
QProgressBar { background-color: @SURFACE@; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }
QProgressBar::chunk { background-color: @ACCENT@; border-radius: 3px; }
QProgressBar[hot="true"]::chunk { background-color: @DANGER@; }
"""
    tokens = {
        "@BG@": BG, "@SURFACE_HI@": SURFACE_HI, "@SURFACE@": SURFACE, "@LINE@": LINE,
        "@TEXT@": TEXT, "@MUTED@": MUTED, "@DIM@": DIM, "@ACCENT@": ACCENT,
        "@DANGER@": DANGER, "@FONT@": UI_FONT,
        "@CHEVRON@": assets["chevron"], "@CHECK@": assets["check"],
    }
    for key, value in tokens.items():
        qss = qss.replace(key, value)
    return qss
class SignalBridge(QObject):
    status_changed = Signal(str)
    metrics_changed = Signal(float, float, float)
    level_changed = Signal(int)
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.bridge = SignalBridge()
        self._meter_hot = False
        self.setWindowTitle("Game Voice TTS — Virtual Microphone")
        self.resize(480, 740)
        self.setMinimumSize(440, 620)
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))
        self.setStyleSheet(build_stylesheet(_build_assets()))
        self._build_ui()
        self._setup_tray()
        # Connect Signals
        self.bridge.status_changed.connect(self.update_status_display)
        self.bridge.metrics_changed.connect(self.update_metrics_display)
        self.bridge.level_changed.connect(self._on_level)
        # Initialize Pipeline Thread
        self.pipeline = VoicePipelineController(
            self.config,
            status_callback=lambda s: self.bridge.status_changed.emit(s),
            metric_callback=lambda stt, tts, tot: self.bridge.metrics_changed.emit(stt, tts, tot),
            level_callback=lambda lvl: self.bridge.level_changed.emit(lvl)
        )
        # Connect LLM Persona controls to pipeline engine
        self.llm_enable_cb.toggled.connect(self.pipeline.llm.set_enabled)
        self.persona_combo.currentTextChanged.connect(self.pipeline.llm.set_persona)
        self._refresh_soundboard_list()
        self.check_virtual_mic_status()
    # ------------------------------------------------------------------
    # UI construction helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _label(text, role):
        lbl = QLabel(text)
        lbl.setProperty("role", role)
        return lbl
    @staticmethod
    def _rule():
        line = QFrame()
        line.setProperty("role", "rule")
        line.setFrameShape(QFrame.NoFrame)
        return line
    def _section(self, title, hint=None):
        """A titled block of content. Sections are separated by hairlines, not boxes."""
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(self._label(title, "section"))
        if hint:
            head.addWidget(self._label(hint, "hint"))
        layout.addLayout(head)
        return box, layout
    def _stat(self, name):
        col = QVBoxLayout()
        col.setSpacing(0)
        value = self._label("0 ms", "statValue")
        col.addWidget(value)
        col.addWidget(self._label(name, "statName"))
        return col, value
    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        central = QWidget()
        central.setObjectName("root")
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(26, 24, 26, 22)
        main_layout.setSpacing(16)
        # ---- Header: identity on the left, live state on the right ----
        header = QHBoxLayout()
        header.setSpacing(14)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        eyebrow = QLabel("GAME AUDIO TOOL")
        eyebrow.setObjectName("appEyebrow")
        titles.addWidget(eyebrow)
        title_lbl = QLabel("Game Voice TTS")
        title_lbl.setObjectName("appTitle")
        titles.addWidget(title_lbl)
        sub_lbl = QLabel("Virtual microphone")
        sub_lbl.setObjectName("appSubtitle")
        titles.addWidget(sub_lbl)
        header.addLayout(titles)
        header.addStretch()
        self.status_pill = QFrame()
        self.status_pill.setObjectName("statusPill")
        pill_layout = QHBoxLayout(self.status_pill)
        pill_layout.setContentsMargins(12, 6, 12, 6)
        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.RichText)
        pill_layout.addWidget(self.status_label)
        header.addWidget(self.status_pill, alignment=Qt.AlignVCenter)
        main_layout.addLayout(header)
        self._set_status("READY", STATE_COLORS["READY"])
        # ---- Audio routing ----
        audio_box, audio_layout = self._section("Audio routing")
        inputs, outputs = AudioRouter.get_devices()
        audio_layout.addWidget(self._label("Microphone", "field"))
        self.input_combo = QComboBox()
        for idx, name in inputs:
            self.input_combo.addItem(name, idx)
        audio_layout.addWidget(self.input_combo)
        audio_layout.addWidget(self._label("Output to virtual cable", "field"))
        self.output_combo = QComboBox()
        v_idx, _, _ = AudioRouter.find_virtual_cable()
        for idx, name in outputs:
            self.output_combo.addItem(name, idx)
            if idx == v_idx:
                self.output_combo.setCurrentIndex(self.output_combo.count() - 1)
        audio_layout.addWidget(self.output_combo)
        main_layout.addWidget(audio_box)
        main_layout.addWidget(self._rule())
        # ---- AI persona ----
        persona_box, persona_layout = self._section("AI persona", "Optional rewrite before text-to-speech.")
        persona_row = QFrame()
        persona_row.setObjectName("personaRow")
        persona_row_layout = QHBoxLayout(persona_row)
        persona_row_layout.setContentsMargins(12, 8, 8, 8)
        persona_row_layout.setSpacing(12)
        self.llm_enable_cb = QCheckBox("Rewrite what I say in a persona")
        self.llm_enable_cb.setChecked(True)
        persona_row_layout.addWidget(self.llm_enable_cb, stretch=1)
        self.persona_combo = QComboBox()
        self.persona_combo.addItems(list(PERSONA_PROMPTS.keys()))
        self.persona_combo.setMinimumWidth(145)
        persona_row_layout.addWidget(self.persona_combo)
        persona_layout.addWidget(persona_row)
        main_layout.addWidget(persona_box)
        # ---- Soundboard ----
        sb_box, sb_layout = self._section(
            "Soundboard", 'Say "/name" out loud to play a clip.'
        )
        soundboard_panel = QFrame()
        soundboard_panel.setObjectName("soundboardPanel")
        soundboard_panel_layout = QVBoxLayout(soundboard_panel)
        soundboard_panel_layout.setContentsMargins(6, 6, 6, 6)
        soundboard_panel_layout.setSpacing(6)
        self.soundboard_list = QListWidget()
        self.soundboard_list.setMinimumHeight(126)
        soundboard_panel_layout.addWidget(self.soundboard_list, stretch=1)
        self.sb_empty = QLabel("No clips yet. Add a .wav file to get started.")
        self.sb_empty.setObjectName("emptyState")
        self.sb_empty.setAlignment(Qt.AlignCenter)
        soundboard_panel_layout.addWidget(self.sb_empty)
        sb_btn_layout = QHBoxLayout()
        sb_btn_layout.setSpacing(10)
        self.play_sound_btn = QPushButton("Play")
        self.play_sound_btn.setMinimumWidth(72)
        self.play_sound_btn.setObjectName("primaryBtn")
        self.play_sound_btn.clicked.connect(self.play_selected_soundboard_entry)
        self.pause_sound_btn = QPushButton("Pause")
        self.pause_sound_btn.setMinimumWidth(72)
        self.pause_sound_btn.clicked.connect(self.toggle_soundboard_pause)
        self.add_sound_btn = QPushButton("Add sound…")
        self.add_sound_btn.clicked.connect(self.add_soundboard_entry)
        self.remove_sound_btn = QPushButton("Remove")
        self.remove_sound_btn.clicked.connect(self.remove_soundboard_entry)
        sb_btn_layout.addWidget(self.play_sound_btn)
        sb_btn_layout.addWidget(self.pause_sound_btn)
        sb_btn_layout.addStretch()
        sb_btn_layout.addWidget(self.add_sound_btn)
        sb_btn_layout.addWidget(self.remove_sound_btn)
        sb_layout.addWidget(soundboard_panel, stretch=1)
        sb_layout.addLayout(sb_btn_layout)
        main_layout.addWidget(sb_box, stretch=1)
        # ---- Monitor ----
        mon_box, mon_layout = self._section("Monitor", "Live input level and processing latency.")
        monitor_panel = QFrame()
        monitor_panel.setObjectName("monitorPanel")
        monitor_panel_layout = QVBoxLayout(monitor_panel)
        monitor_panel_layout.setContentsMargins(12, 12, 12, 12)
        monitor_panel_layout.setSpacing(14)
        meter_well = QFrame()
        meter_well.setObjectName("meterWell")
        meter_well_layout = QVBoxLayout(meter_well)
        meter_well_layout.setContentsMargins(10, 12, 10, 12)
        self.audio_meter = QProgressBar()
        self.audio_meter.setTextVisible(False)
        self.audio_meter.setRange(0, 100)
        self.audio_meter.setProperty("hot", False)
        meter_well_layout.addWidget(self.audio_meter)
        monitor_panel_layout.addWidget(meter_well)
        stats = QHBoxLayout()
        stats.setSpacing(34)
        stt_col, self.stt_value = self._stat("Speech to text")
        tts_col, self.tts_value = self._stat("Text to speech")
        tot_col, self.total_value = self._stat("Total")
        stats.addLayout(stt_col)
        stats.addLayout(tts_col)
        stats.addLayout(tot_col)
        stats.addStretch()
        monitor_panel_layout.addLayout(stats)
        mon_layout.addWidget(monitor_panel)
        main_layout.addWidget(mon_box)
        # ---- Footer ----
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.cancel_btn = QPushButton("Cancel / Silence (ESC)")
        self.cancel_btn.setObjectName("silenceBtn")
        self.cancel_btn.clicked.connect(lambda: self.pipeline.cancel() if hasattr(self, 'pipeline') else None)
        btn_layout.addWidget(self.cancel_btn, stretch=1)
        self.exit_btn = QPushButton("Exit")
        self.exit_btn.setObjectName("quitBtn")
        self.exit_btn.clicked.connect(self.close_app)
        btn_layout.addWidget(self.exit_btn)
        main_layout.addLayout(btn_layout)
        scroll_area.setWidget(central)
        self.setCentralWidget(scroll_area)
    # ------------------------------------------------------------------
    # Status / metrics / meter
    # ------------------------------------------------------------------
    def _set_status(self, text: str, color: str):
        self.status_label.setText(
            f'<span style="color:{color};">●</span>&nbsp;&nbsp;'
            f'<span style="font-weight:600;">{text}</span>'
        )
    def update_status_display(self, state: str):
        self._set_status(state, STATE_COLORS.get(state, TEXT))
    def update_metrics_display(self, stt_ms: float, tts_ms: float, total_ms: float):
        self.stt_value.setText(f"{stt_ms:.0f} ms")
        self.tts_value.setText(f"{tts_ms:.0f} ms")
        self.total_value.setText(f"{total_ms:.0f} ms")
    def _on_level(self, level: int):
        self.audio_meter.setValue(level)
        hot = level >= 90
        if hot != self._meter_hot:
            self._meter_hot = hot
            self.audio_meter.setProperty("hot", hot)
            self.audio_meter.style().unpolish(self.audio_meter)
            self.audio_meter.style().polish(self.audio_meter)
    # ------------------------------------------------------------------
    # Soundboard logic
    # ------------------------------------------------------------------
    def _refresh_soundboard_list(self):
        self.soundboard_list.clear()
        sounds = self.pipeline.soundboard.list_sounds()
        for command, file_path in sounds.items():
            item = QListWidgetItem(f"{command}      {os.path.basename(file_path)}")
            item.setData(Qt.UserRole, command)
            self.soundboard_list.addItem(item)
        has_sounds = self.soundboard_list.count() > 0
        self.soundboard_list.setVisible(has_sounds)
        self.sb_empty.setVisible(not has_sounds)
    def _selected_command(self):
        item = self.soundboard_list.currentItem()
        if not item:
            return None
        return item.data(Qt.UserRole)
    def play_selected_soundboard_entry(self):
        command = self._selected_command()
        if not command:
            return
        file_path = self.pipeline.soundboard.sounds.get(command)
        if file_path and os.path.isfile(file_path):
            threading.Thread(
                target=self.pipeline.tts.play_file,
                args=(file_path,),
                daemon=True
            ).start()
    def toggle_soundboard_pause(self):
        if hasattr(self, 'pipeline') and hasattr(self.pipeline, 'tts'):
            is_paused = self.pipeline.tts.toggle_pause()
            if is_paused:
                self.pause_sound_btn.setText("Resume")
            else:
                self.pause_sound_btn.setText("Pause")
    def add_soundboard_entry(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Sound File", "", "WAV Audio (*.wav)"
        )
        if not file_path:
            return
        command, ok = QInputDialog.getText(
            self, "Soundboard Trigger",
            'Say this to trigger the clip (e.g. type \'1\' to trigger "/1"): '
        )
        if not ok or not command.strip():
            return
        try:
            self.pipeline.soundboard.add_sound(command, file_path)
            self._refresh_soundboard_list()
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Could Not Add Sound", str(e))
    def remove_soundboard_entry(self):
        command = self._selected_command()
        if not command:
            return
        self.pipeline.soundboard.remove_sound(command)
        self._refresh_soundboard_list()
    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------
    def check_virtual_mic_status(self):
        v_idx, _, _ = AudioRouter.find_virtual_cable()
        if v_idx is None:
            self._set_status("VIRTUAL MIC NOT FOUND", DANGER)
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Virtual Microphone Missing")
            msg.setText("VB-Audio Cable was not detected on your system.")
            msg.setInformativeText(
                "Game Voice TTS requires a virtual audio device to output speech into games like Marvel Rivals.\n\n"
                "Please install VB-Audio Virtual Cable and restart the application."
            )
            msg.exec()
    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        if os.path.exists(ICON_PATH):
            self.tray_icon.setIcon(QIcon(ICON_PATH))
        else:
            self.tray_icon.setIcon(QIcon.fromTheme("audio-input-microphone"))
        tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        exit_action = QAction("Exit App", self)
        exit_action.triggered.connect(self.close_app)
        tray_menu.addAction(show_action)
        tray_menu.addAction(exit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
    def closeEvent(self, event):
        """When clicking 'X', perform full application shutdown."""
        self.close_app()
    def close_app(self):
        """Clean process termination."""
        if hasattr(self, 'tray_icon'):
            self.tray_icon.hide()
        if hasattr(self, 'pipeline'):
            self.pipeline.stop()
        QApplication.quit()
        os._exit(0)
