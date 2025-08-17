"""
Tests for utility functions.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, mock_open

from src.pdf_knowledge_extractor.utils import (
    load_config,
    validate_pdf_path,
    create_output_directory
)


class TestUtils(unittest.TestCase):
    """Test cases for utility functions."""
    
    def test_load_config_success(self):
        """Test successful configuration loading."""
        yaml_content = """
        extractor:
          option1: value1
        processor:
          option2: value2
        """
        
        with patch("builtins.open", mock_open(read_data=yaml_content)):
            with patch("pathlib.Path.exists", return_value=True):
                config = load_config("config.yaml")
                
        self.assertIn("extractor", config)
        self.assertIn("processor", config)
        self.assertEqual(config["extractor"]["option1"], "value1")
        
    def test_load_config_file_not_found(self):
        """Test configuration loading with missing file."""
        with self.assertRaises(FileNotFoundError):
            load_config("nonexistent.yaml")
            
    def test_load_config_empty_file(self):
        """Test configuration loading with empty file."""
        with patch("builtins.open", mock_open(read_data="")):
            with patch("pathlib.Path.exists", return_value=True):
                config = load_config("config.yaml")
                
        self.assertEqual(config, {})
        
    def test_validate_pdf_path_success(self):
        """Test successful PDF path validation."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            
        try:
            result = validate_pdf_path(str(tmp_path))
            self.assertEqual(result, tmp_path)
        finally:
            tmp_path.unlink()
            
    def test_validate_pdf_path_not_found(self):
        """Test PDF path validation with missing file."""
        with self.assertRaises(FileNotFoundError):
            validate_pdf_path("nonexistent.pdf")
            
    def test_validate_pdf_path_wrong_extension(self):
        """Test PDF path validation with wrong file extension."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            
        try:
            with self.assertRaises(ValueError):
                validate_pdf_path(str(tmp_path))
        finally:
            tmp_path.unlink()
            
    def test_create_output_directory_new(self):
        """Test creating a new output directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "new_directory"
            result = create_output_directory(str(output_path))
            
            self.assertTrue(result.exists())
            self.assertTrue(result.is_dir())
            
    def test_create_output_directory_existing(self):
        """Test creating output directory that already exists."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir)
            result = create_output_directory(str(output_path))
            
            self.assertEqual(result, output_path)
            self.assertTrue(result.exists())


if __name__ == "__main__":
    unittest.main()