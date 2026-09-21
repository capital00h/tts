import os
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QComboBox, QPushButton, QProgressBar, QSystemTrayIcon, QMenu,
    QMessageBox, QCheckBox
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QIcon, QAction
from audio_manager import AudioRouter
from config import load_config
from pipeline import VoicePipelineController
from llm_engine import PERSONA_PROMPTS

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
        self.setFixedSize(450, 480)

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

        self.check_virtual_mic_status()

    def _build_ui(self):
        central = QWidget()
        layout = QVBoxLayout()

        # Devices Section
        inputs, outputs = AudioRouter.get_devices()
        
        layout.addWidget(QLabel("Physical Microphone:"))
        self.input_combo = QComboBox()
        for idx, name in inputs:
            self.input_combo.addItem(name, idx)
        layout.addWidget(self.input_combo)

        layout.addWidget(QLabel("Virtual Microphone (Output):"))
        self.output_combo = QComboBox()
        v_idx, _, _ = AudioRouter.find_virtual_cable()
        for idx, name in outputs:
            self.output_combo.addItem(name, idx)
            if idx == v_idx:
                self.output_combo.setCurrentIndex(self.output_combo.count() - 1)
        layout.addWidget(self.output_combo)

        # Persona AI Controls Section
        persona_layout = QHBoxLayout()
        self.llm_enable_cb = QCheckBox("Enable AI Persona")
        self.llm_enable_cb.setChecked(True)

        self.persona_combo = QComboBox()
        self.persona_combo.addItems(list(PERSONA_PROMPTS.keys()))

        persona_layout.addWidget(self.llm_enable_cb)
        persona_layout.addWidget(QLabel("Persona:"))
        persona_layout.addWidget(self.persona_combo)
        layout.addLayout(persona_layout)

        # Status Display
        self.status_label = QLabel("READY")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #00FF66; margin: 10px 0;")
        layout.addWidget(self.status_label)

        # Audio Level Meter
        self.audio_meter = QProgressBar()
        self.audio_meter.setTextVisible(False)
        self.audio_meter.setRange(0, 100)
        layout.addWidget(self.audio_meter)

        # Metrics Output
        self.latency_label = QLabel("End-to-End Latency: ~0 ms")
        self.latency_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.latency_label)

        # Buttons Row
        btn_layout = QHBoxLayout()
        
        self.cancel_btn = QPushButton("Cancel / Silence (ESC)")
        self.cancel_btn.clicked.connect(lambda: self.pipeline.cancel() if hasattr(self, 'pipeline') else None)
        btn_layout.addWidget(self.cancel_btn)

        self.exit_btn = QPushButton("Exit App")
        self.exit_btn.setStyleSheet("background-color: #AA2222; color: white; font-weight: bold;")
        self.exit_btn.clicked.connect(self.close_app)
        btn_layout.addWidget(self.exit_btn)

        layout.addLayout(btn_layout)

        central.setLayout(layout)
        self.setCentralWidget(central)

    def check_virtual_mic_status(self):
        v_idx, _, _ = AudioRouter.find_virtual_cable()
        if v_idx is None:
            self.status_label.setText("VIRTUAL MIC NOT FOUND")
            self.status_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #FF3333; margin: 10px 0;")
            
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
            "READY": "#00FF66",
            "LISTENING": "#FFCC00",
            "PROCESSING": "#0099FF",
            "SPEAKING": "#FF3366"
        }
        color = colors.get(state, "#FFFFFF")
        self.status_label.setStyleSheet(f"font-size: 24px; font-weight: bold; color: {color}; margin: 10px 0;")

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