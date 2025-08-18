"""
Command-line interface for the PDF knowledge extractor.

Enhanced CLI that integrates the original pdf_analyzer.py functionality
with the new professional architecture.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Dict

from . import PDFExtractor, TextProcessor, KnowledgeAnalyzer
from .utils import load_config, setup_logging
from .claude_integration import ClaudeIntegration


def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser with both analysis and extraction options."""
    parser = argparse.ArgumentParser(
        description="Analyze and extract knowledge from PDF documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze PDFs in a directory (original pdf_analyzer.py functionality)
  pdf-extract /path/to/pdfs --mode analyze

  # Extract text and analyze a single PDF
  pdf-extract document.pdf --mode extract --extract-text

  # Resume interrupted analysis
  pdf-extract /path/to/pdfs --mode analyze --resume

  # Custom limits for analysis
  pdf-extract /path/to/pdfs --mode analyze --max-size 25 --max-pages 200
  
  # Test Claude CLI health
  pdf-extract --test-claude
  
  # Claude batch processing (after running analysis)
  pdf-extract /path/to/pdfs --mode claude-batch --output ./claude_results
  
  # Claude batch with reliability features
  pdf-extract /path/to/pdfs --mode claude-batch --skip-failed --claude-timeout 180
  
  # Claude batch with custom settings
  pdf-extract /path/to/pdfs --mode claude-batch --batch-size 10 --max-retries 5
        """
    )
    
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to PDF file or directory containing PDFs"
    )
    
    parser.add_argument(
        "-m", "--mode",
        choices=["analyze", "extract", "both", "claude-batch"],
        default="analyze",
        help="Mode of operation: analyze (check size/pages), extract (get text), both, or claude-batch"
    )
    
    parser.add_argument(
        "-o", "--output",
        help="Output directory for results (default: current directory)",
        default="."
    )
    
    parser.add_argument(
        "-c", "--config",
        help="Path to configuration file",
        default="config.yaml"
    )
    
    # Analysis options (from original pdf_analyzer.py)
    parser.add_argument(
        "--max-size", 
        type=float,
        help="Maximum file size in MB for normal processing"
    )
    
    parser.add_argument(
        "--max-pages", 
        type=int,
        help="Maximum page count for normal processing"
    )
    
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Search subdirectories recursively"
    )
    
    # Resume capability
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume interrupted analysis"
    )
    
    parser.add_argument(
        "--resume-file",
        help="Custom resume file path"
    )
    
    # Text extraction options
    parser.add_argument(
        "--extract-text",
        action="store_true",
        help="Extract text content from PDFs"
    )
    
    parser.add_argument(
        "--process-text",
        action="store_true",
        help="Process extracted text (clean, chunk, etc.)"
    )
    
    parser.add_argument(
        "--analyze-content",
        action="store_true",
        help="Perform content analysis on extracted text"
    )
    
    # Claude integration options
    parser.add_argument(
        "--processable-pdfs",
        help="Path to processable_pdfs.json file for Claude batch processing"
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Batch size for Claude processing"
    )
    
    parser.add_argument(
        "--max-retries",
        type=int,
        help="Maximum retry attempts for failed documents"
    )
    
    parser.add_argument(
        "--test-claude",
        action="store_true",
        help="Test Claude CLI health before processing"
    )
    
    parser.add_argument(
        "--skip-failed",
        action="store_true",
        help="Skip documents that fail processing instead of retrying"
    )
    
    parser.add_argument(
        "--claude-timeout",
        type=int,
        help="Timeout in seconds for Claude CLI operations (default: 120)"
    )
    
    # Progress and logging
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    parser.add_argument(
        "--log-file",
        help="Path to log file"
    )
    
    return parser


def test_claude_cli(logger) -> int:
    """Test Claude CLI health and return appropriate exit code."""
    from .claude_integration import ClaudeIntegration
    
    claude_integration = ClaudeIntegration({})
    is_healthy, message = claude_integration.test_claude_cli_health()
    
    if is_healthy:
        logger.info(f"✅ Claude CLI is healthy: {message}")
        return 0
    else:
        logger.error(f"❌ Claude CLI health check failed: {message}")
        logger.error("Please ensure Claude CLI is properly installed and configured.")
        logger.error("Installation: https://github.com/anthropics/claude-cli")
        return 1


def handle_claude_batch_processing(args, config: Dict, logger) -> int:
    """Handle Claude batch processing mode.
    
    Args:
        args: Command line arguments
        config: Configuration dictionary
        logger: Logger instance
        
    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Determine processable PDFs file
        if args.processable_pdfs:
            processable_pdfs_file = Path(args.processable_pdfs)
        else:
            # Look for processable_pdfs.json in the path directory
            path = Path(args.path)
            if path.is_file():
                processable_pdfs_file = path.parent / "processable_pdfs.json"
            else:
                processable_pdfs_file = path / "processable_pdfs.json"
        
        if not processable_pdfs_file.exists():
            logger.error(f"Processable PDFs file not found: {processable_pdfs_file}")
            logger.info("Run PDF analysis first to generate processable_pdfs.json")
            return 1
        
        logger.info(f"Using processable PDFs file: {processable_pdfs_file}")
        
        # Initialize Claude integration
        claude_integration = ClaudeIntegration(config)
        
        # Perform initial health check if enabled
        if not args.skip_failed:  # Only do health check if we're not skipping failures
            is_healthy, health_msg = claude_integration.test_claude_cli_health()
            if not is_healthy:
                logger.error(f"Claude CLI health check failed: {health_msg}")
                logger.error("Consider using --skip-failed to continue processing despite failures")
                return 1
            else:
                logger.info(f"Claude CLI health check passed: {health_msg}")
        
        # Run batch processing
        results = claude_integration.run_batch_processing(
            processable_pdfs_file=processable_pdfs_file,
            output_dir=args.output,
            resume=args.resume
        )
        
        # Print results summary
        logger.info("Claude batch processing completed!")
        logger.info(f"Total documents: {results['total_documents']}")
        logger.info(f"Successfully processed: {results['successful']}")
        logger.info(f"Failed: {results['failed']}")
        logger.info(f"Batches processed: {results['batches_processed']}")
        logger.info(f"Output directory: {results['output_directory']}")
        
        if results['failed'] > 0:
            logger.warning(f"{results['failed']} documents failed processing")
            return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"Claude batch processing failed: {e}")
        if args.verbose:
            import traceback
            logger.error(traceback.format_exc())
        return 1


