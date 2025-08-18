"""
Claude Integration Module

Manages batch processing of PDFs through Claude with intelligent context management,
retry logic, structured output formatting, and cross-referencing capabilities.
"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from dataclasses import dataclass, asdict
from enum import Enum

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

from .extractor import PDFExtractor
from .utils import load_config, create_output_directory

logger = logging.getLogger(__name__)


class ProcessingStatus(Enum):
    """Status of document processing."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY_NEEDED = "retry_needed"
    SKIPPED = "skipped"


class ClaudeErrorType(Enum):
    """Types of Claude CLI errors for better categorization."""
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONTENT_TOO_LARGE = "content_too_large"
    INVALID_CONTENT = "invalid_content"
    CLI_NOT_FOUND = "cli_not_found"
    CLI_AUTH_ERROR = "cli_auth_error"
    NETWORK_ERROR = "network_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class ClaudeError:
    """Claude error information."""
    error_type: ClaudeErrorType
    message: str
    retry_after: Optional[int] = None  # seconds to wait before retry
    is_retryable: bool = True


@dataclass
class DocumentContext:
    """Context information for a document being processed."""
    file_path: str
    filename: str
    size_mb: float
    page_count: int
    text_length: int
    estimated_tokens: int
    chunk_count: int = 1
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    retry_count: int = 0
    last_error: Optional[str] = None
    last_error_type: Optional[ClaudeErrorType] = None
    processing_start: Optional[str] = None
    processing_end: Optional[str] = None
    claude_response_length: int = 0
    related_documents: List[str] = None
    retry_delays: List[float] = None  # Track actual delays used
    content_filtered: bool = False  # Whether content was pre-filtered
    
    def __post_init__(self):
        if self.related_documents is None:
            self.related_documents = []
        if self.retry_delays is None:
            self.retry_delays = []


@dataclass 
class BatchProgress:
    """Progress tracking for batch processing."""
    total_documents: int
    processed_documents: int
    failed_documents: int
    skipped_documents: int
    current_batch: int
    total_batches: int
    start_time: str
    last_update: str
    estimated_completion: Optional[str] = None
    claude_health_status: str = "unknown"  # healthy, degraded, unhealthy
    consecutive_failures: int = 0
    rate_limit_hits: int = 0
    
    @property
    def completion_percentage(self) -> float:
        if self.total_documents == 0:
            return 0.0
        return (self.processed_documents / self.total_documents) * 100
    
    @property
    def success_rate(self) -> float:
        """Current success rate percentage."""
        total_attempted = self.processed_documents + self.failed_documents
        if total_attempted == 0:
            return 0.0
        return (self.processed_documents / total_attempted) * 100


