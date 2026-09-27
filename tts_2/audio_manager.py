import math
import numpy as np
import sounddevice as sd
from scipy.signal import resample_poly

class AudioRouter:
    @staticmethod
    def get_devices():
        devices = sd.query_devices()
        inputs, outputs = [], []
        for idx, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                inputs.append((idx, dev['name']))
            if dev['max_output_channels'] > 0:
                outputs.append((idx, dev['name']))
        return inputs, outputs

    @staticmethod
    def find_virtual_cable() -> tuple[int | None, int, int]:
        for idx, dev in enumerate(sd.query_devices()):
            name = dev['name'].lower()
            if ("cable input" in name or "vb-audio" in name or "virtual cable" in name) and dev['max_output_channels'] > 0:
                return idx, int(dev['default_samplerate']), int(dev['max_output_channels'])
        return None, 48000, 2
    # @staticmethod
    # def find_virtual_cable() -> tuple[int | None, int, int]:
    #     """Finds headphones/default playback device for testing."""
    #     default_out_idx = sd.default.device[1]  # System default output
        
    #     for idx, dev in enumerate(sd.query_devices()):
    #         name = dev['name'].lower()
    #         # Look for typical headphone keywords or fallback to default output
    #         if ("headphone" in name or "headset" in name or idx == default_out_idx) and dev['max_output_channels'] > 0:
    #             return idx, int(dev['default_samplerate']), int(dev['max_output_channels'])
                
    #     return None, 48000, 2
    @staticmethod
    def is_valid_output_device(device_id) -> bool:
        """Confirms a device index exists and actually accepts output, before
        we trust it enough to auto-key the in-game PTT button."""
        if device_id is None:
            return False
        try:
            info = sd.query_devices(device_id)
            return info.get('max_output_channels', 0) > 0
        except Exception:
            return False

    @staticmethod
    def resample(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
        if orig_sr == target_sr or len(audio) == 0:
            return audio.astype(np.float32)
        gcd = math.gcd(int(orig_sr), int(target_sr))
        up = int(target_sr // gcd)
        down = int(orig_sr // gcd)
        return resample_poly(audio, up, down).astype(np.float32)

class AudioRecorder:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
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
        
        # Flatten array shape from (N, 1) to (N,)
        raw_data = np.squeeze(raw_data)
        if raw_data.ndim > 1:
            raw_data = np.mean(raw_data, axis=-1)

        rms = np.sqrt(np.mean(raw_data**2))
        if rms < 0.008:
            return None
            
        return raw_data