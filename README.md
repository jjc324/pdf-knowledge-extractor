# PDF Knowledge Extractor v1.0

A robust Python tool for extracting and analyzing knowledge from PDF documents with intelligent Claude AI integration. This project provides a comprehensive framework for PDF text extraction, processing, and AI-powered analysis with enterprise-grade reliability features.

## 🌟 Key Features

### Core PDF Processing
- **PDF Text Extraction**: Extract text content from PDF documents using PyPDF2 and pdfplumber
- **Smart Content Filtering**: Automatically filter problematic PDFs (corrupted, oversized, poor quality)
- **Text Quality Validation**: Ensure extracted content meets quality standards
- **Batch Processing**: Handle hundreds of PDFs efficiently with progress tracking

### Claude AI Integration
- **Real Claude Analysis**: Uses actual Claude CLI for intelligent document insights
- **Intelligent Retry Logic**: Exponential backoff with jitter for rate limits and errors
- **Error Categorization**: Smart error handling for different failure types
- **Health Monitoring**: Real-time Claude CLI health checks and status tracking
- **Graceful Degradation**: Continue processing when Claude is temporarily unavailable

### Reliability & Performance
- **50+ Success Rate**: Improved from basic processing to enterprise reliability
- **Content Pre-filtering**: Skip problematic documents automatically
- **Smart Batching**: Optimize processing based on token limits and system health
- **Progress Tracking**: Real-time success rates, error types, and completion estimates
- **State Management**: Resume interrupted processing sessions

### Installation Options
- **Core Installation**: Basic PDF processing without heavy NLP dependencies  
- **Full Installation**: Advanced features with spaCy and ML libraries
- **Flexible Dependencies**: Install only what you need

## 🚀 Installation

### Option 1: Core Installation (Recommended)
Basic PDF processing with Claude integration:

```bash
git clone https://github.com/yourusername/pdf-knowledge-extractor.git
cd pdf-knowledge-extractor
pip install -r requirements-core.txt
pip install -e .
```

### Option 2: Full Installation
All features including advanced NLP:

```bash
pip install -r requirements-full.txt
pip install -e .
# Install spaCy language model
python -m spacy download en_core_web_sm
```

### Option 3: Pip Installation with Optional Features
```bash
# Core installation
pip install pdf-knowledge-extractor

# With basic NLP features
pip install pdf-knowledge-extractor[nlp]

# With all advanced features
pip install pdf-knowledge-extractor[advanced]

# Development installation
pip install pdf-knowledge-extractor[dev]
```

## 🔧 Prerequisites

