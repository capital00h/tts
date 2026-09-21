import time
import queue
import threading
import numpy as np
import sounddevice as sd
from pynput import keyboard
from audio_manager import AudioRecorder, AudioRouter
from stt_engine import WhisperSTT
from tts_engine import PiperTTS
from text_processor import TextProcessor
from llm_engine import LLMPersonaEngine, PERSONA_CONFIGS


class VoicePipelineController:
    def __init__(self, config: dict, status_callback=None, metric_callback=None, level_callback=None):
        self.config = config
        self.status_cb = status_callback
        self.metric_cb = metric_callback
        self.level_cb = level_callback
        
        self.max_recording_sec = float(config.get("max_recording_sec", 10.0))
        self.record_start_time = 0.0
        
        self.recorder = AudioRecorder(sample_rate=config.get("sample_rate", 16000))
        self.stt = WhisperSTT(
            model_size=config.get("stt_model", "base.en"),
            device=config.get("stt_device", "cpu"),
            compute_type=config.get("stt_compute_type", "int8")
        )
        
        # Initialize LLM Persona Engine
        self.llm = LLMPersonaEngine(
            enabled=config.get("use_llm_persona", True),
            persona=config.get("persona", "Pirate"),
            provider=config.get("llm_provider", "ollama")
        )
        
        v_idx, target_sr, target_ch = AudioRouter.find_virtual_cable()
        configured_output = config.get("output_device_id")

        # Only trust a device (and therefore only auto-press the in-game PTT
        # key) once we've actually confirmed it's a real, valid output
        # device. `... or v_idx` used to silently discard a configured
        # device index of 0, and silently fell through to None (system
        # default speakers) if no virtual cable was found — which then
        # still auto-pressed PTT and leaked the real mic. Both are fixed here.
        if configured_output is not None and AudioRouter.is_valid_output_device(configured_output):
            output_dev = configured_output
            routing_confirmed = True
        elif v_idx is not None:
            output_dev = v_idx
            routing_confirmed = True
        else:
            output_dev = None
            routing_confirmed = False
            print("[Pipeline] WARNING: No virtual audio cable detected and no valid "
                  "output_device_id configured. TTS will play on your default output "
                  "device only; the in-game PTT key will NOT be auto-pressed, so your "
                  "persona voice won't reach the game until this is fixed.")

        self.tts = PiperTTS(
            model_path=config.get("tts_model_path", "en_US-hfc_female-medium.onnx"),
            output_device_id=output_dev,
            target_sr=target_sr,
            target_channels=target_ch,
            in_game_ptt_key=config.get("in_game_ptt_key", "`"),
            cable_confirmed=routing_confirmed
        )

        self.task_queue = queue.Queue()
        self.is_speaking = False
        self.running = True
        self.stop_current_playback = threading.Event()
        self.key_held = False

        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()
        
        self._init_hotkeys()

    def _update_status(self, state: str):
        if self.status_cb:
            self.status_cb(state)

    def process_live_audio_chunk(self, indata):
        if self.level_cb and len(indata) > 0:
            rms = float(np.sqrt(np.mean(indata.astype(np.float32)**2)))
            level_pct = min(100, int((rms / 32768.0) * 500)) if indata.dtype == np.int16 else min(100, int(rms * 500))
            self.level_cb(level_pct)

        if self.recorder.is_recording:
            self.recorder.append_data(indata)
            if time.time() - self.record_start_time >= self.max_recording_sec:
                self.stop_and_submit_recording()

    def start_recording(self):
        if not self.recorder.is_recording:
            self.record_start_time = time.time()
            self.recorder.start()
            self._update_status("LISTENING")

    def stop_and_submit_recording(self):
        if not self.recorder.is_recording:
            return
        audio_data = self.recorder.stop()
        if audio_data is not None:
            self.task_queue.put(audio_data)
        else:
            self._update_status("READY")

    def _init_hotkeys(self):
        ptt = self.config.get("ptt_key", "v").lower()

        def on_press(key):
            try:
                if hasattr(key, 'char') and key.char and key.char.lower() == ptt:
                    if not self.key_held and not self.is_speaking:
                        self.key_held = True
                        self.start_recording()
                elif key == keyboard.Key.esc:
                    self.cancel()
            except Exception:
                pass

        def on_release(key):
            try:
                if hasattr(key, 'char') and key.char and key.char.lower() == ptt:
                    self.key_held = False
                    self.stop_and_submit_recording()
            except Exception:
                pass

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.start()

    def cancel(self):
        self.stop_current_playback.set()
        with self.task_queue.mutex:
            self.task_queue.queue.clear()
        self.recorder.stop()
        sd.stop()
        self.tts.force_release_ptt()
        self.is_speaking = False
        self._update_status("READY")

    def _worker_loop(self):
        while self.running:
            try:
                audio_data = self.task_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if audio_data is None:
                break

            self.stop_current_playback.clear()
            self.is_speaking = True
            self._update_status("PROCESSING")

            # 1. Speech to Text
            raw_text, stt_ms = self.stt.transcribe(audio_data)

            if raw_text and not self.stop_current_playback.is_set():
                print(f"[Raw Input]: \"{raw_text}\"")

                # 2. LLM Persona Transformation
                character_text, llm_ms = self.llm.transform(raw_text)
                print(f"[Persona Output]: \"{character_text}\"")

                # 3. Text Cleanup
                processed_text = TextProcessor.process(character_text, mode=self.config.get("text_process_mode", "CLEANUP"))
                # 4. Fetch Active Persona's Voice Model & Speed (Only if LLM is enabled)
                if self.llm.enabled:
                    persona_cfg = PERSONA_CONFIGS.get(self.llm.persona, {})
                    voice_model = persona_cfg.get("model_path")
                    speech_speed = persona_cfg.get("length_scale", 1.0)
                else:
                    voice_model = None  # Falls back to self.tts.default_model_path (Female Voice)
                    speech_speed = 1.0

                # 5. Text to Speech
                self._update_status("SPEAKING")
                synth_ms, play_ms = self.tts.synthesize_and_play(
                    processed_text,
                    stop_event=self.stop_current_playback,
                    model_path=voice_model,
                    length_scale=speech_speed
                )

                if self.metric_cb:
                    self.metric_cb(stt_ms, synth_ms, stt_ms + llm_ms + synth_ms)

            self.is_speaking = False
            self._update_status("READY")
            self.task_queue.task_done()

    def stop(self):
        self.running = False
        self.listener.stop()
        self.tts.force_release_ptt()
        self.task_queue.put(None)