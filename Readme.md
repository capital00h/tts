# Game Voice TTS: Real-Time AI Voice Persona for In-Game Chat

A Windows desktop app that turns your **spoken words into a character voice in real time**. Hold a key, speak, and your teammates hear a Pirate, JARVIS, Medieval Knight, or Anime Hero say what you meant, piped straight into game voice chat.

**Pipeline:** Mic → Speech-to-Text (Whisper, GPU) → LLM persona rewrite (local Ollama) → Neural TTS (Piper) → Virtual audio cable → Game voice chat

---

## Highlights

- **End-to-end real-time voice pipeline** combining STT, LLM, and TTS with per-stage latency metrics shown live in the UI.
- **GPU-accelerated transcription** using `faster-whisper` (`distil-large-v3`, `int8_float16`) with VAD filtering and an accent-aware initial prompt.
- **Local LLM persona engine** (Ollama + `llama3.2:3b`) that rewrites speech in a character's style while preserving speaker intent, names, and numbers.
- **Guardrails against LLM hallucination**: validates every output and falls back to the raw transcript if it detects prompt leakage, mutated numbers, runaway length, or generation loops.
- **Per-persona voices**: each persona maps to its own Piper ONNX voice model and speech rate.
- **Voice-chat integration**: routes audio into a VB-Audio virtual cable and auto-presses/releases the game's push-to-talk key around playback.
- **Voice-triggered soundboard**: say "slash laugh" (or `/laugh`) to play a clip, with fuzzy matching to tolerate STT mishearings.
- **Polished PySide6 GUI** with device selection, live mic level meter, persona picker, soundboard editor, system tray support, and a global cancel hotkey.

---

## Tech Stack

| Area | Tools |
|---|---|
| Language | Python 3 |
| GUI | PySide6 (Qt), custom stylesheet, system tray |
| Speech-to-Text | faster-whisper (CTranslate2), CUDA |
| LLM | Ollama (`llama3.2:3b`), REST API; Groq (`llama-3.1-8b-instant`) backend scaffolded |
| Text-to-Speech | Piper (ONNX voice models) |
| Audio | sounddevice, NumPy, SciPy (`resample_poly`), VB-Audio Virtual Cable |
| Input control | pynput (global hotkeys, simulated key press) |
| Concurrency | `threading`, `queue`, `threading.Event` |

---

## How It Works

1. **Capture**: Hold the push-to-talk key (default `V`). A `sounddevice` input stream buffers 16 kHz mono audio, and recordings with too little energy (RMS check) are discarded as silence.
2. **Transcribe**: On release, audio goes to a `faster-whisper` model with beam size 1 and VAD filtering for low latency.
3. **Route**: If the transcript starts with "/" or "slash", it is treated as a soundboard command and never reaches the LLM or TTS. Otherwise it continues to the persona stage.
4. **Transform**: A persona-specific system prompt with few-shot examples rewrites the sentence via Ollama. Prompts preserve speaker direction (a request to a teammate stays a request), keep character names exact, and translate gaming jargon such as "tank" correctly.
5. **Validate**: Output is cleaned and sanity-checked. Bad output is replaced by the original transcript, so the user is never spoken over with garbage.
6. **Synthesize**: Piper generates raw PCM using the persona's voice model and length scale.
7. **Play**: Audio is resampled to the cable's native rate and channel count, then streamed in chunks. The in-game PTT key is held down during playback and released afterward.

---

## Engineering Details Worth Noting

**Resilience and failure handling**
- The Ollama client warms the model at startup and keeps it loaded (`keep_alive`).
- A 4-second request timeout and a failure counter mark the LLM unhealthy after repeated errors, so the app degrades to plain STT to TTS rather than stalling a live conversation.
- The LLM is skipped for single-word inputs to save latency, and the token budget scales with input length.

**Safety around simulated keypresses**
- The app only auto-presses the in-game PTT key when it has **confirmed** audio is going to a virtual cable or a validated output device. Otherwise it would open the player's real mic and leak room audio.
- PTT release is deliberately *not* gated, and it runs in a `finally` block plus a `force_release_ptt()` safety valve on cancel and shutdown, so the key can never get stuck down.

