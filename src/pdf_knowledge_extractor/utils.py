"""
Utility functions for the PDF knowledge extractor.
"""

import logging
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """Set up logging configuration."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    format_string = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    if log_file:
        logging.basicConfig(
            level=log_level,
            format=format_string,
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
    else:
        logging.basicConfig(level=log_level, format=format_string)


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file."""
    config_file = Path(config_path)
    
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
        
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
        
    return config or {}


def validate_pdf_path(pdf_path: str) -> Path:
    """Validate that a PDF file path exists and is readable."""
    path = Path(pdf_path)
    
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
    if not path.suffix.lower() == '.pdf':
        raise ValueError(f"File is not a PDF: {pdf_path}")
        
    if not path.is_file():
        raise ValueError(f"Path is not a file: {pdf_path}")
        
    return path


def create_output_directory(output_path: str) -> Path:
    """Create output directory if it doesn't exist."""
    path = Path(output_path)
    path.mkdir(parents=True, exist_ok=True)
    return path