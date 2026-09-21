import os
import sys
import math
import json
import shutil
import time
import queue
import signal
import threading
import subprocess
import msvcrt
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly
from pynput import keyboard
from pynput.keyboard import Controller as KeyboardController
from faster_whisper import WhisperModel

# Global references for clean shutdown across signal handlers
IN_GAME_PTT_KEY = '`'
KB_CONTROLLER = KeyboardController()
GLOBAL_PIPELINE = None
GLOBAL_LISTENER = None


# ==========================================
# CLEANUP & OS SIGNAL HANDLING
# ==========================================
def flush_input_buffer():
    """Flushes leftover characters from the console keyboard buffer."""
    # Brief pause allows Windows Console Host to register key-release events
    time.sleep(0.1)
    while msvcrt.kbhit():
        try:
            msvcrt.getch()
        except Exception:
            break


def cleanup_and_exit(sig=None, frame=None):
    """Releases hardware locks, stops background threads, flushes keys, and forces exit."""
    global GLOBAL_PIPELINE, GLOBAL_LISTENER
    
    # 1. Release in-game PTT key
    try:
        KB_CONTROLLER.release(IN_GAME_PTT_KEY)
    except Exception:
        pass

    # 2. Stop pynput hook listener thread
    if GLOBAL_LISTENER:
        try:
            GLOBAL_LISTENER.stop()
        except Exception:
            pass

    # 3. Stop Voice Pipeline worker thread
    if GLOBAL_PIPELINE:
        try:
            GLOBAL_PIPELINE.stop()
        except Exception:
            pass

    # 4. Clear console buffer and hard exit process
    flush_input_buffer()
    print("\n[State] Terminated cleanly.")
    os._exit(0)


signal.signal(signal.SIGINT, cleanup_and_exit)
signal.signal(signal.SIGTERM, cleanup_and_exit)


