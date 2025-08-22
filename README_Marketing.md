# 🚀 PDF Knowledge Extractor
### Transform Your Document Collection into an Intelligent Knowledge Graph

## The Problem
- **Information Overload**: Thousands of PDFs scattered across folders
- **No Connections**: Can't find relationships between documents  
- **Manual Work**: Hours spent searching for relevant information
- **Siloed Knowledge**: Insights trapped in individual documents

## What It Does
**Input:** 📁 Folder of PDFs  
**Output:** 🧠 Intelligent knowledge base with connections, insights, and exports

### Key Capabilities
- 🤖 **AI-Powered Analysis** using Claude AI
- 🔗 **Semantic Relationships** between documents
- 📊 **Knowledge Graph Visualization** 
- 📤 **25+ Export Formats** (Obsidian, Notion, Anki, LaTeX, etc.)
- 🎯 **Topic Clustering** and concept extraction

## Live Demo
![Knowledge Graph Demo](demo.gif)
*Interactive knowledge graph of 30 research papers with semantic connections*

## Quick Start
```bash
git clone https://github.com/jjc324/pdf-knowledge-extractor
cd pdf-knowledge-extractor
pip install -r requirements.txt

# Analyze and visualize your PDFs
python -m pdf_knowledge_extractor.cli /path/to/pdfs --mode claude-batch --knowledge-graph --export-formats obsidian