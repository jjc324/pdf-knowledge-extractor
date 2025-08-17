# Getting Started

## Installation

### From source

1. Clone or download the project
2. Navigate to the project directory
3. Install the package:

```bash
pip install -e .
```

### Development installation

For development, install with additional dependencies:

```bash
pip install -e ".[dev]"
```

## Quick Start

### 1. Basic Setup

Create a configuration file (optional):

```bash
cp config.yaml.example config.yaml
```

Edit the configuration file to match your needs.

### 2. Extract text from a PDF

```python
from pdf_knowledge_extractor import PDFExtractor

extractor = PDFExtractor()
text = extractor.extract_text("your_document.pdf")
print(text)
```

### 3. Process and analyze the text

```python
from pdf_knowledge_extractor import TextProcessor, KnowledgeAnalyzer

# Clean and process the text
processor = TextProcessor()
cleaned_text = processor.clean_text(text)

# Analyze the content
analyzer = KnowledgeAnalyzer()
analysis = analyzer.analyze_content(cleaned_text)

# Get insights
insights = analyzer.generate_insights(analysis)
for insight in insights:
    print(insight)
```

### 4. Command line usage

Extract knowledge from a PDF using the command line:

```bash
python -m pdf_knowledge_extractor.cli document.pdf
```

## Configuration

The system uses YAML configuration files to customize behavior:

```yaml
extractor:
  # PDF extraction settings
  
processor:
  remove_special_chars: false
  chunk_size: 1000
  overlap: 100
  
analyzer:
  # Analysis settings
```

## Next Steps

- Read the [API Reference](api_reference.md) for detailed documentation
- Check out [Examples](examples.md) for more usage patterns
- See the configuration template in `config.yaml.example`