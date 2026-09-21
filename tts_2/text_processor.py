class TextProcessor:
    @staticmethod
    def process(text: str, mode: str = "CLEANUP") -> str:
        if mode == "OFF" or not text:
            return text
        if mode == "CLEANUP":
            cleaned = text.strip()
            return cleaned[0].upper() + cleaned[1:] if cleaned else cleaned
        return text