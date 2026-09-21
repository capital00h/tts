import os
import sys
import shutil
import time
import queue
import threading
import subprocess
import msvcrt
import numpy as np
import sounddevice as sd
from pynput import keyboard
from pynput.keyboard import Controller as KeyboardController
from faster_whisper import WhisperModel


# ==========================================
# 1. AUDIO UTILITIES & DEVICE MANAGEMENT
# ==========================================
class AudioRouter:
    @staticmethod
    def get_virtual_cable_index() -> int | None:
        """Finds the output device ID for VB-Audio Virtual Cable across all Windows audio APIs."""
        for idx, dev in enumerate(sd.query_devices()):
            name = dev['name'].lower()
            if ("cable input" in name or "vb-audio" in name or "virtual cable" in name) and dev['max_output_channels'] > 0:
                return idx
        return None

    @staticmethod
    def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """Linear interpolation resampling to ensure compatibility with Windows sample rates."""
        if orig_sr == target_sr or len(audio) == 0:
            return audio
        duration = len(audio) / orig_sr
        target_length = int(duration * target_sr)
        orig_indices = np.linspace(0, len(audio) - 1, num=len(audio))
        target_indices = np.linspace(0, len(audio) - 1, num=target_length)
        return np.interp(target_indices, orig_indices, audio).astype(np.float32)


class AudioRecorder:
    def __init__(self, sample_rate=16000, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.buffer = []
        self.is_recording = False

    def start(self):
        self.buffer = []
        self.is_recording = True

    def append_data(self, indata):
        if self.is_recording:
            self.buffer.append(indata.copy())

    def stop(self) -> np.ndarray | None:
        self.is_recording = False
        if not self.buffer:
            return None
        raw_data = np.concatenate(self.buffer, axis=0)
        return raw_data.astype(np.float32) / 32768.0


# ==========================================
# 2. ENGINES (STT & TTS WITH AUTO-PTT)
# ==========================================
class SpeechToTextEngine:
    def __init__(self, model_size="tiny.en", device="cpu", compute_type="int8"):
        print(f"[Init] Loading Whisper STT model ({model_size})...")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_data: np.ndarray) -> tuple[str, float]:
        t_start = time.perf_counter()
        segments, _ = self.model.transcribe(
            audio_data, 
            beam_size=1, 
            language="en", 
            vad_filter=True
        )
        text = " ".join([seg.text.strip() for seg in segments])
        latency_ms = (time.perf_counter() - t_start) * 1000
        return text, latency_ms


class TextToSpeechEngine:
    def __init__(self, model_path: str, output_device_id: int | None, in_game_ptt_key: str = '`'):
        self.model_path = model_path
        self.output_device_id = output_device_id
        self.in_game_ptt_key = in_game_ptt_key
        self.piper_bin = self._find_piper_binary()
        self.kb_controller = KeyboardController()
        
        # Verify Piper config file presence
        json_config = self.model_path + ".json"
        if not os.path.exists(json_config):
            print(f"[Init] WARNING: Config file '{json_config}' missing! Piper will produce 0 bytes of audio.")

    def _find_piper_binary(self) -> str | None:
        piper_path = shutil.which("piper")
        if piper_path:
            return piper_path
        
        python_scripts_piper = os.path.join(sys.prefix, "Scripts", "piper.exe")
        if os.path.exists(python_scripts_piper):
            return python_scripts_piper

        local_piper = os.path.join(os.getcwd(), "piper.exe")
        if os.path.exists(local_piper):
            return local_piper

        print("[Init] ERROR: piper.exe not found in PATH or environment!")
        return None

    def synthesize_and_play(self, text: str) -> tuple[float, float]:
        if not text.strip() or not self.piper_bin or not os.path.exists(self.model_path):
            print(f"[TTS Warning] Invalid input or missing model: {self.model_path}")
            return 0.0, 0.0

        t_start = time.perf_counter()
        try:
            cmd = [self.piper_bin, "--model", self.model_path, "--output-raw"]
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            raw_pcm, err_out = proc.communicate(input=text.encode("utf-8"))
            t_synth_done = time.perf_counter()

            if proc.returncode != 0 or not raw_pcm:
                print(f"[TTS Error] Piper synthesis failed:\n{err_out.decode('utf-8', errors='ignore')}")
                return 0.0, 0.0

            # Convert 16-bit PCM to float32
            audio_data = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Resample Piper native 22050Hz -> 48000Hz (Windows Virtual Cable Standard)
            audio_48k = AudioRouter.resample(audio_data, orig_sr=22050, target_sr=48000)

            # --- AUTOMATED IN-GAME PTT TRIGGER ---
            self.kb_controller.press(self.in_game_ptt_key)
            time.sleep(0.05)  # 50ms buffer to allow game mic activation
            
            # Play to Virtual Cable (48000Hz)
            sd.play(audio_48k, samplerate=48000, device=self.output_device_id)
            sd.wait()
            
            time.sleep(0.05)  # 50ms trailing buffer
            self.kb_controller.release(self.in_game_ptt_key)
            # -------------------------------------
            
            t_play_done = time.perf_counter()
            return (t_synth_done - t_start) * 1000, (t_play_done - t_synth_done) * 1000
        except Exception as e:
            self.kb_controller.release(self.in_game_ptt_key)
            print(f"[TTS Exception] {e}")
            return 0.0, 0.0


