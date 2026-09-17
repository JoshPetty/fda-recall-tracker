import re

ABBREVIATIONS = {
    "chz": "cheese", "mc": "macaroni", "mac": "macaroni",
    "w": "with", "wo": "without", "bttr": "butter",
    "pnut": "peanut", "choc": "chocolate", "strwbry": "strawberry",
    "veg": "vegetable", "org": "organic", "orig": "original",
    "ct": "count", "pkg": "package", "btl": "bottle",
}

UNITS = re.compile(r"\b\d+(?:\.\d+)?\s?(?:oz|lb|lbs|g|kg|ml|l|ct|pk)\b")
PUNCT = re.compile(r"[^\w\s]")

def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = PUNCT.sub(" ", text.lower())
    text = UNITS.sub(" ", text)
    return " ".join(ABBREVIATIONS.get(word, word) for word in text.split())