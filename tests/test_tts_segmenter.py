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

if __name__ == "__main__":
    unittest.main()

