"""
PDF Knowledge Extractor - A tool for extracting and analyzing knowledge from PDF documents.
"""

__version__ = "0.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

from .extractor import PDFExtractor
from .processor import TextProcessor
from .analyzer import KnowledgeAnalyzer

__all__ = ["PDFExtractor", "TextProcessor", "KnowledgeAnalyzer"]