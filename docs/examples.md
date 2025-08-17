# Examples

## PDF Analysis (Original pdf_analyzer.py functionality)

### Analyze PDFs in a directory

```python
from pdf_knowledge_extractor import PDFExtractor

# Initialize with custom limits
config = {
    'analysis': {
        'max_size_mb': 15.0,
        'max_pages': 150
    }
}
extractor = PDFExtractor(config)

# Analyze all PDFs in a directory
results = extractor.analyze_directory("/path/to/pdfs", recursive=True)

# Print summary
extractor.print_summary()

# Save results to files
saved_files = extractor.save_results("./output")
```

### Resume interrupted analysis

```python
from pdf_knowledge_extractor import PDFExtractor

extractor = PDFExtractor()

# Setup resume capability
extractor.setup_resume("./analysis_resume.json")

# Continue analysis (skips already processed files)
results = extractor.analyze_directory("/path/to/pdfs")
```

## Text Extraction

### Extract text from a single PDF

```python
from pdf_knowledge_extractor import PDFExtractor

# Initialize the extractor
extractor = PDFExtractor()

# Extract text from a PDF
text = extractor.extract_text("document.pdf")
print(text)
```

### Extract text with analysis metadata

```python
from pdf_knowledge_extractor import PDFExtractor

extractor = PDFExtractor()

# Get both analysis and text
result = extractor.extract_with_metadata("document.pdf")

print(f"File: {result['filename']}")
print(f"Size: {result['size_mb']} MB")
print(f"Pages: {result['page_count']}")
if 'text' in result:
    print(f"Text length: {result['text_length']} characters")
```

### Process extracted text

```python
from pdf_knowledge_extractor import TextProcessor

# Initialize the processor
processor = TextProcessor()

# Clean the extracted text
cleaned_text = processor.clean_text(raw_text)

# Split into chunks for analysis
chunks = processor.split_into_chunks(cleaned_text, chunk_size=1000)
```

### Analyze content

```python
from pdf_knowledge_extractor import KnowledgeAnalyzer

# Initialize the analyzer
analyzer = KnowledgeAnalyzer()

# Analyze the content
analysis = analyzer.analyze_content(text)

# Generate insights
insights = analyzer.generate_insights(analysis)
for insight in insights:
    print(f"- {insight}")
```

## Complete Workflow

```python
from pdf_knowledge_extractor import PDFExtractor, TextProcessor, KnowledgeAnalyzer
from pdf_knowledge_extractor.utils import load_config, setup_logging

# Set up logging
setup_logging("INFO")

# Load configuration
config = load_config("config.yaml")

# Initialize components
extractor = PDFExtractor(config.get("extractor", {}))
processor = TextProcessor(config.get("processor", {}))
analyzer = KnowledgeAnalyzer(config.get("analyzer", {}))

# Process a PDF
pdf_path = "research_paper.pdf"

# Extract text
raw_text = extractor.extract_text(pdf_path)

# Process text
cleaned_text = processor.clean_text(raw_text)
chunks = processor.split_into_chunks(cleaned_text)

# Analyze each chunk
all_insights = []
for chunk in chunks:
    analysis = analyzer.analyze_content(chunk)
    insights = analyzer.generate_insights(analysis)
    all_insights.extend(insights)

# Print results
print(f"Processed {len(chunks)} chunks")
print(f"Generated {len(all_insights)} insights")
for insight in all_insights:
    print(f"- {insight}")
```

## Command Line Usage

### Directory Analysis (Original pdf_analyzer.py functionality)

```bash
# Analyze PDFs in a directory (default mode)
pdf-extract /path/to/pdfs

# With custom limits
pdf-extract /path/to/pdfs --max-size 25 --max-pages 200

# Recursive search through subdirectories
pdf-extract /path/to/pdfs --recursive

# Resume interrupted analysis
pdf-extract /path/to/pdfs --resume

# With progress tracking and verbose output
pdf-extract /path/to/pdfs --verbose --output ./results/
```

### Single File Processing

```bash
# Analyze a single PDF file
pdf-extract document.pdf --mode analyze

# Extract text from a single PDF
pdf-extract document.pdf --mode extract --extract-text

# Full analysis and text extraction
pdf-extract document.pdf --mode both --extract-text --analyze-content
```

### Advanced Options

