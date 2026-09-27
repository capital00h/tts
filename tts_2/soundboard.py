import difflib
import json
import os
import re


SOUNDBOARD_FILE = "soundboard.json"


class SoundboardManager:
    """
    Maps spoken slash-commands (e.g. "/1", "/laugh") to local audio files,
    and persists that mapping to disk so it survives app restarts.

    Sounds can be added/removed at any time (from the UI, while the app is
    running) via add_sound()/remove_sound() - each call immediately
    rewrites the JSON file on disk, so nothing is lost between sessions.
    """

    def __init__(self, path: str = SOUNDBOARD_FILE):
        self.path = path
        self.sounds: dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.sounds = data
                else:
                    self.sounds = {}
            except Exception as e:
                print(f"[Soundboard] Failed to load {self.path}: {e}")
                self.sounds = {}
        else:
            self.sounds = {}

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.sounds, f, indent=4)
        except Exception as e:
            print(f"[Soundboard] Failed to save {self.path}: {e}")

    # ------------------------------------------------------------------
    # Editing (dynamic add/remove)
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_command(command: str) -> str:
        command = (command or "").strip().lower()
        command = command.lstrip("/").strip()
        return f"/{command}" if command else ""

    def add_sound(self, command: str, file_path: str):
        cmd = self.normalize_command(command)
        if not cmd:
            raise ValueError("Command cannot be empty.")
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Audio file not found: {file_path}")
        self.sounds[cmd] = file_path
        self._save()
        return cmd

    def remove_sound(self, command: str):
        cmd = self.normalize_command(command)
        if cmd in self.sounds:
            del self.sounds[cmd]
            self._save()
            return True
        return False

    def list_sounds(self) -> dict:
        return dict(self.sounds)

    # ------------------------------------------------------------------
    # Matching against transcribed speech
    # ------------------------------------------------------------------

    def is_slash_command(self, text: str) -> bool:
        """
        Returns True if the utterance starts with '/' or 'slash',
        indicating an attempted soundboard command.
        """
        if not text:
            return False
        cleaned = text.strip().lower()
        cleaned = re.sub(r"[.,!?;:]", "", cleaned).strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.startswith("/") or cleaned.startswith("slash")

    # Below this fuzzy-match ratio (0-1) a garbled "slash ..." utterance is
    # treated as not matching any known command, rather than guessing.
    FUZZY_THRESHOLD = 0.72

    def match(self, text: str) -> str | None:
        """
        Check STT output for a soundboard trigger. Returns the audio file
        path if the (whole) utterance is a recognized command, else None.
        """
        if not text or not self.sounds:
            return None

        cleaned = text.strip().lower()
        cleaned = re.sub(r"[.,!?;:]", "", cleaned)   # Whisper's stray punctuation
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"/\s+", "/", cleaned)
        if not cleaned:
            return None

        candidates = []
        if cleaned.startswith("/"):
            candidates.append(cleaned)
        m = re.match(r"^slash\s+(.+)$", cleaned)
        if m:
            candidates.append(f"/{m.group(1).strip()}")
        elif cleaned.startswith("slash"):
            candidates.append(f"/{cleaned[len('slash'):].strip()}")

        if not candidates:
            return None

        # Ignore standalone slash/empty candidates
        candidates = [c for c in candidates if c not in ("/", "")]
        if not candidates:
            return None

        for candidate in candidates:
            if candidate in self.sounds:
                return self.sounds[candidate]

        # Fuzzy fallback for STT mishearings within an attempted command.
        spoken = candidates[0].lstrip("/")
        if not spoken.strip():
            return None

        best_cmd, best_ratio = None, 0.0
        for cmd in self.sounds:
            ratio = difflib.SequenceMatcher(None, spoken, cmd.lstrip("/")).ratio()
            if ratio > best_ratio:
                best_ratio, best_cmd = ratio, cmd

        if best_cmd and best_ratio >= self.FUZZY_THRESHOLD:
            return self.sounds[best_cmd]

        return None