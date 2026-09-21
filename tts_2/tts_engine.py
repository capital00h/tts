import time
import subprocess
import os
import wave
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
        self.is_playing = False
        self.is_paused = False

    def pause(self):
        """Pause current audio playback."""
        if self.is_playing:
            self.is_paused = True

    def resume(self):
        """Resume paused audio playback."""
        if self.is_playing:
            self.is_paused = False

    def toggle_pause(self) -> bool:
        """Toggle current playback pause/resume state."""
        if self.is_playing:
            self.is_paused = not self.is_paused
            return self.is_paused
        return False

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
        self.is_paused = False
        self.is_playing = False
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

        play_ms = self._route_and_play(audio_float, orig_sr=22050, stop_event=stop_event)
        return synth_ms, play_ms

    # ------------------------------------------------------------------
    # Soundboard playback (bypasses piper entirely — plays a pre-recorded
    # clip through the exact same virtual-cable + PTT routing as TTS).
    # ------------------------------------------------------------------

    def play_file(self, file_path: str, stop_event=None) -> float:
        """
        Play a local audio clip (soundboard trigger) through the same
        output device as synthesized speech, auto-pressing the in-game
        PTT key exactly like synthesize_and_play() does. Returns the
        playback duration in ms (0.0 on failure).
        """
        if not file_path or not os.path.isfile(file_path):
            print(f"[Soundboard] Audio file not found: {file_path}")
            return 0.0

        try:
            audio_float, orig_sr = self._load_wav(file_path)
        except Exception as e:
            print(f"[Soundboard Error] Failed to read '{file_path}': {e}")
            return 0.0

        if audio_float is None or len(audio_float) == 0:
            return 0.0

        return self._route_and_play(audio_float, orig_sr=orig_sr, stop_event=stop_event)

    @staticmethod
    def _load_wav(file_path: str) -> tuple[np.ndarray, int]:
        """Reads a 16-bit PCM .wav file (mono or stereo) into a mono float32
        array in [-1, 1]. Soundboard clips should be .wav files."""
        with wave.open(file_path, "rb") as wf:
            sr = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            frames = wf.readframes(wf.getnframes())

        if sampwidth != 2:
            raise ValueError(
                f"Only 16-bit PCM .wav files are supported (got {sampwidth * 8}-bit)."
            )

        audio_int16 = np.frombuffer(frames, dtype=np.int16)
        if n_channels > 1:
            audio_int16 = audio_int16.reshape(-1, n_channels).mean(axis=1)

        audio_float = audio_int16.astype(np.float32) / 32768.0
        return audio_float, sr

    # ------------------------------------------------------------------
    # Shared routing/playback + PTT auto-press, used by both synthesized
    # speech and soundboard clips so behavior (and the mic-leak safety
    # gating) stays identical between the two.
    # ------------------------------------------------------------------

    def _route_and_play(self, audio_float: np.ndarray, orig_sr: int, stop_event=None) -> float:
        resampled = AudioRouter.resample(audio_float, orig_sr, self.target_sr)

        if self.target_channels > 1:
            resampled = np.column_stack([resampled] * self.target_channels)

        t_play_start = time.perf_counter()

        if self.cable_confirmed:
            print(f"[TTS] Auto-pressing PTT key: '{self.in_game_ptt_key}'")
        else:
            print("[TTS] WARNING: No confirmed virtual-cable routing — playing locally and "
                  "skipping auto PTT press to avoid leaking your real mic into the game.")
        self._press_ptt()

        self.is_playing = True
        self.is_paused = False

        try:
            channels = resampled.shape[1] if resampled.ndim > 1 else 1
            chunk_size = 2048
            pos = 0
            total_frames = len(resampled)

            with sd.OutputStream(samplerate=self.target_sr, device=self.output_device_id, channels=channels, dtype='float32') as stream:
                while pos < total_frames:
                    if stop_event and stop_event.is_set():
                        break

                    if self.is_paused:
                        self._release_ptt()
                        while self.is_paused:
                            if stop_event and stop_event.is_set():
                                break
                            time.sleep(0.01)
                        if not (stop_event and stop_event.is_set()):
                            self._press_ptt()
                        else:
                            break

                    chunk = resampled[pos:pos + chunk_size]
                    stream.write(np.ascontiguousarray(chunk, dtype=np.float32))
                    pos += len(chunk)
        finally:
            self.is_playing = False
            self.is_paused = False
            self._release_ptt()
            print(f"[TTS] Auto-released PTT key: '{self.in_game_ptt_key}'")

        play_ms = (time.perf_counter() - t_play_start) * 1000
        return play_ms