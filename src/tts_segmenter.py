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

    HYPHEN_CHARS = ("-", "\u00ad", "\u2010", "\u2011")
    TERMINAL_PUNCT = (".", "!", "?", "…", ":")
    CLOSING_WRAPPERS = "\"'”’)]»"
    NO_SPACE_BEFORE = {",", ".", ";", ":", "!", "?", "…", ")", "]", "»", "%"}
    NO_SPACE_AFTER = {"(", "[", "«", "“", "‘"}

    @classmethod
    def _ends_with_terminal_punct(cls, text: str) -> bool:
        stripped = text.strip().rstrip(cls.CLOSING_WRAPPERS)
        if not stripped:
            return False
        if not stripped.endswith(cls.TERMINAL_PUNCT):
            return False
        if stripped.endswith("."):
            m = re.search(r"([A-Za-zÀ-ÿ]+)\.$", stripped)
            if m and m.group(1).lower() in cls.ABBREVIATIONS:
                return False
        return True

    @classmethod
    def _should_merge_blocks(cls, prev_block: list[tuple], next_block: list[tuple]) -> bool:
        """Determine whether *next_block* is a continuation of the same paragraph/sentence as *prev_block*."""
        if not prev_block or not next_block:
            return False

        last_text = str(prev_block[-1][4]).strip()
        first_text = str(next_block[0][4]).strip()
        if not last_text or not first_text:
            return False

        # Respect genuine sentence/paragraph endings
        if cls._ends_with_terminal_punct(last_text):
            return False

        # Compute line-height and geometry metrics
        prev_last_line_no = prev_block[-1][6]
        prev_last_block_no = prev_block[-1][5]
        prev_last_line = [
            w for w in prev_block if w[5] == prev_last_block_no and w[6] == prev_last_line_no
        ] or [prev_block[-1]]

        next_first_line_no = next_block[0][6]
        next_first_block_no = next_block[0][5]
        next_first_line = [
            w for w in next_block if w[5] == next_first_block_no and w[6] == next_first_line_no
        ] or [next_block[0]]

        prev_last_y0 = min(float(w[1]) for w in prev_last_line)
        prev_last_y1 = max(float(w[3]) for w in prev_last_line)
        prev_line_h = max(6.0, prev_last_y1 - prev_last_y0)

        next_first_y0 = min(float(w[1]) for w in next_first_line)
        next_first_y1 = max(float(w[3]) for w in next_first_line)
        next_line_h = max(6.0, next_first_y1 - next_first_y0)

        # Protect headings / different font sizes from merging into body text
        if abs(prev_line_h - next_line_h) > max(prev_line_h, next_line_h) * 0.35:
            return False

        # Strong lexical continuation signals (comma, hyphenation, lowercase start, closing punct)
        if last_text.endswith(cls.HYPHEN_CHARS) and first_text[0].islower():
            return True
        if last_text.endswith((",", ";", "(", "[", "«", "—", "–")):
            return True
        if first_text[0].islower() or first_text[0] in cls.NO_SPACE_BEFORE:
            return True

        # Visual same-column line continuation (e.g. wrapped line continuing with a proper noun)
        prev_min_x = min(float(w[0]) for w in prev_block)
        prev_max_x = max(float(w[2]) for w in prev_block)
        next_min_x = min(float(w[0]) for w in next_block)
        next_max_x = max(float(w[2]) for w in next_block)

        horiz_overlap = min(prev_max_x, next_max_x) > max(prev_min_x, next_min_x)
        avg_line_h = (prev_line_h + next_line_h) / 2.0
        vertical_gap = next_first_y0 - prev_last_y1
        vert_adjacent = (-avg_line_h * 0.5) <= vertical_gap <= (avg_line_h * 1.6)
        not_short_heading = len(prev_block) >= 4 or (prev_max_x - prev_min_x) >= 180.0

        return horiz_overlap and vert_adjacent and not_short_heading

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

        # Group words by block_no and filter margin artifacts
        blocks: dict[int, list[tuple]] = {}
        for w in raw_words:
            b_idx = w[5]
            if b_idx not in blocks:
                blocks[b_idx] = []
            blocks[b_idx].append(w)

        filtered_blocks: list[list[tuple]] = []
        for block_idx in sorted(blocks.keys()):
            block_raw_words = blocks[block_idx]
            if not block_raw_words or cls._is_margin_artifact(block_raw_words, page.rect):
                continue
            filtered_blocks.append(block_raw_words)

        # Merge consecutive blocks that belong to the same sentence/paragraph
        merged_blocks: list[list[tuple]] = []
        for block in filtered_blocks:
            if merged_blocks and cls._should_merge_blocks(merged_blocks[-1], block):
                merged_blocks[-1].extend(block)
            else:
                merged_blocks.append(list(block))

        all_paragraphs: list[TtsParagraph] = []
        all_sentences: list[TtsSentence] = []
        global_sentence_idx = 0

        for block_raw_words in merged_blocks:
            if not block_raw_words:
                continue

            # Build full text for block while preserving word offsets
            block_words: list[TtsWord] = []
            block_text_parts: list[str] = []
            curr_pos = 0

            for w_idx, w in enumerate(block_raw_words):
                w_text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", str(w[4])).strip()
                if not w_text:
                    continue

                line_no = w[6]
                rect = fitz.Rect(float(w[0]), float(w[1]), float(w[2]), float(w[3]))

                # Check if this word continues a hyphenated word from the previous line/block
                is_hyphen_continuation = False
                if block_words:
                    prev_w = block_words[-1]
                    is_new_line = (
                        w[5] != prev_w.block_no
                        or line_no > prev_w.line_no
                        or rect.y0 >= (prev_w.rect.y1 - 2.0)
                    )
                    if (
                        prev_w.text.endswith(cls.HYPHEN_CHARS)
                        and len(prev_w.text) > 1
                        and prev_w.text[:-1].isalpha()
                        and is_new_line
                        and w_text[0].islower()
                    ):
                        is_hyphen_continuation = True

                # Remove any stray soft hyphens inside the current token
                if "\u00ad" in w_text and not w_text.endswith("\u00ad"):
                    w_text = w_text.replace("\u00ad", "")

                if is_hyphen_continuation:
                    prev_part = block_text_parts[-1]
                    if prev_part.endswith(cls.HYPHEN_CHARS):
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
                        prev_w = block_words[-1]
                        attach_directly = (
                            all(ch in cls.NO_SPACE_BEFORE for ch in w_text)
                            or (prev_w.text and prev_w.text[-1] in cls.NO_SPACE_AFTER)
                        )
                        if not attach_directly:
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


