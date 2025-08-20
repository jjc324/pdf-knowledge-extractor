"""
Batch Export System
Support for exporting to multiple formats simultaneously with progress tracking
"""

import logging
import json
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
from datetime import datetime
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from .base import BaseExporter, ExportConfig, ExportResult
from .knowledge_management import *
from .academic_research import *
from .learning_memory import *
from .enterprise_collaboration import *
from .data_analysis import *

logger = logging.getLogger(__name__)


class BatchExportResult:
    """Result of a batch export operation."""
    
    def __init__(self):
        self.success: bool = True
        self.total_exports: int = 0
        self.successful_exports: int = 0
        self.failed_exports: int = 0
        self.export_results: Dict[str, ExportResult] = {}
        self.execution_time: float = 0.0
        self.start_time: datetime = datetime.now()
        self.end_time: Optional[datetime] = None
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def add_result(self, format_type: str, result: ExportResult):
        """Add an individual export result."""
        self.export_results[format_type] = result
        self.total_exports += 1
        
        if result.success:
            self.successful_exports += 1
        else:
            self.failed_exports += 1
            self.success = False
            self.errors.extend(result.errors)
    
    def finalize(self):
        """Finalize the batch result."""
        self.end_time = datetime.now()
        self.execution_time = (self.end_time - self.start_time).total_seconds()
        
        if self.failed_exports > 0:
            self.success = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'success': self.success,
            'total_exports': self.total_exports,
            'successful_exports': self.successful_exports,
            'failed_exports': self.failed_exports,
            'execution_time': self.execution_time,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'export_results': {k: v.to_dict() for k, v in self.export_results.items()},
            'errors': self.errors,
            'warnings': self.warnings
        }


