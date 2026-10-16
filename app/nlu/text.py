"""Shared text normalisation for Hindi (Devanagari) and romanised Hindi."""
from __future__ import annotations

import re

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

NUMBER_WORDS = {
    # romanised
    "aadha": 0.5, "adha": 0.5, "ek": 1, "dedh": 1.5, "dhai": 2.5, "do": 2, "teen": 3, "tin": 3, "char": 4,
    "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "che": 6, "saat": 7, "sat": 7, "aath": 8, "nau": 9, "das": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    # Devanagari
    "आधा": 0.5, "एक": 1, "डेढ़": 1.5, "डेढ": 1.5, "ढाई": 2.5, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5,
    "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
}


def norm(text: str) -> str:
    t = (text or "").translate(_DEV_DIGITS).lower()
    t = t.replace("।", " ").replace("‍", "").replace("‌", "")
    return re.sub(r"\s+", " ", t).strip()


def has_any(text: str, words, whole: bool = False) -> bool:
    """Whole-word match for romanised words. Devanagari words match as stems (substring) unless whole=True."""
    for w in words:
        if re.search(r"[\u0900-\u097F]", w):
            if whole:
                if re.search(r"(?<![\u0900-\u097F])" + re.escape(w) + r"(?![\u0900-\u097F])", text):
                    return True
            elif w in text:
                return True
        elif re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", text):
            return True
    return False


def parse_number(tok: str):
    tok = tok.strip().lower()
    try:
        return float(tok)
    except ValueError:
        return NUMBER_WORDS.get(tok)
