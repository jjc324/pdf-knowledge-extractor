"""
Base classes and interfaces for the universal export system.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
import json

logger = logging.getLogger(__name__)


@dataclass
class ExportConfig:
    """Configuration for export operations."""
    
    # Output settings
    output_path: Path
    format_type: str
    
    # Content settings
    include_metadata: bool = True
    include_concepts: bool = True
    include_relationships: bool = True
    include_clusters: bool = True
    include_cross_references: bool = True
    
    # Filtering settings
    min_concept_importance: float = 0.5
    min_similarity_score: float = 0.6
    max_concepts_per_document: int = 50
    
    # Template settings
    template_path: Optional[Path] = None
    custom_templates: Dict[str, str] = field(default_factory=dict)
    
    # Format-specific settings
    format_options: Dict[str, Any] = field(default_factory=dict)
    
    # Batch processing
    batch_size: int = 100
    parallel_processing: bool = True
    
    # Validation
    validate_output: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            'output_path': str(self.output_path),
            'format_type': self.format_type,
            'include_metadata': self.include_metadata,
            'include_concepts': self.include_concepts,
            'include_relationships': self.include_relationships,
            'include_clusters': self.include_clusters,
            'include_cross_references': self.include_cross_references,
            'min_concept_importance': self.min_concept_importance,
            'min_similarity_score': self.min_similarity_score,
            'max_concepts_per_document': self.max_concepts_per_document,
            'template_path': str(self.template_path) if self.template_path else None,
            'custom_templates': self.custom_templates,
            'format_options': self.format_options,
            'batch_size': self.batch_size,
            'parallel_processing': self.parallel_processing,
            'validate_output': self.validate_output
        }


@dataclass
class ExportResult:
    """Result of an export operation."""
    
    success: bool
    format_type: str
    output_path: Path
    exported_documents: List[str]
    exported_concepts: int
    exported_relationships: int
    execution_time: float
    file_size_bytes: int
    
    # Error information
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Export statistics
    stats: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    export_timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            'success': self.success,
            'format_type': self.format_type,
            'output_path': str(self.output_path),
            'exported_documents': self.exported_documents,
            'exported_concepts': self.exported_concepts,
            'exported_relationships': self.exported_relationships,
            'execution_time': self.execution_time,
            'file_size_bytes': self.file_size_bytes,
            'errors': self.errors,
            'warnings': self.warnings,
            'stats': self.stats,
            'export_timestamp': self.export_timestamp.isoformat()
        }


class BaseExporter(ABC):
    """Abstract base class for all exporters."""
    
    def __init__(self, config: ExportConfig):
        """Initialize the exporter with configuration."""
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Template management
        self.templates = {}
        self._load_templates()
    
    @property
    @abstractmethod
    def supported_formats(self) -> List[str]:
        """Return list of supported format types."""
        pass
    
    @property
    @abstractmethod
    def file_extension(self) -> str:
        """Return the file extension for this export format."""
        pass
    
    @abstractmethod
    def export(self, analysis_data: Dict[str, Any], documents: Dict[str, str]) -> ExportResult:
        """
        Export analysis data to the target format.
        
        Args:
            analysis_data: Complete analysis results from KnowledgeAnalyzer
            documents: Original document texts {doc_id: text}
            
        Returns:
            ExportResult with success status and metadata
        """
        pass
    
    def validate_config(self) -> List[str]:
        """Validate export configuration. Returns list of validation errors."""
        errors = []
        
        if not self.config.output_path:
            errors.append("Output path is required")
        
        if self.config.format_type not in self.supported_formats:
            errors.append(f"Format '{self.config.format_type}' not supported by {self.__class__.__name__}")
        
        if self.config.min_concept_importance < 0 or self.config.min_concept_importance > 1:
            errors.append("min_concept_importance must be between 0 and 1")
            
        if self.config.min_similarity_score < 0 or self.config.min_similarity_score > 1:
            errors.append("min_similarity_score must be between 0 and 1")
        
        return errors
    
    def filter_concepts(self, concepts: List[Dict], document_id: str = None) -> List[Dict]:
        """Filter concepts based on configuration settings."""
        filtered = []
        
        for concept in concepts:
            importance = concept.get('importance_score', 0.0)
            if importance >= self.config.min_concept_importance:
                filtered.append(concept)
        
        # Limit number of concepts per document if specified
        if document_id and self.config.max_concepts_per_document > 0:
            # Sort by importance and take top N
            filtered.sort(key=lambda x: x.get('importance_score', 0.0), reverse=True)
            filtered = filtered[:self.config.max_concepts_per_document]
        
        return filtered
    
    def filter_relationships(self, relationships: List[Dict]) -> List[Dict]:
        """Filter relationships based on configuration settings."""
        filtered = []
        
        for rel in relationships:
            similarity = rel.get('similarity_score', rel.get('weight', 0.0))
            if similarity >= self.config.min_similarity_score:
                filtered.append(rel)
        
        return filtered
    
    def prepare_output_path(self) -> Path:
        """Prepare and validate output path."""
        output_path = self.config.output_path
        
        # Add file extension if not present
        if not output_path.suffix:
            output_path = output_path.with_suffix(self.file_extension)
        
        # Create parent directories if they don't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        return output_path
    
    def _load_templates(self):
        """Load export templates."""
        # Load custom templates from config
        self.templates.update(self.config.custom_templates)
        
        # Load templates from template path if specified
        if self.config.template_path and self.config.template_path.exists():
            try:
                template_files = self.config.template_path.glob("*.template")
                for template_file in template_files:
                    template_name = template_file.stem
                    with open(template_file, 'r', encoding='utf-8') as f:
                        self.templates[template_name] = f.read()
            except Exception as e:
                self.logger.warning(f"Failed to load templates from {self.config.template_path}: {e}")
    
    def render_template(self, template_name: str, context: Dict[str, Any]) -> str:
        """Render a template with the given context."""
        if template_name not in self.templates:
            raise ValueError(f"Template '{template_name}' not found")
        
        template = self.templates[template_name]
        
        # Simple template rendering (can be enhanced with Jinja2 if needed)
        try:
            return template.format(**context)
        except KeyError as e:
            raise ValueError(f"Template variable {e} not found in context")
    
    def validate_output(self, output_path: Path) -> List[str]:
        """Validate the exported output. Returns list of validation errors."""
        errors = []
        
        if not output_path.exists():
            errors.append("Output file was not created")
        elif output_path.stat().st_size == 0:
            errors.append("Output file is empty")
        
        return errors
    
    def get_file_size(self, output_path: Path) -> int:
        """Get file size in bytes."""
        try:
            return output_path.stat().st_size
        except Exception:
            return 0
    
    def create_export_result(self, success: bool, output_path: Path, 
                           exported_docs: List[str], execution_time: float,
                           exported_concepts: int = 0, exported_relationships: int = 0,
                           errors: List[str] = None, warnings: List[str] = None,
                           stats: Dict[str, Any] = None) -> ExportResult:
        """Create a standardized export result."""
        return ExportResult(
            success=success,
            format_type=self.config.format_type,
            output_path=output_path,
            exported_documents=exported_docs,
            exported_concepts=exported_concepts,
            exported_relationships=exported_relationships,
            execution_time=execution_time,
            file_size_bytes=self.get_file_size(output_path) if output_path.exists() else 0,
            errors=errors or [],
            warnings=warnings or [],
            stats=stats or {}
        )


class TemplateExporter(BaseExporter):
    """Base class for template-based exporters."""
    
    @property
    @abstractmethod
    def default_templates(self) -> Dict[str, str]:
        """Return default templates for this exporter."""
        pass
    
    def _load_templates(self):
        """Load templates including defaults."""
        super()._load_templates()
        
        # Load default templates (can be overridden by custom templates)
        defaults = self.default_templates
        for name, template in defaults.items():
            if name not in self.templates:
                self.templates[name] = template
    
    def get_template_context(self, analysis_data: Dict[str, Any], 
                           documents: Dict[str, str]) -> Dict[str, Any]:
        """Create template context from analysis data."""
        return {
            'analysis_data': analysis_data,
            'documents': documents,
            'config': self.config.to_dict(),
            'export_timestamp': datetime.now().isoformat(),
            'total_documents': len(documents),
            'total_concepts': len(analysis_data.get('semantic_analysis', {}).get('concepts', [])),
            'total_relationships': len(analysis_data.get('semantic_analysis', {}).get('similarities', [])),
        }