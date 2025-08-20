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
    quality_score: float = 0.0  # Overall quality score (0-1)
    quality_metrics: Dict[str, float] = None  # Detailed quality metrics
    document_type: str = "unknown"  # Detected document type
    processing_difficulty: str = "normal"  # easy, normal, hard, very_hard
    
    # Smart retry and quarantine fields
    quarantined: bool = False  # Whether document is quarantined
    quarantine_reason: Optional[str] = None  # Reason for quarantine
    quarantine_timestamp: Optional[str] = None  # When quarantined
    consecutive_failures: int = 0  # Consecutive failures for this document
    failure_pattern: List[str] = None  # Pattern of failure types
    retry_strategy: str = "standard"  # standard, aggressive, conservative, skip
    next_retry_time: Optional[str] = None  # When to retry next (for quarantined docs)
    success_probability: float = 1.0  # Estimated success probability (0-1)
    
    def __post_init__(self):
        if self.related_documents is None:
            self.related_documents = []
        if self.retry_delays is None:
            self.retry_delays = []
        if self.quality_metrics is None:
            self.quality_metrics = {}
        if self.failure_pattern is None:
            self.failure_pattern = []


@dataclass 
class BatchProgress:
    """Enhanced progress tracking for batch processing with ETA and trends."""
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
    
    # Enhanced tracking fields
    processing_rate_history: List[float] = None  # docs/minute over time
    success_rate_history: List[float] = None  # success rate over time  
    batch_durations: List[float] = None  # time per batch in minutes
    documents_per_minute: float = 0.0
    tokens_per_minute: float = 0.0
    average_doc_processing_time: float = 0.0  # seconds
    time_per_token: float = 0.0  # seconds per token
    
    # Quality and type tracking
    quality_distribution: Dict[str, int] = None  # quality ranges -> count
    type_distribution: Dict[str, int] = None  # doc types -> count
    difficulty_distribution: Dict[str, int] = None  # difficulty -> count
    
    def __post_init__(self):
        if self.processing_rate_history is None:
            self.processing_rate_history = []
        if self.success_rate_history is None:
            self.success_rate_history = []
        if self.batch_durations is None:
            self.batch_durations = []
        if self.quality_distribution is None:
            self.quality_distribution = {}
        if self.type_distribution is None:
            self.type_distribution = {}
        if self.difficulty_distribution is None:
            self.difficulty_distribution = {}
    
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
    
    @property
    def success_rate_trend(self) -> str:
        """Calculate success rate trend over recent history."""
        if len(self.success_rate_history) < 3:
            return "stable"
        
        # Compare last 3 vs previous 3 rates
        recent_rates = self.success_rate_history[-3:]
        earlier_rates = self.success_rate_history[-6:-3] if len(self.success_rate_history) >= 6 else []
        
        if not earlier_rates:
            return "stable"
        
        recent_avg = sum(recent_rates) / len(recent_rates)
        earlier_avg = sum(earlier_rates) / len(earlier_rates)
        
        if recent_avg > earlier_avg + 5:
            return "improving"
        elif recent_avg < earlier_avg - 5:
            return "declining"
        else:
            return "stable"
    
    @property
    def processing_rate_trend(self) -> str:
        """Calculate processing rate trend over recent history."""
        if len(self.processing_rate_history) < 3:
            return "stable"
        
        # Compare last 3 vs previous 3 rates
        recent_rates = self.processing_rate_history[-3:]
        earlier_rates = self.processing_rate_history[-6:-3] if len(self.processing_rate_history) >= 6 else []
        
        if not earlier_rates:
            return "stable"
        
        recent_avg = sum(recent_rates) / len(recent_rates)
        earlier_avg = sum(earlier_rates) / len(earlier_rates)
        
        if recent_avg > earlier_avg * 1.1:
            return "accelerating"
        elif recent_avg < earlier_avg * 0.9:
            return "slowing"
        else:
            return "stable"
    
    def update_processing_metrics(self, elapsed_minutes: float, tokens_processed: int = 0):
        """Update processing rate metrics.
        
        Args:
            elapsed_minutes: Time elapsed since start
            tokens_processed: Total tokens processed so far
        """
        if elapsed_minutes > 0:
            self.documents_per_minute = self.processed_documents / elapsed_minutes
            
            if tokens_processed > 0:
                self.tokens_per_minute = tokens_processed / elapsed_minutes
                self.time_per_token = (elapsed_minutes * 60) / tokens_processed
            
            if self.processed_documents > 0:
                self.average_doc_processing_time = (elapsed_minutes * 60) / self.processed_documents
            
            # Add to history (keep last 20 measurements)
            self.processing_rate_history.append(self.documents_per_minute)
            if len(self.processing_rate_history) > 20:
                self.processing_rate_history.pop(0)
            
            self.success_rate_history.append(self.success_rate)
            if len(self.success_rate_history) > 20:
                self.success_rate_history.pop(0)


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
    
    def calculate_success_probability(self, context: DocumentContext) -> float:
        """Calculate estimated success probability for a document based on its history.
        
        Args:
            context: Document context with retry history
            
        Returns:
            Success probability (0.0 to 1.0)
        """
        base_probability = 0.8  # Base success rate
        
        # Adjust based on retry count
        retry_penalty = min(context.retry_count * 0.15, 0.6)  # Max 60% penalty
        probability = base_probability - retry_penalty
        
        # Adjust based on failure pattern
        if context.failure_pattern:
            # Count different error types
            error_types = set(context.failure_pattern)
            
            # Multiple different error types indicate systemic issues
            if len(error_types) > 2:
                probability *= 0.7
            
            # Check for non-retryable errors
            non_retryable_count = sum(
                1 for error_type in context.failure_pattern
                if error_type in ['CLI_NOT_FOUND', 'CLI_AUTH_ERROR', 'CONTENT_TOO_LARGE']
            )
            if non_retryable_count > 0:
                probability *= 0.3
        
        # Adjust based on document quality
        if hasattr(context, 'quality_score'):
            quality_factor = max(context.quality_score, 0.2)  # Min factor of 0.2
            probability *= quality_factor
        
        # Adjust based on document size/complexity
        if context.estimated_tokens > 50000:  # Very large documents
            probability *= 0.8
        elif context.estimated_tokens > 20000:  # Large documents
            probability *= 0.9
        
        return max(min(probability, 1.0), 0.0)  # Clamp to [0, 1]
    
    def determine_retry_strategy(self, context: DocumentContext) -> str:
        """Determine the best retry strategy for a document.
        
        Args:
            context: Document context
            
        Returns:
            Retry strategy: 'aggressive', 'standard', 'conservative', 'skip'
        """
        success_prob = self.calculate_success_probability(context)
        
        # Skip strategy for very low probability
        if success_prob < 0.2:
            return "skip"
        
        # Conservative strategy for problematic documents
        if (context.consecutive_failures >= 3 or 
            success_prob < 0.4 or
            context.retry_count >= self.max_retries - 1):
            return "conservative"
        
        # Aggressive strategy for high-quality documents with temporary issues
        if (success_prob > 0.7 and 
            context.retry_count <= 1 and
            hasattr(context, 'quality_score') and context.quality_score > 0.8):
            return "aggressive"
        
        # Standard strategy for most cases
        return "standard"
    
    def should_quarantine_document(self, context: DocumentContext, 
                                 error_type: ClaudeErrorType) -> Tuple[bool, str]:
        """Determine if a document should be quarantined.
        
        Args:
            context: Document context
            error_type: Latest error type
            
        Returns:
            Tuple of (should_quarantine, reason)
        """
        # Already quarantined
        if context.quarantined:
            return False, "Already quarantined"
        
        # Immediate quarantine conditions
        if error_type in [ClaudeErrorType.CLI_NOT_FOUND, ClaudeErrorType.CLI_AUTH_ERROR]:
            return True, f"Critical system error: {error_type.value}"
        
        # Quarantine after multiple failures
        if context.consecutive_failures >= 5:
            return True, f"Too many consecutive failures ({context.consecutive_failures})"
        
        # Quarantine if same error type repeats multiple times
        if context.failure_pattern:
            last_error_count = sum(
                1 for err in context.failure_pattern[-3:]  # Last 3 errors
                if err == error_type.value
            )
            if last_error_count >= 3:
                return True, f"Repeated {error_type.value} errors"
        
        # Quarantine very low success probability documents
        success_prob = self.calculate_success_probability(context)
        if success_prob < 0.1:
            return True, f"Very low success probability ({success_prob:.2f})"
        
        return False, "No quarantine needed"
    
    def quarantine_document(self, context: DocumentContext, reason: str) -> None:
        """Quarantine a problematic document.
        
        Args:
            context: Document context
            reason: Reason for quarantine
        """
        context.quarantined = True
        context.quarantine_reason = reason
        context.quarantine_timestamp = datetime.now().isoformat()
        context.processing_status = ProcessingStatus.SKIPPED
        
        # Calculate next retry time (exponential backoff from quarantine)
        quarantine_delay_hours = min(2 ** context.consecutive_failures, 24)  # Max 24 hours
        next_retry = datetime.now() + timedelta(hours=quarantine_delay_hours)
        context.next_retry_time = next_retry.isoformat()
        
        logger.warning(f"Quarantined document {context.filename}: {reason}")
        logger.info(f"Next retry scheduled for: {next_retry.strftime('%Y-%m-%d %H:%M:%S')}")
    
    def check_quarantine_release(self, context: DocumentContext) -> bool:
        """Check if a quarantined document can be released for retry.
        
        Args:
            context: Quarantined document context
            
        Returns:
            True if document can be released from quarantine
        """
        if not context.quarantined or not context.next_retry_time:
            return False
        
        next_retry = datetime.fromisoformat(context.next_retry_time)
        return datetime.now() >= next_retry
    
    def release_from_quarantine(self, context: DocumentContext) -> None:
        """Release a document from quarantine.
        
        Args:
            context: Document context to release
        """
        context.quarantined = False
        context.processing_status = ProcessingStatus.PENDING
        context.next_retry_time = None
        
        # Reset some counters for fresh start
        context.consecutive_failures = max(0, context.consecutive_failures - 1)
        
        logger.info(f"Released {context.filename} from quarantine")
    
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
    
    def calculate_document_quality_score(self, text: str, context: DocumentContext) -> Dict[str, float]:
        """Calculate comprehensive document quality score with detailed metrics.
        
        Args:
            text: Document text content
            context: Document context with metadata
            
        Returns:
            Dictionary with quality metrics and overall score
        """
        metrics = {
            'text_quality': 0.0,
            'extraction_ratio': 0.0,
            'content_density': 0.0,
            'language_quality': 0.0,
            'structure_quality': 0.0,
            'overall_score': 0.0
        }
        
        if not text or not text.strip():
            return metrics
        
        # 1. Text Quality (40% weight)
        alphanumeric_chars = sum(1 for c in text if c.isalnum())
        total_chars = len(text)
        
        if total_chars > 0:
            # Basic alphanumeric ratio
            alphanumeric_ratio = alphanumeric_chars / total_chars
            
            # Adjust for reasonable punctuation and whitespace
            if 0.6 <= alphanumeric_ratio <= 0.9:
                metrics['text_quality'] = 1.0
            elif 0.4 <= alphanumeric_ratio < 0.6:
                metrics['text_quality'] = 0.7
            elif 0.2 <= alphanumeric_ratio < 0.4:
                metrics['text_quality'] = 0.4
            else:
                metrics['text_quality'] = 0.1
        
        # 2. Text Extraction Ratio (25% weight)
        # Compare actual text length to expected based on pages
        expected_chars_per_page = 2500  # Reasonable estimate for text-heavy documents
        expected_total = context.page_count * expected_chars_per_page
        
        if expected_total > 0:
            extraction_ratio = min(len(text) / expected_total, 2.0)  # Cap at 2.0 for dense documents
            
            if extraction_ratio >= 0.8:
                metrics['extraction_ratio'] = 1.0
            elif extraction_ratio >= 0.5:
                metrics['extraction_ratio'] = 0.8
            elif extraction_ratio >= 0.2:
                metrics['extraction_ratio'] = 0.5
            else:
                metrics['extraction_ratio'] = 0.2
        
        # 3. Content Density (15% weight)
        # Check for reasonable word-to-character ratio
        words = text.split()
        if words:
            avg_word_length = len(''.join(words)) / len(words)
            
            # Reasonable average word length is 4-8 characters
            if 4 <= avg_word_length <= 8:
                metrics['content_density'] = 1.0
            elif 3 <= avg_word_length < 4 or 8 < avg_word_length <= 12:
                metrics['content_density'] = 0.7
            else:
                metrics['content_density'] = 0.3
        
        # 4. Language Quality (10% weight)
        # Check for excessive repetition and gibberish
        if len(words) > 50:
            unique_words = len(set(word.lower() for word in words))
            unique_ratio = unique_words / len(words)
            
            if unique_ratio >= 0.4:
                metrics['language_quality'] = 1.0
            elif unique_ratio >= 0.2:
                metrics['language_quality'] = 0.6
            elif unique_ratio >= 0.1:
                metrics['language_quality'] = 0.3
            else:
                metrics['language_quality'] = 0.1
        else:
            metrics['language_quality'] = 0.8  # Give benefit of doubt for short texts
        
        # 5. Structure Quality (10% weight)
        # Look for structural elements that indicate proper text extraction
        structure_indicators = [
            r'\n\n',  # Paragraph breaks
            r'[.!?]\s+[A-Z]',  # Sentence boundaries
            r':\s*\n',  # Lists or definitions
            r'^\s*\d+\.',  # Numbered lists
            r'^\s*[•\-\*]',  # Bullet points
        ]
        
        structure_score = 0
        for pattern in structure_indicators:
            import re
            if re.search(pattern, text):
                structure_score += 0.2
        
        metrics['structure_quality'] = min(structure_score, 1.0)
        
        # Calculate overall weighted score
        weights = {
            'text_quality': 0.40,
            'extraction_ratio': 0.25,
            'content_density': 0.15,
            'language_quality': 0.10,
            'structure_quality': 0.10
        }
        
        metrics['overall_score'] = sum(
            metrics[metric] * weight 
            for metric, weight in weights.items()
        )
        
        return metrics

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
    
    def detect_document_type(self, text: str, context: DocumentContext) -> str:
        """Detect document type based on content analysis.
        
        Args:
            text: Document text content
            context: Document context with metadata
            
        Returns:
            Detected document type (academic, business, technical, creative, legal, etc.)
        """
        if not text:
            return "unknown"
        
        text_lower = text.lower()
        
        # Academic indicators
        academic_keywords = [
            'abstract', 'methodology', 'literature review', 'hypothesis', 'research',
            'citation', 'bibliography', 'peer review', 'journal', 'publication',
            'experiment', 'data analysis', 'statistical', 'study', 'findings',
            'conclusion', 'university', 'professor', 'phd', 'doctoral'
        ]
        
        # Business indicators  
        business_keywords = [
            'revenue', 'profit', 'market', 'business plan', 'strategy', 'roi',
            'investment', 'financial', 'quarterly', 'annual report', 'stakeholder',
            'executive summary', 'kpi', 'metrics', 'corporate', 'company',
            'organization', 'management', 'board of directors', 'shareholder'
        ]
        
        # Technical indicators
        technical_keywords = [
            'algorithm', 'implementation', 'system', 'architecture', 'framework',
            'api', 'database', 'server', 'client', 'protocol', 'specification',
            'technical', 'engineering', 'software', 'hardware', 'documentation',
            'manual', 'guide', 'tutorial', 'installation', 'configuration'
        ]
        
        # Legal indicators
        legal_keywords = [
            'contract', 'agreement', 'clause', 'provision', 'legal', 'law',
            'regulation', 'compliance', 'terms', 'conditions', 'liability',
            'warranty', 'intellectual property', 'copyright', 'patent',
            'litigation', 'court', 'judge', 'jury', 'counsel'
        ]
        
        # Creative indicators
        creative_keywords = [
            'story', 'narrative', 'character', 'plot', 'theme', 'creative',
            'artistic', 'design', 'aesthetic', 'poetry', 'novel', 'fiction',
            'non-fiction', 'memoir', 'autobiography', 'biography', 'essay'
        ]
        
        # Count keyword matches
        keyword_counts = {
            'academic': sum(1 for kw in academic_keywords if kw in text_lower),
            'business': sum(1 for kw in business_keywords if kw in text_lower),
            'technical': sum(1 for kw in technical_keywords if kw in text_lower),
            'legal': sum(1 for kw in legal_keywords if kw in text_lower),
            'creative': sum(1 for kw in creative_keywords if kw in text_lower)
        }
        
        # Determine document type based on highest keyword count
        if max(keyword_counts.values()) == 0:
            return "general"
        
        return max(keyword_counts.items(), key=lambda x: x[1])[0]
    
    def should_filter_document(self, context: DocumentContext, text: str) -> Tuple[bool, str]:
        """Determine if document should be filtered before Claude processing using advanced quality scoring.
        
        Args:
            context: Document context
            text: Document text
            
        Returns:
            Tuple of (should_filter, reason)
        """
        # Check if already filtered
        if context.content_filtered:
            return False, "Already filtered"
        
        # Get quality threshold from config
        quality_threshold = self.config.get('claude', {}).get('quality_threshold', 0.5)
        
        # Calculate comprehensive quality score
        quality_metrics = self.calculate_document_quality_score(text, context)
        overall_score = quality_metrics['overall_score']
        
        # Store quality metrics in context for later reference
        context.quality_score = overall_score
        context.quality_metrics = quality_metrics
        
        # Very large documents - size-based filtering
        if context.size_mb > 50:  # 50MB+ files
            return True, f"File too large (>50MB) - Quality: {overall_score:.2f}"
        
        # Too many pages (likely scanned documents with poor text extraction)  
        if context.page_count > 500:
            return True, f"Too many pages (>500) - Quality: {overall_score:.2f}"
        
        # Quality-based filtering
        if overall_score < quality_threshold:
            # Provide detailed reason based on weakest metric
            weak_metrics = [
                (metric, score) for metric, score in quality_metrics.items()
                if metric != 'overall_score' and score < 0.3
            ]
            
            if weak_metrics:
                weakest_metric, weakest_score = min(weak_metrics, key=lambda x: x[1])
                reason = f"Low quality score ({overall_score:.2f} < {quality_threshold}) - Weak {weakest_metric}: {weakest_score:.2f}"
            else:
                reason = f"Low quality score ({overall_score:.2f} < {quality_threshold})"
            
            return True, reason
        
        # Detect document type for processing optimization
        doc_type = self.detect_document_type(text, context)
        context.document_type = doc_type
        
        # Special handling for certain document types
        if doc_type == "unknown" and overall_score < 0.7:
            return True, f"Unknown document type with moderate quality ({overall_score:.2f})"
        
        # Text quality issues (fallback)
        is_valid, reason = self.validate_text_quality(text)
        if not is_valid:
            return True, f"Text validation failed: {reason} - Quality: {overall_score:.2f}"
        
        return False, f"Document passes filtering - Quality: {overall_score:.2f}, Type: {doc_type}"
    
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
    
    def calculate_adaptive_batch_size(self, context: DocumentContext) -> int:
        """Calculate adaptive batch size based on document complexity.
        
        Args:
            context: Document context with complexity metrics
            
        Returns:
            Recommended batch size for this document type
        """
        # Base batch size from configuration
        base_batch_size = self.batch_size
        
        # Small documents (< 5k tokens): batches of 8-10
        if context.estimated_tokens < 5000:
            return min(base_batch_size * 2, 10)
        
        # Medium documents (5k-20k tokens): batches of 3-5
        elif context.estimated_tokens < 20000:
            return min(base_batch_size, 5)
        
        # Large documents (20k+ tokens): batches of 1-2
        else:
            return min(base_batch_size // 2, 2)
    
    def group_documents_by_complexity(self) -> Dict[str, List[Tuple[str, DocumentContext]]]:
        """Group documents by complexity for intelligent batching.
        
        Returns:
            Dictionary mapping complexity level to list of (path, context) tuples
        """
        complexity_groups = {
            'small': [],    # < 5k tokens
            'medium': [],   # 5k-20k tokens  
            'large': [],    # 20k+ tokens
            'failed': []    # Previously failed documents
        }
        
        for path, context in self.document_contexts.items():
            if context.processing_status != ProcessingStatus.PENDING:
                continue
                
            # Group failed documents separately for special handling
            if context.retry_count > 0:
                complexity_groups['failed'].append((path, context))
            elif context.estimated_tokens < 5000:
                complexity_groups['small'].append((path, context))
            elif context.estimated_tokens < 20000:
                complexity_groups['medium'].append((path, context))
            else:
                complexity_groups['large'].append((path, context))
        
        return complexity_groups

    def create_batches(self) -> List[List[str]]:
        """Create processing batches with intelligent sizing based on document complexity.
        
        Returns:
            List of batches, each batch is a list of document paths
        """
        batches = []
        
        # Check if adaptive batching is enabled
        adaptive_batching = self.config.get('claude', {}).get('adaptive_batching', True)
        
        if not adaptive_batching:
            # Fall back to original batching logic
            return self._create_simple_batches()
        
        # Group documents by complexity
        complexity_groups = self.group_documents_by_complexity()
        
        # Process each complexity group with appropriate batch sizes
        for complexity_level, docs in complexity_groups.items():
            if not docs:
                continue
                
            logger.info(f"Creating batches for {len(docs)} {complexity_level} documents")
            
            # Sort documents within group (smaller first for better progress tracking)
            docs.sort(key=lambda x: x[1].estimated_tokens)
            
            current_batch = []
            current_batch_tokens = 0
            
            for file_path, context in docs:
                # Calculate adaptive batch size for this document type
                adaptive_size = self.calculate_adaptive_batch_size(context)
                
                # Calculate token limit based on document complexity
                if complexity_level == 'large':
                    # Large documents: be more conservative with token limits
                    token_limit = self.max_tokens_per_request // 2
                elif complexity_level == 'failed':
                    # Failed documents: process individually for easier debugging
                    token_limit = context.estimated_tokens + 1000  # Small buffer
                    adaptive_size = 1
                else:
                    # Small/medium documents: use normal token limits
                    token_limit = self.max_tokens_per_request
                
                # Check if adding this document would exceed limits
                would_exceed_count = len(current_batch) >= adaptive_size
                would_exceed_tokens = current_batch_tokens + context.estimated_tokens > token_limit
                
                if (would_exceed_count or would_exceed_tokens) and current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_batch_tokens = 0
                
                current_batch.append(file_path)
                current_batch_tokens += context.estimated_tokens
            
            # Add final batch for this complexity group
            if current_batch:
                batches.append(current_batch)
        
        # Log batch statistics
        self._log_batch_statistics(batches, complexity_groups)
        
        return batches
    
    def _create_simple_batches(self) -> List[List[str]]:
        """Create simple batches using original logic (fallback).
        
        Returns:
            List of batches using original batching algorithm
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
        
        logger.info(f"Created {len(batches)} simple processing batches")
        return batches
    
    def _log_batch_statistics(self, batches: List[List[str]], 
                            complexity_groups: Dict[str, List[Tuple[str, DocumentContext]]]) -> None:
        """Log detailed statistics about created batches.
        
        Args:
            batches: Created batches
            complexity_groups: Document groups by complexity
        """
        total_docs = sum(len(group) for group in complexity_groups.values())
        
        # Calculate batch size statistics
        batch_sizes = [len(batch) for batch in batches]
        avg_batch_size = sum(batch_sizes) / len(batch_sizes) if batch_sizes else 0
        
        # Calculate token statistics
        batch_tokens = []
        for batch in batches:
            batch_token_count = sum(
                self.document_contexts[path].estimated_tokens 
                for path in batch
            )
            batch_tokens.append(batch_token_count)
        
        avg_batch_tokens = sum(batch_tokens) / len(batch_tokens) if batch_tokens else 0
        
        logger.info(f"Adaptive batch creation summary:")
        logger.info(f"  Total documents: {total_docs}")
        logger.info(f"  Small docs (<5k tokens): {len(complexity_groups['small'])}")
        logger.info(f"  Medium docs (5k-20k tokens): {len(complexity_groups['medium'])}")
        logger.info(f"  Large docs (20k+ tokens): {len(complexity_groups['large'])}")
        logger.info(f"  Previously failed docs: {len(complexity_groups['failed'])}")
        logger.info(f"  Total batches created: {len(batches)}")
        logger.info(f"  Average batch size: {avg_batch_size:.1f} documents")
        logger.info(f"  Average tokens per batch: {avg_batch_tokens:,.0f}")
        
        if batch_sizes:
            logger.info(f"  Batch size range: {min(batch_sizes)}-{max(batch_sizes)} documents")
        if batch_tokens:
            logger.info(f"  Token range per batch: {min(batch_tokens):,}-{max(batch_tokens):,}")
    
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
                    
                    # Update failure tracking
                    context.consecutive_failures += 1
                    context.failure_pattern.append(claude_error.error_type.value)
                    
                    # Keep only last 10 failure patterns to avoid memory bloat
                    if len(context.failure_pattern) > 10:
                        context.failure_pattern.pop(0)
                    
                    # Update success probability
                    context.success_probability = self.calculate_success_probability(context)
                    
                    # Determine retry strategy
                    context.retry_strategy = self.determine_retry_strategy(context)
                    
                    # Check for quarantine
                    should_quarantine, quarantine_reason = self.should_quarantine_document(
                        context, claude_error.error_type
                    )
                    
                    if should_quarantine:
                        self.quarantine_document(context, quarantine_reason)
                        return False, f"Document quarantined: {quarantine_reason}"
                    
                    # Check if error is retryable
                    if not claude_error.is_retryable:
                        logger.error(f"Non-retryable error for {context.filename}: {claude_error.error_type.value} - {e}")
                        context.processing_status = ProcessingStatus.FAILED
                        context.processing_end = datetime.now().isoformat()
                        return False, f"Non-retryable error: {str(e)}"
                    
                    # Check retry strategy
                    if context.retry_strategy == "skip":
                        logger.warning(f"Skipping {context.filename} due to low success probability ({context.success_probability:.2f})")
                        context.processing_status = ProcessingStatus.SKIPPED
                        context.processing_end = datetime.now().isoformat()
                        return False, f"Skipped due to low success probability: {str(e)}"
                    
                except Exception:
                    # Fallback error categorization
                    claude_error = ClaudeError(
                        error_type=ClaudeErrorType.UNKNOWN_ERROR,
                        message=str(e),
                        is_retryable=True
                    )
                    context.last_error_type = claude_error.error_type
                    context.consecutive_failures += 1
                
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
                    # Calculate intelligent backoff delay based on retry strategy
                    base_delay = self.calculate_exponential_backoff(attempt, claude_error.error_type)
                    
                    # Adjust delay based on retry strategy
                    strategy_multipliers = {
                        "aggressive": 0.5,    # Retry faster
                        "standard": 1.0,      # Normal delay
                        "conservative": 2.0,  # Wait longer
                    }
                    
                    strategy_multiplier = strategy_multipliers.get(context.retry_strategy, 1.0)
                    delay = base_delay * strategy_multiplier
                    
                    # Use specific retry delay for certain errors
                    if claude_error.retry_after:
                        delay = max(delay, claude_error.retry_after)
                    
                    # Additional delay for consecutive failures
                    if context.consecutive_failures > 2:
                        failure_multiplier = 1.0 + (context.consecutive_failures - 2) * 0.3
                        delay *= failure_multiplier
                    
                    context.retry_delays.append(delay)
                    
                    logger.warning(f"Attempt {attempt + 1} failed for {context.filename} "
                                 f"({claude_error.error_type.value}), strategy: {context.retry_strategy}, "
                                 f"probability: {context.success_probability:.2f}, "
                                 f"retrying in {delay:.1f}s: {e}")
                    
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
        """Update enhanced batch progress tracking with detailed metrics.
        
        Args:
            batch_number: Current batch number
            total_batches: Total number of batches
        """
        if not self.batch_progress:
            return
        
        # Count documents by status
        processed = sum(1 for ctx in self.document_contexts.values() 
                       if ctx.processing_status == ProcessingStatus.COMPLETED)
        failed = sum(1 for ctx in self.document_contexts.values() 
                    if ctx.processing_status == ProcessingStatus.FAILED)
        skipped = sum(1 for ctx in self.document_contexts.values() 
                     if ctx.processing_status == ProcessingStatus.SKIPPED)
        
        self.batch_progress.processed_documents = processed
        self.batch_progress.failed_documents = failed
        self.batch_progress.skipped_documents = skipped
        self.batch_progress.current_batch = batch_number
        self.batch_progress.total_batches = total_batches
        self.batch_progress.last_update = datetime.now().isoformat()
        
        # Calculate elapsed time
        start_time = datetime.fromisoformat(self.batch_progress.start_time)
        elapsed = datetime.now() - start_time
        elapsed_minutes = elapsed.total_seconds() / 60
        
        # Calculate total tokens processed
        total_tokens = sum(
            ctx.estimated_tokens for ctx in self.document_contexts.values()
            if ctx.processing_status == ProcessingStatus.COMPLETED
        )
        
        # Update processing metrics
        self.batch_progress.update_processing_metrics(elapsed_minutes, total_tokens)
        
        # Update quality and type distributions
        self._update_distribution_metrics()
        
        # Enhanced ETA calculation with trend consideration
        if processed > 0:
            # Base ETA calculation
            avg_time_per_doc = elapsed.total_seconds() / processed
            remaining_docs = self.batch_progress.total_documents - processed - failed - skipped
            
            # Adjust for processing rate trend
            rate_trend = self.batch_progress.processing_rate_trend
            rate_multiplier = 1.0
            
            if rate_trend == "accelerating":
                rate_multiplier = 0.9  # 10% faster
            elif rate_trend == "slowing":
                rate_multiplier = 1.1  # 10% slower
            
            # Consider success rate trend for retry overhead
            success_trend = self.batch_progress.success_rate_trend
            if success_trend == "declining":
                rate_multiplier *= 1.2  # 20% more time for retries
            
            adjusted_time_per_doc = avg_time_per_doc * rate_multiplier
            estimated_seconds = remaining_docs * adjusted_time_per_doc
            
            # Add buffer based on Claude health status
            health_buffer = {
                "healthy": 1.0,
                "degraded": 1.2,
                "unhealthy": 1.5
            }.get(self.batch_progress.claude_health_status, 1.1)
            
            estimated_seconds *= health_buffer
            
            estimated_completion = datetime.now() + timedelta(seconds=estimated_seconds)
            self.batch_progress.estimated_completion = estimated_completion.isoformat()
    
    def _update_distribution_metrics(self) -> None:
        """Update quality, type, and difficulty distribution metrics."""
        if not self.batch_progress:
            return
        
        # Reset distributions
        self.batch_progress.quality_distribution = {
            "high (0.8-1.0)": 0,
            "good (0.6-0.8)": 0,
            "fair (0.4-0.6)": 0,
            "poor (0.2-0.4)": 0,
            "very_poor (0.0-0.2)": 0
        }
        
        self.batch_progress.type_distribution = {}
        self.batch_progress.difficulty_distribution = {
            "easy": 0,
            "normal": 0, 
            "hard": 0,
            "very_hard": 0
        }
        
        # Count distributions from all document contexts
        for context in self.document_contexts.values():
            # Quality distribution
            if hasattr(context, 'quality_score'):
                score = context.quality_score
                if score >= 0.8:
                    self.batch_progress.quality_distribution["high (0.8-1.0)"] += 1
                elif score >= 0.6:
                    self.batch_progress.quality_distribution["good (0.6-0.8)"] += 1
                elif score >= 0.4:
                    self.batch_progress.quality_distribution["fair (0.4-0.6)"] += 1
                elif score >= 0.2:
                    self.batch_progress.quality_distribution["poor (0.2-0.4)"] += 1
                else:
                    self.batch_progress.quality_distribution["very_poor (0.0-0.2)"] += 1
            
            # Document type distribution
            if hasattr(context, 'document_type'):
                doc_type = context.document_type
                self.batch_progress.type_distribution[doc_type] = \
                    self.batch_progress.type_distribution.get(doc_type, 0) + 1
            
            # Processing difficulty distribution
            if hasattr(context, 'processing_difficulty'):
                difficulty = context.processing_difficulty
                if difficulty in self.batch_progress.difficulty_distribution:
                    self.batch_progress.difficulty_distribution[difficulty] += 1
    
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
        
        # Generate final summary and performance report
        self.generate_final_summary(total_successful, total_failed)
        self.generate_performance_report()
        
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
    
    def generate_performance_report(self) -> str:
        """Generate detailed performance report with metrics and insights.
        
        Returns:
            Path to generated performance report
        """
        if not self.output_directory:
            return ""
        
        report_path = self.output_directory / "performance_report.md"
        
        # Calculate comprehensive metrics
        start_time = datetime.fromisoformat(self.batch_progress.start_time)
        end_time = datetime.now()
        total_duration = end_time - start_time
        
        # Document statistics
        total_docs = len(self.document_contexts)
        completed_docs = len([ctx for ctx in self.document_contexts.values() 
                            if ctx.processing_status == ProcessingStatus.COMPLETED])
        failed_docs = len([ctx for ctx in self.document_contexts.values() 
                         if ctx.processing_status == ProcessingStatus.FAILED])
        skipped_docs = len([ctx for ctx in self.document_contexts.values() 
                          if ctx.processing_status == ProcessingStatus.SKIPPED])
        quarantined_docs = len([ctx for ctx in self.document_contexts.values() 
                              if ctx.quarantined])
        
        # Quality and type analysis
        quality_metrics = self._analyze_quality_performance()
        type_performance = self._analyze_type_performance()
        retry_analysis = self._analyze_retry_patterns()
        
        # Performance metrics
        total_tokens = sum(ctx.estimated_tokens for ctx in self.document_contexts.values() 
                          if ctx.processing_status == ProcessingStatus.COMPLETED)
        
        avg_processing_time = (total_duration.total_seconds() / completed_docs) if completed_docs > 0 else 0
        tokens_per_second = total_tokens / total_duration.total_seconds() if total_duration.total_seconds() > 0 else 0
        
        report_lines = []
        report_lines.append("# PDF Knowledge Extractor - Performance Report")
        report_lines.append("")
        report_lines.append(f"**Generated**: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append(f"**Processing Duration**: {str(total_duration).split('.')[0]}")
        report_lines.append("")
        
        # Executive Summary
        report_lines.append("## Executive Summary")
        report_lines.append("")
        success_rate = (completed_docs / total_docs * 100) if total_docs > 0 else 0
        report_lines.append(f"- **Overall Success Rate**: {success_rate:.1f}% ({completed_docs}/{total_docs} documents)")
        report_lines.append(f"- **Processing Speed**: {self.batch_progress.documents_per_minute:.1f} docs/min, {tokens_per_second:.0f} tokens/sec")
        report_lines.append(f"- **Average Processing Time**: {avg_processing_time:.1f} seconds per document")
        report_lines.append(f"- **Total Tokens Processed**: {total_tokens:,}")
        report_lines.append(f"- **Failed Documents**: {failed_docs} ({failed_docs/total_docs*100:.1f}%)")
        report_lines.append(f"- **Quarantined Documents**: {quarantined_docs}")
        report_lines.append("")
        
        # Processing Trends
        if len(self.batch_progress.success_rate_history) > 1:
            report_lines.append("## Processing Trends")
            report_lines.append("")
            report_lines.append(f"- **Success Rate Trend**: {self.batch_progress.success_rate_trend}")
            report_lines.append(f"- **Processing Rate Trend**: {self.batch_progress.processing_rate_trend}")
            
            if self.batch_progress.rate_limit_hits > 0:
                report_lines.append(f"- **Rate Limit Hits**: {self.batch_progress.rate_limit_hits}")
            
            if self.batch_progress.consecutive_failures > 0:
                report_lines.append(f"- **Peak Consecutive Failures**: {self.batch_progress.consecutive_failures}")
            
            report_lines.append("")
        
        # Quality Performance Analysis
        report_lines.extend(quality_metrics)
        
        # Document Type Performance
        report_lines.extend(type_performance)
        
        # Retry and Error Analysis
        report_lines.extend(retry_analysis)
        
        # Batch Performance
        if self.batch_progress.batch_durations:
            report_lines.append("## Batch Performance")
            report_lines.append("")
            avg_batch_time = sum(self.batch_progress.batch_durations) / len(self.batch_progress.batch_durations)
            min_batch_time = min(self.batch_progress.batch_durations)
            max_batch_time = max(self.batch_progress.batch_durations)
            
            report_lines.append(f"- **Total Batches**: {len(self.batch_progress.batch_durations)}")
            report_lines.append(f"- **Average Batch Time**: {avg_batch_time:.1f} minutes")
            report_lines.append(f"- **Fastest Batch**: {min_batch_time:.1f} minutes")
            report_lines.append(f"- **Slowest Batch**: {max_batch_time:.1f} minutes")
            report_lines.append("")
        
        # Recommendations
        report_lines.append("## Performance Recommendations")
        report_lines.append("")
        
        recommendations = self._generate_performance_recommendations(
            success_rate, total_docs, failed_docs, quarantined_docs, 
            quality_metrics, type_performance
        )
        
        for rec in recommendations:
            report_lines.append(f"- {rec}")
        
        report_lines.append("")
        report_lines.append("---")
        report_lines.append("*Generated by PDF Knowledge Extractor Performance Monitor*")
        
        # Save report
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(report_lines))
        
        logger.info(f"Generated performance report: performance_report.md")
        return str(report_path)
    
    def _analyze_quality_performance(self) -> List[str]:
        """Analyze performance by document quality."""
        lines = []
        lines.append("## Quality Performance Analysis")
        lines.append("")
        
        quality_performance = {
            "high": {"total": 0, "completed": 0, "failed": 0},
            "medium": {"total": 0, "completed": 0, "failed": 0},
            "low": {"total": 0, "completed": 0, "failed": 0}
        }
        
        for ctx in self.document_contexts.values():
            if hasattr(ctx, 'quality_score'):
                if ctx.quality_score >= 0.7:
                    quality_level = "high"
                elif ctx.quality_score >= 0.4:
                    quality_level = "medium"
                else:
                    quality_level = "low"
                
                quality_performance[quality_level]["total"] += 1
                if ctx.processing_status == ProcessingStatus.COMPLETED:
                    quality_performance[quality_level]["completed"] += 1
                elif ctx.processing_status == ProcessingStatus.FAILED:
                    quality_performance[quality_level]["failed"] += 1
        
        for quality_level, stats in quality_performance.items():
            if stats["total"] > 0:
                success_rate = (stats["completed"] / stats["total"]) * 100
                lines.append(f"**{quality_level.title()} Quality Documents**:")
                lines.append(f"- Total: {stats['total']}")
                lines.append(f"- Success Rate: {success_rate:.1f}%")
                lines.append(f"- Completed: {stats['completed']}, Failed: {stats['failed']}")
                lines.append("")
        
        return lines
    
    def _analyze_type_performance(self) -> List[str]:
        """Analyze performance by document type."""
        lines = []
        lines.append("## Document Type Performance")
        lines.append("")
        
        type_performance = {}
        
        for ctx in self.document_contexts.values():
            if hasattr(ctx, 'document_type'):
                doc_type = ctx.document_type
                if doc_type not in type_performance:
                    type_performance[doc_type] = {"total": 0, "completed": 0, "failed": 0}
                
                type_performance[doc_type]["total"] += 1
                if ctx.processing_status == ProcessingStatus.COMPLETED:
                    type_performance[doc_type]["completed"] += 1
                elif ctx.processing_status == ProcessingStatus.FAILED:
                    type_performance[doc_type]["failed"] += 1
        
        # Sort by success rate
        sorted_types = sorted(
            type_performance.items(),
            key=lambda x: (x[1]["completed"] / x[1]["total"]) if x[1]["total"] > 0 else 0,
            reverse=True
        )
        
        for doc_type, stats in sorted_types:
            if stats["total"] > 0:
                success_rate = (stats["completed"] / stats["total"]) * 100
                lines.append(f"**{doc_type.title()} Documents**:")
                lines.append(f"- Success Rate: {success_rate:.1f}% ({stats['completed']}/{stats['total']})")
                lines.append("")
        
        return lines
    
    def _analyze_retry_patterns(self) -> List[str]:
        """Analyze retry patterns and error types."""
        lines = []
        lines.append("## Retry and Error Analysis")
        lines.append("")
        
        error_types = {}
        retry_stats = {"no_retries": 0, "1_retry": 0, "2_retries": 0, "3_plus_retries": 0}
        total_retries = 0
        
        for ctx in self.document_contexts.values():
            # Count retry patterns
            if ctx.retry_count == 0:
                retry_stats["no_retries"] += 1
            elif ctx.retry_count == 1:
                retry_stats["1_retry"] += 1
            elif ctx.retry_count == 2:
                retry_stats["2_retries"] += 1
            else:
                retry_stats["3_plus_retries"] += 1
            
            total_retries += ctx.retry_count
            
            # Count error types
            if ctx.last_error_type:
                error_type = ctx.last_error_type.value
                error_types[error_type] = error_types.get(error_type, 0) + 1
        
        lines.append("**Retry Distribution**:")
        for retry_category, count in retry_stats.items():
            lines.append(f"- {retry_category.replace('_', ' ').title()}: {count} documents")
        lines.append(f"- Total Retries: {total_retries}")
        lines.append("")
        
        if error_types:
            lines.append("**Most Common Error Types**:")
            sorted_errors = sorted(error_types.items(), key=lambda x: x[1], reverse=True)
            for error_type, count in sorted_errors[:5]:  # Top 5 errors
                lines.append(f"- {error_type}: {count} occurrences")
            lines.append("")
        
        return lines
    
    def _generate_performance_recommendations(self, success_rate: float, total_docs: int, 
                                           failed_docs: int, quarantined_docs: int,
                                           quality_metrics: List[str], 
                                           type_performance: List[str]) -> List[str]:
        """Generate performance improvement recommendations."""
        recommendations = []
        
        # Success rate recommendations
        if success_rate < 70:
            recommendations.append("🔴 Low success rate detected - consider using --quality-threshold to filter problematic documents")
        
        if failed_docs > total_docs * 0.2:
            recommendations.append("🟠 High failure rate - consider using --skip-failed to avoid retry overhead")
        
        if quarantined_docs > 0:
            recommendations.append(f"⚠️ {quarantined_docs} documents quarantined - review quarantine reasons and consider document preprocessing")
        
        # Rate limit recommendations
        if self.batch_progress.rate_limit_hits > 5:
            recommendations.append("🐌 Multiple rate limits hit - consider reducing batch size or increasing delays")
        
        # Processing speed recommendations
        if self.batch_progress.documents_per_minute < 2:
            recommendations.append("⏱️ Slow processing speed - consider using --fast-mode or --adaptive-batching")
        
        # Quality-based recommendations
        low_quality_count = len([ctx for ctx in self.document_contexts.values() 
                               if hasattr(ctx, 'quality_score') and ctx.quality_score < 0.4])
        if low_quality_count > total_docs * 0.3:
            recommendations.append("📉 Many low-quality documents - consider preprocessing or quality filtering")
        
        # Token efficiency
        if self.batch_progress.time_per_token > 0.01:  # >10ms per token
            recommendations.append("🔢 High time per token - consider optimizing document preprocessing")
        
        if not recommendations:
            recommendations.append("✅ Performance looks good! No major issues detected.")
        
        return recommendations