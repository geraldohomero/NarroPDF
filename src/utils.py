"""Utility functions for text normalization and language detection."""

from __future__ import annotations

import re


def normalize_text_for_tts(text: str) -> str:
    """Clean and normalize extracted PDF text for natural TTS output.

    Handles common PDF extraction artifacts like broken hyphenation,
    control characters, and inconsistent whitespace.
    """
    if not text:
        return ""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove control characters common in PDF extraction.
    normalized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", normalized)

    # Join hyphenated line breaks: "exem-\nplo" → "exemplo".
    normalized = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", normalized)

    # Preserve paragraphs: single newlines become spaces, double newlines kept.
    normalized = re.sub(r"(?<!\n)\n(?!\n)", " ", normalized)
    normalized = re.sub(r"\n{2,}", "\n\n", normalized)

    # Fix spaces before punctuation and collapse excess whitespace.
    normalized = re.sub(r"\s+([,.;:!?])", r"\1", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized)

    # Fix broken abbreviations: "n ." → "n."
    normalized = re.sub(
        r"\b([A-Za-zÀ-ÖØ-öø-ÿ])\s+\.\s*", r"\1. ", normalized
    )

    return normalized.strip()


def detect_language_from_text(sample: str) -> str:
    """Detect document language from a text sample using heuristics.

    Returns the language code (e.g., 'pt-BR', 'en-US', 'es-ES').
    Defaults to 'pt-BR' when uncertain.
    """
    lower_sample = sample.lower()

    # English markers — checked first because English loan words appear in
    # many languages, but high-frequency function words are distinctive.
    en_markers = r"\b(the|and|with|from|this|that|have|been|will|which)\b"
    en_count = len(re.findall(en_markers, lower_sample))

    # Spanish markers
    es_markers = r"\b(el|los|las|que|con|una|por|para|como|pero)\b"
    es_count = len(re.findall(es_markers, lower_sample))

    # Portuguese markers (includes words distinct from Spanish)
    pt_markers = r"\b(não|são|também|para|como|ainda|mais|pode|sobre|muito)\b"
    pt_count = len(re.findall(pt_markers, lower_sample))

    scores = {"en-US": en_count, "es-ES": es_count, "pt-BR": pt_count}
    best = max(scores, key=scores.get)

    # Only trust the result if there's a meaningful signal.
    if scores[best] < 3:
        return "pt-BR"

    return best
