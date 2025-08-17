# API Reference

## PDFExtractor

The `PDFExtractor` class handles extraction of text and metadata from PDF documents.

### Constructor

```python
PDFExtractor(config: Optional[Dict] = None)
```

### Methods

#### extract_text(pdf_path)
Extract plain text from a PDF file.

**Parameters:**
- `pdf_path` (str | Path): Path to the PDF file

**Returns:**
- `str`: Extracted text content

#### extract_with_metadata(pdf_path)
Extract text along with metadata from a PDF file.

**Parameters:**
- `pdf_path` (str | Path): Path to the PDF file

**Returns:**
- `Dict`: Dictionary containing text and metadata

#### extract_from_multiple(pdf_paths)
Extract text and metadata from multiple PDF files.

**Parameters:**
- `pdf_paths` (List[str | Path]): List of PDF file paths

**Returns:**
- `List[Dict]`: List of extraction results

## TextProcessor

The `TextProcessor` class handles cleaning and processing of extracted text.

### Constructor

```python
TextProcessor(config: Optional[Dict] = None)
```

### Methods

#### clean_text(text)
Clean and normalize extracted text.

**Parameters:**
- `text` (str): Raw text to clean

**Returns:**
- `str`: Cleaned text

#### split_into_chunks(text, chunk_size=1000, overlap=100)
Split text into overlapping chunks for processing.

**Parameters:**
- `text` (str): Text to split
- `chunk_size` (int): Maximum size of each chunk
- `overlap` (int): Number of characters to overlap between chunks

**Returns:**
- `List[str]`: List of text chunks

## KnowledgeAnalyzer

The `KnowledgeAnalyzer` class performs analysis on processed text to extract insights.

### Constructor

```python
KnowledgeAnalyzer(config: Optional[Dict] = None)
```

### Methods

#### analyze_content(text)
Perform comprehensive analysis of text content.

**Parameters:**
- `text` (str): Text to analyze

**Returns:**
- `Dict`: Analysis results including word count, topics, entities, etc.

#### generate_insights(analysis)
Generate human-readable insights from analysis results.

**Parameters:**
- `analysis` (Dict): Analysis results from analyze_content

**Returns:**
- `List[str]`: List of insight strings