```bash
# With custom configuration
pdf-extract /path/to/pdfs --config my_config.yaml

# Disable progress bar
pdf-extract /path/to/pdfs --no-progress

# With custom resume file
pdf-extract /path/to/pdfs --resume --resume-file ./my_resume.json

# With detailed logging
pdf-extract /path/to/pdfs --verbose --log-file analysis.log

# Claude batch processing (after running analysis)
pdf-extract /path/to/pdfs --mode claude-batch --output ./claude_results

# Claude batch with custom settings
pdf-extract /path/to/pdfs --mode claude-batch --batch-size 10 --max-retries 5

# Claude batch with custom processable PDFs file
pdf-extract . --mode claude-batch --processable-pdfs ./results/processable_pdfs.json

# Resume interrupted Claude processing
pdf-extract /path/to/pdfs --mode claude-batch --resume --output ./claude_results
```

## Configuration Examples

### Basic configuration (config.yaml)

```yaml
# PDF Analysis limits
analysis:
  max_size_mb: 15.0
  max_pages: 150

# Progress tracking
progress:
  enabled: true

# Logging
logging:
  level: INFO
  file: "analysis.log"
```

### Advanced configuration

```yaml
# Analysis settings with resume capability
analysis:
  max_size_mb: 25.0
  max_pages: 200
  extract_text_for_processable: true

# Progress and resume
progress:
  enabled: true
  resume:
    enabled: true
    file_name: ".analysis_resume.json"
    save_interval: 5

# Text processing
processor:
  remove_special_chars: true
  chunk_size: 1500
  overlap: 200
  
# Content analysis
analyzer:
  max_topics: 10
  include_sentiment: true
```

## Migration from Original pdf_analyzer.py

### Direct replacement

Replace your existing `pdf_analyzer.py` usage:

```bash
# Old usage
python pdf_analyzer.py /path/to/pdfs --max-size 15 --max-pages 150 --recursive --output ./results

# New usage (identical functionality)
pdf-extract /path/to/pdfs --max-size 15 --max-pages 150 --recursive --output ./results
```

### Python API migration

```python
# Old usage
from pdf_analyzer import PDFAnalyzer

analyzer = PDFAnalyzer(max_size_mb=15.0, max_pages=150)
results = analyzer.analyze_directory("/path/to/pdfs", recursive=True)
analyzer.print_summary()
analyzer.save_results()

# New usage (enhanced with configuration)
from pdf_knowledge_extractor import PDFExtractor

config = {'analysis': {'max_size_mb': 15.0, 'max_pages': 150}}
extractor = PDFExtractor(config)
results = extractor.analyze_directory("/path/to/pdfs", recursive=True)
extractor.print_summary()
extractor.save_results("./results")
```

## Claude Integration (Batch Processing)

### Process PDFs through Claude

```python
from pdf_knowledge_extractor.claude_integration import ClaudeIntegration

# Initialize with configuration
config = {
    'claude': {
        'batch_size': 5,
        'max_retries': 3,
        'context_window_size': 200000
    }
}
claude_integration = ClaudeIntegration(config)

# Run batch processing (requires processable_pdfs.json from previous analysis)
results = claude_integration.run_batch_processing(
    processable_pdfs_file="./processable_pdfs.json",
    output_dir="./claude_results",
    resume=True  # Resume from previous state if interrupted
)

print(f"Processed {results['successful']} documents successfully")
```

### Resume interrupted Claude processing

```python
from pdf_knowledge_extractor.claude_integration import ClaudeIntegration

claude_integration = ClaudeIntegration()

# Automatically resumes from saved state
results = claude_integration.run_batch_processing(
    processable_pdfs_file="./processable_pdfs.json",
    output_dir="./claude_results",
    resume=True
)
```

### Process with custom context management

```python
from pdf_knowledge_extractor.claude_integration import ClaudeIntegration

config = {
    'claude': {
        'max_tokens_per_request': 8000,
        'context_window_size': 200000,
        'batch_size': 3,  # Smaller batches for large documents
        'max_retries': 5,
        'retry_delay_base': 2.0
    }
}

claude_integration = ClaudeIntegration(config)
results = claude_integration.run_batch_processing(
    processable_pdfs_file="./processable_pdfs.json",
    output_dir="./claude_results"
)
```