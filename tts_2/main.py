import os
import sys
import threading
import sounddevice as sd
os.environ["QT_QUICK_CONTROLS_STYLE"] = "Basic"
os.environ["QSG_RHI_BACKEND"] = "opengl"
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle  # <-- ADD THIS IMPORT
from PySide6.QtCore import QObject, Signal, Slot, Property, QUrl
from PySide6.QtGui import QIcon, QAction

from audio_manager import AudioRouter
from config import load_config, save_config
from pipeline import VoicePipelineController
from llm_engine import PERSONA_PROMPTS

ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soundboard.ico")


class BackendBridge(QObject):
    """Bridge layer exposing Python logic, pipeline signals, and audio routing to QML."""
    
    statusChanged = Signal(str)
    metricsChanged = Signal(float, float, float)
    levelChanged = Signal(int)
    soundboardUpdated = Signal()
    showWarning = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = load_config()

        self._inputs, self._outputs = AudioRouter.get_devices()
        self._v_idx, _, _ = AudioRouter.find_virtual_cable()

        # Initialize Pipeline Controller
        self.pipeline = VoicePipelineController(
            self.config,
            status_callback=lambda s: self.statusChanged.emit(s),
            metric_callback=lambda stt, tts, tot: self.metricsChanged.emit(stt, tts, tot),
            level_callback=lambda lvl: self.levelChanged.emit(lvl)
        )

        self._is_paused = False
        self.stream = None

    def start_audio_stream(self):
        """Starts the sounddevice input stream passing chunks to pipeline."""
        sample_rate = self.config.get("sample_rate", 16000)
        device_id = self.config.get("input_device_id", None)

        def audio_callback(indata, frames, time_info, status):
            self.pipeline.process_live_audio_chunk(indata)

        try:
            self.stream = sd.InputStream(
                samplerate=sample_rate, 
                device=device_id,
                channels=1, 
                dtype='int16', 
                callback=audio_callback
            )
            self.stream.start()
        except Exception as e:
            print(f"[Error] Failed to start audio input stream: {e}")
            self.showWarning.emit("Audio Error", f"Failed to start audio input stream:\n{e}")

    def stop_audio_stream(self):
        """Safely stops the audio stream."""
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

    # --- Properties Exposed to QML ---
    @Property(list, constant=True)
    def inputDevices(self):
        return [name for _, name in self._inputs]

    @Property(list, constant=True)
    def outputDevices(self):
        return [name for _, name in self._outputs]

    @Property(int, constant=True)
    def defaultVirtualCableIndex(self):
        configured = self.config.get("output_device_id")
        target = configured if AudioRouter.is_valid_output_device(configured) else self._v_idx
        for idx, (dev_id, _) in enumerate(self._outputs):
            if dev_id == target:
                return idx
        return 0

    @Property(int, constant=True)
    def defaultInputDeviceIndex(self):
        configured = self.config.get("input_device_id")
        for idx, (dev_id, _) in enumerate(self._inputs):
            if dev_id == configured:
                return idx
        return 0

    @Property(list, constant=True)
    def personas(self):
        return list(PERSONA_PROMPTS.keys())

    @Property(str, constant=True)
    def currentPersona(self):
        return self.pipeline.llm.persona

    @Property(bool, constant=True)
    def llmEnabled(self):
        return self.pipeline.llm.enabled

    @Property(list, notify=soundboardUpdated)
    def soundboardItems(self):
        items = []
        for command, file_path in self.pipeline.soundboard.list_sounds().items():
            items.append(f"{command}   →   {os.path.basename(file_path)}")
        return items

    # --- Slots Callable from QML ---
    @Slot(bool)
    def setLlmEnabled(self, enabled: bool):
        self.pipeline.llm.set_enabled(enabled)
        self.config["use_llm_persona"] = enabled
        save_config(self.config)

    @Slot(str)
    def setPersona(self, persona_name: str):
        self.pipeline.llm.set_persona(persona_name)
        self.config["persona"] = persona_name
        save_config(self.config)

    @Slot(int)
    def setInputDevice(self, index: int):
        if 0 <= index < len(self._inputs):
            device_id = self._inputs[index][0]
            self.config["input_device_id"] = device_id
            save_config(self.config)
            self.stop_audio_stream()
            self.start_audio_stream()

    @Slot(int)
    def setOutputDevice(self, index: int):
        if 0 <= index < len(self._outputs):
            device_id = self._outputs[index][0]
            self.config["output_device_id"] = device_id
            save_config(self.config)
            self.pipeline.tts.output_device_id = device_id
            self.pipeline.tts.cable_confirmed = AudioRouter.is_valid_output_device(device_id)

    @Slot(int)
    def playSoundboardIndex(self, index: int):
        sounds = list(self.pipeline.soundboard.list_sounds().items())
        if 0 <= index < len(sounds):
            command, file_path = sounds[index]
            if file_path and os.path.isfile(file_path):
                threading.Thread(
                    target=self.pipeline.tts.play_file,
                    args=(file_path,),
                    daemon=True
                ).start()

    @Slot(result=bool)
    def togglePause(self):
        if hasattr(self.pipeline, 'tts'):
            self._is_paused = self.pipeline.tts.toggle_pause()
        return self._is_paused

    @Slot(str, str)
    def addSoundboardEntry(self, file_url: str, command: str):
        file_path = QUrl(file_url).toLocalFile() if file_url.startswith("file:") else file_url
        if file_path and command.strip():
            try:
                self.pipeline.soundboard.add_sound(command.strip(), file_path)
                self.soundboardUpdated.emit()
            except (ValueError, FileNotFoundError) as e:
                self.showWarning.emit("Could Not Add Sound", str(e))

    @Slot(int)
    def removeSoundboardIndex(self, index: int):
        sounds = list(self.pipeline.soundboard.list_sounds().items())
        if 0 <= index < len(sounds):
            command, _ = sounds[index]
            self.pipeline.soundboard.remove_sound(command)
            self.soundboardUpdated.emit()

    @Slot()
    def checkVirtualMicStatus(self):
        v_idx, _, _ = AudioRouter.find_virtual_cable()
        if v_idx is None:
            self.statusChanged.emit("VIRTUAL MIC NOT FOUND")
            self.showWarning.emit(
                "Virtual Microphone Missing",
                "VB-Audio Cable was not detected on your system.\n\nPlease install VB-Audio Virtual Cable and restart the application."
            )

    @Slot()
    def cancel(self):
        self.pipeline.cancel()

    @Slot()
    def closeApp(self):
        self.stop_audio_stream()
        if hasattr(self, 'pipeline'):
            self.pipeline.stop()
        QApplication.quit()
        os._exit(0)


