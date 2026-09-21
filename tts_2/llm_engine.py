import os
import re
import time
import requests


# ============================================================
# PERSONA CONFIGURATION
# ============================================================

PERSONA_CONFIGS = {
    "Pirate": {
        "prompt": (
            "Rewrite the user's spoken voice chat sentence as brief, natural pirate speech.\n\n"

            "ROLE & PERSPECTIVE RULES:\n"
            "- If the user asks a teammate a question/request ('can you...'), KEEP IT as a request to that teammate. Do NOT change it to 'I will'.\n"
            "- Always preserve who is speaking and who is being spoken to.\n"
            "- Keep all character/player names exactly as spoken (e.g., Rocket, Bucky, Venom).\n\n"

            "GAMING TERMS:\n"
            "- 'tank' = frontline/draw enemy fire (NOT hold fire)\n"
            "- 'look at / check' = watch out for / target\n\n"

            "CRITICAL RULES:\n"
            "- Preserve exact numbers, names, and intent.\n"
            "- Output exactly ONE sentence.\n"
            "- Output ONLY the rewritten sentence.\n"
            "- Never explain your changes.\n\n"

            "EXAMPLES:\n"
            "Input: Rocket, can you tank? I can play Bucky.\n"
            "Output: Rocket, can ye take the front line, matey? I'll take up the mantle of Bucky!\n\n"

            "Input: Bucky, can you look at the Penni nest please?\n"
            "Output: Bucky, check on that Penni nest for us, matey!\n"
        ),
        "model_path": "models/en_US-ryan-high.onnx",
        "length_scale": 1.05,
    },

    "Jarvis": {
        "prompt": (
            "You are rewriting a gamer's spoken team voice-chat into the voice of JARVIS (a calm, polite, dry-witted AI butler speaking on behalf of the user).\n\n"

            "PERSPECTIVE & SPEAKER DIRECTION (CRITICAL):\n"
            "- PRESERVE THE SPEAKER'S DIRECTION:\n"
            "  * If the user is asking/ordering a teammate ('Bucky, can you look at...'), rewrite it as a polite request TO THAT TEAMMATE ('Bucky, would you mind inspecting...').\n"
            "  * NEVER change a request to a teammate into an action the speaker is doing (Do NOT change 'can you look' to 'I will inspect').\n"
            "  * Maintain 'I' for the user and 'You/They' for teammates/enemies.\n\n"

            "GAMING & MARVEL RIVALS JARGON:\n"
            "- 'tank' = serve as the frontline / absorb incoming damage (NOT hold fire).\n"
            "- 'look at / watch' = monitor, inspect, or target.\n"
            "- 'play [character]' = assume the role of [character].\n"
            "- Keep character names (Rocket, Bucky, Penni, Magneto) exact.\n\n"

            "VOICE & FORMAT:\n"
            "- Tone: Calm, formal, understated, dry. No exclamation marks.\n"
            "- Output exactly ONE sentence.\n"
            "- Output ONLY the rewritten sentence.\n\n"

            "EXAMPLES:\n"
            "Input: Rocket, can you tank? I can play Bucky.\n"
            "Output: Rocket, are you able to hold the frontline? I am prepared to step in as Bucky.\n\n"

            "Input: Bucky, can you look at the penny nest please?\n"
            "Output: Bucky, would you kindly inspect the Penni nest when you have a moment?\n\n"

            "Input: Guys let's lock in.\n"
            "Output: Gentlemen, let us focus our efforts now.\n\n"

            "Input: My food is coming in four minutes.\n"
            "Output: My food is scheduled to arrive in four minutes.\n"
        ),
        "model_path": "models/en_GB-northern_english_male-medium.onnx",
        "length_scale": 1.02,
    },

    "Medieval Knight": {
        "prompt": (
            "Rewrite the user's spoken voice chat sentence into brief heroic medieval phrasing on behalf of the user.\n\n"

            "CRITICAL RULES:\n"
            "- Preserve requests to teammates as requests. If the speaker asks 'can you...', keep it directed at the teammate.\n"
            "- 'tank' = shield the group / draw enemy rage.\n"
            "- Keep character names intact.\n"
            "- Output exactly ONE sentence.\n"
            "- Output ONLY the rewritten sentence.\n\n"

            "EXAMPLES:\n"
            "Input: Rocket, can you tank? I can play Bucky.\n"
            "Output: Rocket, wilt thou bear the shield? I shall take the field as Bucky!\n\n"

            "Input: Bucky, can you look at the penny nest please?\n"
            "Output: Bucky, prithee keep watch over yonder Penni nest!\n"
        ),
        "model_path": "models/en_GB-alan-medium.onnx",
        "length_scale": 1.02,
    },

    "Anime Hero": {
        "prompt": (
            "Rewrite the user's spoken voice chat sentence as an energetic anime hero.\n\n"

            "CRITICAL RULES:\n"
            "- Preserve speaker direction (requests to teammates remain requests).\n"
            "- 'tank' = take the frontline / absorb damage.\n"
            "- Output exactly ONE sentence.\n"
            "- Output ONLY the rewritten sentence.\n\n"

            "EXAMPLES:\n"
            "Input: Rocket, can you tank? I can play Bucky.\n"
            "Output: Rocket, take the frontline! I'll cover us as Bucky!\n\n"

            "Input: Bucky, can you look at the penny nest please?\n"
            "Output: Bucky, take out that Penni nest right now!\n"
        ),
        "model_path": "models/en_US-joe-medium.onnx",
        "length_scale": 0.95,
    },
}


