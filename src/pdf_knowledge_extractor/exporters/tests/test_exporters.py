"""
Test suite for export system functionality.
"""

import pytest
import tempfile
import json
from pathlib import Path
from datetime import datetime
import shutil

from ..base import ExportConfig, ExportResult
from ..knowledge_management import ObsidianExporter, NotionExporter
from ..academic_research import LaTeXExporter, CSVExporter
from ..learning_memory import AnkiExporter
from ..data_analysis import JSONLDExporter
from ..batch_exporter import BatchExporter
from ..export_manager import ExportManager


class TestExportBase:
    """Test base export functionality."""
    
    @pytest.fixture
    def sample_analysis_data(self):
        """Sample analysis data for testing."""
        return {
            'total_documents': 2,
            'individual_analyses': {
                'doc1.pdf': {
                    'word_count': 1000,
                    'character_count': 5000,
                    'topics': [{'topic': 'machine learning', 'frequency': 10}],
                    'entities': [],
                    'sentiment': {'sentiment': 'positive', 'score': 0.7}
                },
                'doc2.pdf': {
                    'word_count': 800,
                    'character_count': 4000,
                    'topics': [{'topic': 'data science', 'frequency': 8}],
                    'entities': [],
                    'sentiment': {'sentiment': 'neutral', 'score': 0.0}
                }
            },
            'semantic_analysis': {
                'concepts': [
                    {
                        'text': 'artificial intelligence',
                        'concept_type': 'keyword',
                        'importance_score': 0.9,
                        'frequency': 15,
                        'document_ids': ['doc1.pdf', 'doc2.pdf'],
                        'context_sentences': ['AI is transforming industries worldwide.']
                    },
                    {
                        'text': 'neural networks',
                        'concept_type': 'technical_term',
                        'importance_score': 0.8,
                        'frequency': 12,
                        'document_ids': ['doc1.pdf'],
                        'context_sentences': ['Neural networks mimic brain function.']
                    }
                ],
                'similarities': [
                    {
                        'doc1_id': 'doc1.pdf',
                        'doc2_id': 'doc2.pdf',
                        'similarity_score': 0.75,
                        'similarity_type': 'cosine',
                        'shared_concepts': ['artificial intelligence']
                    }
                ],
                'clusters': [
                    {
                        'cluster_id': 'cluster_1',
                        'cluster_label': 'AI Research',
                        'document_ids': ['doc1.pdf', 'doc2.pdf'],
                        'coherence_score': 0.85,
                        'main_topics': ['artificial intelligence', 'machine learning']
                    }
                ]
            }
        }
    
    @pytest.fixture
    def sample_documents(self):
        """Sample documents for testing."""
        return {
            'doc1.pdf': 'This document discusses artificial intelligence and machine learning applications in various industries. Neural networks are a key component of modern AI systems.',
            'doc2.pdf': 'Data science and artificial intelligence are closely related fields. This document explores their intersection and practical applications.'
        }
    
    @pytest.fixture
    def temp_dir(self):
        """Temporary directory for test outputs."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)


class TestObsidianExporter(TestExportBase):
    """Test Obsidian exporter."""
    
    def test_obsidian_export_basic(self, sample_analysis_data, sample_documents, temp_dir):
        """Test basic Obsidian export functionality."""
        output_path = temp_dir / "obsidian_vault"
        
        config = ExportConfig(
            output_path=output_path,
            format_type='obsidian',
            include_concepts=True,
            include_relationships=True
        )
        
        exporter = ObsidianExporter(config)
        result = exporter.export(sample_analysis_data, sample_documents)
        
        assert result.success
        assert result.format_type == 'obsidian'
        assert len(result.exported_documents) == 2
        assert result.exported_concepts > 0
        
        # Check if vault was created
        assert output_path.exists()
        assert output_path.is_dir()
        
        # Check for markdown files
        md_files = list(output_path.glob('*.md'))
        assert len(md_files) >= 2  # At least document files
        
        # Check Obsidian config
        obsidian_dir = output_path / ".obsidian"
        assert obsidian_dir.exists()
        assert (obsidian_dir / "app.json").exists()
    
    def test_obsidian_concept_filtering(self, sample_analysis_data, sample_documents, temp_dir):
        """Test concept filtering in Obsidian export."""
        output_path = temp_dir / "obsidian_filtered"
        
        config = ExportConfig(
            output_path=output_path,
            format_type='obsidian',
            min_concept_importance=0.85,  # High threshold
            max_concepts_per_document=1
        )
        
        exporter = ObsidianExporter(config)
        result = exporter.export(sample_analysis_data, sample_documents)
        
        assert result.success
        # Should have fewer concepts due to filtering
        assert result.exported_concepts <= len(sample_analysis_data['semantic_analysis']['concepts'])


class TestLaTeXExporter(TestExportBase):
    """Test LaTeX exporter."""
    
    def test_latex_export_basic(self, sample_analysis_data, sample_documents, temp_dir):
        """Test basic LaTeX export."""
        output_path = temp_dir / "document.tex"
        
        config = ExportConfig(
            output_path=output_path,
            format_type='latex',
            include_concepts=True,
            include_relationships=True
        )
        
        exporter = LaTeXExporter(config)
        result = exporter.export(sample_analysis_data, sample_documents)
        
        assert result.success
        assert result.format_type == 'latex'
        assert output_path.exists()
        
        # Check LaTeX content
        content = output_path.read_text()
        assert '\\documentclass' in content
        assert '\\begin{document}' in content
        assert '\\end{document}' in content
        
        # Check bibliography file
        bib_path = output_path.with_suffix('.bib')
        assert bib_path.exists()


class TestAnkiExporter(TestExportBase):
    """Test Anki exporter."""
    
    def test_anki_export_basic(self, sample_analysis_data, sample_documents, temp_dir):
        """Test basic Anki export."""
        output_path = temp_dir / "anki_cards.txt"
        
        config = ExportConfig(
            output_path=output_path,
            format_type='anki',
            include_concepts=True,
            max_concepts_per_document=10
        )
        
        exporter = AnkiExporter(config)
        result = exporter.export(sample_analysis_data, sample_documents)
        
        assert result.success
        assert output_path.exists()
        
        # Check Anki format
        content = output_path.read_text()
        assert '#separator:Tab' in content
        assert '#html:true' in content
        assert '#tags:pdf-analysis' in content


class TestJSONLDExporter(TestExportBase):
    """Test JSON-LD exporter."""
    
    def test_jsonld_export_basic(self, sample_analysis_data, sample_documents, temp_dir):
        """Test basic JSON-LD export."""
        output_path = temp_dir / "knowledge_graph.jsonld"
        
        config = ExportConfig(
            output_path=output_path,
            format_type='json-ld'
        )
        
        exporter = JSONLDExporter(config)
        result = exporter.export(sample_analysis_data, sample_documents)
        
        assert result.success
        assert output_path.exists()
        
        # Check JSON-LD structure
        with open(output_path, 'r') as f:
            data = json.load(f)
        
        assert '@context' in data
        assert '@graph' in data
        assert isinstance(data['@graph'], list)
        assert len(data['@graph']) > 0


class TestBatchExporter(TestExportBase):
    """Test batch export functionality."""
    
    def test_batch_export_multiple_formats(self, sample_analysis_data, sample_documents, temp_dir):
        """Test exporting to multiple formats."""
        batch_exporter = BatchExporter(temp_dir, parallel=False)
        
        formats = ['obsidian', 'csv', 'anki']
        base_config = {
            'include_concepts': True,
            'include_relationships': True,
            'min_concept_importance': 0.5
        }
        
        result = batch_exporter.export_multiple(formats, sample_analysis_data, sample_documents, base_config)
        
        assert result.success
        assert result.total_exports == 3
        assert result.successful_exports == 3
        assert result.failed_exports == 0
        
        # Check individual results
        for format_type in formats:
            assert format_type in result.export_results
            individual_result = result.export_results[format_type]
            assert individual_result.success
    
    def test_batch_export_with_failures(self, sample_analysis_data, sample_documents, temp_dir):
        """Test batch export with some failures."""
        batch_exporter = BatchExporter(temp_dir)
        
        # Include invalid format to trigger failure
        formats = ['obsidian', 'invalid_format', 'csv']
        
        result = batch_exporter.export_multiple(formats, sample_analysis_data, sample_documents)
        
        assert not result.success  # Overall should fail due to invalid format
        assert result.total_exports == 2  # Only valid formats attempted
        assert result.failed_exports == 0  # Valid formats should succeed
    
    def test_batch_export_parallel(self, sample_analysis_data, sample_documents, temp_dir):
        """Test parallel batch export."""
        batch_exporter = BatchExporter(temp_dir, parallel=True, max_workers=2)
        
        formats = ['obsidian', 'csv', 'anki', 'json-ld']
        
        result = batch_exporter.export_multiple(formats, sample_analysis_data, sample_documents)
        
        assert result.success
        assert result.successful_exports == 4


class TestExportManager(TestExportBase):
    """Test export manager functionality."""
    
    @pytest.fixture
    def export_manager(self, temp_dir):
        """Export manager with temporary config."""
        config_file = temp_dir / "export_config.json"
        manager = ExportManager(config_file)
        manager.settings['default_output_directory'] = str(temp_dir / "exports")
        return manager
    
    def test_single_export(self, export_manager, sample_analysis_data, sample_documents):
        """Test single format export through manager."""
        result = export_manager.export_single(
            format_type='csv',
            analysis_data=sample_analysis_data,
            documents=sample_documents
        )
        
        assert result.success
        assert result.format_type == 'csv'
    
    def test_batch_export_via_manager(self, export_manager, sample_analysis_data, sample_documents):
        """Test batch export through manager."""
        formats = ['obsidian', 'csv']
        
        result = export_manager.export_batch(
            formats=formats,
            analysis_data=sample_analysis_data,
            documents=sample_documents
        )
        
        assert result.success
        assert result.successful_exports == 2
    
    def test_export_profile_creation(self, export_manager):
        """Test creating and using export profiles."""
        # Create profile
        export_manager.create_export_profile(
            name='test_profile',
            formats=['obsidian', 'csv'],
            description='Test profile'
        )
        
        # Check profile was created
        profiles = export_manager.list_export_profiles()
        assert 'test_profile' in profiles
        assert profiles['test_profile']['description'] == 'Test profile'
        assert len(profiles['test_profile']['formats']) == 2
    
    def test_configuration_validation(self, export_manager):
        """Test configuration validation."""
        # Valid config
        valid_errors = export_manager.validate_configuration('csv', {
            'include_concepts': True,
            'min_concept_importance': 0.5
        })
        assert len(valid_errors) == 0
        
        # Invalid config
        invalid_errors = export_manager.validate_configuration('csv', {
            'min_concept_importance': 1.5  # Invalid range
        })
        assert len(invalid_errors) > 0


class TestConfigurationValidation:
    """Test export configuration validation."""
    
    def test_export_config_validation(self):
        """Test ExportConfig validation."""
        # Valid config
        config = ExportConfig(
            output_path=Path('/tmp/test.csv'),
            format_type='csv',
            min_concept_importance=0.5,
            min_similarity_score=0.7
        )
        
        assert config.min_concept_importance == 0.5
        assert config.min_similarity_score == 0.7
    
    def test_invalid_config_values(self):
        """Test validation of invalid configuration values."""
        # This would be caught by exporter validation
        config = ExportConfig(
            output_path=Path('/tmp/test.csv'),
            format_type='csv',
            min_concept_importance=1.5,  # Invalid
            min_similarity_score=-0.1     # Invalid
        )
        
        from ..academic_research import CSVExporter
        exporter = CSVExporter(config)
        errors = exporter.validate_config()
        
        assert len(errors) > 0


class TestTemplateSystem:
    """Test template-based export system."""
    
    def test_custom_templates(self, temp_dir):
        """Test using custom templates."""
        # Create custom template
        template_dir = temp_dir / "templates"
        template_dir.mkdir()
        
        custom_template = template_dir / "document.template"
        custom_template.write_text("Custom template: {title} - {concept_count} concepts")
        
        config = ExportConfig(
            output_path=temp_dir / "test.md",
            format_type='obsidian',
            template_path=template_dir,
            custom_templates={
                'test_template': "Test: {title}"
            }
        )
        
        exporter = ObsidianExporter(config)
        
        # Check templates were loaded
        assert 'document' in exporter.templates
        assert 'test_template' in exporter.templates


if __name__ == '__main__':
    pytest.main([__file__])