def main() -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Set up logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(log_level, args.log_file)
    
    logger = logging.getLogger(__name__)
    
    try:
        # Load configuration
        config = {}
        if Path(args.config).exists():
            config = load_config(args.config)
            logger.info(f"Loaded configuration from {args.config}")
        else:
            logger.info("No configuration file found, using defaults")
        
        # Override config with command line arguments
        if args.max_size is not None:
            config.setdefault('analysis', {})['max_size_mb'] = args.max_size
        if args.max_pages is not None:
            config.setdefault('analysis', {})['max_pages'] = args.max_pages
        
        # Claude integration settings
        if args.batch_size is not None:
            config.setdefault('claude', {})['batch_size'] = args.batch_size
        if args.max_retries is not None:
            config.setdefault('claude', {})['max_retries'] = args.max_retries
        if args.claude_timeout is not None:
            config.setdefault('claude', {})['timeout'] = args.claude_timeout
        if args.skip_failed:
            config.setdefault('claude', {})['skip_failed'] = args.skip_failed
        
        # Progress settings
        if args.no_progress:
            config.setdefault('progress', {})['enabled'] = False
        
        # Handle test-claude flag
        if args.test_claude:
            return test_claude_cli(logger)
        
        # Check if path is required and provided
        if not args.path:
            logger.error("Path argument is required for this operation")
            logger.error("Use --help to see available options")
            return 1
        
        # Handle Claude batch processing mode
        if args.mode == "claude-batch":
            return handle_claude_batch_processing(args, config, logger)
        
        # Determine if path is file or directory
        path = Path(args.path)
        if not path.exists():
            logger.error(f"Path does not exist: {args.path}")
            return 1
        
        is_directory = path.is_dir()
        
        # Initialize PDF extractor with full config
        extractor = PDFExtractor(config)
        
        # Setup resume if requested
        if args.resume or args.resume_file:
            resume_file = args.resume_file or Path(args.output) / ".pdf_analysis_resume.json"
            extractor.setup_resume(resume_file)
            logger.info(f"Resume capability enabled: {resume_file}")
        
        # Perform analysis based on mode and path type
        if is_directory:
            logger.info(f"Analyzing directory: {path}")
            logger.info(f"Recursive search: {args.recursive}")
            
            # Directory analysis (main functionality from original pdf_analyzer.py)
            results = extractor.analyze_directory(path, recursive=args.recursive)
            
            # Save results
            saved_files = extractor.save_results(args.output)
            extractor.print_summary()
            
            logger.info(f"Analysis complete! Results saved:")
            for result_type, file_path in saved_files.items():
                logger.info(f"  {result_type}: {file_path}")
        
        else:
            # Single file processing
            logger.info(f"Processing single file: {path}")
            
            if args.mode in ["analyze", "both"]:
                # Analyze single file
                analysis = extractor.analyze_file(path)
                logger.info(f"Analysis result: {analysis}")
            
            if args.mode in ["extract", "both"] or args.extract_text:
                # Extract text from single file
                try:
                    text = extractor.extract_text(path)
                    logger.info(f"Extracted {len(text)} characters of text")
                    
                    if args.process_text:
                        # Process the text
                        processor = TextProcessor(config.get("processor", {}))
                        cleaned_text = processor.clean_text(text)
                        chunks = processor.split_into_chunks(cleaned_text)
                        logger.info(f"Processed text into {len(chunks)} chunks")
                    
                    if args.analyze_content:
                        # Analyze the content
                        analyzer = KnowledgeAnalyzer(config.get("analyzer", {}))
                        analysis = analyzer.analyze_content(text)
                        insights = analyzer.generate_insights(analysis)
                        
                        logger.info("Content Analysis Results:")
                        for insight in insights:
                            logger.info(f"  - {insight}")
                    
                    # Save single file results
                    output_file = Path(args.output) / f"{path.stem}_analysis.json"
                    import json
                    result_data = {
                        "file_path": str(path),
                        "analysis": analysis if 'analysis' in locals() else None,
                        "text_length": len(text),
                        "has_text": bool(text.strip())
                    }
                    
                    if args.process_text and 'chunks' in locals():
                        result_data["chunks_count"] = len(chunks)
                    
                    if args.analyze_content and 'insights' in locals():
                        result_data["insights"] = insights
                    
                    with open(output_file, 'w') as f:
                        json.dump(result_data, f, indent=2)
                    
                    logger.info(f"Results saved to: {output_file}")
                    
                except Exception as e:
                    logger.error(f"Failed to extract text: {e}")
                    return 1
        
        logger.info("Processing completed successfully!")
        return 0
        
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.verbose:
            import traceback
            logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())