"""
Tests for Claude integration functionality.
"""

import json
import tempfile
import unittest
from unittest.mock import Mock, patch, mock_open
from pathlib import Path

from src.pdf_knowledge_extractor.claude_integration import (
    ClaudeIntegration, DocumentContext, ProcessingStatus, BatchProgress
)


class TestDocumentContext(unittest.TestCase):
    """Test cases for DocumentContext dataclass."""
    
    def test_document_context_creation(self):
        """Test DocumentContext creation with defaults."""
        context = DocumentContext(
            file_path="/test/doc.pdf",
            filename="doc.pdf",
            size_mb=5.0,
            page_count=10,
            text_length=1000,
            estimated_tokens=250
        )
        
        self.assertEqual(context.file_path, "/test/doc.pdf")
        self.assertEqual(context.filename, "doc.pdf")
        self.assertEqual(context.processing_status, ProcessingStatus.PENDING)
        self.assertEqual(context.retry_count, 0)
        self.assertEqual(context.related_documents, [])


class TestBatchProgress(unittest.TestCase):
    """Test cases for BatchProgress dataclass."""
    
    def test_completion_percentage(self):
        """Test completion percentage calculation."""
        progress = BatchProgress(
            total_documents=100,
            processed_documents=25,
            failed_documents=5,
            skipped_documents=0,
            current_batch=1,
            total_batches=10,
            start_time="2024-01-01T00:00:00",
            last_update="2024-01-01T01:00:00"
        )
        
        self.assertEqual(progress.completion_percentage, 25.0)
        
        # Test with zero total documents
        progress.total_documents = 0
        self.assertEqual(progress.completion_percentage, 0.0)