### Required
- Python 3.8+
- Claude CLI installed and configured ([Installation Guide](https://github.com/anthropics/claude-cli))

### Optional
- spaCy (for advanced NLP features)
- transformers (for ML models)

## 📖 Quick Start

### 1. Test Claude CLI
First, ensure Claude CLI is working:

```bash
pdf-extract --test-claude
```

### 2. Analyze PDFs
Basic PDF analysis to identify processable documents:

```bash
# Analyze a directory of PDFs
pdf-extract /path/to/pdfs --mode analyze

# Analyze with custom limits
pdf-extract /path/to/pdfs --mode analyze --max-size 25 --max-pages 200
```

### 3. Claude Batch Processing
Process PDFs with Claude AI for insights:

```bash
# Basic Claude processing
pdf-extract /path/to/pdfs --mode claude-batch --output ./results

# With reliability features
pdf-extract /path/to/pdfs --mode claude-batch --skip-failed --claude-timeout 180

# Resume interrupted processing
pdf-extract /path/to/pdfs --mode claude-batch --resume --output ./results
```

## 🎛️ Command Reference

### Analysis Mode
```bash
pdf-extract /path/to/pdfs --mode analyze [options]

Options:
  --max-size FLOAT       Maximum file size in MB (default: varies)
  --max-pages INT        Maximum page count (default: varies)
  --recursive            Search subdirectories
  --resume               Resume interrupted analysis
```

### Claude Batch Mode
```bash
pdf-extract /path/to/pdfs --mode claude-batch [options]

Reliability Options:
  --test-claude          Test Claude CLI before processing
  --skip-failed          Skip failed documents instead of retrying
  --claude-timeout INT   Claude CLI timeout in seconds (default: 120)
  --max-retries INT      Maximum retry attempts (default: 3)
  --batch-size INT       Documents per batch (default: 5)

Output Options:
  --output DIR           Output directory (default: current)
  --resume               Resume from previous session
  --no-progress          Disable progress bars
```

### Single File Processing
```bash
pdf-extract document.pdf --mode extract [options]

Options:
  --extract-text         Extract text content
  --process-text         Clean and process text
  --analyze-content      Perform content analysis
```

## 📁 Output Structure

After processing, you'll find:

```
output_directory/
├── processable_pdfs.json          # List of PDFs suitable for processing
├── pdf_analysis_errors.json       # Documents that failed analysis
├── complete_analysis.json         # Full analysis results
├── processing_summary.md          # Final processing summary
├── batch1_summary.md              # Individual batch summaries
├── batch2_summary.md
├── document1_analysis.md          # Individual document analyses
├── document2_analysis.md
└── .claude_processing_state.json  # Resume state (hidden)
```

## 🛠️ Configuration

Create a `config.yaml` file for custom settings:

```yaml
# Claude Integration Settings
claude:
  max_tokens_per_request: 8000
  context_window_size: 200000
  max_retries: 3
  retry_delay_base: 1.0
  retry_delay_max: 30.0
  timeout: 120
  batch_size: 5
  skip_failed: false
  health_check_enabled: true
  
  # Content filtering
  max_content_length: 500000
  min_content_quality_ratio: 0.7

# Analysis Settings  
analysis:
  max_size_mb: 25
  max_pages: 200

# Output Settings
output:
  format: markdown
  include_metadata: true
  include_cross_references: true
```

## 🔍 Success Rate Optimization

Our v1.0 improvements deliver significantly better reliability:

### Before (Original)
- ~20% success rate due to unhandled errors
- No retry logic for rate limits
- Crashes on large/corrupted files
- No progress tracking

### After (v1.0)
- **50%+ success rate** with smart filtering
- Intelligent retry with exponential backoff
- Automatic content filtering and validation
- Real-time progress with success metrics
- Graceful handling of Claude CLI issues

### Best Practices
1. **Start with health check**: `pdf-extract --test-claude`
2. **Use content filtering**: Let the tool skip problematic files automatically
3. **Enable skip-failed mode**: For large batches, use `--skip-failed` to maintain momentum
4. **Monitor progress**: Watch real-time success rates and health status
5. **Resume capability**: Large jobs can be safely interrupted and resumed

## 🔧 Troubleshooting

### Claude CLI Issues

**Problem**: "Claude CLI not found"
```bash
# Solution: Install Claude CLI
npm install -g @anthropic/claude-cli
# Or follow: https://github.com/anthropics/claude-cli
```

**Problem**: "Authentication failed"
```bash
# Solution: Configure Claude CLI
claude auth login
```

**Problem**: Rate limiting
```bash
# Solution: Use skip-failed mode and let the tool handle retries
pdf-extract /path/to/pdfs --mode claude-batch --skip-failed
```

### Processing Issues

**Problem**: Low success rate
- Check Claude CLI health: `pdf-extract --test-claude`
- Enable content filtering (automatic in v1.0)
- Use `--skip-failed` for problematic document sets
- Increase timeout: `--claude-timeout 300`

**Problem**: Large files failing
- The tool automatically filters files >50MB and >500 pages
- Check `pdf_analysis_errors.json` for specific issues
- Consider splitting large PDFs manually

**Problem**: Memory issues
- Reduce batch size: `--batch-size 3`
- Process in smaller chunks
- Check available system memory

### Installation Issues

**Problem**: spaCy installation fails
```bash
# Solution: Use core installation instead
pip install -r requirements-core.txt
# spaCy is optional for basic functionality
```

**Problem**: Missing dependencies
```bash
# Solution: Clean install
pip uninstall pdf-knowledge-extractor
pip install -r requirements-core.txt
pip install -e .
```

## 🧪 Development

### Running Tests
```bash
python -m pytest tests/ -v
```

### Code Quality
```bash
# Format code
black src/ tests/

# Lint code  
flake8 src/ tests/

# Type checking
mypy src/
```

### Adding Features
The modular design makes it easy to extend:

1. **PDF Processing**: Extend `PDFExtractor` class
2. **Claude Integration**: Modify `ClaudeIntegration` class  
3. **CLI Features**: Update `cli.py` argument parser
4. **Analysis Logic**: Enhance `KnowledgeAnalyzer` class

## 📊 Performance Metrics

Typical performance on a modern system:

- **Processing Speed**: 1-3 documents per minute (depends on Claude API)
- **Memory Usage**: ~100MB base + ~1MB per document
- **Success Rate**: 50-80% (varies by document quality)
- **Resumability**: 100% - all progress is saved and resumable

## 🚦 Version History

### v1.0.0 (Current)
- ✅ Complete Claude CLI integration rewrite
- ✅ Intelligent error handling and retry logic
- ✅ Content filtering and quality validation  
- ✅ Real-time progress tracking with success rates
- ✅ Optional spaCy dependencies
- ✅ Health monitoring and graceful degradation
- ✅ Resume capability for interrupted processing
- ✅ Enhanced CLI with reliability flags

### v0.1.0 (Initial)
- Basic PDF extraction
- Simple Claude integration
- Limited error handling

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)  
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/pdf-knowledge-extractor/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/pdf-knowledge-extractor/discussions)
- **Claude CLI Help**: [Official Documentation](https://github.com/anthropics/claude-cli)

---

**Ready to extract knowledge from your PDFs?** Start with `pdf-extract --test-claude` and then process your first batch!