class BatchExporter:
    """Batch exporter for multiple export formats."""
    
    # Registry of all available exporters
    EXPORTERS = {
        # Knowledge Management
        'obsidian': ObsidianExporter,
        'notion': NotionExporter,
        'roam': RoamResearchExporter,
        'logseq': LogseqExporter,
        'dendron': DendronExporter,
        
        # Academic & Research
        'zotero': ZoteroExporter,
        'latex': LaTeXExporter,
        'tex': LaTeXExporter,
        'gdocs': GoogleDocsExporter,
        'html': GoogleDocsExporter,
        'csv': CSVExporter,
        'excel': ExcelExporter,
        'xlsx': ExcelExporter,
        
        # Learning & Memory
        'anki': AnkiExporter,
        'quizlet': QuizletExporter,
        'flashcards-json': FlashcardExporter,
        'flashcards-xml': FlashcardExporter,
        
        # Enterprise & Collaboration
        'confluence': ConfluenceExporter,
        'teams': TeamsExporter,
        'sharepoint': SharePointExporter,
        
        # Data & Analysis
        'advanced-csv': AdvancedCSVExporter,
        'csv-multi': AdvancedCSVExporter,
        'advanced-excel': AdvancedExcelExporter,
        'excel-analytics': AdvancedExcelExporter,
        'json-ld': JSONLDExporter,
        'jsonld': JSONLDExporter,
        'rdf': RDFExporter,
        'rdf-xml': RDFExporter
    }
    
    def __init__(self, output_directory: Path, parallel: bool = True, max_workers: int = 4):
        """Initialize batch exporter."""
        self.output_directory = Path(output_directory)
        self.parallel = parallel
        self.max_workers = max_workers
        self.progress_callback: Optional[callable] = None
        self.logger = logging.getLogger(__name__)
    
    def set_progress_callback(self, callback: callable):
        """Set callback function for progress updates."""
        self.progress_callback = callback
    
    def export_multiple(self, 
                       formats: List[str], 
                       analysis_data: Dict[str, Any], 
                       documents: Dict[str, str],
                       base_config: Dict[str, Any] = None) -> BatchExportResult:
        """
        Export to multiple formats.
        
        Args:
            formats: List of format names to export to
            analysis_data: Analysis results from KnowledgeAnalyzer
            documents: Original document texts
            base_config: Base configuration to apply to all exports
            
        Returns:
            BatchExportResult with results of all exports
        """
        
        batch_result = BatchExportResult()
        base_config = base_config or {}
        
        # Validate formats
        invalid_formats = [f for f in formats if f not in self.EXPORTERS]
        if invalid_formats:
            batch_result.success = False
            batch_result.errors.append(f"Invalid formats: {', '.join(invalid_formats)}")
            batch_result.finalize()
            return batch_result
        
        # Create export jobs
        export_jobs = []
        for format_name in formats:
            job = self._create_export_job(format_name, analysis_data, documents, base_config)
            if job:
                export_jobs.append(job)
            else:
                batch_result.errors.append(f"Failed to create job for format: {format_name}")
        
        # Execute exports
        if self.parallel and len(export_jobs) > 1:
            self._execute_parallel(export_jobs, batch_result)
        else:
            self._execute_sequential(export_jobs, batch_result)
        
        # Generate batch report
        self._generate_batch_report(batch_result)
        
        batch_result.finalize()
        return batch_result
    
    def export_with_configs(self, 
                           export_configs: Dict[str, Dict[str, Any]], 
                           analysis_data: Dict[str, Any], 
                           documents: Dict[str, str]) -> BatchExportResult:
        """
        Export with individual configurations for each format.
        
        Args:
            export_configs: Dict mapping format names to their specific configs
            analysis_data: Analysis results
            documents: Original documents
            
        Returns:
            BatchExportResult
        """
        
        batch_result = BatchExportResult()
        
        # Create export jobs with individual configs
        export_jobs = []
        for format_name, config in export_configs.items():
            if format_name not in self.EXPORTERS:
                batch_result.errors.append(f"Invalid format: {format_name}")
                continue
            
            job = self._create_export_job(format_name, analysis_data, documents, config)
            if job:
                export_jobs.append(job)
        
        # Execute exports
        if self.parallel and len(export_jobs) > 1:
            self._execute_parallel(export_jobs, batch_result)
        else:
            self._execute_sequential(export_jobs, batch_result)
        
        self._generate_batch_report(batch_result)
        batch_result.finalize()
        return batch_result
    
    def export_all_supported(self, 
                           analysis_data: Dict[str, Any], 
                           documents: Dict[str, str],
                           base_config: Dict[str, Any] = None) -> BatchExportResult:
        """Export to all supported formats."""
        all_formats = list(self.EXPORTERS.keys())
        return self.export_multiple(all_formats, analysis_data, documents, base_config)
    
    def export_by_category(self, 
                          category: str, 
                          analysis_data: Dict[str, Any], 
                          documents: Dict[str, str],
                          base_config: Dict[str, Any] = None) -> BatchExportResult:
        """
        Export to all formats in a specific category.
        
        Categories: knowledge-management, academic, learning, enterprise, data-analysis
        """
        
        category_formats = {
            'knowledge-management': ['obsidian', 'notion', 'roam', 'logseq', 'dendron'],
            'academic': ['zotero', 'latex', 'gdocs', 'csv', 'excel'],
            'learning': ['anki', 'quizlet', 'flashcards-json'],
            'enterprise': ['confluence', 'teams', 'sharepoint'],
            'data-analysis': ['advanced-csv', 'advanced-excel', 'json-ld', 'rdf']
        }
        
        if category not in category_formats:
            batch_result = BatchExportResult()
            batch_result.success = False
            batch_result.errors.append(f"Invalid category: {category}")
            batch_result.finalize()
            return batch_result
        
        formats = category_formats[category]
        return self.export_multiple(formats, analysis_data, documents, base_config)
    
    def _create_export_job(self, format_name: str, analysis_data: Dict, documents: Dict, config: Dict) -> Optional[Dict]:
        """Create an export job."""
        try:
            exporter_class = self.EXPORTERS[format_name]
            
            # Create output path
            output_filename = self._generate_filename(format_name, documents)
            output_path = self.output_directory / output_filename
            
            # Create export configuration
            export_config = ExportConfig(
                output_path=output_path,
                format_type=format_name,
                **config
            )
            
            return {
                'format_name': format_name,
                'exporter_class': exporter_class,
                'export_config': export_config,
                'analysis_data': analysis_data,
                'documents': documents
            }
            
        except Exception as e:
            self.logger.error(f"Failed to create job for {format_name}: {e}")
            return None
    
    def _execute_sequential(self, export_jobs: List[Dict], batch_result: BatchExportResult):
        """Execute exports sequentially."""
        for i, job in enumerate(export_jobs):
            format_name = job['format_name']
            
            try:
                if self.progress_callback:
                    self.progress_callback(f"Exporting to {format_name}...", i, len(export_jobs))
                
                result = self._execute_single_export(job)
                batch_result.add_result(format_name, result)
                
                self.logger.info(f"Export to {format_name}: {'Success' if result.success else 'Failed'}")
                
            except Exception as e:
                self.logger.error(f"Error exporting to {format_name}: {e}")
                # Create failed result
                failed_result = ExportResult(
                    success=False,
                    format_type=format_name,
                    output_path=job['export_config'].output_path,
                    exported_documents=[],
                    exported_concepts=0,
                    exported_relationships=0,
                    execution_time=0,
                    file_size_bytes=0,
                    errors=[str(e)]
                )
                batch_result.add_result(format_name, failed_result)
    
    def _execute_parallel(self, export_jobs: List[Dict], batch_result: BatchExportResult):
        """Execute exports in parallel."""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all jobs
            future_to_format = {
                executor.submit(self._execute_single_export, job): job['format_name'] 
                for job in export_jobs
            }
            
            completed = 0
            for future in as_completed(future_to_format):
                format_name = future_to_format[future]
                completed += 1
                
                try:
                    if self.progress_callback:
                        self.progress_callback(f"Completed {format_name}", completed, len(export_jobs))
                    
                    result = future.result()
                    batch_result.add_result(format_name, result)
                    
                    self.logger.info(f"Export to {format_name}: {'Success' if result.success else 'Failed'}")
                    
                except Exception as e:
                    self.logger.error(f"Error exporting to {format_name}: {e}")
                    # Create failed result
                    failed_result = ExportResult(
                        success=False,
                        format_type=format_name,
                        output_path=Path("unknown"),
                        exported_documents=[],
                        exported_concepts=0,
                        exported_relationships=0,
                        execution_time=0,
                        file_size_bytes=0,
                        errors=[str(e)]
                    )
                    batch_result.add_result(format_name, failed_result)
    
    def _execute_single_export(self, job: Dict) -> ExportResult:
        """Execute a single export job."""
        exporter_class = job['exporter_class']
        export_config = job['export_config']
        analysis_data = job['analysis_data']
        documents = job['documents']
        
        # Create exporter instance
        exporter = exporter_class(export_config)
        
        # Execute export
        return exporter.export(analysis_data, documents)
    
    def _generate_filename(self, format_name: str, documents: Dict) -> str:
        """Generate output filename for a format."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        doc_count = len(documents)
        
        # Get file extension
        exporter_class = self.EXPORTERS[format_name]
        temp_config = ExportConfig(output_path=Path("temp"), format_type=format_name)
        temp_exporter = exporter_class(temp_config)
        extension = temp_exporter.file_extension
        
        return f"pdf_knowledge_{format_name}_{doc_count}docs_{timestamp}{extension}"
    
    def _generate_batch_report(self, batch_result: BatchExportResult):
        """Generate batch export report."""
        report_path = self.output_directory / f"batch_export_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump(batch_result.to_dict(), f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Batch export report saved to: {report_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save batch report: {e}")
    
    @classmethod
    def list_supported_formats(cls) -> Dict[str, List[str]]:
        """List all supported export formats by category."""
        return {
            'Knowledge Management': ['obsidian', 'notion', 'roam', 'logseq', 'dendron'],
            'Academic & Research': ['zotero', 'latex', 'tex', 'gdocs', 'html', 'csv', 'excel', 'xlsx'],
            'Learning & Memory': ['anki', 'quizlet', 'flashcards-json', 'flashcards-xml'],
            'Enterprise & Collaboration': ['confluence', 'teams', 'sharepoint'],
            'Data & Analysis': ['advanced-csv', 'csv-multi', 'advanced-excel', 'excel-analytics', 'json-ld', 'jsonld', 'rdf', 'rdf-xml']
        }
    
    @classmethod
    def get_format_description(cls, format_name: str) -> str:
        """Get description of a format."""
        descriptions = {
            'obsidian': 'Obsidian vault with wikilinks and graph connections',
            'notion': 'Notion database with relations and properties',
            'roam': 'Roam Research with block references and bidirectional links',
            'logseq': 'Logseq with block structure and page references',
            'dendron': 'Dendron VSCode workspace with schemas and hierarchies',
            'zotero': 'Zotero library with metadata, notes, and collections',
            'latex': 'LaTeX document with citations and bibliography',
            'gdocs': 'Google Docs compatible HTML format',
            'csv': 'Basic CSV format for data analysis',
            'excel': 'Excel workbook with multiple sheets',
            'anki': 'Anki flashcard deck for spaced repetition',
            'quizlet': 'Quizlet study sets with terms and definitions',
            'flashcards-json': 'Custom JSON flashcard format',
            'confluence': 'Confluence wiki pages with spaces and templates',
            'teams': 'Microsoft Teams shared documents format',
            'sharepoint': 'SharePoint knowledge base structure',
            'advanced-csv': 'Multiple CSV files with comprehensive data',
            'advanced-excel': 'Excel with advanced charts and analytics',
            'json-ld': 'JSON-LD structured data format',
            'rdf': 'RDF/XML semantic web format'
        }
        
        return descriptions.get(format_name, 'No description available')


class ProgressTracker:
    """Simple progress tracker for exports."""
    
    def __init__(self, total_exports: int):
        self.total_exports = total_exports
        self.completed_exports = 0
        self.current_task = ""
        self.start_time = time.time()
        self.callbacks = []
    
    def add_callback(self, callback: callable):
        """Add progress callback."""
        self.callbacks.append(callback)
    
    def update(self, task_description: str, completed: int, total: int):
        """Update progress."""
        self.current_task = task_description
        self.completed_exports = completed
        
        progress_percent = (completed / total) * 100 if total > 0 else 0
        elapsed_time = time.time() - self.start_time
        
        # Estimate remaining time
        if completed > 0:
            avg_time_per_task = elapsed_time / completed
            remaining_tasks = total - completed
            estimated_remaining = avg_time_per_task * remaining_tasks
        else:
            estimated_remaining = 0
        
        # Notify callbacks
        for callback in self.callbacks:
            callback({
                'task': task_description,
                'completed': completed,
                'total': total,
                'progress_percent': progress_percent,
                'elapsed_time': elapsed_time,
                'estimated_remaining': estimated_remaining
            })
    
    def complete(self):
        """Mark as complete."""
        self.completed_exports = self.total_exports
        total_time = time.time() - self.start_time
        
        for callback in self.callbacks:
            callback({
                'task': 'Batch export completed',
                'completed': self.total_exports,
                'total': self.total_exports,
                'progress_percent': 100.0,
                'elapsed_time': total_time,
                'estimated_remaining': 0
            })