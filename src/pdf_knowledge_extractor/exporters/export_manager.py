"""
Export Management System
Central management for all export operations with configuration and validation
"""

import logging
import json
import yaml
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
from datetime import datetime
import time

from .base import ExportConfig, ExportResult
from .batch_exporter import BatchExporter, BatchExportResult, ProgressTracker

logger = logging.getLogger(__name__)


class ExportManager:
    """Central manager for all export operations."""
    
    def __init__(self, config_file: Optional[Path] = None):
        """Initialize export manager with optional configuration file."""
        self.config_file = config_file
        self.settings = self._load_settings()
        self.batch_exporter = BatchExporter(
            output_directory=Path(self.settings.get('default_output_directory', 'exports')),
            parallel=self.settings.get('parallel_exports', True),
            max_workers=self.settings.get('max_workers', 4)
        )
        self.logger = logging.getLogger(__name__)
    
    def export_single(self, 
                     format_type: str,
                     analysis_data: Dict[str, Any],
                     documents: Dict[str, str],
                     output_path: Optional[Path] = None,
                     config_overrides: Dict[str, Any] = None) -> ExportResult:
        """
        Export to a single format.
        
        Args:
            format_type: Export format name
            analysis_data: Analysis results from KnowledgeAnalyzer
            documents: Original document texts
            output_path: Optional custom output path
            config_overrides: Optional configuration overrides
            
        Returns:
            ExportResult
        """
        
        # Validate format
        if format_type not in BatchExporter.EXPORTERS:
            raise ValueError(f"Unsupported format: {format_type}")
        
        # Get format-specific configuration
        format_config = self._get_format_config(format_type)
        
        # Apply overrides
        if config_overrides:
            format_config.update(config_overrides)
        
        # Set output path
        if not output_path:
            output_dir = Path(self.settings.get('default_output_directory', 'exports'))
            output_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            doc_count = len(documents)
            
            # Get file extension
            exporter_class = BatchExporter.EXPORTERS[format_type]
            temp_config = ExportConfig(output_path=Path("temp"), format_type=format_type)
            temp_exporter = exporter_class(temp_config)
            extension = temp_exporter.file_extension
            
            output_path = output_dir / f"pdf_knowledge_{format_type}_{doc_count}docs_{timestamp}{extension}"
        
        # Create export configuration
        export_config = ExportConfig(
            output_path=output_path,
            format_type=format_type,
            **format_config
        )
        
        # Create exporter and execute
        exporter_class = BatchExporter.EXPORTERS[format_type]
        exporter = exporter_class(export_config)
        
        return exporter.export(analysis_data, documents)
    
    def export_batch(self,
                    formats: List[str],
                    analysis_data: Dict[str, Any],
                    documents: Dict[str, str],
                    output_directory: Optional[Path] = None,
                    progress_callback: Optional[callable] = None) -> BatchExportResult:
        """
        Export to multiple formats in batch.
        
        Args:
            formats: List of format names
            analysis_data: Analysis results
            documents: Original documents
            output_directory: Optional output directory
            progress_callback: Optional progress callback function
            
        Returns:
            BatchExportResult
        """
        
        # Set output directory
        if output_directory:
            self.batch_exporter.output_directory = output_directory
        
        # Set progress callback
        if progress_callback:
            self.batch_exporter.set_progress_callback(progress_callback)
        
        # Get base configuration
        base_config = self._get_base_config()
        
        return self.batch_exporter.export_multiple(formats, analysis_data, documents, base_config)
    
    def export_by_profile(self,
                         profile_name: str,
                         analysis_data: Dict[str, Any],
                         documents: Dict[str, str],
                         output_directory: Optional[Path] = None) -> BatchExportResult:
        """
        Export using a predefined profile.
        
        Args:
            profile_name: Name of export profile
            analysis_data: Analysis results
            documents: Original documents
            output_directory: Optional output directory
            
        Returns:
            BatchExportResult
        """
        
        profiles = self.settings.get('export_profiles', {})
        if profile_name not in profiles:
            raise ValueError(f"Export profile '{profile_name}' not found")
        
        profile = profiles[profile_name]
        formats = profile.get('formats', [])
        
        # Set output directory
        if output_directory:
            self.batch_exporter.output_directory = output_directory
        
        # Create format-specific configurations
        export_configs = {}
        for format_name in formats:
            format_config = self._get_format_config(format_name)
            
            # Apply profile-specific overrides
            profile_overrides = profile.get('format_configs', {}).get(format_name, {})
            format_config.update(profile_overrides)
            
            export_configs[format_name] = format_config
        
        return self.batch_exporter.export_with_configs(export_configs, analysis_data, documents)
    
    def create_export_profile(self,
                             name: str,
                             formats: List[str],
                             description: str = "",
                             format_configs: Dict[str, Dict[str, Any]] = None):
        """Create a new export profile."""
        
        if 'export_profiles' not in self.settings:
            self.settings['export_profiles'] = {}
        
        profile = {
            'description': description,
            'formats': formats,
            'format_configs': format_configs or {},
            'created': datetime.now().isoformat()
        }
        
        self.settings['export_profiles'][name] = profile
        self._save_settings()
        
        self.logger.info(f"Created export profile '{name}' with {len(formats)} formats")
    
    def list_export_profiles(self) -> Dict[str, Dict[str, Any]]:
        """List all available export profiles."""
        return self.settings.get('export_profiles', {})
    
    def get_supported_formats(self) -> Dict[str, List[str]]:
        """Get all supported export formats by category."""
        return BatchExporter.list_supported_formats()
    
    def validate_configuration(self, format_type: str, config: Dict[str, Any]) -> List[str]:
        """Validate export configuration for a format."""
        
        if format_type not in BatchExporter.EXPORTERS:
            return [f"Unsupported format: {format_type}"]
        
        try:
            # Create temporary export config to validate
            temp_path = Path("/tmp/validate_config")
            export_config = ExportConfig(
                output_path=temp_path,
                format_type=format_type,
                **config
            )
            
            # Create exporter and validate config
            exporter_class = BatchExporter.EXPORTERS[format_type]
            exporter = exporter_class(export_config)
            
            return exporter.validate_config()
            
        except Exception as e:
            return [f"Configuration validation error: {str(e)}"]
    
    def estimate_export_time(self,
                           formats: List[str],
                           document_count: int,
                           total_concepts: int = 0) -> Dict[str, float]:
        """Estimate export times based on format and data size."""
        
        # Base time estimates (in seconds) per document
        base_times = {
            'obsidian': 0.5,
            'notion': 1.0,
            'roam': 0.8,
            'logseq': 0.6,
            'dendron': 0.7,
            'zotero': 0.4,
            'latex': 1.2,
            'gdocs': 0.8,
            'csv': 0.1,
            'excel': 0.3,
            'anki': 0.6,
            'quizlet': 0.3,
            'flashcards-json': 0.4,
            'confluence': 1.0,
            'teams': 0.5,
            'sharepoint': 0.8,
            'advanced-csv': 0.2,
            'advanced-excel': 0.8,
            'json-ld': 0.3,
            'rdf': 0.4
        }
        
        estimates = {}
        for format_type in formats:
            if format_type in base_times:
                base_time = base_times[format_type]
                # Scale with document count and concept complexity
                concept_factor = 1 + (total_concepts / 1000) * 0.1  # 10% increase per 1000 concepts
                estimated_time = base_time * document_count * concept_factor
                estimates[format_type] = round(estimated_time, 2)
            else:
                estimates[format_type] = 1.0  # Default estimate
        
        return estimates
    
    def get_export_statistics(self) -> Dict[str, Any]:
        """Get export usage statistics."""
        
        stats_file = Path(self.settings.get('default_output_directory', 'exports')) / 'export_stats.json'
        
        if not stats_file.exists():
            return {
                'total_exports': 0,
                'format_usage': {},
                'successful_exports': 0,
                'failed_exports': 0,
                'last_export': None
            }
        
        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load export statistics: {e}")
            return {}
    
    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from configuration file."""
        
        default_settings = {
            'default_output_directory': 'exports',
            'parallel_exports': True,
            'max_workers': 4,
            'default_configs': {
                'include_metadata': True,
                'include_concepts': True,
                'include_relationships': True,
                'include_clusters': True,
                'min_concept_importance': 0.5,
                'min_similarity_score': 0.6,
                'max_concepts_per_document': 50,
                'validate_output': True
            },
            'format_specific_configs': {},
            'export_profiles': {
                'knowledge_management': {
                    'description': 'Export to all knowledge management formats',
                    'formats': ['obsidian', 'notion', 'roam', 'logseq'],
                    'format_configs': {}
                },
                'academic': {
                    'description': 'Export to academic and research formats',
                    'formats': ['zotero', 'latex', 'csv', 'excel'],
                    'format_configs': {}
                },
                'complete': {
                    'description': 'Export to all supported formats',
                    'formats': list(BatchExporter.EXPORTERS.keys()),
                    'format_configs': {}
                }
            }
        }
        
        if not self.config_file or not self.config_file.exists():
            return default_settings
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                if self.config_file.suffix.lower() in ['.yaml', '.yml']:
                    loaded_settings = yaml.safe_load(f)
                else:
                    loaded_settings = json.load(f)
            
            # Merge with defaults
            settings = default_settings.copy()
            settings.update(loaded_settings)
            return settings
            
        except Exception as e:
            self.logger.error(f"Failed to load settings from {self.config_file}: {e}")
            return default_settings
    
    def _save_settings(self):
        """Save current settings to configuration file."""
        
        if not self.config_file:
            return
        
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                if self.config_file.suffix.lower() in ['.yaml', '.yml']:
                    yaml.dump(self.settings, f, default_flow_style=False, indent=2)
                else:
                    json.dump(self.settings, f, indent=2, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"Failed to save settings to {self.config_file}: {e}")
    
    def _get_base_config(self) -> Dict[str, Any]:
        """Get base export configuration."""
        return self.settings.get('default_configs', {}).copy()
    
    def _get_format_config(self, format_type: str) -> Dict[str, Any]:
        """Get configuration for a specific format."""
        base_config = self._get_base_config()
        format_specific = self.settings.get('format_specific_configs', {}).get(format_type, {})
        
        config = base_config.copy()
        config.update(format_specific)
        
        return config
    
    def _update_export_statistics(self, format_type: str, success: bool):
        """Update export usage statistics."""
        
        stats_file = Path(self.settings.get('default_output_directory', 'exports')) / 'export_stats.json'
        stats = self.get_export_statistics()
        
        # Update statistics
        stats['total_exports'] = stats.get('total_exports', 0) + 1
        stats['last_export'] = datetime.now().isoformat()
        
        if success:
            stats['successful_exports'] = stats.get('successful_exports', 0) + 1
        else:
            stats['failed_exports'] = stats.get('failed_exports', 0) + 1
        
        # Update format usage
        format_usage = stats.get('format_usage', {})
        format_usage[format_type] = format_usage.get(format_type, 0) + 1
        stats['format_usage'] = format_usage
        
        # Save statistics
        try:
            stats_file.parent.mkdir(parents=True, exist_ok=True)
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.logger.error(f"Failed to update export statistics: {e}")


class ConfigurationWizard:
    """Interactive configuration wizard for export settings."""
    
    def __init__(self, manager: ExportManager):
        self.manager = manager
    
    def run_wizard(self) -> Dict[str, Any]:
        """Run interactive configuration wizard."""
        
        print("PDF Knowledge Extractor - Export Configuration Wizard")
        print("=" * 55)
        
        config = {}
        
        # Output directory
        default_dir = self.manager.settings.get('default_output_directory', 'exports')
        output_dir = input(f"Output directory [{default_dir}]: ").strip() or default_dir
        config['default_output_directory'] = output_dir
        
        # Parallel processing
        parallel = input("Enable parallel processing? [Y/n]: ").strip().lower()
        config['parallel_exports'] = parallel != 'n'
        
        if config['parallel_exports']:
            max_workers = input("Maximum parallel workers [4]: ").strip() or "4"
            config['max_workers'] = int(max_workers)
        
        # Content filtering
        print("\nContent Filtering Options:")
        
        min_importance = input("Minimum concept importance (0.0-1.0) [0.5]: ").strip() or "0.5"
        min_similarity = input("Minimum similarity score (0.0-1.0) [0.6]: ").strip() or "0.6"
        max_concepts = input("Maximum concepts per document [50]: ").strip() or "50"
        
        config['default_configs'] = {
            'include_metadata': True,
            'include_concepts': True,
            'include_relationships': True,
            'include_clusters': True,
            'min_concept_importance': float(min_importance),
            'min_similarity_score': float(min_similarity),
            'max_concepts_per_document': int(max_concepts),
            'validate_output': True
        }
        
        # Export profiles
        print(f"\nWould you like to create custom export profiles?")
        create_profiles = input("Create profiles? [y/N]: ").strip().lower() == 'y'
        
        if create_profiles:
            config['export_profiles'] = self._create_profiles_interactive()
        
        return config
    
    def _create_profiles_interactive(self) -> Dict[str, Dict[str, Any]]:
        """Create export profiles interactively."""
        
        profiles = {}
        
        while True:
            profile_name = input("\nProfile name (or 'done' to finish): ").strip()
            if profile_name.lower() == 'done':
                break
            
            description = input("Profile description: ").strip()
            
            # Show available formats
            print("\nAvailable formats by category:")
            supported_formats = BatchExporter.list_supported_formats()
            
            all_formats = []
            for category, formats in supported_formats.items():
                print(f"  {category}: {', '.join(formats)}")
                all_formats.extend(formats)
            
            # Select formats
            print(f"\nEnter formats for '{profile_name}' profile (comma-separated):")
            formats_input = input("Formats: ").strip()
            
            if formats_input:
                selected_formats = [f.strip() for f in formats_input.split(',')]
                # Validate formats
                valid_formats = [f for f in selected_formats if f in all_formats]
                
                if valid_formats:
                    profiles[profile_name] = {
                        'description': description,
                        'formats': valid_formats,
                        'format_configs': {},
                        'created': datetime.now().isoformat()
                    }
                    print(f"Created profile '{profile_name}' with {len(valid_formats)} formats")
                else:
                    print("No valid formats selected")
        
        return profiles