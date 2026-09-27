import json
import os

CONFIG_FILE = "config.json"
#"tts_model_path": r"E:\tts\tts_2\models\en_US-hfc_female-medium.onnx",
DEFAULT_CONFIG = {
    "input_device_id": None,
    "output_device_id": None,
    "ptt_key": "v",
    "in_game_ptt_key": "`",
    
    # --- STT ACCENT & PERFORMANCE OPTIMIZATIONS ---
    # "distil-large-v3" gives large-model accuracy at under 1.5GB VRAM
    "stt_model": "distil-large-v3", 
    "stt_device": "cuda",
    
    # "int8_float16" halves VRAM usage with zero noticeable loss in quality
    "stt_compute_type": "int8_float16", 
    
    # Give Whisper contextual hints for voice commands & accents
    "stt_initial_prompt": "Indian English accent, voice commands: slash, blade theme, play soundboard.",
    
    # --- TTS & AUDIO SETTINGS ---
    "tts_model_path": r"E:\tts\tts_2\models\ru_RU-irina-medium.onnx",
    "text_process_mode": "CLEANUP",
    "max_recording_sec": 10,
    "sample_rate": 16000,
    "queue_mode": "INTERRUPT",
    "soundboard_file": "soundboard.json",
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