"""Text segmentation into paragraphs, sentences, and words with PyMuPDF bounding rects."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import fitz


@dataclass
class TtsWord:
    """Represents an extracted word with its PDF bounding box and character offsets."""
    text: str
    rect: fitz.Rect
    word_index: int
    char_start: int
    char_end: int
    block_no: int = 0
    line_no: int = 0


@dataclass
class TtsSentence:
    """Represents a logically bounded sentence in a page."""
    page_index: int
    paragraph_index: int
    sentence_index: int
    text: str
    words: list[TtsWord]
    line_rects: list[fitz.Rect] = field(default_factory=list)


@dataclass
class TtsParagraph:
    """Represents a structural block containing one or more sentences."""
    page_index: int
    paragraph_index: int
    sentences: list[TtsSentence]


class TtsSegmenter:
    """Extracts, segments and maps PDF page text into structured paragraphs and sentences."""

    # Common abbreviations to avoid false sentence breaks
    ABBREVIATIONS = {
        "sr", "sra", "dr", "dra", "prof", "profa", "mr", "mrs", "ms", "vs", "etc",
        "fig", "art", "cap", "pág", "pag", "vol", "av", "ed"
    }

    @classmethod
    def segment_page(
        cls, page: fitz.Page, page_index: int
    ) -> tuple[list[TtsParagraph], list[TtsSentence]]:
        """Segment a PyMuPDF page into structured paragraphs and sentences with word coordinates."""
        import fitz

        raw_words = page.get_text("words")
        if not raw_words:
            return [], []

        # Sort words in natural reading order: block, line, word
        raw_words.sort(key=lambda w: (w[5], w[6], w[7]))

        # Group words by block_no
        blocks: dict[int, list[tuple]] = {}
        for w in raw_words:
            b_idx = w[5]
            if b_idx not in blocks:
                blocks[b_idx] = []
            blocks[b_idx].append(w)

        all_paragraphs: list[TtsParagraph] = []
        all_sentences: list[TtsSentence] = []
        global_sentence_idx = 0

        for block_idx in sorted(blocks.keys()):
            block_raw_words = blocks[block_idx]
            if not block_raw_words:
                continue

            if cls._is_margin_artifact(block_raw_words, page.rect):
                continue

            # Build full text for block while preserving word offsets
            block_words: list[TtsWord] = []
            block_text_parts: list[str] = []
            curr_pos = 0

            for w_idx, w in enumerate(block_raw_words):
                w_text = str(w[4]).strip()
                if not w_text:
                    continue

                line_no = w[6]
                rect = fitz.Rect(float(w[0]), float(w[1]), float(w[2]), float(w[3]))

                # Check if this word continues a hyphenated word from the previous line
                is_hyphen_continuation = False
                if block_words:
                    prev_w = block_words[-1]
                    if (
                        prev_w.text.endswith("-")
                        and len(prev_w.text) > 1
                        and prev_w.text[:-1].isalpha()
                        and line_no > prev_w.line_no
                        and w_text[0].islower()
                    ):
                        is_hyphen_continuation = True

                if is_hyphen_continuation:
                    prev_part = block_text_parts[-1]
                    if prev_part.endswith("-"):
                        block_text_parts[-1] = prev_part[:-1]
                        curr_pos -= 1
                        prev_w.char_end -= 1
                        prev_w.text = prev_w.text[:-1]

                    start = curr_pos
                    end = curr_pos + len(w_text)
                    block_text_parts.append(w_text)
                    curr_pos = end

                    block_words.append(
                        TtsWord(
                            text=w_text,
                            rect=rect,
                            word_index=w_idx,
                            char_start=start,
                            char_end=end,
                            block_no=w[5],
                            line_no=line_no,
                        )
                    )
                else:
                    if block_text_parts:
                        block_text_parts.append(" ")
                        curr_pos += 1

                    start = curr_pos
                    end = curr_pos + len(w_text)
                    block_text_parts.append(w_text)
                    curr_pos = end

                    block_words.append(
                        TtsWord(
                            text=w_text,
                            rect=rect,
                            word_index=w_idx,
                            char_start=start,
                            char_end=end,
                            block_no=w[5],
                            line_no=line_no,
                        )
                    )

            if not block_words:
                continue

            full_block_text = "".join(block_text_parts)
            sentence_spans = cls._split_into_sentence_spans(full_block_text)

            paragraph_sentences: list[TtsSentence] = []
            paragraph_idx = len(all_paragraphs)

            for s_start, s_end in sentence_spans:
                s_text = full_block_text[s_start:s_end].strip()
                if not s_text:
                    continue

                # Collect words that overlap or belong to this sentence span
                sent_words: list[TtsWord] = []
                for w in block_words:
                    if w.char_end > s_start and w.char_start < s_end:
                        # Re-index word locally to the sentence
                        local_w = TtsWord(
                            text=w.text,
                            rect=w.rect,
                            word_index=len(sent_words),
                            char_start=max(0, w.char_start - s_start),
                            char_end=max(0, w.char_end - s_start),
                            block_no=w.block_no,
                            line_no=w.line_no,
                        )
                        sent_words.append(local_w)

                if not sent_words:
                    continue

                # Merge adjacent words on the same line into contiguous line rects
                line_rects = cls._compute_line_rects(sent_words)

                sentence = TtsSentence(
                    page_index=page_index,
                    paragraph_index=paragraph_idx,
                    sentence_index=global_sentence_idx,
                    text=s_text,
                    words=sent_words,
                    line_rects=line_rects,
                )
                paragraph_sentences.append(sentence)
                all_sentences.append(sentence)
                global_sentence_idx += 1

            if paragraph_sentences:
                paragraph = TtsParagraph(
                    page_index=page_index,
                    paragraph_index=paragraph_idx,
                    sentences=paragraph_sentences,
                )
                all_paragraphs.append(paragraph)

        return all_paragraphs, all_sentences

    @classmethod
    def _split_into_sentence_spans(cls, text: str) -> list[tuple[int, int]]:
        """Split text into sentence start/end character offsets, respecting abbreviations and numbers."""
        spans: list[tuple[int, int]] = []
        if not text.strip():
            return spans

        # Pattern matches sentence-ending punctuation [.!?…] followed by quotes/closing braces
        pattern = re.compile(r'([.!?…]+["\')\]»]*)(?:\s+|$)')
        start = 0

        for match in pattern.finditer(text):
            end = match.end()
            punct_start = match.start(1)

            # Check if this is a decimal number (e.g. 3.14)
            if punct_start > 0 and punct_start < len(text) - 1:
                prev_char = text[punct_start - 1]
                next_char = text[punct_start + 1] if punct_start + 1 < len(text) else ""
                if prev_char.isdigit() and next_char.isdigit():
                    continue

            # Check if preceded by a known abbreviation
            word_before_match = re.search(r'([A-Za-zÀ-ÿ]+)\.$', text[start:punct_start + 1])
            if word_before_match:
                abbr = word_before_match.group(1).lower()
                if abbr in cls.ABBREVIATIONS:
                    continue

            # Valid sentence break found
            candidate = text[start:end].strip()
            if candidate:
                spans.append((start, end))
            start = end

        # Remainder of text if not terminated with sentence punctuation
        if start < len(text):
            candidate = text[start:].strip()
            if candidate:
                spans.append((start, len(text)))

        return spans if spans else [(0, len(text))]

    @classmethod
    def _compute_line_rects(cls, words: list[TtsWord]) -> list[fitz.Rect]:
        """Group words sharing the same line into unified rectangles for clean background highlights."""
        import fitz

        if not words:
            return []

        line_groups: dict[tuple[int, int], list[fitz.Rect]] = {}
        for w in words:
            key = (w.block_no, w.line_no)
            if key not in line_groups:
                line_groups[key] = []
            line_groups[key].append(w.rect)

        merged_rects: list[fitz.Rect] = []
        for key in sorted(line_groups.keys()):
            rects = line_groups[key]
            x0 = min(r.x0 for r in rects)
            y0 = min(r.y0 for r in rects)
            x1 = max(r.x1 for r in rects)
            y1 = max(r.y1 for r in rects)
            merged_rects.append(fitz.Rect(x0, y0, x1, y1))

        return merged_rects

    @classmethod
    def find_sentence_at_point(
        cls,
        sentences: list[TtsSentence],
        x: float,
        y: float,
        threshold: float = 8.0,
    ) -> tuple[TtsSentence, int] | None:
        """Find the sentence and word index matching coordinate (x, y)."""
        # 1. Exact match test
        for sentence in sentences:
            for word in sentence.words:
                r = word.rect
                if r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1:
                    return sentence, word.word_index

        # 2. Proximity fallback
        best_match = None
        min_dist2 = float("inf")
        th2 = threshold * threshold

        for sentence in sentences:
            for word in sentence.words:
                r = word.rect
                cx = (r.x0 + r.x1) / 2
                cy = (r.y0 + r.y1) / 2
                dx = x - cx
                dy = y - cy
                dist2 = dx * dx + dy * dy
                if dist2 < min_dist2 and dist2 <= th2:
                    min_dist2 = dist2
                    best_match = (sentence, word.word_index)

        return best_match

    @classmethod
    def _is_margin_artifact(cls, words: list[tuple], page_rect: fitz.Rect) -> bool:
        """Determines if a block is an isolated page number, header/footer artifact, or margin watermark."""
        if not words:
            return True

        min_x = min(w[0] for w in words)
        min_y = min(w[1] for w in words)
        max_x = max(w[2] for w in words)
        max_y = max(w[3] for w in words)

        block_text = "".join(str(w[4]).strip() for w in words).strip()
        if not block_text:
            return True

        h = page_rect.height
        w = page_rect.width

        # Top or bottom margin page numbers / short labels
        is_top = max_y <= h * 0.05
        is_bottom = min_y >= h * 0.95
        if is_top or is_bottom:
            cleaned = re.sub(r'[\s\-_/|•·]', '', block_text.lower())
            if cleaned.isdigit():
                return True
            if cleaned.startswith("pág") or cleaned.startswith("pag") or cleaned.startswith("page"):
                suffix = re.sub(r'^(pág|pag|page)\.?', '', cleaned)
                if suffix.isdigit():
                    return True

        # Extreme left or right vertical watermarks/slugs
        if (max_x <= 35 or min_x >= w - 35) and (max_y - min_y) > (max_x - min_x) * 4:
            return True

        return False


