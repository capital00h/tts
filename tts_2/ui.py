import os
import sys
import threading
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QComboBox, QPushButton, QProgressBar, QSystemTrayIcon, QMenu,
    QMessageBox, QCheckBox, QListWidget, QFileDialog, QInputDialog, QFrame
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QIcon, QAction

from audio_manager import AudioRouter
from config import load_config
from pipeline import VoicePipelineController
from llm_engine import PERSONA_PROMPTS


# Absolute path to your application icon
ICON_PATH = r"E:\tts\tts_2\soundboard.ico"


# ==============================================================================
# ROCK-SOLID, BUG-FREE DARK APP STYLESHEET
# ==============================================================================
CLEAN_DARK_STYLE = """
QMainWindow {
    background-color: #0F1117;
}

QWidget {
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    color: #E2E8F0;
}

/* Container Cards */
QFrame#statusCard, QFrame#audioCard, QFrame#personaCard, QFrame#soundboardCard, QFrame#monitorCard {
    background-color: #161922;
    border: 1px solid #232736;
    border-radius: 10px;
}

/* Section Headers */
QLabel.header-label {
    font-size: 11px;
    font-weight: 700;
    color: #6366F1;
    letter-spacing: 1px;
}

/* Sub labels */
QLabel {
    font-size: 12px;
    color: #94A3B8;
}

/* Combobox Styling */
QComboBox {
    background-color: #0D0F14;
    border: 1px solid #2D3245;
    border-radius: 6px;
    padding: 6px 10px;
    color: #F1F5F9;
    font-size: 12px;
}
QComboBox:hover {
    border-color: #6366F1;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #161922;
    border: 1px solid #2D3245;
    selection-background-color: #232736;
    selection-color: #818CF8;
    outline: none;
}

/* Checkbox */
QCheckBox {
    font-size: 12px;
    font-weight: 600;
    color: #E2E8F0;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #2D3245;
    background-color: #0D0F14;
}
QCheckBox::indicator:checked {
    background-color: #6366F1;
    border-color: #6366F1;
}

/* List Widget (Soundboard) */
QListWidget {
    background-color: #0D0F14;
    border: 1px solid #2D3245;
    border-radius: 6px;
    color: #CBD5E1;
    font-size: 12px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    padding: 6px;
    border-radius: 4px;
}
QListWidget::item:hover {
    background-color: #1E2330;
    color: #FFFFFF;
}
QListWidget::item:selected {
    background-color: #2D3245;
    color: #818CF8;
    font-weight: bold;
}

/* Buttons */
QPushButton {
    background-color: #1E2330;
    border: 1px solid #2D3245;
    border-radius: 6px;
    color: #E2E8F0;
    font-weight: 600;
    font-size: 12px;
    padding: 6px 12px;
}
QPushButton:hover {
    background-color: #282E3F;
    border-color: #4F46E5;
    color: #FFFFFF;
}
QPushButton:pressed {
    background-color: #161922;
}

/* Special Button Variants */
QPushButton#primaryBtn {
    background-color: #4F46E5;
    color: #FFFFFF;
    border: none;
}
QPushButton#primaryBtn:hover {
    background-color: #6366F1;
}

QPushButton#dangerBtn {
    background-color: #2C161B;
    color: #F87171;
    border: 1px solid #481D24;
}
QPushButton#dangerBtn:hover {
    background-color: #DC2626;
    color: #FFFFFF;
    border-color: #DC2626;
}

/* Audio Level Progress Bar */
QProgressBar {
    background-color: #0D0F14;
    border: 1px solid #2D3245;
    border-radius: 6px;
    height: 12px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:0.7 #F59E0B, stop:1 #EF4444);
    border-radius: 5px;
}
"""

