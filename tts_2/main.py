import sys
import sounddevice as sd
from PySide6.QtWidgets import QApplication
from ui import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = MainWindow()

    def audio_callback(indata, frames, time_info, status):
        window.pipeline.process_live_audio_chunk(indata)

    sample_rate = window.config.get("sample_rate", 16000)
    device_id = window.config.get("input_device_id", None)

    try:
        stream = sd.InputStream(
            samplerate=sample_rate, 
            device=device_id,
            channels=1, 
            dtype='int16', 
            callback=audio_callback
        )
        stream.start()
        
        window.show()
        exit_code = app.exec()
        
        stream.stop()
        stream.close()
        sys.exit(exit_code)
    except Exception as e:
        print(f"[Error] Failed to start audio input stream: {e}")

if __name__ == "__main__":
    main()