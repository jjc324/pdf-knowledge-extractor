#!/usr/bin/env python3
"""
PDF File Analyzer Script

Analyzes PDF files in a directory to check file sizes and page counts,
then categorizes them for processing or special handling based on configurable limits.
"""

import os
import sys
import json
from pathlib import Path
from typing import List, Dict, Tuple
import argparse

try:
    import PyPDF2
except ImportError:
    print("Error: PyPDF2 is required. Install with: pip install PyPDF2")
    sys.exit(1)


class PDFAnalyzer:
    def __init__(self, max_size_mb: float = 10.0, max_pages: int = 100):
        """
        Initialize PDF analyzer with size and page limits.
        
        Args:
            max_size_mb: Maximum file size in MB for normal processing
            max_pages: Maximum page count for normal processing
        """
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.max_pages = max_pages
        self.results = {
            'processable': [],
            'special_handling': [],
            'errors': []
        }
    
    def get_file_size(self, file_path: Path) -> int:
        """Get file size in bytes."""
        return file_path.stat().st_size
    
    def get_page_count(self, file_path: Path) -> int:
        """Get PDF page count."""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                return len(pdf_reader.pages)
        except Exception as e:
            raise Exception(f"Failed to read PDF: {str(e)}")
    
    def analyze_file(self, file_path: Path) -> Dict:
        """Analyze a single PDF file."""
        try:
            file_size = self.get_file_size(file_path)
            page_count = self.get_page_count(file_path)
            
            file_info = {
                'path': str(file_path),
                'size_bytes': file_size,
                'size_mb': round(file_size / (1024 * 1024), 2),
                'page_count': page_count,
                'exceeds_size_limit': file_size > self.max_size_bytes,
                'exceeds_page_limit': page_count > self.max_pages
            }
            
            # Determine if file needs special handling
            needs_special_handling = (
                file_info['exceeds_size_limit'] or 
                file_info['exceeds_page_limit']
            )
            
            if needs_special_handling:
                file_info['reason'] = []
                if file_info['exceeds_size_limit']:
                    file_info['reason'].append(f"Size {file_info['size_mb']}MB exceeds {self.max_size_bytes/(1024*1024)}MB limit")
                if file_info['exceeds_page_limit']:
                    file_info['reason'].append(f"Page count {page_count} exceeds {self.max_pages} limit")
                
                self.results['special_handling'].append(file_info)
            else:
                self.results['processable'].append(file_info)
            
            return file_info
            
        except Exception as e:
            error_info = {
                'path': str(file_path),
                'error': str(e)
            }
            self.results['errors'].append(error_info)
            return error_info
    
    def analyze_directory(self, directory: Path, recursive: bool = False) -> Dict:
        """Analyze all PDF files in a directory."""
        if not directory.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")
        
        pattern = "**/*.pdf" if recursive else "*.pdf"
        pdf_files = list(directory.glob(pattern))
        
        if not pdf_files:
            print(f"No PDF files found in {directory}")
            return self.results
        
        print(f"Found {len(pdf_files)} PDF files to analyze...")
        
        for pdf_file in pdf_files:
            self.analyze_file(pdf_file)
        
        return self.results
    
    def save_results(self, output_file: Path = None):
        """Save analysis results to files."""
        base_path = output_file.parent if output_file else Path.cwd()
        
        # Save processable files list
        processable_file = base_path / "processable_pdfs.json"
        with open(processable_file, 'w') as f:
            json.dump(self.results['processable'], f, indent=2)
        
        # Save special handling files list
        special_file = base_path / "special_handling_pdfs.json"
        with open(special_file, 'w') as f:
            json.dump(self.results['special_handling'], f, indent=2)
        
        # Save errors if any
        if self.results['errors']:
            errors_file = base_path / "pdf_analysis_errors.json"
            with open(errors_file, 'w') as f:
                json.dump(self.results['errors'], f, indent=2)
        
        print(f"\nResults saved:")
        print(f"  - Processable files: {processable_file}")
        print(f"  - Special handling: {special_file}")
        if self.results['errors']:
            print(f"  - Errors: {errors_file}")
    
    def print_summary(self):
        """Print analysis summary."""
        total_files = len(self.results['processable']) + len(self.results['special_handling']) + len(self.results['errors'])
        
        print(f"\n=== PDF Analysis Summary ===")
        print(f"Total files analyzed: {total_files}")
        print(f"Processable files: {len(self.results['processable'])}")
        print(f"Special handling required: {len(self.results['special_handling'])}")
        print(f"Errors: {len(self.results['errors'])}")
        
        if self.results['special_handling']:
            print(f"\nFiles requiring special handling:")
            for file_info in self.results['special_handling']:
                print(f"  - {Path(file_info['path']).name}: {', '.join(file_info['reason'])}")


def main():
    parser = argparse.ArgumentParser(description="Analyze PDF files for size and page count")
    parser.add_argument("directory", help="Directory containing PDF files")
    parser.add_argument("--max-size", type=float, default=10.0, 
                       help="Maximum file size in MB (default: 10.0)")
    parser.add_argument("--max-pages", type=int, default=100,
                       help="Maximum page count (default: 100)")
    parser.add_argument("--recursive", "-r", action="store_true",
                       help="Search subdirectories recursively")
    parser.add_argument("--output", "-o", help="Output directory for results files")
    
    args = parser.parse_args()
    
    directory = Path(args.directory)
    output_path = Path(args.output) if args.output else directory
    
    try:
        analyzer = PDFAnalyzer(max_size_mb=args.max_size, max_pages=args.max_pages)
        analyzer.analyze_directory(directory, recursive=args.recursive)
        analyzer.print_summary()
        analyzer.save_results(output_path)
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()