class SignalBridge(QObject):
    status_changed = Signal(str)
    metrics_changed = Signal(float, float, float)
    level_changed = Signal(int)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.bridge = SignalBridge()

        self.setWindowTitle("Game Voice TTS - Virtual Microphone")
        
        # Enable Window Resizing & Maximizing
        self.resize(460, 680)
        self.setMinimumSize(440, 600)
        
        # Set Window Icon
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        self.setStyleSheet(CLEAN_DARK_STYLE)

        self._build_ui()
        self._setup_tray()
        
        # Connect Signals
        self.bridge.status_changed.connect(self.update_status_display)
        self.bridge.metrics_changed.connect(self.update_metrics_display)
        self.bridge.level_changed.connect(self.audio_meter.setValue)

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

    def _build_ui(self):
        central = QWidget()
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(10)

        # ----------------------------------------------------
        # 1. STATUS DISPLAY
        # ----------------------------------------------------
        status_card = QFrame()
        status_card.setObjectName("statusCard")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(10, 8, 10, 8)

        self.status_label = QLabel("READY")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 20px; font-weight: 800; color: #10B981; letter-spacing: 1px;")
        status_layout.addWidget(self.status_label)
        
        main_layout.addWidget(status_card)

        # ----------------------------------------------------
        # 2. AUDIO ROUTING SECTION
        # ----------------------------------------------------
        audio_card = QFrame()
        audio_card.setObjectName("audioCard")
        audio_layout = QVBoxLayout(audio_card)
        audio_layout.setContentsMargins(12, 10, 12, 12)
        audio_layout.setSpacing(6)

        hdr_audio = QLabel("AUDIO ROUTING")
        hdr_audio.setProperty("class", "header-label")
        audio_layout.addWidget(hdr_audio)

        inputs, outputs = AudioRouter.get_devices()

        lbl_input = QLabel("Physical Input Microphone:")
        audio_layout.addWidget(lbl_input)

        self.input_combo = QComboBox()
        for idx, name in inputs:
            self.input_combo.addItem(name, idx)
        audio_layout.addWidget(self.input_combo)

        lbl_output = QLabel("Virtual Cable Output:")
        audio_layout.addWidget(lbl_output)

        self.output_combo = QComboBox()
        v_idx, _, _ = AudioRouter.find_virtual_cable()
        for idx, name in outputs:
            self.output_combo.addItem(name, idx)
            if idx == v_idx:
                self.output_combo.setCurrentIndex(self.output_combo.count() - 1)
        audio_layout.addWidget(self.output_combo)

        main_layout.addWidget(audio_card)

        # ----------------------------------------------------
        # 3. PERSONA AI CONTROLS SECTION
        # ----------------------------------------------------
        persona_card = QFrame()
        persona_card.setObjectName("personaCard")
        persona_layout = QVBoxLayout(persona_card)
        persona_layout.setContentsMargins(12, 10, 12, 12)
        persona_layout.setSpacing(6)

        hdr_persona = QLabel("AI PERSONA ENGINE")
        hdr_persona.setProperty("class", "header-label")
        persona_layout.addWidget(hdr_persona)

        persona_row = QHBoxLayout()
        self.llm_enable_cb = QCheckBox("Enable AI Persona")
        self.llm_enable_cb.setChecked(True)

        self.persona_combo = QComboBox()
        self.persona_combo.addItems(list(PERSONA_PROMPTS.keys()))

        persona_row.addWidget(self.llm_enable_cb)
        persona_row.addSpacing(10)
        persona_row.addWidget(QLabel("Persona:"))
        persona_row.addWidget(self.persona_combo, stretch=1)

        persona_layout.addLayout(persona_row)
        main_layout.addWidget(persona_card)

        # ----------------------------------------------------
        # 4. SOUNDBOARD SECTION
        # ----------------------------------------------------
        sb_card = QFrame()
        sb_card.setObjectName("soundboardCard")
        sb_layout = QVBoxLayout(sb_card)
        sb_layout.setContentsMargins(12, 10, 12, 12)
        sb_layout.setSpacing(6)

        hdr_sb = QLabel("SOUNDBOARD ( Say \"/name\" to trigger )")
        hdr_sb.setProperty("class", "header-label")
        sb_layout.addWidget(hdr_sb)

        self.soundboard_list = QListWidget()
        self.soundboard_list.setMinimumHeight(95)
        sb_layout.addWidget(self.soundboard_list)

        sb_btn_layout = QHBoxLayout()
        sb_btn_layout.setSpacing(6)

        self.play_sound_btn = QPushButton("Play")
        self.play_sound_btn.setObjectName("primaryBtn")
        self.play_sound_btn.clicked.connect(self.play_selected_soundboard_entry)

        self.pause_sound_btn = QPushButton("Pause")
        self.pause_sound_btn.clicked.connect(self.toggle_soundboard_pause)

        self.add_sound_btn = QPushButton("Add Sound...")
        self.add_sound_btn.clicked.connect(self.add_soundboard_entry)

        self.remove_sound_btn = QPushButton("Remove Selected")
        self.remove_sound_btn.clicked.connect(self.remove_soundboard_entry)

        sb_btn_layout.addWidget(self.play_sound_btn)
        sb_btn_layout.addWidget(self.pause_sound_btn)
        sb_btn_layout.addWidget(self.add_sound_btn)
        sb_btn_layout.addWidget(self.remove_sound_btn)

        sb_layout.addLayout(sb_btn_layout)
        main_layout.addWidget(sb_card, stretch=1)

        # ----------------------------------------------------
        # 5. LIVE MONITOR & METRICS SECTION
        # ----------------------------------------------------
        mon_card = QFrame()
        mon_card.setObjectName("monitorCard")
        mon_layout = QVBoxLayout(mon_card)
        mon_layout.setContentsMargins(12, 10, 12, 10)
        mon_layout.setSpacing(6)

        hdr_mon = QLabel("LIVE MONITOR")
        hdr_mon.setProperty("class", "header-label")
        mon_layout.addWidget(hdr_mon)

        self.audio_meter = QProgressBar()
        self.audio_meter.setTextVisible(False)
        self.audio_meter.setRange(0, 100)
        mon_layout.addWidget(self.audio_meter)

        self.latency_label = QLabel("End-to-End Latency: ~0 ms")
        self.latency_label.setAlignment(Qt.AlignCenter)
        self.latency_label.setStyleSheet("color: #64748B; font-size: 11px;")
        mon_layout.addWidget(self.latency_label)

        main_layout.addWidget(mon_card)

        # ----------------------------------------------------
        # 6. BOTTOM ACTION BUTTONS
        # ----------------------------------------------------
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.cancel_btn = QPushButton("Cancel / Silence (ESC)")
        self.cancel_btn.clicked.connect(lambda: self.pipeline.cancel() if hasattr(self, 'pipeline') else None)
        btn_layout.addWidget(self.cancel_btn, stretch=1)

        self.exit_btn = QPushButton("Exit App")
        self.exit_btn.setObjectName("dangerBtn")
        self.exit_btn.clicked.connect(self.close_app)
        btn_layout.addWidget(self.exit_btn)

        main_layout.addLayout(btn_layout)

        central.setLayout(main_layout)
        self.setCentralWidget(central)

    # ------------------------------------------------------------------
    # Soundboard - dynamic add/remove/play/pause, persisted permanently
    # via SoundboardManager (writes to soundboard.json on every change).
    # ------------------------------------------------------------------

    def _refresh_soundboard_list(self):
        self.soundboard_list.clear()
        for command, file_path in self.pipeline.soundboard.list_sounds().items():
            self.soundboard_list.addItem(f"{command}   →   {os.path.basename(file_path)}")

    def play_selected_soundboard_entry(self):
        item = self.soundboard_list.currentItem()
        if not item:
            return
        command = item.text().split("   →   ")[0].strip()
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
            "Say this to trigger the clip (e.g. type '1' to trigger \"/1\"):"
        )
        if not ok or not command.strip():
            return

        try:
            self.pipeline.soundboard.add_sound(command, file_path)
            self._refresh_soundboard_list()
        except (ValueError, FileNotFoundError) as e:
            QMessageBox.warning(self, "Could Not Add Sound", str(e))

    def remove_soundboard_entry(self):
        item = self.soundboard_list.currentItem()
        if not item:
            return
        command = item.text().split("   →   ")[0].strip()
        self.pipeline.soundboard.remove_sound(command)
        self._refresh_soundboard_list()

    def check_virtual_mic_status(self):
        v_idx, _, _ = AudioRouter.find_virtual_cable()
        if v_idx is None:
            self.status_label.setText("VIRTUAL MIC NOT FOUND")
            self.status_label.setStyleSheet("font-size: 16px; font-weight: 800; color: #EF4444;")
            
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
        
        # Use custom icon if available, otherwise system fallback
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

    def update_status_display(self, state: str):
        self.status_label.setText(state)
        colors = {
            "READY": "#10B981",
            "LISTENING": "#F59E0B",
            "PROCESSING": "#6366F1",
            "SPEAKING": "#EC4899"
        }
        color = colors.get(state, "#FFFFFF")
        self.status_label.setStyleSheet(f"font-size: 20px; font-weight: 800; color: {color}; letter-spacing: 1px;")

    def update_metrics_display(self, stt_ms: float, tts_ms: float, total_ms: float):
        self.latency_label.setText(f"Latency: STT {stt_ms:.0f}ms | TTS {tts_ms:.0f}ms | Total {total_ms:.0f}ms")

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