# ==========================================
# 1. AUDIO UTILITIES & DEVICE MANAGEMENT
# ==========================================
class AudioRouter:
    @staticmethod
    def get_virtual_cable_info() -> tuple[int | None, int, int]:
        """Queries Windows Sound API to get VB-Cable's EXACT device ID, sample rate, and channels."""
        for idx, dev in enumerate(sd.query_devices()):
            name = dev['name'].lower()
            if ("cable input" in name or "vb-audio" in name or "virtual cable" in name) and dev['max_output_channels'] > 0:
                rate = int(dev['default_samplerate'])
                channels = int(dev['max_output_channels'])
                return idx, rate, channels
        return None, 48000, 2

    @staticmethod
    def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        """High-quality polyphase anti-aliasing resampling."""
        if orig_sr == target_sr or len(audio) == 0:
            return audio.astype(np.float32)
        
        gcd = math.gcd(int(orig_sr), int(target_sr))
        up = int(target_sr // gcd)
        down = int(orig_sr // gcd)
        
        return resample_poly(audio, up, down).astype(np.float32)


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
        
        raw_data = np.concatenate(self.buffer, axis=0).astype(np.float32) / 32768.0
        
        # RMS Silence Check - prevents processing ambient room noise or empty hotkey taps
        rms = np.sqrt(np.mean(raw_data**2))
        if rms < 0.008:
            return None

        return raw_data


# ==========================================
# 2. ENGINES (STT & TTS WITH AUTO-PTT)
# ==========================================
class SpeechToTextEngine:
    def __init__(self, model_size="base.en", device="cpu", compute_type="int8"):
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
    def __init__(self, model_path: str, output_device_id: int | None, target_sr: int = 48000, target_channels: int = 2, in_game_ptt_key: str = '`'):
        self.model_path = model_path
        self.output_device_id = output_device_id
        self.target_sr = target_sr
        self.target_channels = target_channels
        self.in_game_ptt_key = in_game_ptt_key
        self.piper_bin = self._find_piper_binary()
        self.piper_sr = self._detect_sample_rate()

    def _detect_sample_rate(self) -> int:
        json_config = self.model_path + ".json"
        if os.path.exists(json_config):
            try:
                with open(json_config, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    return cfg.get("audio", {}).get("sample_rate", 22050)
            except Exception:
                pass
        print(f"[Init] WARNING: Could not read sample rate from '{json_config}'. Defaulting to 22050Hz.")
        return 22050

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
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creationflags
            )
            raw_pcm, err_out = proc.communicate(input=text.encode("utf-8"))
            t_synth_done = time.perf_counter()

            if proc.returncode != 0 or not raw_pcm:
                print(f"[TTS Error] Piper synthesis failed:\n{err_out.decode('utf-8', errors='ignore')}")
                return 0.0, 0.0

            # Convert 16-bit PCM to float32
            audio_data = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Peak Normalization
            max_val = np.max(np.abs(audio_data))
            if max_val > 0:
                audio_data = (audio_data / max_val) * 0.90

            # Dynamic Polyphase Resample (Piper Native SR -> VB-Cable Target SR)
            audio_resampled = AudioRouter.resample(audio_data, orig_sr=self.piper_sr, target_sr=self.target_sr)

            # Mono to Stereo Conversion
            if self.target_channels >= 2 and audio_resampled.ndim == 1:
                audio_resampled = np.column_stack([audio_resampled] * self.target_channels)

            # AUTOMATED IN-GAME PTT TRIGGER
            KB_CONTROLLER.press(self.in_game_ptt_key)
            time.sleep(0.05)
            
            sd.play(audio_resampled, samplerate=self.target_sr, device=self.output_device_id)
            sd.wait()
            
            time.sleep(0.05)
            KB_CONTROLLER.release(self.in_game_ptt_key)
            
            t_play_done = time.perf_counter()
            return (t_synth_done - t_start) * 1000, (t_play_done - t_synth_done) * 1000
        except Exception as e:
            KB_CONTROLLER.release(self.in_game_ptt_key)
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
        
        virtual_cable_idx, target_sr, target_channels = AudioRouter.get_virtual_cable_info()
        if virtual_cable_idx is not None:
            dev_info = sd.query_devices(virtual_cable_idx)
            print(f"[Init] Audio Output set to Device #{virtual_cable_idx}: '{dev_info['name']}' ({target_sr}Hz | {target_channels} Ch)")
        else:
            print("[Init] ERROR: VB-Audio Cable Input NOT found! Defaulting to system output.")

        self.tts = TextToSpeechEngine(
            model_path, 
            virtual_cable_idx,
            target_sr=target_sr,
            target_channels=target_channels,
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
                print("[State] STT Output was empty or unrecognized.")

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
def main():
    global GLOBAL_PIPELINE, GLOBAL_LISTENER
    ptt_key = 'v'
    
    GLOBAL_PIPELINE = VoicePipelineController(in_game_ptt_key=IN_GAME_PTT_KEY)
    key_is_held = False

    def audio_callback(indata, frames, time_info, status):
        if not GLOBAL_PIPELINE.is_speaking:
            GLOBAL_PIPELINE.recorder.append_data(indata)

    def on_press(key):
        nonlocal key_is_held
        try:
            # Catch Ctrl+C / Ctrl+Q hotkey characters directly
            if hasattr(key, 'char') and key.char in ['\x03', '\x11']:
                cleanup_and_exit()

            if hasattr(key, 'char') and key.char and key.char.lower() == ptt_key:
                if not key_is_held and not GLOBAL_PIPELINE.is_speaking:
                    key_is_held = True
                    GLOBAL_PIPELINE.recorder.start()
                    print("\n[State] LISTENING...")
        except Exception:
            pass

    def on_release(key):
        nonlocal key_is_held
        try:
            if hasattr(key, 'char') and key.char and key.char.lower() == ptt_key:
                key_is_held = False
                audio_data = GLOBAL_PIPELINE.recorder.stop()
                if audio_data is not None:
                    GLOBAL_PIPELINE.submit_audio(audio_data)
                else:
                    print("[State] READY")
        except Exception:
            pass

    print("\n=== Real-Time Voice Transformer Ready ===")
    print(f"Hold '{ptt_key.upper()}' to record voice.")
    print(f"Auto In-Game PTT Key: '{IN_GAME_PTT_KEY}'")
    print("Press Ctrl+C or Ctrl+Q to exit.")
    print("[State] READY")

    try:
        with sd.InputStream(samplerate=16000, channels=1, dtype='int16', callback=audio_callback):
            GLOBAL_LISTENER = keyboard.Listener(on_press=on_press, on_release=on_release)
            GLOBAL_LISTENER.start()
            
            while GLOBAL_LISTENER.running:
                time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        cleanup_and_exit()


if __name__ == "__main__":
    main()