**Concurrency**
- Audio capture runs on the sounddevice callback thread, hotkeys on a pynput listener thread, and the STT, LLM, and TTS work on a single background worker fed by a `queue.Queue`.
- A shared `threading.Event` lets the ESC hotkey interrupt transcription, synthesis, or playback mid-stream. Pause and resume are supported during playback.

**Soundboard**
- Commands persist to `soundboard.json` on every add or remove, so changes survive restarts and can be made while the app runs.
- Matching handles Whisper's stray punctuation, "slash x" versus "/x" forms, and uses `difflib` fuzzy matching (threshold 0.72). Unrecognized slash commands are suppressed instead of being spoken aloud.

---

## Project Structure

```
tts_2/
├── main.py            # App entry point, mic stream, Qt event loop
├── ui.py              # PySide6 GUI (devices, personas, soundboard, live monitor, tray)
├── pipeline.py        # Orchestrator: hotkeys, worker thread, stage sequencing, metrics
├── stt_engine.py      # faster-whisper wrapper (abstract STT interface + Whisper impl)
├── llm_engine.py      # Persona prompts, Ollama/Groq clients, output validation
├── tts_engine.py      # Piper synthesis, resampling, playback, PTT control
├── audio_manager.py   # Device discovery, virtual cable detection, resampler, recorder
├── soundboard.py      # Persisted slash-command soundboard with fuzzy matching
├── text_processor.py  # Post-LLM text cleanup
├── config.py          # JSON-backed settings with defaults
└── models/            # Piper voice model configs (6 voices)
```

---

## Personas

| Persona | Style | Voice model |
|---|---|---|
| Pirate | Playful pirate speech | `en_US-ryan-high` |
| Jarvis | Calm, formal, dry-witted AI butler | `en_GB-northern_english_male-medium` |
| Medieval Knight | Heroic archaic phrasing | `en_GB-alan-medium` |
| Anime Hero | Energetic, dramatic | `en_US-joe-medium` |

Adding a persona means adding one entry (prompt, voice model, speech rate) to `PERSONA_CONFIGS`.

---

## Setup

**Requirements:** Windows, Python 3.10+, NVIDIA GPU with CUDA (or set `stt_device` to `cpu`), [Ollama](https://ollama.com), [VB-Audio Virtual Cable](https://vb-audio.com/Cable/), and [Piper](https://github.com/rhasspy/piper) with voice models.

```bash
# 1. Install dependencies
pip install PySide6 sounddevice numpy scipy faster-whisper pynput requests

# 2. Pull the local LLM
ollama pull llama3.2:3b

# 3. Place piper.exe in the working directory and the .onnx voice models in ./models

# 4. Update tts_model_path in config.py (or config.json) to your local model path

# 5. Run
cd tts_2
python main.py
```

In your game, set the microphone to **CABLE Output** and set a push-to-talk key that matches `in_game_ptt_key` in the config.

> The `.onnx` voice weights and `piper.exe` are not included in the repo (only the `.json` model configs are).

---

## Configuration

Settings live in `config.json` (created on first save) and cover audio devices, push-to-talk keys, Whisper model and compute type, voice model path, max recording length, and queue behavior. LLM behavior can be tuned with the environment variables `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT`, `OLLAMA_KEEP_ALIVE`, and `TTS_DEBUG`.

---

## What This Project Demonstrates

- Designing and integrating a **multi-model AI pipeline** (ASR → LLM → TTS) under real-time latency constraints
- **Prompt engineering** with few-shot examples and programmatic output validation to make a small local LLM reliable
- **Multithreaded desktop application** design with safe cancellation and shared state
- **Low-level audio engineering**: device routing, sample-rate conversion, chunked streaming
- Defensive programming around side effects (simulated input, hardware routing) and graceful degradation when services fail
- Building a complete, user-facing **GUI application** around ML components

---

## Roadmap

- Hosted LLM fallback (Groq backend is already scaffolded)
- More personas and multilingual voices
- Configurable persona and voice editor in the UI
- Packaged installer (PyInstaller)