"""
Tests for PDF extraction and analysis functionality.

Updated tests for the refactored PDFExtractor class that includes
the original pdf_analyzer.py functionality.
"""

import json
import tempfile
import unittest
from unittest.mock import Mock, patch, mock_open
from pathlib import Path

from src.pdf_knowledge_extractor.extractor import PDFExtractor


class TestPDFExtractor(unittest.TestCase):
    """Test cases for PDFExtractor class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            'analysis': {
                'max_size_mb': 5.0,
                'max_pages': 50
            },
            'progress': {
                'enabled': False  # Disable progress bar for tests
            }
        }
        
    def test_init_with_default_config(self):
        """Test initialization with default configuration."""
        with patch('src.pdf_knowledge_extractor.extractor.PyPDF2'):
            extractor = PDFExtractor()
            self.assertEqual(extractor.config, {})
            self.assertEqual(extractor.max_size_mb, 10.0)
            self.assertEqual(extractor.max_pages, 100)
    
    def test_init_with_custom_config(self):
        """Test initialization with custom configuration."""
        with patch('src.pdf_knowledge_extractor.extractor.PyPDF2'):
            extractor = PDFExtractor(self.config)
            self.assertEqual(extractor.config, self.config)
            self.assertEqual(extractor.max_size_mb, 5.0)
            self.assertEqual(extractor.max_pages, 50)
    
    def test_init_without_pypdf2(self):
        """Test initialization fails without PyPDF2."""
        with patch('src.pdf_knowledge_extractor.extractor.PyPDF2', None):
            with self.assertRaises(ImportError):
                PDFExtractor()
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_get_file_size(self, mock_pypdf2):
        """Test file size calculation."""
        extractor = PDFExtractor()
        
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"test content")
            tmp_path = Path(tmp.name)
        
        try:
            size = extractor.get_file_size(tmp_path)
            self.assertEqual(size, 12)  # Length of "test content"
        finally:
            tmp_path.unlink()
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    @patch('builtins.open', mock_open())
    def test_get_page_count_success(self, mock_pypdf2):
        """Test successful page count extraction."""
        # Mock PyPDF2.PdfReader
        mock_reader = Mock()
        mock_reader.pages = [Mock(), Mock(), Mock()]  # 3 pages
        mock_pypdf2.PdfReader.return_value = mock_reader
        
        extractor = PDFExtractor()
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        try:
            page_count = extractor.get_page_count(tmp_path)
            self.assertEqual(page_count, 3)
        finally:
            tmp_path.unlink()
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    @patch('builtins.open', side_effect=Exception("File error"))
    def test_get_page_count_failure(self, mock_open, mock_pypdf2):
        """Test page count extraction failure."""
        extractor = PDFExtractor()
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        try:
            with self.assertRaises(Exception):
                extractor.get_page_count(tmp_path)
        finally:
            tmp_path.unlink()
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_analyze_file_processable(self, mock_pypdf2):
        """Test analysis of a file that's processable."""
        # Mock PyPDF2.PdfReader
        mock_reader = Mock()
        mock_reader.pages = [Mock()]  # 1 page
        mock_pypdf2.PdfReader.return_value = mock_reader
        
        extractor = PDFExtractor(self.config)
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(b"small content")  # Small file
            tmp_path = Path(tmp.name)
        
        try:
            with patch('builtins.open', mock_open()):
                result = extractor.analyze_file(tmp_path)
            
            self.assertIn('path', result)
            self.assertIn('filename', result)
            self.assertIn('size_bytes', result)
            self.assertIn('size_mb', result)
            self.assertIn('page_count', result)
            self.assertFalse(result['exceeds_size_limit'])
            self.assertFalse(result['exceeds_page_limit'])
            
            # Should be added to processable list
            self.assertEqual(len(extractor.results['processable']), 1)
            self.assertEqual(len(extractor.results['special_handling']), 0)
            
        finally:
            tmp_path.unlink()
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_analyze_file_special_handling(self, mock_pypdf2):
        """Test analysis of a file that needs special handling."""
        # Mock PyPDF2.PdfReader with many pages
        mock_reader = Mock()
        mock_reader.pages = [Mock() for _ in range(100)]  # 100 pages (exceeds limit)
        mock_pypdf2.PdfReader.return_value = mock_reader
        
        extractor = PDFExtractor(self.config)
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            # Create a large file (exceeds size limit)
            tmp.write(b"x" * (6 * 1024 * 1024))  # 6MB (exceeds 5MB limit)
            tmp_path = Path(tmp.name)
        
        try:
            with patch('builtins.open', mock_open()):
                result = extractor.analyze_file(tmp_path)
            
            self.assertTrue(result['exceeds_size_limit'])
            self.assertTrue(result['exceeds_page_limit'])
            self.assertIn('reason', result)
            self.assertEqual(len(result['reason']), 2)  # Both size and page limits exceeded
            
            # Should be added to special handling list
            self.assertEqual(len(extractor.results['processable']), 0)
            self.assertEqual(len(extractor.results['special_handling']), 1)
            
        finally:
            tmp_path.unlink()
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_analyze_file_error(self, mock_pypdf2):
        """Test analysis of a file that causes an error."""
        mock_pypdf2.PdfReader.side_effect = Exception("PDF reading error")
        
        extractor = PDFExtractor(self.config)
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        try:
            with patch('builtins.open', mock_open()):
                result = extractor.analyze_file(tmp_path)
            
            self.assertIn('error', result)
            self.assertIn('error_type', result)
            
            # Should be added to errors list
            self.assertEqual(len(extractor.results['errors']), 1)
            
        finally:
            tmp_path.unlink()
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_extract_text(self, mock_pypdf2):
        """Test text extraction from PDF."""
        # Mock PyPDF2.PdfReader
        mock_page1 = Mock()
        mock_page1.extract_text.return_value = "Page 1 content"
        mock_page2 = Mock()
        mock_page2.extract_text.return_value = "Page 2 content"
        
        mock_reader = Mock()
        mock_reader.pages = [mock_page1, mock_page2]
        mock_pypdf2.PdfReader.return_value = mock_reader
        
        extractor = PDFExtractor()
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        
        try:
            with patch('builtins.open', mock_open()):
                text = extractor.extract_text(tmp_path)
            
            self.assertEqual(text, "Page 1 content\nPage 2 content")
            
        finally:
            tmp_path.unlink()
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_resume_functionality(self, mock_pypdf2):
        """Test resume capability."""
        extractor = PDFExtractor(self.config)
        
        # Create a mock resume file
        resume_data = {
            'processed_files': ['/path/to/file1.pdf', '/path/to/file2.pdf'],
            'last_updated': '/some/path'
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(resume_data, tmp)
            resume_file = Path(tmp.name)
        
        try:
            extractor.setup_resume(resume_file)
            
            self.assertEqual(len(extractor.processed_files), 2)
            self.assertIn('/path/to/file1.pdf', extractor.processed_files)
            self.assertIn('/path/to/file2.pdf', extractor.processed_files)
            
        finally:
            resume_file.unlink()
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_save_results(self, mock_pypdf2):
        """Test saving analysis results."""
        extractor = PDFExtractor(self.config)
        
        # Add some mock results
        extractor.results['processable'] = [{'path': 'test1.pdf', 'size_mb': 1.0}]
        extractor.results['special_handling'] = [{'path': 'test2.pdf', 'size_mb': 20.0}]
        extractor.results['errors'] = [{'path': 'test3.pdf', 'error': 'Failed'}]
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            saved_files = extractor.save_results(tmp_dir)
            
            # Check that all expected files were created
            self.assertIn('processable', saved_files)
            self.assertIn('special_handling', saved_files)
            self.assertIn('errors', saved_files)
            self.assertIn('complete', saved_files)
            
            # Check files exist
            for file_path in saved_files.values():
                self.assertTrue(file_path.exists())
            
            # Verify content of processable file
            with open(saved_files['processable'], 'r') as f:
                data = json.load(f)
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]['path'], 'test1.pdf')
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_get_summary(self, mock_pypdf2):
        """Test summary statistics generation."""
        extractor = PDFExtractor(self.config)
        
        # Set up mock results
        extractor.results['processable'] = [{'path': 'test1.pdf'}]
        extractor.results['special_handling'] = [{'path': 'test2.pdf'}]
        extractor.results['errors'] = [{'path': 'test3.pdf'}]
        extractor.results['metadata'] = {
            'total_analyzed': 3,
            'total_size_bytes': 1024 * 1024,  # 1MB
            'total_pages': 15,
            'max_size_mb': 5.0,
            'max_pages': 50
        }
        
        summary = extractor.get_summary()
        
        self.assertEqual(summary['total_files'], 3)
        self.assertEqual(summary['processable_files'], 1)
        self.assertEqual(summary['special_handling_files'], 1)
        self.assertEqual(summary['error_files'], 1)
        self.assertEqual(summary['total_size_mb'], 1.0)
        self.assertEqual(summary['total_pages'], 15)
        self.assertEqual(summary['average_pages_per_file'], 5.0)


class TestPDFExtractorIntegration(unittest.TestCase):
    """Integration tests for PDFExtractor with file system operations."""
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_analyze_directory_no_files(self, mock_pypdf2):
        """Test directory analysis with no PDF files."""
        extractor = PDFExtractor({'progress': {'enabled': False}})
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            results = extractor.analyze_directory(tmp_dir)
            
            self.assertEqual(len(results['processable']), 0)
            self.assertEqual(len(results['special_handling']), 0)
            self.assertEqual(len(results['errors']), 0)
    
    @patch('src.pdf_knowledge_extractor.extractor.PyPDF2')
    def test_analyze_directory_nonexistent(self, mock_pypdf2):
        """Test directory analysis with nonexistent directory."""
        extractor = PDFExtractor()
        
        with self.assertRaises(FileNotFoundError):
            extractor.analyze_directory("/nonexistent/path")


if __name__ == "__main__":
    unittest.main()