# UI compatibility
PERSONA_PROMPTS = {
    persona: cfg["prompt"]
    for persona, cfg in PERSONA_CONFIGS.items()
}


# ============================================================
# SETTINGS
# ============================================================

DEBUG = bool(os.environ.get("TTS_DEBUG"))

OLLAMA_URL = os.environ.get(
    "OLLAMA_URL",
    "http://localhost:11434/api/generate"
)

OLLAMA_MODEL = os.environ.get(
    "OLLAMA_MODEL",
    "llama3.2:3b"
)

OLLAMA_KEEP_ALIVE = os.environ.get(
    "OLLAMA_KEEP_ALIVE",
    "30m"
)

# Short timeout because this sits inside a real-time voice pipeline.
OLLAMA_TIMEOUT = float(
    os.environ.get("OLLAMA_TIMEOUT", "4.0")
)

# Number of consecutive failures before we stop trying every utterance.
MAX_FAILURES = 2


# ============================================================
# GENERATION BUDGET
# ============================================================

def _scaled_num_predict(text: str) -> int:
    """
    Ensure short inputs have enough token budget to finish full sentences.
    """
    word_count = max(1, len(text.split()))

    # Floor of 32 tokens guarantees room for subwords and complete punctuation
    return min(64, max(32, word_count * 3))


# ============================================================
# TEXT VALIDATION
# ============================================================

def _clean_output(text: str) -> str:
    """
    Remove common LLM formatting garbage.
    """

    if not text:
        return ""

    text = text.strip()

    # Remove surrounding quotes.
    text = text.strip("\"'`").strip()

    # Remove common accidental prefixes.
    prefixes = (
        "Output:",
        "output:",
        "Answer:",
        "answer:",
        "Response:",
        "response:",
        "Rewritten:",
        "rewritten:",
    )

    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()

    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def _looks_like_bad_output(original: str, transformed: str) -> bool:
    """
    Conservative safety check.

    If the LLM starts hallucinating, return the original STT text instead.
    """

    if not transformed:
        return True

    original_words = original.split()
    output_words = transformed.split()

    # Never allow a gigantic expansion.
    if len(output_words) > max(12, len(original_words) * 3):
        if DEBUG:
            print(
                f"[LLM Debug] Rejecting output: too long "
                f"({len(output_words)} words vs {len(original_words)} input)"
            )
        return True

    # Reject if the LLM hallucinated/mutated numbers from the input.
    orig_numbers = re.findall(r"\b\d+\b", original)
    trans_numbers = re.findall(r"\b\d+\b", transformed)
    if orig_numbers and orig_numbers != trans_numbers:
        if DEBUG:
            print(
                f"[LLM Debug] Rejecting output: mutated numbers "
                f"({orig_numbers} vs {trans_numbers})"
            )
        return True

    # Reject obvious prompt leakage.
    bad_markers = (
        "Input:",
        "Output:",
        "Explanation:",
        "Note:",
        "Here is",
        "Here's",
        "Sure,",
        "Certainly,",
        "As an AI",
    )

    lowered = transformed.lower()

    for marker in bad_markers:
        if marker.lower() in lowered:
            if DEBUG:
                print(
                    f"[LLM Debug] Rejecting output: prompt leakage "
                    f"({marker!r})"
                )
            return True

    # Reject outputs containing suspiciously long numeric sequences not in original.
    suspicious_numbers = re.findall(r"\b\d{5,}\b", transformed)

    if suspicious_numbers:
        original_long_numbers = re.findall(r"\b\d{5,}\b", original)

        if not original_long_numbers:
            if DEBUG:
                print(
                    f"[LLM Debug] Rejecting output: invented number "
                    f"{suspicious_numbers}"
                )
            return True

    # Reject repeated punctuation / obvious generation loops.
    if "!!!" in transformed or "???" in transformed:
        if len(transformed) > len(original) * 3:
            return True

    return False


