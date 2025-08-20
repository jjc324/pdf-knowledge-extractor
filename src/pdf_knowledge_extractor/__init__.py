"""
PDF Knowledge Extractor - A tool for extracting and analyzing knowledge from PDF documents.
Enhanced with semantic analysis and knowledge graph capabilities.
"""

__version__ = "2.1.0"
__author__ = "Your Name"
__email__ = "your.email@example.com"

from .extractor import PDFExtractor
from .processor import TextProcessor
from .analyzer import KnowledgeAnalyzer
from .claude_integration import ClaudeIntegration
from .semantic_analyzer import SemanticAnalyzer
from .exporters.export_manager import ExportManager
from .exporters.batch_exporter import BatchExporter

__all__ = ["PDFExtractor", "TextProcessor", "KnowledgeAnalyzer", "ClaudeIntegration", "SemanticAnalyzer", "ExportManager", "BatchExporter"]