class ClaudeIntegration:
    """
    Manages batch processing of PDFs through Claude with intelligent context management.
    
    Features:
    - Automatic context window management
    - Smart retry logic with exponential backoff
    - Structured output formatting (markdown)
    - Cross-referencing between related documents
    - Progress tracking and state persistence
    - Integration with PDFExtractor
    """
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize Claude integration with configuration.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Claude-specific configuration
        claude_config = self.config.get('claude', {})
        self.max_tokens_per_request = claude_config.get('max_tokens_per_request', 8000)
        self.context_window_size = claude_config.get('context_window_size', 200000)
        self.max_retries = claude_config.get('max_retries', 3)
        self.retry_delay_base = claude_config.get('retry_delay_base', 1.0)
        self.retry_delay_max = claude_config.get('retry_delay_max', 30.0)
        self.batch_size = claude_config.get('batch_size', 5)
        self.claude_timeout = claude_config.get('timeout', 120)
        
        # Content filtering configuration
        self.max_content_length = claude_config.get('max_content_length', 500000)  # ~125k tokens
        self.min_content_quality_ratio = claude_config.get('min_content_quality_ratio', 0.7)
        
        # Reliability features
        self.skip_failed = claude_config.get('skip_failed', False)
        self.health_check_enabled = claude_config.get('health_check_enabled', True)
        self.rate_limit_backoff_multiplier = claude_config.get('rate_limit_backoff_multiplier', 2.0)
        
        # Output formatting
        output_config = self.config.get('output', {})
        self.output_format = output_config.get('format', 'markdown')
        self.include_metadata = output_config.get('include_metadata', True)
        self.include_cross_references = output_config.get('include_cross_references', True)
        
        # State management
        self.state_file = None
        self.progress_file = None
        self.output_directory = None
        
        # Processing state
        self.document_contexts: Dict[str, DocumentContext] = {}
        self.batch_progress: Optional[BatchProgress] = None
        self.keyword_index: Dict[str, Set[str]] = {}  # keyword -> set of document paths
        self.processed_batches: List[str] = []
        
        # Initialize PDF extractor
        self.extractor = PDFExtractor(self.config)
        
        logger.info("Claude integration initialized")
    
    def setup_state_management(self, output_dir: Union[str, Path]) -> None:
        """Setup state management files.
        
        Args:
            output_dir: Directory for output and state files
        """
        self.output_directory = create_output_directory(str(output_dir))
        self.state_file = self.output_directory / ".claude_processing_state.json"
        self.progress_file = self.output_directory / ".claude_progress.json"
        
        logger.info(f"State management setup in: {self.output_directory}")
    
    def load_state(self) -> bool:
        """Load processing state from previous session.
        
        Returns:
            True if state was loaded successfully, False otherwise
        """
        if not self.state_file or not self.state_file.exists():
            return False
        
        try:
            with open(self.state_file, 'r') as f:
                state_data = json.load(f)
            
            # Restore document contexts
            self.document_contexts = {}
            for path, context_data in state_data.get('document_contexts', {}).items():
                context_data['processing_status'] = ProcessingStatus(context_data['processing_status'])
                self.document_contexts[path] = DocumentContext(**context_data)
            
            # Restore other state
            self.keyword_index = {k: set(v) for k, v in state_data.get('keyword_index', {}).items()}
            self.processed_batches = state_data.get('processed_batches', [])
            
            # Load progress if available
            if self.progress_file and self.progress_file.exists():
                with open(self.progress_file, 'r') as f:
                    progress_data = json.load(f)
                    self.batch_progress = BatchProgress(**progress_data)
            
            logger.info(f"Loaded state: {len(self.document_contexts)} documents, "
                       f"{len(self.processed_batches)} batches processed")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            return False
    
    def save_state(self) -> None:
        """Save current processing state."""
        if not self.state_file:
            return
        
        try:
            # Prepare state data
            state_data = {
                'document_contexts': {
                    path: {**asdict(context), 'processing_status': context.processing_status.value}
                    for path, context in self.document_contexts.items()
                },
                'keyword_index': {k: list(v) for k, v in self.keyword_index.items()},
                'processed_batches': self.processed_batches,
                'last_updated': datetime.now().isoformat()
            }
            
            with open(self.state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
            
            # Save progress
            if self.batch_progress and self.progress_file:
                with open(self.progress_file, 'w') as f:
                    json.dump(asdict(self.batch_progress), f, indent=2)
            
            logger.debug("State saved successfully")
            
        except Exception as e:
            logger.error(f"Failed to save state: {e}")
    
    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.
        
        Args:
            text: Text to estimate tokens for
            
        Returns:
            Estimated token count
        """
        # Rough estimation: ~4 characters per token for English text
        return len(text) // 4
    
    def categorize_claude_error(self, error_msg: str, return_code: int) -> ClaudeError:
        """Categorize Claude CLI error for appropriate handling.
        
        Args:
            error_msg: Error message from Claude CLI
            return_code: Process return code
            
        Returns:
            ClaudeError with categorization and retry strategy
        """
        error_msg_lower = error_msg.lower()
        
        # Rate limiting
        if "rate limit" in error_msg_lower or "too many requests" in error_msg_lower:
            return ClaudeError(
                error_type=ClaudeErrorType.RATE_LIMIT,
                message=error_msg,
                retry_after=60,  # Wait 1 minute for rate limits
                is_retryable=True
            )
        
        # Timeout errors
        if "timeout" in error_msg_lower or return_code == 124:
            return ClaudeError(
                error_type=ClaudeErrorType.TIMEOUT,
                message=error_msg,
                retry_after=5,
                is_retryable=True
            )
        
        # Content size issues
        if "too large" in error_msg_lower or "content length" in error_msg_lower:
            return ClaudeError(
                error_type=ClaudeErrorType.CONTENT_TOO_LARGE,
                message=error_msg,
                is_retryable=False  # Don't retry without content filtering
            )
        
        # Authentication issues
        if "auth" in error_msg_lower or "unauthorized" in error_msg_lower or return_code == 401:
            return ClaudeError(
                error_type=ClaudeErrorType.CLI_AUTH_ERROR,
                message=error_msg,
                is_retryable=False
            )
        
        # CLI not found
        if "command not found" in error_msg_lower or "no such file" in error_msg_lower or return_code == 127:
            return ClaudeError(
                error_type=ClaudeErrorType.CLI_NOT_FOUND,
                message=error_msg,
                is_retryable=False
            )
        
        # Network issues
        if "network" in error_msg_lower or "connection" in error_msg_lower:
            return ClaudeError(
                error_type=ClaudeErrorType.NETWORK_ERROR,
                message=error_msg,
                retry_after=10,
                is_retryable=True
            )
        
        # Content issues
        if "invalid" in error_msg_lower or "malformed" in error_msg_lower:
            return ClaudeError(
                error_type=ClaudeErrorType.INVALID_CONTENT,
                message=error_msg,
                is_retryable=False
            )
        
        # Default to unknown error
        return ClaudeError(
            error_type=ClaudeErrorType.UNKNOWN_ERROR,
            message=error_msg,
            retry_after=5,
            is_retryable=True
        )
    
    def calculate_exponential_backoff(self, attempt: int, error_type: ClaudeErrorType, 
                                    base_delay: Optional[float] = None) -> float:
        """Calculate exponential backoff delay with jitter.
        
        Args:
            attempt: Current attempt number (0-based)
            error_type: Type of error encountered
            base_delay: Override base delay
            
        Returns:
            Delay in seconds
        """
        if base_delay is None:
            base_delay = self.retry_delay_base
        
        # Different base delays for different error types
        if error_type == ClaudeErrorType.RATE_LIMIT:
            base_delay = max(base_delay, 2.0) * self.rate_limit_backoff_multiplier
        elif error_type == ClaudeErrorType.NETWORK_ERROR:
            base_delay = max(base_delay, 1.0)
        
        # Exponential backoff with jitter
        import random
        delay = min(base_delay * (2 ** attempt), self.retry_delay_max)
        jitter = random.uniform(0.1, 0.3) * delay  # 10-30% jitter
        
        return delay + jitter
    
    def test_claude_cli_health(self) -> Tuple[bool, str]:
        """Test Claude CLI availability and basic functionality.
        
        Returns:
            Tuple of (is_healthy, status_message)
        """
        if not self.health_check_enabled:
            return True, "Health check disabled"
        
        import subprocess
        
        try:
            # Test basic Claude CLI availability
            result = subprocess.run(
                ['claude', '--version'],
                capture_output=True,
                text=True,
                timeout=10,
                check=False
            )
            
            if result.returncode == 0:
                return True, f"Claude CLI healthy: {result.stdout.strip()}"
            elif result.returncode == 127:
                return False, "Claude CLI not found in PATH"
            else:
                return False, f"Claude CLI error: {result.stderr.strip()}"
                
        except subprocess.TimeoutExpired:
            return False, "Claude CLI health check timed out"
        except FileNotFoundError:
            return False, "Claude CLI executable not found"
        except Exception as e:
            return False, f"Health check failed: {e}"
    
    def clean_text_for_claude(self, text: str) -> str:
        """Clean and prepare text for Claude processing.
        
        Args:
            text: Raw text to clean
            
        Returns:
            Cleaned text
        """
        if not text:
            return text
        
        # Remove excessive whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove control characters but keep newlines and tabs
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        
        # Normalize unicode
        import unicodedata
        text = unicodedata.normalize('NFKC', text)
        
        # Remove very long repeated patterns that might confuse Claude
        text = re.sub(r'(.{10,}?)\1{3,}', r'\1\1', text)
        
        return text.strip()
    
    def validate_text_quality(self, text: str) -> Tuple[bool, str]:
        """Validate text quality for Claude processing.
        
        Args:
            text: Text to validate
            
        Returns:
            Tuple of (is_valid, reason)
        """
        if not text or not text.strip():
            return False, "Empty or whitespace-only text"
        
        # Check length limits
        if len(text) > self.max_content_length:
            return False, f"Text too long: {len(text)} > {self.max_content_length}"
        
        # Check for reasonable text quality
        alphanumeric_chars = sum(1 for c in text if c.isalnum())
        total_chars = len(text)
        
        if total_chars > 0:
            quality_ratio = alphanumeric_chars / total_chars
            if quality_ratio < self.min_content_quality_ratio:
                return False, f"Poor text quality: {quality_ratio:.2f} < {self.min_content_quality_ratio}"
        
        # Check for excessive repetition
        words = text.split()
        if len(words) > 100:  # Only check for longer texts
            unique_words = len(set(words))
            if unique_words / len(words) < 0.1:  # Less than 10% unique words
                return False, "Excessive repetition detected"
        
        return True, "Text quality acceptable"
    
    def should_filter_document(self, context: DocumentContext, text: str) -> Tuple[bool, str]:
        """Determine if document should be filtered before Claude processing.
        
        Args:
            context: Document context
            text: Document text
            
        Returns:
            Tuple of (should_filter, reason)
        """
        # Check if already filtered
        if context.content_filtered:
            return False, "Already filtered"
        
        # Very large documents
        if context.size_mb > 50:  # 50MB+ files
            return True, "File too large (>50MB)"
        
        # Too many pages (likely scanned documents with poor text extraction)
        if context.page_count > 500:
            return True, "Too many pages (>500)"
        
        # Poor text extraction ratio
        expected_chars_per_page = 2000  # Rough estimate
        expected_total = context.page_count * expected_chars_per_page
        if expected_total > 0 and len(text) < (expected_total * 0.1):
            return True, "Poor text extraction ratio"
        
        # Text quality issues
        is_valid, reason = self.validate_text_quality(text)
        if not is_valid:
            return True, f"Text quality issue: {reason}"
        
        return False, "Document passes filtering"
    
    def should_chunk_document(self, context: DocumentContext) -> bool:
        """Determine if document should be chunked based on size.
        
        Args:
            context: Document context
            
        Returns:
            True if document should be chunked
        """
        return context.estimated_tokens > (self.context_window_size * 0.7)  # 70% of context window
    
    def load_processable_pdfs(self, json_file: Union[str, Path]) -> List[Dict]:
        """Load processable PDFs from JSON file.
        
        Args:
            json_file: Path to processable_pdfs.json file
            
        Returns:
            List of PDF metadata dictionaries
        """
        json_path = Path(json_file)
        if not json_path.exists():
            raise FileNotFoundError(f"Processable PDFs file not found: {json_file}")
        
        with open(json_path, 'r') as f:
            pdfs = json.load(f)
        
        logger.info(f"Loaded {len(pdfs)} processable PDFs from {json_file}")
        return pdfs
    
    def initialize_document_contexts(self, pdf_list: List[Dict]) -> None:
        """Initialize document contexts from PDF list.
        
        Args:
            pdf_list: List of PDF metadata dictionaries
        """
        for pdf_info in pdf_list:
            file_path = pdf_info['path']
            
            # Skip if already in contexts (resuming)
            if file_path in self.document_contexts:
                continue
            
            try:
                # Extract text to get accurate token estimate
                text = self.extractor.extract_text(file_path)
                text_length = len(text)
                estimated_tokens = self.estimate_tokens(text)
                
                context = DocumentContext(
                    file_path=file_path,
                    filename=pdf_info['filename'],
                    size_mb=pdf_info['size_mb'],
                    page_count=pdf_info['page_count'],
                    text_length=text_length,
                    estimated_tokens=estimated_tokens
                )
                
                # Determine if chunking is needed
                if self.should_chunk_document(context):
                    # Calculate chunk count (simplified - could be more sophisticated)
                    context.chunk_count = max(1, estimated_tokens // (self.context_window_size // 2))
                
                self.document_contexts[file_path] = context
                logger.debug(f"Initialized context for {context.filename}: "
                           f"{estimated_tokens} tokens, {context.chunk_count} chunks")
                
            except Exception as e:
                logger.error(f"Failed to initialize context for {file_path}: {e}")
                # Create minimal context for failed document
                self.document_contexts[file_path] = DocumentContext(
                    file_path=file_path,
                    filename=pdf_info.get('filename', Path(file_path).name),
                    size_mb=pdf_info.get('size_mb', 0),
                    page_count=pdf_info.get('page_count', 0),
                    text_length=0,
                    estimated_tokens=0,
                    processing_status=ProcessingStatus.FAILED,
                    last_error=str(e)
                )
    
    def create_batches(self) -> List[List[str]]:
        """Create processing batches based on token limits and configuration.
        
        Returns:
            List of batches, each batch is a list of document paths
        """
        batches = []
        current_batch = []
        current_batch_tokens = 0
        
        # Sort documents by token count (process smaller ones first)
        sorted_docs = sorted(
            [(path, ctx) for path, ctx in self.document_contexts.items() 
             if ctx.processing_status == ProcessingStatus.PENDING],
            key=lambda x: x[1].estimated_tokens
        )
        
        for file_path, context in sorted_docs:
            # Check if adding this document would exceed batch limits
            if (len(current_batch) >= self.batch_size or 
                current_batch_tokens + context.estimated_tokens > self.max_tokens_per_request):
                
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_batch_tokens = 0
            
            current_batch.append(file_path)
            current_batch_tokens += context.estimated_tokens
        
        # Add final batch if not empty
        if current_batch:
            batches.append(current_batch)
        
        logger.info(f"Created {len(batches)} processing batches")
        return batches
    
    def extract_keywords(self, text: str, max_keywords: int = 20) -> List[str]:
        """Extract keywords from text for cross-referencing.
        
        Args:
            text: Text to extract keywords from
            max_keywords: Maximum number of keywords to extract
            
        Returns:
            List of extracted keywords
        """
        # Simple keyword extraction - could be enhanced with NLP
        words = re.findall(r'\b[A-Za-z]{4,}\b', text.lower())
        
        # Common stop words to exclude
        stop_words = {
            'this', 'that', 'with', 'have', 'will', 'from', 'they', 'been', 
            'were', 'said', 'each', 'which', 'their', 'time', 'would', 'there',
            'more', 'very', 'what', 'know', 'just', 'first', 'into', 'over',
            'after', 'back', 'other', 'many', 'than', 'then', 'them', 'these',
            'some', 'could', 'make', 'like', 'only', 'also', 'when', 'here',
            'how', 'our', 'out', 'may', 'way', 'use', 'her', 'new', 'now',
            'old', 'see', 'him', 'two', 'who', 'its', 'did', 'yes', 'his',
            'had', 'let', 'put', 'say', 'she', 'too', 'end', 'why', 'try',
            'god', 'six', 'dog', 'eat', 'ago', 'sit', 'fun', 'bad', 'yet',
            'arm', 'far', 'off', 'ill', 'own', 'under', 'last'
        }
        
        # Count word frequencies
        word_freq = {}
        for word in words:
            if word not in stop_words and len(word) >= 4:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        # Return top keywords
        keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, freq in keywords[:max_keywords]]
    
    def build_keyword_index(self, file_path: str, text: str) -> None:
        """Build keyword index for cross-referencing.
        
        Args:
            file_path: Path to the document
            text: Document text content
        """
        keywords = self.extract_keywords(text)
        
        for keyword in keywords:
            if keyword not in self.keyword_index:
                self.keyword_index[keyword] = set()
            self.keyword_index[keyword].add(file_path)
    
    def find_related_documents(self, file_path: str, min_shared_keywords: int = 3) -> List[str]:
        """Find documents related to the given document based on shared keywords.
        
        Args:
            file_path: Path to the document
            min_shared_keywords: Minimum number of shared keywords for relation
            
        Returns:
            List of related document paths
        """
        if file_path not in self.document_contexts:
            return []
        
        # Get keywords for this document
        doc_keywords = set()
        for keyword, docs in self.keyword_index.items():
            if file_path in docs:
                doc_keywords.add(keyword)
        
        # Find documents with shared keywords
        related_docs = {}
        for keyword in doc_keywords:
            for doc_path in self.keyword_index[keyword]:
                if doc_path != file_path:
                    related_docs[doc_path] = related_docs.get(doc_path, 0) + 1
        
        # Filter by minimum shared keywords
        related = [doc for doc, count in related_docs.items() 
                  if count >= min_shared_keywords]
        
        # Sort by number of shared keywords
        related.sort(key=lambda x: related_docs[x], reverse=True)
        
        return related[:10]  # Return top 10 related documents
    
    def format_document_output(self, file_path: str, claude_response: str, 
                             related_docs: List[str] = None) -> str:
        """Format the output for a processed document.
        
        Args:
            file_path: Path to the processed document
            claude_response: Response from Claude
            related_docs: List of related document paths
            
        Returns:
            Formatted output string
        """
        context = self.document_contexts.get(file_path)
        if not context:
            return claude_response
        
        if self.output_format.lower() != 'markdown':
            return claude_response
        
        # Create markdown formatted output
        output_lines = []
        
        # Header
        output_lines.append(f"# Analysis: {context.filename}")
        output_lines.append("")
        
        # Metadata section
        if self.include_metadata:
            output_lines.append("## Document Metadata")
            output_lines.append(f"- **File**: `{context.filename}`")
            output_lines.append(f"- **Size**: {context.size_mb} MB")
            output_lines.append(f"- **Pages**: {context.page_count}")
            output_lines.append(f"- **Processing Date**: {context.processing_end or 'In Progress'}")
            output_lines.append(f"- **Token Estimate**: {context.estimated_tokens:,}")
            
            if context.chunk_count > 1:
                output_lines.append(f"- **Chunks Processed**: {context.chunk_count}")
            
            output_lines.append("")
        
        # Main content
        output_lines.append("## Analysis")
        output_lines.append("")
        output_lines.append(claude_response)
        output_lines.append("")
        
        # Cross-references
        if self.include_cross_references and related_docs:
            output_lines.append("## Related Documents")
            output_lines.append("")
            for related_path in related_docs:
                related_context = self.document_contexts.get(related_path)
                if related_context:
                    output_lines.append(f"- [{related_context.filename}]({related_context.filename})")
            output_lines.append("")
        
        # Processing info
        output_lines.append("---")
        output_lines.append("*Generated by PDF Knowledge Extractor with Claude Integration*")
        
        return "\n".join(output_lines)
    
    def claude_processing(self, text: str, file_path: str) -> str:
        """Process document text using Claude Code CLI for real insights.
        
        Args:
            text: Text to process
            file_path: Path to the source file
            
        Returns:
            Claude analysis response
            
        Raises:
            Exception: If Claude processing fails after all retries
        """
        import subprocess
        import tempfile
        import os
        
        context = self.document_contexts.get(file_path)
        filename = context.filename if context else Path(file_path).name
        
        # Pre-filter and clean text
        cleaned_text = self.clean_text_for_claude(text)
        
        # Validate text quality
        is_valid, reason = self.validate_text_quality(cleaned_text)
        if not is_valid:
            raise Exception(f"Text validation failed: {reason}")
        
        # Create a temporary file with the document text
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as temp_file:
            temp_file.write(f"Document: {filename}\n")
            temp_file.write(f"Source: {file_path}\n")
            temp_file.write("=" * 80 + "\n\n")
            temp_file.write(cleaned_text)
            temp_file_path = temp_file.name
        
        try:
            # Craft a comprehensive prompt for Claude
            prompt = f"""Please analyze this document and provide comprehensive insights. The document is from a PDF extraction process.

Please provide:

1. **Executive Summary**: A concise overview of the main purpose and key points of this document.

2. **Key Insights**: The most important insights, concepts, or findings from this document. Focus on actionable information and unique perspectives.

3. **Main Themes**: Identify and explain the primary themes or topics covered.

4. **Notable Quotes or Concepts**: Highlight any particularly insightful quotes, frameworks, or concepts that stand out.

5. **Practical Applications**: How can the insights from this document be applied in real-world scenarios?

6. **Connections**: What broader topics, fields, or other knowledge areas does this document connect to?

7. **Questions for Further Exploration**: What questions does this document raise that would be worth investigating further?

Please format your response in clear markdown with appropriate headers. Focus on extracting valuable knowledge and insights rather than just summarizing content."""

            # Use Claude CLI with stdin approach (correct syntax)
            claude_response = None
            last_error = None
            
            # Primary approach: stdin-based Claude CLI
            try:
                full_input = f"{prompt}\n\n{cleaned_text}"
                result = subprocess.run(
                    ['claude'],
                    input=full_input,
                    capture_output=True,
                    text=True,
                    timeout=self.claude_timeout,
                    check=False
                )
                
                if result.returncode == 0 and result.stdout.strip():
                    claude_response = result.stdout.strip()
                else:
                    # Categorize the error for better handling
                    error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                    claude_error = self.categorize_claude_error(error_msg, result.returncode)
                    last_error = claude_error
                    logger.debug(f"Claude CLI failed: {claude_error.error_type.value} - {error_msg}")
                    
            except subprocess.TimeoutExpired:
                last_error = ClaudeError(
                    error_type=ClaudeErrorType.TIMEOUT,
                    message=f"Command timed out after {self.claude_timeout}s",
                    is_retryable=True
                )
                logger.debug(f"Claude CLI timed out")
                
            except FileNotFoundError:
                last_error = ClaudeError(
                    error_type=ClaudeErrorType.CLI_NOT_FOUND,
                    message="Claude CLI not found",
                    is_retryable=False
                )
                logger.debug(f"Claude CLI not found")
            
            # Fallback: try 'claude code' command with stdin
            if not claude_response and last_error and last_error.error_type != ClaudeErrorType.CLI_NOT_FOUND:
                try:
                    full_input = f"{prompt}\n\n{cleaned_text}"
                    result = subprocess.run(
                        ['claude', 'code'],
                        input=full_input,
                        capture_output=True,
                        text=True,
                        timeout=self.claude_timeout,
                        check=False
                    )
                    
                    if result.returncode == 0 and result.stdout.strip():
                        claude_response = result.stdout.strip()
                    else:
                        error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
                        last_error = self.categorize_claude_error(error_msg, result.returncode)
                        logger.debug(f"Claude Code CLI failed: {error_msg}")
                        
                except subprocess.TimeoutExpired:
                    last_error = ClaudeError(
                        error_type=ClaudeErrorType.TIMEOUT,
                        message=f"Claude Code command timed out after {self.claude_timeout}s",
                        is_retryable=True
                    )
                except FileNotFoundError:
                    last_error = ClaudeError(
                        error_type=ClaudeErrorType.CLI_NOT_FOUND,
                        message="Claude Code CLI not found",
                        is_retryable=False
                    )
            
            if not claude_response:
                error_msg = f"Claude processing failed: {last_error.message if last_error else 'Unknown error'}"
                raise Exception(error_msg)
                
            # Add metadata to the response
            word_count = len(text.split())
            char_count = len(text)
            
            enhanced_response = f"""{claude_response}

---

## Processing Metadata
- **Document**: {filename}
- **Word Count**: {word_count:,}
- **Character Count**: {char_count:,}
- **Estimated Tokens**: {self.estimate_tokens(text):,}
- **Processing Timestamp**: {datetime.now().isoformat()}
- **Processing Method**: Claude Code CLI"""

            return enhanced_response
            
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except OSError:
                pass
    
    def process_document_with_retry(self, file_path: str) -> Tuple[bool, str]:
        """Process a single document with improved retry logic and error handling.
        
        Args:
            file_path: Path to the document to process
            
        Returns:
            Tuple of (success, response/error_message)
        """
        context = self.document_contexts.get(file_path)
        if not context:
            return False, "Document context not found"
        
        context.processing_start = datetime.now().isoformat()
        context.processing_status = ProcessingStatus.IN_PROGRESS
        context.retry_delays = []
        
        # Extract text once before retries
        try:
            text = self.extractor.extract_text(file_path)
            if not text.strip():
                context.processing_status = ProcessingStatus.FAILED
                context.last_error = "No text extracted from PDF"
                context.last_error_type = ClaudeErrorType.INVALID_CONTENT
                return False, "No text extracted from PDF"
        except Exception as e:
            context.processing_status = ProcessingStatus.FAILED
            context.last_error = f"Text extraction failed: {str(e)}"
            context.last_error_type = ClaudeErrorType.INVALID_CONTENT
            return False, f"Text extraction failed: {str(e)}"
        
        # Pre-filter problematic documents
        should_filter, filter_reason = self.should_filter_document(context, text)
        if should_filter:
            context.processing_status = ProcessingStatus.SKIPPED
            context.last_error = f"Document filtered: {filter_reason}"
            context.content_filtered = True
            
            if self.skip_failed:
                logger.info(f"Skipping filtered document: {context.filename} - {filter_reason}")
                return False, f"Document filtered and skipped: {filter_reason}"
            else:
                logger.warning(f"Processing filtered document anyway: {context.filename} - {filter_reason}")
        
        # Build keyword index for cross-referencing (once)
        self.build_keyword_index(file_path, text)
        
        claude_error = None
        for attempt in range(self.max_retries + 1):
            try:
                # Process with Claude
                claude_response = self.claude_processing(text, file_path)
                
                # Update context on success
                context.claude_response_length = len(claude_response)
                context.processing_end = datetime.now().isoformat()
                context.processing_status = ProcessingStatus.COMPLETED
                context.last_error_type = None
                
                return True, claude_response
                
            except Exception as e:
                context.retry_count = attempt
                context.last_error = str(e)
                
                # Try to categorize the error for better retry strategy
                try:
                    # Extract Claude error information if available
                    if "Claude processing failed:" in str(e):
                        claude_error = self.categorize_claude_error(str(e), 1)
                    else:
                        claude_error = self.categorize_claude_error(str(e), 1)
                    
                    context.last_error_type = claude_error.error_type
                    
                    # Check if error is retryable
                    if not claude_error.is_retryable:
                        logger.error(f"Non-retryable error for {context.filename}: {claude_error.error_type.value} - {e}")
                        context.processing_status = ProcessingStatus.FAILED
                        context.processing_end = datetime.now().isoformat()
                        return False, f"Non-retryable error: {str(e)}"
                    
                except Exception:
                    # Fallback error categorization
                    claude_error = ClaudeError(
                        error_type=ClaudeErrorType.UNKNOWN_ERROR,
                        message=str(e),
                        is_retryable=True
                    )
                    context.last_error_type = claude_error.error_type
                
                # Skip failed documents if configured
                if self.skip_failed and claude_error.error_type in [
                    ClaudeErrorType.CLI_NOT_FOUND, 
                    ClaudeErrorType.CLI_AUTH_ERROR,
                    ClaudeErrorType.CONTENT_TOO_LARGE
                ]:
                    logger.info(f"Skipping failed document: {context.filename} - {claude_error.error_type.value}")
                    context.processing_status = ProcessingStatus.SKIPPED
                    context.processing_end = datetime.now().isoformat()
                    return False, f"Document skipped: {str(e)}"
                
                if attempt < self.max_retries:
                    # Calculate intelligent backoff delay
                    delay = self.calculate_exponential_backoff(attempt, claude_error.error_type)
                    
                    # Use specific retry delay for certain errors
                    if claude_error.retry_after:
                        delay = max(delay, claude_error.retry_after)
                    
                    context.retry_delays.append(delay)
                    
                    logger.warning(f"Attempt {attempt + 1} failed for {context.filename} "
                                 f"({claude_error.error_type.value}), retrying in {delay:.1f}s: {e}")
                    
                    # Update batch progress for rate limit tracking
                    if self.batch_progress and claude_error.error_type == ClaudeErrorType.RATE_LIMIT:
                        self.batch_progress.rate_limit_hits += 1
                        self.batch_progress.claude_health_status = "degraded"
                    
                    time.sleep(delay)
                else:
                    logger.error(f"All retry attempts failed for {context.filename}: {e}")
                    context.processing_status = ProcessingStatus.FAILED
                    context.processing_end = datetime.now().isoformat()
                    
                    # Update batch progress for consecutive failures
                    if self.batch_progress:
                        self.batch_progress.consecutive_failures += 1
                        if self.batch_progress.consecutive_failures >= 5:
                            self.batch_progress.claude_health_status = "unhealthy"
                    
                    return False, str(e)
        
        return False, "Max retries exceeded"
    
    def process_batch(self, batch: List[str], batch_number: int) -> Tuple[int, int]:
        """Process a batch of documents with enhanced progress tracking.
        
        Args:
            batch: List of document paths to process
            batch_number: Batch number for progress tracking
            
        Returns:
            Tuple of (successful_count, failed_count)
        """
        logger.info(f"Processing batch {batch_number} with {len(batch)} documents")
        
        # Health check before starting batch
        if self.health_check_enabled:
            is_healthy, health_msg = self.test_claude_cli_health()
            if not is_healthy:
                logger.error(f"Claude CLI health check failed: {health_msg}")
                if self.batch_progress:
                    self.batch_progress.claude_health_status = "unhealthy"
                
                if self.skip_failed:
                    logger.info("Skipping batch due to Claude CLI health issues")
                    return 0, len(batch)
            else:
                logger.info(f"Claude CLI health check passed: {health_msg}")
                if self.batch_progress:
                    self.batch_progress.claude_health_status = "healthy"
                    self.batch_progress.consecutive_failures = 0
        
        successful = 0
        failed = 0
        
        # Enhanced progress bar with success rate
        if tqdm:
            progress_bar = tqdm(
                batch, 
                desc=f"Batch {batch_number} (Success: 0%, Health: {getattr(self.batch_progress, 'claude_health_status', 'unknown')})",
                unit="doc"
            )
        else:
            progress_bar = batch
        
        for i, file_path in enumerate(progress_bar):
            context = self.document_contexts.get(file_path)
            if not context:
                failed += 1
                continue
            
            success, response = self.process_document_with_retry(file_path)
            
            if success:
                successful += 1
                
                # Reset consecutive failures on success
                if self.batch_progress:
                    self.batch_progress.consecutive_failures = 0
                    if self.batch_progress.claude_health_status == "degraded":
                        self.batch_progress.claude_health_status = "healthy"
                
                # Find related documents
                related_docs = self.find_related_documents(file_path)
                context.related_documents = related_docs
                
                # Format and save output
                formatted_output = self.format_document_output(file_path, response, related_docs)
                
                # Save individual document output
                output_filename = f"{Path(context.filename).stem}_analysis.md"
                output_path = self.output_directory / output_filename
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(formatted_output)
                
                logger.info(f"✅ Completed {context.filename} -> {output_filename}")
                
            else:
                failed += 1
                logger.error(f"❌ Failed to process {context.filename}: {response}")
            
            # Update progress bar with real-time stats
            if tqdm and isinstance(progress_bar, tqdm):
                total_processed = successful + failed
                success_rate = (successful / total_processed * 100) if total_processed > 0 else 0
                health_status = getattr(self.batch_progress, 'claude_health_status', 'unknown')
                
                progress_bar.set_description(
                    f"Batch {batch_number} (Success: {success_rate:.1f}%, Health: {health_status})"
                )
                
                # Add success/failure counts to postfix
                progress_bar.set_postfix({
                    'success': successful,
                    'failed': failed,
                    'rate_limits': getattr(self.batch_progress, 'rate_limit_hits', 0)
                })
            
            # Log progress every 10 documents
            if (successful + failed) % 10 == 0:
                total_processed = successful + failed
                success_rate = (successful / total_processed * 100) if total_processed > 0 else 0
                logger.info(f"Batch {batch_number} progress: {total_processed}/{len(batch)} "
                           f"({success_rate:.1f}% success rate)")
            
            # Save state periodically
            if (successful + failed) % 5 == 0:
                self.save_state()
        
        # Mark batch as processed
        batch_key = f"batch_{batch_number}_{len(batch)}_docs"
        if batch_key not in self.processed_batches:
            self.processed_batches.append(batch_key)
        
        logger.info(f"Batch {batch_number} completed: {successful} successful, {failed} failed")
        return successful, failed
    
    def generate_batch_summary(self, batch_number: int, successful: int, failed: int, 
                             processed_files: List[str]) -> str:
        """Generate summary file for a batch.
        
        Args:
            batch_number: Batch number
            successful: Number of successful processes
            failed: Number of failed processes
            processed_files: List of processed file paths
            
        Returns:
            Path to generated summary file
        """
        summary_filename = f"batch{batch_number}_summary.md"
        summary_path = self.output_directory / summary_filename
        
        summary_lines = []
        summary_lines.append(f"# Batch {batch_number} Processing Summary")
        summary_lines.append("")
        summary_lines.append(f"**Processing Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        summary_lines.append(f"**Documents Processed**: {len(processed_files)}")
        summary_lines.append(f"**Successful**: {successful}")
        summary_lines.append(f"**Failed**: {failed}")
        summary_lines.append(f"**Success Rate**: {(successful/len(processed_files)*100):.1f}%")
        summary_lines.append("")
        
        # Document list
        summary_lines.append("## Processed Documents")
        summary_lines.append("")
        
        for file_path in processed_files:
            context = self.document_contexts.get(file_path)
            if context:
                status_emoji = {
                    ProcessingStatus.COMPLETED: "✅",
                    ProcessingStatus.FAILED: "❌",
                    ProcessingStatus.RETRY_NEEDED: "🔄"
                }.get(context.processing_status, "❓")
                
                summary_lines.append(f"{status_emoji} **{context.filename}**")
                summary_lines.append(f"   - Size: {context.size_mb} MB, Pages: {context.page_count}")
                summary_lines.append(f"   - Tokens: {context.estimated_tokens:,}")
                
                if context.processing_status == ProcessingStatus.COMPLETED:
                    output_file = f"{Path(context.filename).stem}_analysis.md"
                    summary_lines.append(f"   - Output: [{output_file}]({output_file})")
                    
                    if context.related_documents:
                        summary_lines.append(f"   - Related: {len(context.related_documents)} documents")
                
                if context.processing_status == ProcessingStatus.FAILED:
                    summary_lines.append(f"   - Error: {context.last_error}")
                
                summary_lines.append("")
        
        # Cross-reference map
        if self.include_cross_references:
            summary_lines.append("## Document Relationships")
            summary_lines.append("")
            
            # Create relationship matrix
            completed_docs = [fp for fp in processed_files 
                            if self.document_contexts[fp].processing_status == ProcessingStatus.COMPLETED]
            
            if len(completed_docs) > 1:
                for file_path in completed_docs:
                    context = self.document_contexts[file_path]
                    if context.related_documents:
                        summary_lines.append(f"**{context.filename}**:")
                        for related_path in context.related_documents[:5]:  # Top 5 related
                            related_context = self.document_contexts.get(related_path)
                            if related_context:
                                summary_lines.append(f"  - {related_context.filename}")
                        summary_lines.append("")
        
        # Save summary
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(summary_lines))
        
        logger.info(f"Generated batch summary: {summary_filename}")
        return str(summary_path)
    
    def update_progress(self, batch_number: int, total_batches: int) -> None:
        """Update batch progress tracking.
        
        Args:
            batch_number: Current batch number
            total_batches: Total number of batches
        """
        if not self.batch_progress:
            return
        
        processed = sum(1 for ctx in self.document_contexts.values() 
                       if ctx.processing_status == ProcessingStatus.COMPLETED)
        failed = sum(1 for ctx in self.document_contexts.values() 
                    if ctx.processing_status == ProcessingStatus.FAILED)
        
        self.batch_progress.processed_documents = processed
        self.batch_progress.failed_documents = failed
        self.batch_progress.current_batch = batch_number
        self.batch_progress.total_batches = total_batches
        self.batch_progress.last_update = datetime.now().isoformat()
        
        # Estimate completion time
        if processed > 0:
            elapsed = datetime.now() - datetime.fromisoformat(self.batch_progress.start_time)
            avg_time_per_doc = elapsed.total_seconds() / processed
            remaining_docs = self.batch_progress.total_documents - processed - failed
            estimated_seconds = remaining_docs * avg_time_per_doc
            estimated_completion = datetime.now() + timedelta(seconds=estimated_seconds)
            self.batch_progress.estimated_completion = estimated_completion.isoformat()
    
    def run_batch_processing(self, processable_pdfs_file: Union[str, Path], 
                           output_dir: Union[str, Path], resume: bool = True) -> Dict[str, Any]:
        """Run complete batch processing workflow.
        
        Args:
            processable_pdfs_file: Path to processable_pdfs.json
            output_dir: Output directory for results
            resume: Whether to resume from previous state
            
        Returns:
            Processing results summary
        """
        logger.info("Starting Claude batch processing workflow")
        
        # Setup state management
        self.setup_state_management(output_dir)
        
        # Load previous state if resuming
        if resume:
            self.load_state()
        
        # Load processable PDFs
        pdf_list = self.load_processable_pdfs(processable_pdfs_file)
        
        # Initialize document contexts
        self.initialize_document_contexts(pdf_list)
        
        # Initialize progress tracking
        if not self.batch_progress:
            self.batch_progress = BatchProgress(
                total_documents=len(self.document_contexts),
                processed_documents=0,
                failed_documents=0,
                skipped_documents=0,
                current_batch=0,
                total_batches=0,
                start_time=datetime.now().isoformat(),
                last_update=datetime.now().isoformat()
            )
        
        # Create processing batches
        batches = self.create_batches()
        self.batch_progress.total_batches = len(batches)
        
        # Process batches
        total_successful = 0
        total_failed = 0
        
        for batch_num, batch in enumerate(batches, 1):
            logger.info(f"Starting batch {batch_num}/{len(batches)}")
            
            successful, failed = self.process_batch(batch, batch_num)
            total_successful += successful
            total_failed += failed
            
            # Update progress
            self.update_progress(batch_num, len(batches))
            
            # Generate batch summary
            self.generate_batch_summary(batch_num, successful, failed, batch)
            
            # Save state after each batch
            self.save_state()
        
        # Generate final summary
        self.generate_final_summary(total_successful, total_failed)
        
        # Final state save
        self.save_state()
        
        result = {
            'total_documents': len(self.document_contexts),
            'successful': total_successful,
            'failed': total_failed,
            'batches_processed': len(batches),
            'output_directory': str(self.output_directory),
            'processing_time': datetime.now().isoformat()
        }
        
        logger.info(f"Batch processing completed: {result}")
        return result
    
    def generate_final_summary(self, total_successful: int, total_failed: int) -> str:
        """Generate final processing summary.
        
        Args:
            total_successful: Total successful documents
            total_failed: Total failed documents
            
        Returns:
            Path to final summary file
        """
        summary_path = self.output_directory / "processing_summary.md"
        
        summary_lines = []
        summary_lines.append("# PDF Knowledge Extraction - Final Summary")
        summary_lines.append("")
        summary_lines.append(f"**Processing Completed**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        summary_lines.append(f"**Total Documents**: {len(self.document_contexts)}")
        summary_lines.append(f"**Successfully Processed**: {total_successful}")
        summary_lines.append(f"**Failed**: {total_failed}")
        summary_lines.append(f"**Success Rate**: {(total_successful/len(self.document_contexts)*100):.1f}%")
        summary_lines.append(f"**Total Batches**: {len(self.processed_batches)}")
        summary_lines.append("")
        
        # Processing statistics
        total_tokens = sum(ctx.estimated_tokens for ctx in self.document_contexts.values())
        total_size = sum(ctx.size_mb for ctx in self.document_contexts.values())
        
        summary_lines.append("## Processing Statistics")
        summary_lines.append(f"- **Total Content Size**: {total_size:.1f} MB")
        summary_lines.append(f"- **Total Estimated Tokens**: {total_tokens:,}")
        summary_lines.append(f"- **Average Document Size**: {total_size/len(self.document_contexts):.2f} MB")
        summary_lines.append("")
        
        # Status breakdown
        status_counts = {}
        for context in self.document_contexts.values():
            status = context.processing_status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        summary_lines.append("## Status Breakdown")
        for status, count in status_counts.items():
            emoji = {
                ProcessingStatus.COMPLETED: "✅",
                ProcessingStatus.FAILED: "❌",
                ProcessingStatus.PENDING: "⏳",
                ProcessingStatus.IN_PROGRESS: "🔄"
            }.get(status, "❓")
            summary_lines.append(f"- {emoji} {status.value.title()}: {count}")
        summary_lines.append("")
        
        # Generated files
        summary_lines.append("## Generated Files")
        summary_lines.append("")
        
        # List all generated analysis files
        completed_contexts = [ctx for ctx in self.document_contexts.values() 
                            if ctx.processing_status == ProcessingStatus.COMPLETED]
        
        for context in sorted(completed_contexts, key=lambda x: x.filename):
            output_file = f"{Path(context.filename).stem}_analysis.md"
            summary_lines.append(f"- [{context.filename}]({output_file})")
        
        summary_lines.append("")
        summary_lines.append("## Batch Summary Files")
        summary_lines.append("")
        
        for i, batch_key in enumerate(self.processed_batches, 1):
            summary_file = f"batch{i}_summary.md"
            summary_lines.append(f"- [Batch {i} Summary]({summary_file})")
        
        summary_lines.append("")
        summary_lines.append("---")
        summary_lines.append("*Generated by PDF Knowledge Extractor with Claude Integration*")
        
        # Save final summary
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(summary_lines))
        
        logger.info(f"Generated final summary: processing_summary.md")
        return str(summary_path)