# ============================================================
# LLM ENGINE
# ============================================================

class LLMPersonaEngine:

    def __init__(
        self,
        enabled: bool = True,
        persona: str = "Pirate",
        provider: str = "ollama",
        api_key: str = "",
    ):
        self.enabled = enabled
        self.persona = persona
        self.provider = provider
        self.api_key = api_key

        self.ollama_healthy = False
        self._failure_count = 0

        # Prevent concurrent LLM requests from piling up.
        self._busy = False

        if self.enabled and self.provider == "ollama":
            self._warm_up()

    # ========================================================
    # STARTUP / HEALTH
    # ========================================================

    def _warm_up(self):
        """
        Warm Ollama once at startup.
        """

        t_start = time.perf_counter()

        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": "Respond with: OK",
                    "stream": False,
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": {
                        "num_predict": 2,
                        "temperature": 0.0,
                    },
                },
                timeout=15.0,
            )

            response.raise_for_status()

            self.ollama_healthy = True
            self._failure_count = 0

            warm_ms = (
                time.perf_counter() - t_start
            ) * 1000

            print(
                f"[LLM] Ollama {OLLAMA_MODEL} warmed up "
                f"({warm_ms:.0f}ms). Persona engine ready."
            )

        except Exception as e:
            self.ollama_healthy = False

            print(
                f"[LLM] WARNING: Ollama not reachable at startup "
                f"({e})."
            )

            print(
                "[LLM] Persona mode will fall back to raw STT "
                "until Ollama becomes available."
            )

    def _mark_failure(self):
        self._failure_count += 1

        if self._failure_count >= MAX_FAILURES:
            self.ollama_healthy = False

            if DEBUG:
                print(
                    "[LLM Debug] Ollama marked unhealthy after "
                    f"{self._failure_count} failures."
                )

    def _mark_success(self):
        self._failure_count = 0
        self.ollama_healthy = True

    # ========================================================
    # SETTINGS
    # ========================================================

    def set_persona(self, persona: str):
        if persona in PERSONA_CONFIGS:
            self.persona = persona

            print(
                f"[LLM] Persona changed to: {self.persona}"
            )
        else:
            print(
                f"[LLM] WARNING: Unknown persona {persona!r}"
            )

    def set_enabled(self, enabled: bool):
        self.enabled = enabled

        print(
            f"[LLM] Persona engine enabled: {self.enabled}"
        )

        if (
            self.enabled
            and self.provider == "ollama"
            and not self.ollama_healthy
        ):
            self._warm_up()

    # ========================================================
    # SHORT-CIRCUIT LOGIC
    # ========================================================

    def _should_bypass_llm(self, text: str) -> bool:
        """
        Decide whether an LLM call is unnecessary.
        """

        cleaned = text.strip()

        if not cleaned:
            return True

        words = cleaned.split()

        if len(words) <= 1:
            return True

        return False

    # ========================================================
    # OLLAMA REQUEST
    # ========================================================

    def _transform_ollama(
        self,
        text: str,
        system_prompt: str,
        num_predict: int,
    ) -> str:

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "system": system_prompt,
                "prompt": (
                    "Rewrite ONLY this input sentence. Preserve intent, direct address, and subject/action targets.\n\n"
                    f"Input: {text}"
                ),
                "stream": False,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.8,
                    "repeat_penalty": 1.15,
                    "num_predict": num_predict,
                },

                "stop": [
                    "\n",
                    "\n\n",
                    "Input:",
                    "Output:",
                    "Explanation:",
                    "Note:",
                    "User:",
                    "Assistant:",
                ],
            },
            timeout=OLLAMA_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        return data.get("response", "").strip()

    # ========================================================
    # GROQ REQUEST
    # ========================================================

    def _transform_groq(
        self,
        text: str,
        system_prompt: str,
        num_predict: int,
    ) -> str:

        if not self.api_key:
            raise RuntimeError(
                "Groq provider selected but no API key was supplied."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "llama-3.1-8b-instant",

            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": (
                        "Rewrite ONLY this input sentence. Preserve intent, direct address, and subject/action targets.\n\n"
                        f"Input: {text}"
                    ),
                },
            ],

            "temperature": 0.1,
            "top_p": 0.8,
            "max_tokens": num_predict,

            "stop": [
                "\n",
                "Input:",
                "Output:",
                "Explanation:",
                "Note:",
            ],
        }

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=OLLAMA_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        return (
            data["choices"][0]["message"]["content"]
            .strip()
        )

    # ========================================================
    # MAIN TRANSFORM
    # ========================================================

    def transform(self, text: str) -> tuple[str, float]:
        """
        Transform STT text into the selected persona.

        Returns:
            (transformed_text, latency_ms)
        """

        original = text.strip()

        if not self.enabled or not original:
            return original, 0.0

        if self._should_bypass_llm(original):
            if DEBUG:
                print(
                    f"[LLM Debug] Bypassing LLM for short input: "
                    f"{original!r}"
                )

            return original, 0.0

        if self.provider not in ("ollama", "groq"):
            if DEBUG:
                print(
                    f"[LLM Debug] Unknown provider "
                    f"{self.provider!r}; using raw text."
                )

            return original, 0.0

        if (
            self.provider == "ollama"
            and not self.ollama_healthy
        ):
            if DEBUG:
                print(
                    "[LLM Debug] Ollama marked unhealthy; "
                    "skipping request."
                )

            return original, 0.0

        if self._busy:
            if DEBUG:
                print(
                    "[LLM Debug] LLM already busy; "
                    "returning raw STT."
                )

            return original, 0.0

        self._busy = True

        t_start = time.perf_counter()

        try:
            persona_cfg = PERSONA_CONFIGS.get(
                self.persona,
                PERSONA_CONFIGS["Pirate"],
            )

            system_prompt = persona_cfg["prompt"]

            num_predict = _scaled_num_predict(
                original
            )

            if self.provider == "ollama":

                raw = self._transform_ollama(
                    original,
                    system_prompt,
                    num_predict,
                )

            else:

                raw = self._transform_groq(
                    original,
                    system_prompt,
                    num_predict,
                )

            transformed = _clean_output(raw)

            if _looks_like_bad_output(
                original,
                transformed,
            ):
                if DEBUG:
                    print(
                        "[LLM Debug] Output failed validation. "
                        "Using raw STT text."
                    )

                transformed = original

            self._mark_success()

            llm_ms = (
                time.perf_counter() - t_start
            ) * 1000

            if DEBUG:
                print(
                    f"[LLM Debug] "
                    f"Persona={self.persona!r} "
                    f"num_predict={num_predict} "
                    f"latency={llm_ms:.0f}ms"
                )

                print(
                    f"[LLM Debug] "
                    f"Input={original!r}"
                )

                print(
                    f"[LLM Debug] "
                    f"Output={transformed!r}"
                )

            return transformed, llm_ms

        except requests.Timeout:
            self._mark_failure()

            print(
                "[LLM] Request timed out. "
                "Using raw STT text."
            )

            return original, (
                time.perf_counter() - t_start
            ) * 1000

        except requests.RequestException as e:
            self._mark_failure()

            print(
                f"[LLM] Network error: {e}. "
                "Using raw STT text."
            )

            return original, (
                time.perf_counter() - t_start
            ) * 1000

        except Exception as e:
            self._mark_failure()

            print(
                f"[LLM Error] {e}. "
                "Using raw STT text."
            )

            return original, (
                time.perf_counter() - t_start
            ) * 1000

        finally:
            self._busy = False