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

if __name__ == "__main__":
    unittest.main()