# ==========================================
# 3. TEXT PROCESSING LAYER
# ==========================================
class TextProcessor:
    @staticmethod
    def process(text: str, mode: str = "CLEANUP") -> str:
        if mode == "OFF" or not text:
            return text
        if mode == "CLEANUP":
            cleaned = text.strip()
            return cleaned[0].upper() + cleaned[1:] if cleaned else cleaned
        return text


# ==========================================
# 4. PIPELINE CONTROLLER
# ==========================================
class VoicePipelineController:
    def __init__(self, model_path="en_US-lessac-medium.onnx", in_game_ptt_key="`"):
        self.recorder = AudioRecorder()
        self.stt = SpeechToTextEngine()
        
        virtual_cable_idx = AudioRouter.get_virtual_cable_index()
        if virtual_cable_idx is not None:
            dev_info = sd.query_devices(virtual_cable_idx)
            print(f"[Init] Audio Output set to Device #{virtual_cable_idx}: '{dev_info['name']}'")
        else:
            print("[Init] ERROR: VB-Audio Cable Input NOT found! Defaulting to system output.")

        self.tts = TextToSpeechEngine(
            model_path, 
            virtual_cable_idx,
            in_game_ptt_key=in_game_ptt_key
        )
        self.task_queue = queue.Queue()
        self.is_speaking = False
        self.running = True

        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def _worker_loop(self):
        while self.running:
            try:
                audio_data = self.task_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if audio_data is None:
                break

            self.is_speaking = True
            print("[State] PROCESSING (STT)...")
            
            text, stt_ms = self.stt.transcribe(audio_data)
            processed_text = TextProcessor.process(text, mode="CLEANUP")

            if processed_text:
                print(f"[STT Output] \"{processed_text}\"")
                print("[State] SPEAKING (Virtual Mic + Auto PTT)...")
                synth_ms, play_ms = self.tts.synthesize_and_play(processed_text)
                print(f"[Metrics] STT: {stt_ms:.0f}ms | TTS: {synth_ms:.0f}ms | Total: {stt_ms+synth_ms:.0f}ms")
            else:
                print("[State] STT Output was empty or unrecognised.")

            self.is_speaking = False
            print("[State] READY\n")
            self.task_queue.task_done()

    def submit_audio(self, audio_data: np.ndarray):
        self.task_queue.put(audio_data.flatten())

    def stop(self):
        self.running = False
        self.task_queue.put(None)


# ==========================================
# 5. ENTRY POINT & HOTKEY HANDLER
# ==========================================
def flush_input_buffer():
    while msvcrt.kbhit():
        msvcrt.getch()


def main():
    ptt_key = 'v'
    in_game_ptt_key = '`'
    
    pipeline = VoicePipelineController(in_game_ptt_key=in_game_ptt_key)
    key_is_held = False

    def audio_callback(indata, frames, time_info, status):
        if not pipeline.is_speaking:
            pipeline.recorder.append_data(indata)

    def on_press(key):
        nonlocal key_is_held
        try:
            if hasattr(key, 'char') and key.char == '\x11':
                print("\n[State] Ctrl+Q pressed. Exiting application...")
                return False

            if hasattr(key, 'char') and key.char and key.char.lower() == ptt_key:
                if not key_is_held and not pipeline.is_speaking:
                    key_is_held = True
                    pipeline.recorder.start()
                    print("\n[State] LISTENING...")
        except Exception:
            pass

    def on_release(key):
        nonlocal key_is_held
        try:
            if hasattr(key, 'char') and key.char and key.char.lower() == ptt_key:
                key_is_held = False
                audio_data = pipeline.recorder.stop()
                if audio_data is not None:
                    pipeline.submit_audio(audio_data)
                else:
                    print("[State] READY")
        except Exception:
            pass

    print("\n=== Real-Time Voice Transformer Ready ===")
    print(f"Hold '{ptt_key.upper()}' to record voice.")
    print(f"Auto In-Game PTT Key: '{in_game_ptt_key}'")
    print("[State] READY")

    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype='int16', callback=audio_callback):
            with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
                listener.join()
    except KeyboardInterrupt:
        print("\n[State] Interrupted by user.")
    finally:
        pipeline.stop()
        flush_input_buffer()
        print("[State] Terminated cleanly.")


if __name__ == "__main__":
    main()