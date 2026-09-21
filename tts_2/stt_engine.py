import time
import numpy as np
from abc import ABC, abstractmethod
from faster_whisper import WhisperModel
import os
import sys

# Auto-add NVIDIA CUDA DLL paths on Windows
if sys.platform == "win32":
    cuda_libs = [
        os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cublas", "bin"),
        os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cudnn", "bin"),
    ]
    for lib_path in cuda_libs:
        if os.path.exists(lib_path):
            os.add_dll_directory(lib_path)
            os.environ["PATH"] = lib_path + os.pathsep + os.environ["PATH"]

class SpeechToTextEngine(ABC):
    @abstractmethod
    def transcribe(self, audio_data: np.ndarray) -> tuple[str, float]:
        pass

class WhisperSTT(SpeechToTextEngine):
    def __init__(self, model_size="base.en", device="cpu", compute_type="int8"):
        print(f"[STT] Loading Faster-Whisper ({model_size})...")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_data: np.ndarray) -> tuple[str, float]:
        t_start = time.perf_counter()
        segments, _ = self.model.transcribe(
            audio_data, beam_size=1, language="en", vad_filter=True
        )
        text = " ".join([seg.text.strip() for seg in segments])
        latency_ms = (time.perf_counter() - t_start) * 1000
        return text, latency_ms