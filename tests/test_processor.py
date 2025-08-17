"""
Tests for text processing functionality.
"""

import unittest

from src.pdf_knowledge_extractor.processor import TextProcessor


class TestTextProcessor(unittest.TestCase):
    """Test cases for TextProcessor class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.processor = TextProcessor()
        
    def test_init_with_default_config(self):
        """Test initialization with default configuration."""
        processor = TextProcessor()
        self.assertEqual(processor.config, {})
        
    def test_clean_text_basic(self):
        """Test basic text cleaning."""
        text = "  Hello    world  \n\n  "
        cleaned = self.processor.clean_text(text)
        self.assertEqual(cleaned, "Hello world")
        
    def test_clean_text_empty(self):
        """Test cleaning empty text."""
        self.assertEqual(self.processor.clean_text(""), "")
        self.assertEqual(self.processor.clean_text(None), "")
        
    def test_clean_text_with_special_chars_removal(self):
        """Test text cleaning with special character removal."""
        config = {"remove_special_chars": True}
        processor = TextProcessor(config)
        
        text = "Hello, world! How are you?"
        cleaned = processor.clean_text(text)
        self.assertEqual(cleaned, "Hello world How are you")
        
    def test_split_into_chunks_basic(self):
        """Test basic text chunking."""
        text = "a" * 2500  # 2500 characters
        chunks = self.processor.split_into_chunks(text, chunk_size=1000, overlap=100)
        
        self.assertTrue(len(chunks) > 1)
        self.assertTrue(all(len(chunk) <= 1000 for chunk in chunks))
        
    def test_split_into_chunks_empty_text(self):
        """Test chunking with empty text."""
        chunks = self.processor.split_into_chunks("")
        self.assertEqual(chunks, [])
        
    def test_split_into_chunks_sentence_boundary(self):
        """Test chunking respects sentence boundaries."""
        text = "First sentence. " * 100 + "Last sentence."
        chunks = self.processor.split_into_chunks(text, chunk_size=500)
        
        # Check that chunks end with periods when possible
        for chunk in chunks[:-1]:  # All but last chunk
            if len(chunk) > 400:  # Only check reasonably long chunks
                self.assertTrue(chunk.rstrip().endswith('.'))
                
    def test_extract_keywords_not_implemented(self):
        """Test that extract_keywords raises NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            self.processor.extract_keywords("sample text")
            
    def test_summarize_not_implemented(self):
        """Test that summarize raises NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            self.processor.summarize("sample text")


if __name__ == "__main__":
    unittest.main()