def setup_tray(app, engine):
    tray = QSystemTrayIcon()
    if os.path.exists(ICON_PATH):
        tray.setIcon(QIcon(ICON_PATH))
    else:
        tray.setIcon(QIcon.fromTheme("audio-input-microphone"))

    menu = QMenu()
    show_action = QAction("Show Window", menu)
    
    def show_window():
        root_objects = engine.rootObjects()
        if root_objects:
            root_objects[0].show()
            root_objects[0].raise_()

    show_action.triggered.connect(show_window)
    exit_action = QAction("Exit App", menu)
    
    bridge = engine.rootContext().contextProperty("backend")
    exit_action.triggered.connect(lambda: bridge.closeApp() if bridge else app.quit())

    menu.addAction(show_action)
    menu.addAction(exit_action)
    tray.setContextMenu(menu)
    tray.show()
    return tray


if __name__ == "__main__":
    # Force QML to use the customizable Basic style
    QQuickStyle.setStyle("Basic")  # <-- ADD THIS LINE

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

    engine = QQmlApplicationEngine()
    backend = BackendBridge()

    engine.rootContext().setContextProperty("backend", backend)

    qml_file = os.path.join(os.path.dirname(__file__), "main.qml")
    engine.load(QUrl.fromLocalFile(qml_file))

    if not engine.rootObjects():
        sys.exit(-1)

    tray_icon = setup_tray(app, engine)

    backend.start_audio_stream()
    backend.checkVirtualMicStatus()

    exit_code = app.exec()
    backend.closeApp()
    sys.exit(exit_code)