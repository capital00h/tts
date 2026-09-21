import time
import subprocess
import os
import numpy as np
import sounddevice as sd
from pynput.keyboard import Controller, Key
from audio_manager import AudioRouter

class PiperTTS:
    def __init__(self, model_path: str, output_device_id: int, target_sr: int = 48000, target_channels: int = 2,
                 in_game_ptt_key: str = "`", cable_confirmed: bool = False):
        self.default_model_path = model_path
        self.output_device_id = output_device_id
        self.target_sr = target_sr
        self.target_channels = target_channels
        self.in_game_ptt_key = in_game_ptt_key
        self.keyboard = Controller()
        # Only auto-press the in-game PTT key when we've *confirmed* audio is
        # actually routed to a virtual cable (or a validated output device).
        # If this is False, sd.play() is falling back to your default output
        # device (speakers/headphones) instead of the cable — auto-pressing
        # PTT in that state would open your real game mic and leak your real
        # voice/room audio instead of (or alongside) the persona voice.
        self.cable_confirmed = cable_confirmed

    def _press_ptt(self):
        if not self.in_game_ptt_key or not self.cable_confirmed:
            return
        try:
            if len(self.in_game_ptt_key) == 1:
                self.keyboard.press(self.in_game_ptt_key)
            else:
                key_attr = getattr(Key, self.in_game_ptt_key, None)
                if key_attr:
                    self.keyboard.press(key_attr)
                else:
                    print(f"[TTS] PTT Press Warning: '{self.in_game_ptt_key}' is not a recognized special key; PTT not pressed.")
        except Exception as e:
            print(f"[TTS] PTT Press Error: {e}")

    def _release_ptt(self):
        # Deliberately NOT gated on cable_confirmed: if a press ever did go
        # through (e.g. cable_confirmed changed mid-session), we always want
        # to attempt a release so the game's PTT key never gets stuck down.
        if not self.in_game_ptt_key:
            return
        try:
            if len(self.in_game_ptt_key) == 1:
                self.keyboard.release(self.in_game_ptt_key)
            else:
                key_attr = getattr(Key, self.in_game_ptt_key, None)
                if key_attr:
                    self.keyboard.release(key_attr)
        except Exception as e:
            print(f"[TTS] PTT Release Error: {e}")

    def force_release_ptt(self):
        """Safety valve: call on cancel/shutdown in case a press ever got
        left holding the key down (crash mid-playback, etc.)."""
        self._release_ptt()

    def synthesize_and_play(self, text: str, stop_event=None, model_path: str = None, length_scale: float = 0.5) -> tuple[float, float]:
        t_start = time.perf_counter()

        # FIX: Check os.path.isfile so folder paths don't get selected
        if model_path and os.path.isfile(model_path):
            active_model = model_path
        elif os.path.isfile(self.default_model_path):
            active_model = self.default_model_path
        else:
            # Fallback: look for any .onnx voice model in the models folder
            models_dir = "models"
            if os.path.isdir(models_dir):
                valid_models = [os.path.join(models_dir, f) for f in os.listdir(models_dir) if f.endswith(".onnx")]
            else:
                print(f"[TTS Error] Models directory '{models_dir}' not found.")
                valid_models = []

            if valid_models:
                active_model = valid_models[0]
            else:
                print("[TTS Error] No valid .onnx voice model found!")
                return 0.0, 0.0

        cmd = [
            ".\\piper.exe",
            "--model", active_model,
            "--output-raw",
            "--length-scale", str(length_scale)
        ]

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL
            )
            raw_bytes, _ = process.communicate(input=text.encode("utf-8"))
        except Exception as e:
            print(f"[TTS Error] Failed to run piper.exe: {e}")
            return 0.0, 0.0

        synth_ms = (time.perf_counter() - t_start) * 1000

        if not raw_bytes:
            return synth_ms, 0.0

        audio_int16 = np.frombuffer(raw_bytes, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0

        # Resample from 22050 Hz default output to target sample rate
        resampled = AudioRouter.resample(audio_float, 22050, self.target_sr)

        if self.target_channels > 1:
            resampled = np.column_stack([resampled] * self.target_channels)

        t_play_start = time.perf_counter()

        if self.cable_confirmed:
            print(f"[TTS] Auto-pressing PTT key: '{self.in_game_ptt_key}'")
        else:
            print("[TTS] WARNING: No confirmed virtual-cable routing — playing locally and "
                  "skipping auto PTT press to avoid leaking your real mic into the game.")
        self._press_ptt()

        try:
            sd.play(resampled, samplerate=self.target_sr, device=self.output_device_id)

            duration = len(resampled) / self.target_sr
            end_time = time.time() + duration

            while time.time() < end_time:
                if stop_event and stop_event.is_set():
                    sd.stop()
                    break
                time.sleep(0.01)
        finally:
            self._release_ptt()
            print(f"[TTS] Auto-released PTT key: '{self.in_game_ptt_key}'")

        play_ms = (time.perf_counter() - t_play_start) * 1000
        return synth_ms, play_ms