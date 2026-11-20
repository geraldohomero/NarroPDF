import unittest
import fitz
import os
import sys

# Ensure project root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.tts_segmenter import TtsSegmenter, TtsWord, TtsSentence, TtsParagraph

class TestTtsSegmenter(unittest.TestCase):
    def test_segment_page_sentences(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), "Primeira frase aqui. Segunda frase agora!")
        paragraphs, sentences = TtsSegmenter.segment_page(page, 0)
        
        self.assertEqual(len(sentences), 2)
        self.assertEqual(sentences[0].text, "Primeira frase aqui.")
        self.assertEqual(sentences[1].text, "Segunda frase agora!")
        self.assertEqual(len(sentences[0].words), 3)
        self.assertEqual(len(sentences[1].words), 3)
        self.assertTrue(len(sentences[0].line_rects) >= 1)
        self.assertIsInstance(sentences[0].words[0].rect, fitz.Rect)

    def test_sentence_with_special_punctuation(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 72), "O valor é 3.14 para o Sr. Silva... Será que funciona? Sim!")
        paragraphs, sentences = TtsSegmenter.segment_page(page, 0)
        
        self.assertTrue(len(sentences) >= 2)
        full_text = " ".join(s.text for s in sentences)
        self.assertIn("3.14", full_text)
        self.assertIn("Será que funciona?", full_text)
        self.assertIn("Sim!", full_text)

    def test_find_sentence_at_point(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((100, 100), "Palavra de teste.")
        _, sentences = TtsSegmenter.segment_page(page, 0)
        self.assertEqual(len(sentences), 1)
        
        first_word_rect = sentences[0].words[0].rect
        mid_x = (first_word_rect.x0 + first_word_rect.x1) / 2
        mid_y = (first_word_rect.y0 + first_word_rect.y1) / 2
        
        result = TtsSegmenter.find_sentence_at_point(sentences, mid_x, mid_y)
        self.assertIsNotNone(result)
        sent, word_idx = result
        self.assertEqual(sent.sentence_index, 0)
        self.assertEqual(word_idx, 0)

    def test_empty_page(self):
        doc = fitz.open()
        page = doc.new_page()
        paragraphs, sentences = TtsSegmenter.segment_page(page, 0)
        self.assertEqual(len(paragraphs), 0)
        self.assertEqual(len(sentences), 0)

    def test_hyphenated_words_across_lines_are_joined_in_sentence_text(self):
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        page.insert_text((72, 100), "Algo-")
        page.insert_text((72, 115), "rithmic recommendation works.")
        _, sentences = TtsSegmenter.segment_page(page, 0)
        self.assertEqual(len(sentences), 1)
        self.assertIn("Algorithmic", sentences[0].text)
        self.assertNotIn("Algo- rithmic", sentences[0].text)

    def test_page_number_and_margin_artifacts_filtered(self):
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        # Top header number at y=20 (< 28)
        page.insert_text((250, 20), "42")
        # Body text
        page.insert_text((72, 200), "O conteúdo principal desta página.")
        # Bottom footer number at y=685 (> 672)
        page.insert_text((250, 685), "43")
        _, sentences = TtsSegmenter.segment_page(page, 0)
        full_text = " ".join(s.text for s in sentences)
        self.assertIn("O conteúdo principal", full_text)
        self.assertNotIn("42", full_text)
        self.assertNotIn("43", full_text)

    def test_split_blocks_mid_sentence_are_merged_into_single_sentence(self):
        from unittest.mock import MagicMock

        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 500, 800)
        # Simulate PyMuPDF splitting consecutive lines of the same sentence into separate block_nos
        page.get_text.return_value = [
            (72, 100, 100, 114, "novo", 0, 0, 0),
            (105, 100, 150, 114, "estágio", 0, 0, 1),
            (155, 100, 170, 114, "do", 0, 0, 2),
            (175, 100, 220, 114, "capital", 0, 0, 3),
            (225, 100, 300, 114, "globalizado,", 0, 0, 4),
            (72, 120, 95, 134, "mas", 1, 0, 0),
            (100, 120, 145, 134, "também", 1, 0, 1),
            (150, 120, 185, 134, "como", 1, 0, 2),
            (190, 120, 270, 134, "configurações", 1, 0, 3),
            (275, 120, 295, 134, "que", 1, 0, 4),
            (300, 120, 355, 134, "permitem", 1, 0, 5),
            (360, 120, 375, 134, "ao", 1, 0, 6),
            (380, 120, 415, 134, "crítico", 1, 0, 7),
            (420, 120, 435, 134, "de", 1, 0, 8),
            (440, 120, 475, 134, "cultura", 1, 0, 9),
            (478, 120, 535, 134, "destrinchar", 1, 0, 10),
            (72, 140, 88, 154, "os", 2, 0, 0),
            (92, 140, 140, 154, "germes.", 2, 0, 1),
        ]

        paragraphs, sentences = TtsSegmenter.segment_page(page, 0)
        self.assertEqual(len(paragraphs), 1)
        self.assertEqual(len(sentences), 1)
        self.assertEqual(
            sentences[0].text,
            "novo estágio do capital globalizado, mas também como configurações que permitem ao crítico de cultura destrinchar os germes.",
        )
        self.assertEqual(len(sentences[0].line_rects), 3)

    def test_hyphenation_across_split_blocks_is_joined(self):
        from unittest.mock import MagicMock

        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 500, 800)
        page.get_text.return_value = [
            (72, 100, 120, 114, "destrin-", 0, 0, 0),
            (72, 120, 100, 134, "char", 1, 0, 0),
            (105, 120, 120, 134, "os", 1, 0, 1),
            (125, 120, 180, 134, "germes.", 1, 0, 2),
        ]

        _, sentences = TtsSegmenter.segment_page(page, 0)
        self.assertEqual(len(sentences), 1)
        self.assertEqual(sentences[0].text, "destrinchar os germes.")

    def test_detached_punctuation_has_no_spurious_spaces(self):
        from unittest.mock import MagicMock

        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 500, 800)
        page.get_text.return_value = [
            (72, 100, 150, 114, "globalizado", 0, 0, 0),
            (155, 100, 160, 114, ",", 0, 0, 1),
            (168, 100, 190, 114, "mas", 0, 0, 2),
            (195, 100, 200, 114, "(", 0, 0, 3),
            (202, 100, 240, 114, "texto", 0, 0, 4),
            (242, 100, 247, 114, ")", 0, 0, 5),
            (249, 100, 253, 114, ".", 0, 0, 6),
        ]

        _, sentences = TtsSegmenter.segment_page(page, 0)
        self.assertEqual(len(sentences), 1)
        self.assertEqual(sentences[0].text, "globalizado, mas (texto).")

    def test_real_paragraphs_and_headings_are_not_merged(self):
        from unittest.mock import MagicMock

        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 500, 800)
        page.get_text.return_value = [
            # Large-font heading (24pt tall)
            (72, 80, 180, 104, "Capítulo", 0, 0, 0),
            (186, 80, 210, 104, "1", 0, 0, 1),
            # Body paragraph 1 (12pt tall) ending with period
            (72, 130, 130, 142, "Primeiro", 1, 0, 0),
            (135, 130, 210, 142, "parágrafo.", 1, 0, 1),
            # Body paragraph 2 (12pt tall)
            (72, 165, 130, 177, "Segundo", 2, 0, 0),
            (135, 165, 210, 177, "parágrafo.", 2, 0, 1),
        ]

        paragraphs, sentences = TtsSegmenter.segment_page(page, 0)
        self.assertEqual(len(paragraphs), 3)
        self.assertEqual(len(sentences), 3)
        self.assertEqual(sentences[0].text, "Capítulo 1")
        self.assertEqual(sentences[1].text, "Primeiro parágrafo.")
        self.assertEqual(sentences[2].text, "Segundo parágrafo.")

    def test_wrapped_line_continuing_with_proper_noun_merges(self):
        from unittest.mock import MagicMock

        page = MagicMock()
        page.rect = fitz.Rect(0, 0, 500, 800)
        page.get_text.return_value = [
            (72, 100, 90, 114, "A", 0, 0, 0),
            (95, 100, 145, 114, "análise", 0, 0, 1),
            (150, 100, 200, 114, "crítica", 0, 0, 2),
            (205, 100, 225, 114, "da", 0, 0, 3),
            (230, 100, 290, 114, "cultura", 0, 0, 4),
            (295, 100, 320, 114, "no", 0, 0, 5),
            (72, 120, 120, 134, "Brasil", 1, 0, 0),
            (125, 120, 175, 134, "avança.", 1, 0, 1),
        ]

        paragraphs, sentences = TtsSegmenter.segment_page(page, 0)
        self.assertEqual(len(paragraphs), 1)
        self.assertEqual(len(sentences), 1)
        self.assertEqual(sentences[0].text, "A análise crítica da cultura no Brasil avança.")

if __name__ == "__main__":
    unittest.main()

