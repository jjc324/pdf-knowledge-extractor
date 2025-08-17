"""
PDF analysis and extraction functionality.

Refactored from the original pdf_analyzer.py to provide comprehensive
PDF analysis including size checking, page counting, text extraction,
and categorization for processing workflows.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

from .utils import create_output_directory, validate_pdf_path

logger = logging.getLogger(__name__)


class PDFExtractor:
    """Extract text and analyze PDF documents with comprehensive analysis capabilities."""
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize the PDF extractor with configuration.
        
        Args:
            config: Configuration dictionary with analysis parameters
        """
        self.config = config or {}
        
        # Analysis limits from config
        analysis_config = self.config.get('analysis', {})
        self.max_size_mb = analysis_config.get('max_size_mb', 10.0)
        self.max_pages = analysis_config.get('max_pages', 100)
        self.max_size_bytes = self.max_size_mb * 1024 * 1024
        
        # Progress tracking
        self.enable_progress = self.config.get('progress', {}).get('enabled', True)
        
        # Resume capability
        self.resume_file = None
        self.processed_files = set()
        
        # Results storage
        self.results = {
            'processable': [],
            'special_handling': [],
            'errors': [],
            'metadata': {
                'total_analyzed': 0,
                'total_size_bytes': 0,
                'total_pages': 0,
                'max_size_mb': self.max_size_mb,
                'max_pages': self.max_pages
            }
        }
        
        if PyPDF2 is None:
            logger.error("PyPDF2 is required for PDF analysis. Install with: pip install PyPDF2")
            raise ImportError("PyPDF2 is required for PDF analysis")
    
    def setup_resume(self, resume_file: Union[str, Path]) -> None:
        """Setup resume capability by loading previous progress.
        
        Args:
            resume_file: Path to resume file for tracking progress
        """
        self.resume_file = Path(resume_file)
        
        if self.resume_file.exists():
            try:
                with open(self.resume_file, 'r') as f:
                    resume_data = json.load(f)
                    self.processed_files = set(resume_data.get('processed_files', []))
                    logger.info(f"Resuming analysis - {len(self.processed_files)} files already processed")
            except Exception as e:
                logger.warning(f"Could not load resume file: {e}")
                self.processed_files = set()
    
    def save_resume_state(self) -> None:
        """Save current progress to resume file."""
        if self.resume_file:
            try:
                resume_data = {
                    'processed_files': list(self.processed_files),
                    'last_updated': str(Path().cwd())
                }
                with open(self.resume_file, 'w') as f:
                    json.dump(resume_data, f, indent=2)
            except Exception as e:
                logger.warning(f"Could not save resume state: {e}")
    
    def get_file_size(self, file_path: Path) -> int:
        """Get file size in bytes.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            File size in bytes
        """
        return file_path.stat().st_size
    
    def get_page_count(self, file_path: Path) -> int:
        """Get PDF page count.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Number of pages in the PDF
            
        Raises:
            Exception: If PDF cannot be read
        """
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                return len(pdf_reader.pages)
        except Exception as e:
            raise Exception(f"Failed to read PDF: {str(e)}")
    
    def extract_text(self, pdf_path: Union[str, Path]) -> str:
        """Extract plain text from a PDF file.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Extracted text content
        """
        file_path = Path(pdf_path)
        validate_pdf_path(str(file_path))
        
        try:
            text_content = []
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                for page in pdf_reader.pages:
                    try:
                        text_content.append(page.extract_text())
                    except Exception as e:
                        logger.warning(f"Could not extract text from page: {e}")
                        continue
            
            return "\n".join(text_content)
            
        except Exception as e:
            logger.error(f"Failed to extract text from {pdf_path}: {e}")
            raise
    
    def analyze_file(self, file_path: Path) -> Dict:
        """Analyze a single PDF file for size, pages, and content.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Dictionary containing analysis results
        """
        try:
            file_size = self.get_file_size(file_path)
            page_count = self.get_page_count(file_path)
            
            file_info = {
                'path': str(file_path),
                'filename': file_path.name,
                'size_bytes': file_size,
                'size_mb': round(file_size / (1024 * 1024), 2),
                'page_count': page_count,
                'exceeds_size_limit': file_size > self.max_size_bytes,
                'exceeds_page_limit': page_count > self.max_pages,
                'last_modified': file_path.stat().st_mtime
            }
            
            # Update metadata
            self.results['metadata']['total_analyzed'] += 1
            self.results['metadata']['total_size_bytes'] += file_size
            self.results['metadata']['total_pages'] += page_count
            
            # Determine if file needs special handling
            needs_special_handling = (
                file_info['exceeds_size_limit'] or 
                file_info['exceeds_page_limit']
            )
            
            if needs_special_handling:
                file_info['reason'] = []
                if file_info['exceeds_size_limit']:
                    file_info['reason'].append(
                        f"Size {file_info['size_mb']}MB exceeds {self.max_size_mb}MB limit"
                    )
                if file_info['exceeds_page_limit']:
                    file_info['reason'].append(
                        f"Page count {page_count} exceeds {self.max_pages} limit"
                    )
                
                self.results['special_handling'].append(file_info)
            else:
                self.results['processable'].append(file_info)
            
            # Mark as processed for resume capability
            self.processed_files.add(str(file_path))
            
            return file_info
            
        except Exception as e:
            error_info = {
                'path': str(file_path),
                'filename': file_path.name,
                'error': str(e),
                'error_type': type(e).__name__
            }
            self.results['errors'].append(error_info)
            logger.error(f"Failed to analyze {file_path}: {e}")
            return error_info
    
    def extract_with_metadata(self, pdf_path: Union[str, Path]) -> Dict:
        """Extract text along with metadata from a PDF file.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            Dictionary containing text and metadata
        """
        file_path = Path(pdf_path)
        analysis = self.analyze_file(file_path)
        
        # If analysis succeeded and file is processable, extract text
        if 'error' not in analysis and analysis['path'] in [f['path'] for f in self.results['processable']]:
            try:
                text = self.extract_text(file_path)
                analysis['text'] = text
                analysis['text_length'] = len(text)
                analysis['has_text'] = bool(text.strip())
            except Exception as e:
                analysis['text_extraction_error'] = str(e)
                logger.warning(f"Could not extract text from {pdf_path}: {e}")
        
        return analysis
    
    def analyze_directory(self, directory: Union[str, Path], recursive: bool = False) -> Dict:
        """Analyze all PDF files in a directory.
        
        Args:
            directory: Directory containing PDF files
            recursive: Whether to search subdirectories
            
        Returns:
            Dictionary containing analysis results
        """
        dir_path = Path(directory)
        
        if not dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        pattern = "**/*.pdf" if recursive else "*.pdf"
        pdf_files = list(dir_path.glob(pattern))
        
        if not pdf_files:
            logger.info(f"No PDF files found in {directory}")
            return self.results
        
        # Filter out already processed files if resuming
        if self.processed_files:
            pdf_files = [f for f in pdf_files if str(f) not in self.processed_files]
            logger.info(f"Resuming: {len(pdf_files)} files remaining to process")
        
        logger.info(f"Found {len(pdf_files)} PDF files to analyze...")
        
        # Use tqdm for progress tracking if available
        if tqdm and self.enable_progress:
            pdf_files = tqdm(pdf_files, desc="Analyzing PDFs")
        
        for pdf_file in pdf_files:
            self.analyze_file(pdf_file)
            
            # Save resume state periodically (every 10 files)
            if len(self.processed_files) % 10 == 0:
                self.save_resume_state()
        
        # Final resume state save
        self.save_resume_state()
        
        return self.results
    
    def extract_from_multiple(self, pdf_paths: List[Union[str, Path]], extract_text: bool = False) -> List[Dict]:
        """Extract metadata and optionally text from multiple PDF files.
        
        Args:
            pdf_paths: List of PDF file paths
            extract_text: Whether to extract text content
            
        Returns:
            List of analysis results
        """
        results = []
        
        # Use tqdm for progress tracking if available
        if tqdm and self.enable_progress:
            pdf_paths = tqdm(pdf_paths, desc="Processing PDFs")
        
        for pdf_path in pdf_paths:
            try:
                if extract_text:
                    result = self.extract_with_metadata(pdf_path)
                else:
                    result = self.analyze_file(Path(pdf_path))
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process {pdf_path}: {e}")
                results.append({"error": str(e), "file": str(pdf_path)})
        
        return results
    
    def save_results(self, output_dir: Union[str, Path]) -> Dict[str, Path]:
        """Save analysis results to JSON files.
        
        Args:
            output_dir: Directory to save results
            
        Returns:
            Dictionary mapping result type to file path
        """
        output_path = create_output_directory(str(output_dir))
        saved_files = {}
        
        # Save processable files list
        processable_file = output_path / "processable_pdfs.json"
        with open(processable_file, 'w') as f:
            json.dump(self.results['processable'], f, indent=2)
        saved_files['processable'] = processable_file
        
        # Save special handling files list
        special_file = output_path / "special_handling_pdfs.json"
        with open(special_file, 'w') as f:
            json.dump(self.results['special_handling'], f, indent=2)
        saved_files['special_handling'] = special_file
        
        # Save errors if any
        if self.results['errors']:
            errors_file = output_path / "pdf_analysis_errors.json"
            with open(errors_file, 'w') as f:
                json.dump(self.results['errors'], f, indent=2)
            saved_files['errors'] = errors_file
        
        # Save complete results with metadata
        complete_file = output_path / "complete_analysis.json"
        with open(complete_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        saved_files['complete'] = complete_file
        
        logger.info(f"Results saved to {output_path}")
        return saved_files
    
    def get_summary(self) -> Dict:
        """Get analysis summary statistics.
        
        Returns:
            Dictionary containing summary statistics
        """
        metadata = self.results['metadata']
        
        return {
            'total_files': metadata['total_analyzed'],
            'processable_files': len(self.results['processable']),
            'special_handling_files': len(self.results['special_handling']),
            'error_files': len(self.results['errors']),
            'total_size_mb': round(metadata['total_size_bytes'] / (1024 * 1024), 2),
            'total_pages': metadata['total_pages'],
            'average_pages_per_file': (
                round(metadata['total_pages'] / metadata['total_analyzed'], 1) 
                if metadata['total_analyzed'] > 0 else 0
            ),
            'limits': {
                'max_size_mb': metadata['max_size_mb'],
                'max_pages': metadata['max_pages']
            }
        }
    
    def print_summary(self) -> None:
        """Print analysis summary to console."""
        summary = self.get_summary()
        
        print(f"\n=== PDF Analysis Summary ===")
        print(f"Total files analyzed: {summary['total_files']}")
        print(f"Processable files: {summary['processable_files']}")
        print(f"Special handling required: {summary['special_handling_files']}")
        print(f"Errors: {summary['error_files']}")
        print(f"Total size: {summary['total_size_mb']} MB")
        print(f"Total pages: {summary['total_pages']}")
        print(f"Average pages per file: {summary['average_pages_per_file']}")
        
        print(f"\nLimits used:")
        print(f"  Max size: {summary['limits']['max_size_mb']} MB")
        print(f"  Max pages: {summary['limits']['max_pages']}")
        
        if self.results['special_handling']:
            print(f"\nFiles requiring special handling:")
            for file_info in self.results['special_handling']:
                print(f"  - {file_info['filename']}: {', '.join(file_info['reason'])}")
        
        if self.results['errors']:
            print(f"\nFiles with errors:")
            for error_info in self.results['errors']:
                print(f"  - {error_info['filename']}: {error_info['error']}")