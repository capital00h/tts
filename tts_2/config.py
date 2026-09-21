import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "input_device_id": None,
    "output_device_id": None,
    "ptt_key": "v",
    "in_game_ptt_key": "`",
    "stt_model": "distil-medium.en",
    "stt_device": "cuda",
    "stt_compute_type": "float16",
    # FIX: Point directly to the female .onnx file
    "tts_model_path": r"E:\tts\tts_2\models\en_US-hfc_female-medium.onnx",
    "text_process_mode": "CLEANUP",
    "max_recording_sec": 10,
    "sample_rate": 16000,
    "queue_mode": "INTERRUPT",
}

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
        except Exception as e:
            print(f"[Config] Failed to load config: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(config: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"[Config] Failed to save config: {e}")