class TestClaudeIntegration(unittest.TestCase):
    """Test cases for ClaudeIntegration class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.config = {
            'claude': {
                'batch_size': 3,
                'max_retries': 2,
                'context_window_size': 100000
            },
            'progress': {
                'enabled': False
            }
        }
    
    def test_initialization(self):
        """Test ClaudeIntegration initialization."""
        claude_integration = ClaudeIntegration(self.config)
        
        self.assertEqual(claude_integration.batch_size, 3)
        self.assertEqual(claude_integration.max_retries, 2)
        self.assertEqual(claude_integration.context_window_size, 100000)
        self.assertEqual(claude_integration.output_format, 'markdown')
    
    def test_initialization_with_defaults(self):
        """Test initialization with default configuration."""
        claude_integration = ClaudeIntegration()
        
        self.assertEqual(claude_integration.batch_size, 5)
        self.assertEqual(claude_integration.max_retries, 3)
        self.assertEqual(claude_integration.context_window_size, 200000)
    
    def test_estimate_tokens(self):
        """Test token estimation."""
        claude_integration = ClaudeIntegration()
        
        text = "This is a test text with some words."
        tokens = claude_integration.estimate_tokens(text)
        
        # Should be approximately length / 4
        expected = len(text) // 4
        self.assertEqual(tokens, expected)
    
    def test_should_chunk_document(self):
        """Test document chunking decision."""
        claude_integration = ClaudeIntegration(self.config)
        
        # Small document - no chunking
        small_context = DocumentContext(
            file_path="small.pdf",
            filename="small.pdf",
            size_mb=1.0,
            page_count=5,
            text_length=1000,
            estimated_tokens=1000
        )
        self.assertFalse(claude_integration.should_chunk_document(small_context))
        
        # Large document - should chunk
        large_context = DocumentContext(
            file_path="large.pdf",
            filename="large.pdf",
            size_mb=10.0,
            page_count=100,
            text_length=100000,
            estimated_tokens=80000  # 80% of 100k context window
        )
        self.assertTrue(claude_integration.should_chunk_document(large_context))
    
    def test_extract_keywords(self):
        """Test keyword extraction."""
        claude_integration = ClaudeIntegration()
        
        text = """
        This document discusses machine learning algorithms and artificial intelligence.
        The research focuses on deep learning and neural networks.
        Machine learning is a subset of artificial intelligence.
        """
        
        keywords = claude_integration.extract_keywords(text, max_keywords=5)
        
        # Should extract meaningful keywords
        self.assertIsInstance(keywords, list)
        self.assertLessEqual(len(keywords), 5)
        
        # Should include important technical terms
        keyword_text = ' '.join(keywords)
        self.assertTrue(any(term in keyword_text for term in 
                          ['machine', 'learning', 'artificial', 'intelligence', 'neural']))
    
    def test_build_keyword_index(self):
        """Test keyword index building."""
        claude_integration = ClaudeIntegration()
        
        text1 = "Machine learning and artificial intelligence research."
        text2 = "Deep learning neural networks and machine learning."
        
        claude_integration.build_keyword_index("doc1.pdf", text1)
        claude_integration.build_keyword_index("doc2.pdf", text2)
        
        # Check that shared keywords link documents
        self.assertIn("machine", claude_integration.keyword_index)
        self.assertIn("learning", claude_integration.keyword_index)
        
        # Both documents should be in machine learning keywords
        if "machine" in claude_integration.keyword_index:
            machine_docs = claude_integration.keyword_index["machine"]
            self.assertIn("doc1.pdf", machine_docs)
            self.assertIn("doc2.pdf", machine_docs)
    
    def test_find_related_documents(self):
        """Test finding related documents."""
        claude_integration = ClaudeIntegration()
        
        # Setup document contexts
        doc1_path = "doc1.pdf"
        doc2_path = "doc2.pdf"
        doc3_path = "doc3.pdf"
        
        claude_integration.document_contexts[doc1_path] = DocumentContext(
            file_path=doc1_path, filename="doc1.pdf", size_mb=1, page_count=1,
            text_length=100, estimated_tokens=25
        )
        claude_integration.document_contexts[doc2_path] = DocumentContext(
            file_path=doc2_path, filename="doc2.pdf", size_mb=1, page_count=1,
            text_length=100, estimated_tokens=25
        )
        claude_integration.document_contexts[doc3_path] = DocumentContext(
            file_path=doc3_path, filename="doc3.pdf", size_mb=1, page_count=1,
            text_length=100, estimated_tokens=25
        )
        
        # Build keyword index with shared keywords
        for keyword in ["machine", "learning", "artificial", "intelligence"]:
            claude_integration.keyword_index[keyword] = {doc1_path, doc2_path}
        
        # doc3 has different keywords
        claude_integration.keyword_index["biology"] = {doc3_path}
        claude_integration.keyword_index["chemistry"] = {doc3_path}
        
        # Find related documents
        related = claude_integration.find_related_documents(doc1_path, min_shared_keywords=3)
        
        # doc2 should be related (4 shared keywords), doc3 should not (0 shared keywords)
        self.assertIn(doc2_path, related)
        self.assertNotIn(doc3_path, related)
    
    def test_load_processable_pdfs(self):
        """Test loading processable PDFs from JSON."""
        claude_integration = ClaudeIntegration()
        
        pdf_data = [
            {
                "path": "/test/doc1.pdf",
                "filename": "doc1.pdf",
                "size_mb": 2.5,
                "page_count": 10
            },
            {
                "path": "/test/doc2.pdf", 
                "filename": "doc2.pdf",
                "size_mb": 5.0,
                "page_count": 25
            }
        ]
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            json.dump(pdf_data, tmp)
            tmp_path = Path(tmp.name)
        
        try:
            loaded_pdfs = claude_integration.load_processable_pdfs(tmp_path)
            
            self.assertEqual(len(loaded_pdfs), 2)
            self.assertEqual(loaded_pdfs[0]['filename'], 'doc1.pdf')
            self.assertEqual(loaded_pdfs[1]['filename'], 'doc2.pdf')
            
        finally:
            tmp_path.unlink()
    
    def test_load_processable_pdfs_file_not_found(self):
        """Test loading processable PDFs with missing file."""
        claude_integration = ClaudeIntegration()
        
        with self.assertRaises(FileNotFoundError):
            claude_integration.load_processable_pdfs("/nonexistent/file.json")
    
    @patch('src.pdf_knowledge_extractor.claude_integration.PDFExtractor')
    def test_initialize_document_contexts(self, mock_extractor_class):
        """Test initializing document contexts."""
        # Mock the extractor
        mock_extractor = Mock()
        mock_extractor.extract_text.return_value = "Sample text content " * 100  # ~2000 chars
        mock_extractor_class.return_value = mock_extractor
        
        claude_integration = ClaudeIntegration()
        claude_integration.extractor = mock_extractor
        
        pdf_list = [
            {
                "path": "/test/doc1.pdf",
                "filename": "doc1.pdf",
                "size_mb": 2.5,
                "page_count": 10
            }
        ]
        
        claude_integration.initialize_document_contexts(pdf_list)
        
        # Check that context was created
        self.assertIn("/test/doc1.pdf", claude_integration.document_contexts)
        
        context = claude_integration.document_contexts["/test/doc1.pdf"]
        self.assertEqual(context.filename, "doc1.pdf")
        self.assertEqual(context.size_mb, 2.5)
        self.assertEqual(context.page_count, 10)
        self.assertGreater(context.text_length, 0)
        self.assertGreater(context.estimated_tokens, 0)
    
    def test_create_batches(self):
        """Test batch creation."""
        claude_integration = ClaudeIntegration(self.config)  # batch_size = 3
        
        # Create document contexts
        for i in range(5):
            path = f"doc{i}.pdf"
            claude_integration.document_contexts[path] = DocumentContext(
                file_path=path,
                filename=f"doc{i}.pdf",
                size_mb=1.0,
                page_count=5,
                text_length=1000,
                estimated_tokens=250
            )
        
        batches = claude_integration.create_batches()
        
        # Should create 2 batches: [doc0, doc1, doc2] and [doc3, doc4]
        self.assertEqual(len(batches), 2)
        self.assertEqual(len(batches[0]), 3)
        self.assertEqual(len(batches[1]), 2)
    
    def test_format_document_output(self):
        """Test document output formatting."""
        claude_integration = ClaudeIntegration()
        
        # Create a document context
        file_path = "test.pdf"
        claude_integration.document_contexts[file_path] = DocumentContext(
            file_path=file_path,
            filename="test.pdf",
            size_mb=2.5,
            page_count=10,
            text_length=5000,
            estimated_tokens=1250,
            processing_end="2024-01-01T12:00:00"
        )
        
        claude_response = "This is a test analysis response from Claude."
        related_docs = ["related1.pdf", "related2.pdf"]
        
        # Add related document contexts
        for related_path in related_docs:
            claude_integration.document_contexts[related_path] = DocumentContext(
                file_path=related_path,
                filename=related_path,
                size_mb=1.0,
                page_count=5,
                text_length=1000,
                estimated_tokens=250
            )
        
        formatted_output = claude_integration.format_document_output(
            file_path, claude_response, related_docs
        )
        
        # Check formatting
        self.assertIn("# Analysis: test.pdf", formatted_output)
        self.assertIn("## Document Metadata", formatted_output)
        self.assertIn("**Size**: 2.5 MB", formatted_output)
        self.assertIn("**Pages**: 10", formatted_output)
        self.assertIn("## Analysis", formatted_output)
        self.assertIn(claude_response, formatted_output)
        self.assertIn("## Related Documents", formatted_output)
    
    def test_simulate_claude_processing(self):
        """Test Claude processing simulation."""
        claude_integration = ClaudeIntegration()
        
        file_path = "test.pdf"
        claude_integration.document_contexts[file_path] = DocumentContext(
            file_path=file_path,
            filename="test.pdf",
            size_mb=1.0,
            page_count=5,
            text_length=1000,
            estimated_tokens=250
        )
        
        text = "This is sample text content for processing."
        response = claude_integration.simulate_claude_processing(text, file_path)
        
        # Check response structure
        self.assertIsInstance(response, str)
        self.assertIn("test.pdf", response)
        self.assertIn("Key Analysis Points", response)
        self.assertIn("Summary", response)
        self.assertIn("Technical Details", response)
    
    @patch('src.pdf_knowledge_extractor.claude_integration.PDFExtractor')
    def test_process_document_with_retry_success(self, mock_extractor_class):
        """Test successful document processing."""
        mock_extractor = Mock()
        mock_extractor.extract_text.return_value = "Sample document text content."
        mock_extractor_class.return_value = mock_extractor
        
        claude_integration = ClaudeIntegration()
        claude_integration.extractor = mock_extractor
        
        file_path = "test.pdf"
        claude_integration.document_contexts[file_path] = DocumentContext(
            file_path=file_path,
            filename="test.pdf",
            size_mb=1.0,
            page_count=5,
            text_length=1000,
            estimated_tokens=250
        )
        
        success, response = claude_integration.process_document_with_retry(file_path)
        
        self.assertTrue(success)
        self.assertIsInstance(response, str)
        self.assertGreater(len(response), 0)
        
        # Check context was updated
        context = claude_integration.document_contexts[file_path]
        self.assertEqual(context.processing_status, ProcessingStatus.COMPLETED)
        self.assertIsNotNone(context.processing_start)
        self.assertIsNotNone(context.processing_end)
    
    @patch('src.pdf_knowledge_extractor.claude_integration.PDFExtractor')
    def test_process_document_with_retry_failure(self, mock_extractor_class):
        """Test document processing failure with retries."""
        mock_extractor = Mock()
        mock_extractor.extract_text.side_effect = Exception("Extraction failed")
        mock_extractor_class.return_value = mock_extractor
        
        claude_integration = ClaudeIntegration(self.config)  # max_retries = 2
        claude_integration.extractor = mock_extractor
        
        file_path = "test.pdf"
        claude_integration.document_contexts[file_path] = DocumentContext(
            file_path=file_path,
            filename="test.pdf",
            size_mb=1.0,
            page_count=5,
            text_length=1000,
            estimated_tokens=250
        )
        
        with patch('time.sleep'):  # Mock sleep to speed up test
            success, response = claude_integration.process_document_with_retry(file_path)
        
        self.assertFalse(success)
        self.assertIn("Extraction failed", response)
        
        # Check context was updated
        context = claude_integration.document_contexts[file_path]
        self.assertEqual(context.processing_status, ProcessingStatus.FAILED)
        self.assertEqual(context.retry_count, 2)  # max_retries
        self.assertIsNotNone(context.last_error)
    
    def test_state_management(self):
        """Test state saving and loading."""
        claude_integration = ClaudeIntegration()
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Setup state management
            claude_integration.setup_state_management(tmp_dir)
            
            # Add some test data
            claude_integration.document_contexts["test.pdf"] = DocumentContext(
                file_path="test.pdf",
                filename="test.pdf",
                size_mb=1.0,
                page_count=5,
                text_length=1000,
                estimated_tokens=250,
                processing_status=ProcessingStatus.COMPLETED
            )
            
            claude_integration.keyword_index = {
                "machine": {"test.pdf", "other.pdf"},
                "learning": {"test.pdf"}
            }
            
            claude_integration.processed_batches = ["batch_1_5_docs"]
            
            # Save state
            claude_integration.save_state()
            
            # Create new instance and load state
            new_integration = ClaudeIntegration()
            new_integration.setup_state_management(tmp_dir)
            loaded = new_integration.load_state()
            
            self.assertTrue(loaded)
            self.assertIn("test.pdf", new_integration.document_contexts)
            self.assertEqual(
                new_integration.document_contexts["test.pdf"].processing_status,
                ProcessingStatus.COMPLETED
            )
            self.assertIn("machine", new_integration.keyword_index)
            self.assertEqual(new_integration.processed_batches, ["batch_1_5_docs"])


class TestClaudeIntegrationIntegration(unittest.TestCase):
    """Integration tests for Claude integration workflow."""
    
    @patch('src.pdf_knowledge_extractor.claude_integration.PDFExtractor')
    @patch('src.pdf_knowledge_extractor.claude_integration.tqdm', None)  # Disable progress bar
    def test_run_batch_processing_workflow(self, mock_extractor_class):
        """Test complete batch processing workflow."""
        # Mock the extractor
        mock_extractor = Mock()
        mock_extractor.extract_text.return_value = "Sample document content for analysis."
        mock_extractor_class.return_value = mock_extractor
        
        # Create test PDF list file
        pdf_data = [
            {
                "path": "/test/doc1.pdf",
                "filename": "doc1.pdf",
                "size_mb": 1.0,
                "page_count": 5
            },
            {
                "path": "/test/doc2.pdf",
                "filename": "doc2.pdf", 
                "size_mb": 2.0,
                "page_count": 10
            }
        ]
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create processable PDFs file
            pdf_file = Path(tmp_dir) / "processable_pdfs.json"
            with open(pdf_file, 'w') as f:
                json.dump(pdf_data, f)
            
            # Run batch processing
            claude_integration = ClaudeIntegration({'progress': {'enabled': False}})
            claude_integration.extractor = mock_extractor
            
            with patch('time.sleep'):  # Speed up processing
                results = claude_integration.run_batch_processing(
                    processable_pdfs_file=pdf_file,
                    output_dir=tmp_dir,
                    resume=False
                )
            
            # Check results
            self.assertEqual(results['total_documents'], 2)
            self.assertEqual(results['successful'], 2)
            self.assertEqual(results['failed'], 0)
            self.assertGreater(results['batches_processed'], 0)
            
            # Check output files were created
            output_dir = Path(results['output_directory'])
            self.assertTrue((output_dir / "processing_summary.md").exists())
            self.assertTrue((output_dir / "doc1_analysis.md").exists())
            self.assertTrue((output_dir / "doc2_analysis.md").exists())


if __name__ == "__main__":
    unittest.main()