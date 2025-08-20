"""
Command-line interface for the PDF knowledge extractor.

Enhanced CLI that integrates the original pdf_analyzer.py functionality
with the new professional architecture.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Dict

from . import PDFExtractor, TextProcessor, KnowledgeAnalyzer
from .utils import load_config, setup_logging
from .claude_integration import ClaudeIntegration


def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser with both analysis and extraction options."""
    parser = argparse.ArgumentParser(
        description="Analyze and extract knowledge from PDF documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze PDFs in a directory (original pdf_analyzer.py functionality)
  pdf-extract /path/to/pdfs --mode analyze

  # Extract text and analyze a single PDF
  pdf-extract document.pdf --mode extract --extract-text

  # Resume interrupted analysis
  pdf-extract /path/to/pdfs --mode analyze --resume

  # Custom limits for analysis
  pdf-extract /path/to/pdfs --mode analyze --max-size 25 --max-pages 200
  
  # Test Claude CLI health
  pdf-extract --test-claude
  
  # Claude batch processing (after running analysis)
  pdf-extract /path/to/pdfs --mode claude-batch --output ./claude_results
  
  # Claude batch with reliability features
  pdf-extract /path/to/pdfs --mode claude-batch --skip-failed --claude-timeout 180
  
  # Claude batch with custom settings
  pdf-extract /path/to/pdfs --mode claude-batch --batch-size 10 --max-retries 5
  
  # Semantic analysis - find document connections
  pdf-extract /path/to/pdfs --mode claude-batch --generate-connections
  
  # Advanced semantic analysis with knowledge graph
  pdf-extract /path/to/pdfs --mode claude-batch --generate-connections --knowledge-graph --topic-clustering
  
  # Find documents similar to a specific document
  pdf-extract /path/to/pdfs --find-similar "document.pdf" --similarity-threshold 0.8
  
  # Extract concepts and export knowledge graph
  pdf-extract /path/to/pdfs --mode claude-batch --extract-concepts --knowledge-graph --export-formats graphml,json,html
  
  # Full semantic analysis with custom settings
  pdf-extract /path/to/pdfs --mode claude-batch --generate-connections --topic-clustering --extract-concepts --knowledge-graph --max-concepts 150
        """
    )
    
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to PDF file or directory containing PDFs"
    )
    
    parser.add_argument(
        "-m", "--mode",
        choices=["analyze", "extract", "both", "claude-batch"],
        default="analyze",
        help="Mode of operation: analyze (check size/pages), extract (get text), both, or claude-batch"
    )
    
    parser.add_argument(
        "-o", "--output",
        help="Output directory for results (default: current directory)",
        default="."
    )
    
    parser.add_argument(
        "-c", "--config",
        help="Path to configuration file",
        default="config.yaml"
    )
    
    # Analysis options (from original pdf_analyzer.py)
    parser.add_argument(
        "--max-size", 
        type=float,
        help="Maximum file size in MB for normal processing"
    )
    
    parser.add_argument(
        "--max-pages", 
        type=int,
        help="Maximum page count for normal processing"
    )
    
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        help="Search subdirectories recursively"
    )
    
    # Resume capability
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume interrupted analysis"
    )
    
    parser.add_argument(
        "--resume-file",
        help="Custom resume file path"
    )
    
    # Text extraction options
    parser.add_argument(
        "--extract-text",
        action="store_true",
        help="Extract text content from PDFs"
    )
    
    parser.add_argument(
        "--process-text",
        action="store_true",
        help="Process extracted text (clean, chunk, etc.)"
    )
    
    parser.add_argument(
        "--analyze-content",
        action="store_true",
        help="Perform content analysis on extracted text"
    )
    
    # Claude integration options
    parser.add_argument(
        "--processable-pdfs",
        help="Path to processable_pdfs.json file for Claude batch processing"
    )
    
    parser.add_argument(
        "--batch-size",
        type=int,
        help="Batch size for Claude processing"
    )
    
    parser.add_argument(
        "--max-retries",
        type=int,
        help="Maximum retry attempts for failed documents"
    )
    
    parser.add_argument(
        "--test-claude",
        action="store_true",
        help="Test Claude CLI health before processing"
    )
    
    parser.add_argument(
        "--skip-failed",
        action="store_true",
        help="Skip documents that fail processing instead of retrying"
    )
    
    parser.add_argument(
        "--claude-timeout",
        type=int,
        help="Timeout in seconds for Claude CLI operations (default: 120)"
    )
    
    # New smart batch optimization options
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview job difficulty and estimated success rate without processing"
    )
    
    parser.add_argument(
        "--adaptive-batching",
        action="store_true", 
        default=True,
        help="Enable intelligent batch sizing based on document complexity (default: enabled)"
    )
    
    parser.add_argument(
        "--no-adaptive-batching",
        action="store_true",
        help="Disable adaptive batching and use simple batching"
    )
    
    parser.add_argument(
        "--quality-threshold",
        type=float,
        help="Minimum document quality score (0.0-1.0) for processing (default: 0.5)"
    )
    
    parser.add_argument(
        "--fast-mode",
        action="store_true",
        help="Fast processing mode - skip quality analysis and use aggressive settings"
    )
    
    parser.add_argument(
        "--quarantine-management",
        choices=["release", "list", "clear"],
        help="Manage quarantined documents: release, list, or clear all"
    )
    
    # Semantic analysis options
    parser.add_argument(
        "--generate-connections",
        action="store_true",
        help="Enable semantic analysis to find document connections and relationships"
    )
    
    parser.add_argument(
        "--similarity-threshold",
        type=float,
        default=0.7,
        help="Similarity threshold for document connections (0.0-1.0, default: 0.7)"
    )
    
    parser.add_argument(
        "--topic-clustering",
        action="store_true",
        help="Enable topic clustering and theme detection"
    )
    
    parser.add_argument(
        "--num-clusters",
        type=int,
        help="Number of clusters for topic clustering (auto-detect if not specified)"
    )
    
    parser.add_argument(
        "--extract-concepts",
        action="store_true",
        help="Extract key concepts, entities, and keywords from documents"
    )
    
    parser.add_argument(
        "--concept-method",
        choices=["tfidf", "entities", "phrases", "all"],
        default="all",
        help="Method for concept extraction (default: all)"
    )
    
    parser.add_argument(
        "--knowledge-graph",
        action="store_true",
        help="Generate knowledge graph from document relationships"
    )
    
    parser.add_argument(
        "--export-formats",
        help="Comma-separated list of export formats: graphml,json,gexf,html (default: json)"
    )
    
    parser.add_argument(
        "--find-similar",
        help="Find documents similar to the specified document ID or filename"
    )
    
    parser.add_argument(
        "--max-concepts",
        type=int,
        default=100,
        help="Maximum number of concepts to extract (default: 100)"
    )
    
    parser.add_argument(
        "--min-concept-frequency",
        type=int,
        default=2,
        help="Minimum frequency for concept inclusion (default: 2)"
    )
    
    # Progress and logging
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bar"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    parser.add_argument(
        "--log-file",
        help="Path to log file"
    )
    
    return parser


def test_claude_cli(logger) -> int:
    """Test Claude CLI health and return appropriate exit code."""
    from .claude_integration import ClaudeIntegration
    
    claude_integration = ClaudeIntegration({})
    is_healthy, message = claude_integration.test_claude_cli_health()
    
    if is_healthy:
        logger.info(f"✅ Claude CLI is healthy: {message}")
        return 0
    else:
        logger.error(f"❌ Claude CLI health check failed: {message}")
        logger.error("Please ensure Claude CLI is properly installed and configured.")
        logger.error("Installation: https://github.com/anthropics/claude-cli")
        return 1


def handle_preview_mode(args, config: Dict, logger) -> int:
    """Handle preview mode to estimate job difficulty and success rate.
    
    Args:
        args: Command line arguments
        config: Configuration dictionary
        logger: Logger instance
        
    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Check if path is provided
        if not args.path:
            logger.error("Path argument is required for preview mode")
            return 1
        
        path = Path(args.path)
        if not path.exists():
            logger.error(f"Path does not exist: {args.path}")
            return 1
        
        # Initialize PDF extractor for analysis
        extractor = PDFExtractor(config)
        
        logger.info("🔍 Analyzing documents for processing preview...")
        
        if path.is_dir():
            # Analyze directory
            results = extractor.analyze_directory(path, recursive=args.recursive)
        else:
            # Single file analysis
            results = {"processable": [], "special_handling": [], "errors": []}
            analysis = extractor.analyze_file(path)
            
            if 'error' in analysis:
                results['errors'].append(analysis)
            elif analysis.get('exceeds_size_limit') or analysis.get('exceeds_page_limit'):
                results['special_handling'].append(analysis)
            else:
                results['processable'].append(analysis)
        
        # Initialize Claude integration for quality assessment
        claude_integration = ClaudeIntegration(config)
        
        # Analyze quality and complexity for processable documents
        quality_stats = {
            "high_quality": 0,
            "medium_quality": 0,
            "low_quality": 0,
            "total_tokens": 0,
            "type_distribution": {},
            "complexity_distribution": {"small": 0, "medium": 0, "large": 0}
        }
        
        estimated_success_rate = 0.0
        estimated_processing_time = 0.0
        
        for doc_info in results['processable']:
            try:
                # Extract text for quality analysis
                text = extractor.extract_text(doc_info['path'])
                
                # Create temporary context for analysis
                temp_context = DocumentContext(
                    file_path=doc_info['path'],
                    filename=doc_info['filename'],
                    size_mb=doc_info['size_mb'],
                    page_count=doc_info['page_count'],
                    text_length=len(text),
                    estimated_tokens=claude_integration.estimate_tokens(text)
                )
                
                # Calculate quality metrics
                quality_metrics = claude_integration.calculate_document_quality_score(text, temp_context)
                overall_score = quality_metrics['overall_score']
                
                # Detect document type
                doc_type = claude_integration.detect_document_type(text, temp_context)
                
                # Update statistics
                quality_stats["total_tokens"] += temp_context.estimated_tokens
                quality_stats["type_distribution"][doc_type] = quality_stats["type_distribution"].get(doc_type, 0) + 1
                
                if overall_score >= 0.7:
                    quality_stats["high_quality"] += 1
                elif overall_score >= 0.4:
                    quality_stats["medium_quality"] += 1
                else:
                    quality_stats["low_quality"] += 1
                
                # Complexity classification
                if temp_context.estimated_tokens < 5000:
                    quality_stats["complexity_distribution"]["small"] += 1
                elif temp_context.estimated_tokens < 20000:
                    quality_stats["complexity_distribution"]["medium"] += 1
                else:
                    quality_stats["complexity_distribution"]["large"] += 1
                
                # Estimate success probability and processing time
                success_prob = claude_integration.calculate_success_probability(temp_context)
                estimated_success_rate += success_prob
                
                # Estimate processing time (rough estimate: 5-30 seconds per document)
                base_time = 10 + (temp_context.estimated_tokens / 1000)  # Base time + token complexity
                estimated_processing_time += base_time * (2.0 - success_prob)  # Adjust for retry likelihood
                
            except Exception as e:
                logger.warning(f"Could not analyze {doc_info['filename']}: {e}")
                quality_stats["low_quality"] += 1
        
        # Calculate final statistics
        total_processable = len(results['processable'])
        if total_processable > 0:
            estimated_success_rate = (estimated_success_rate / total_processable) * 100
            estimated_processing_time_minutes = estimated_processing_time / 60
        else:
            estimated_success_rate = 0
            estimated_processing_time_minutes = 0
        
        # Generate batches for batch count estimation
        if total_processable > 0:
            claude_integration.initialize_document_contexts(results['processable'])
            batches = claude_integration.create_batches()
            estimated_batches = len(batches)
        else:
            estimated_batches = 0
        
        # Print comprehensive preview
        print("\n" + "="*80)
        print("🎯 PDF KNOWLEDGE EXTRACTOR - PROCESSING PREVIEW")
        print("="*80)
        
        print(f"\n📁 Document Analysis:")
        print(f"  • Total documents found: {len(results['processable']) + len(results['special_handling']) + len(results['errors'])}")
        print(f"  • Processable documents: {total_processable}")
        print(f"  • Special handling required: {len(results['special_handling'])}")
        print(f"  • Errors/Unreadable: {len(results['errors'])}")
        
        if total_processable > 0:
            print(f"\n📊 Quality Distribution:")
            print(f"  • High quality (≥70%): {quality_stats['high_quality']} documents")
            print(f"  • Medium quality (40-70%): {quality_stats['medium_quality']} documents")
            print(f"  • Low quality (<40%): {quality_stats['low_quality']} documents")
            
            print(f"\n📚 Document Types:")
            for doc_type, count in sorted(quality_stats['type_distribution'].items()):
                print(f"  • {doc_type.title()}: {count} documents")
            
            print(f"\n⚖️ Complexity Distribution:")
            print(f"  • Small (<5k tokens): {quality_stats['complexity_distribution']['small']} documents")
            print(f"  • Medium (5k-20k tokens): {quality_stats['complexity_distribution']['medium']} documents")
            print(f"  • Large (>20k tokens): {quality_stats['complexity_distribution']['large']} documents")
            
            print(f"\n🎲 Processing Estimates:")
            print(f"  • Estimated success rate: {estimated_success_rate:.1f}%")
            print(f"  • Estimated processing time: {estimated_processing_time_minutes:.1f} minutes")
            print(f"  • Estimated batches: {estimated_batches}")
            print(f"  • Total tokens to process: {quality_stats['total_tokens']:,}")
            
            # Success rate assessment
            if estimated_success_rate >= 85:
                success_assessment = "🟢 Excellent - High success rate expected"
            elif estimated_success_rate >= 70:
                success_assessment = "🟡 Good - Moderate success rate expected"
            elif estimated_success_rate >= 50:
                success_assessment = "🟠 Fair - Some challenges expected"
            else:
                success_assessment = "🔴 Challenging - Many failures likely"
            
            print(f"\n📈 Assessment: {success_assessment}")
            
            # Recommendations
            print(f"\n💡 Recommendations:")
            if quality_stats['low_quality'] > total_processable * 0.3:
                print(f"  • Consider increasing --quality-threshold to filter low-quality documents")
            if quality_stats['complexity_distribution']['large'] > 0:
                print(f"  • Large documents detected - consider using --adaptive-batching")
            if estimated_success_rate < 70:
                print(f"  • Lower success rate expected - consider using --skip-failed option")
            if estimated_processing_time_minutes > 60:
                print(f"  • Long processing time expected - consider using --fast-mode for quicker processing")
        
        print("\n" + "="*80)
        
        return 0
        
    except Exception as e:
        logger.error(f"Preview mode failed: {e}")
        if args.verbose:
            import traceback
            logger.error(traceback.format_exc())
        return 1


def handle_claude_batch_processing(args, config: Dict, logger) -> int:
    """Handle Claude batch processing mode.
    
    Args:
        args: Command line arguments
        config: Configuration dictionary
        logger: Logger instance
        
    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        # Determine processable PDFs file
        if args.processable_pdfs:
            processable_pdfs_file = Path(args.processable_pdfs)
        else:
            # Look for processable_pdfs.json in the path directory
            path = Path(args.path)
            if path.is_file():
                processable_pdfs_file = path.parent / "processable_pdfs.json"
            else:
                processable_pdfs_file = path / "processable_pdfs.json"
        
        if not processable_pdfs_file.exists():
            logger.error(f"Processable PDFs file not found: {processable_pdfs_file}")
            logger.info("Run PDF analysis first to generate processable_pdfs.json")
            return 1
        
        logger.info(f"Using processable PDFs file: {processable_pdfs_file}")
        
        # Initialize Claude integration
        claude_integration = ClaudeIntegration(config)
        
        # Perform initial health check if enabled
        if not args.skip_failed:  # Only do health check if we're not skipping failures
            is_healthy, health_msg = claude_integration.test_claude_cli_health()
            if not is_healthy:
                logger.error(f"Claude CLI health check failed: {health_msg}")
                logger.error("Consider using --skip-failed to continue processing despite failures")
                return 1
            else:
                logger.info(f"Claude CLI health check passed: {health_msg}")
        
        # Run batch processing
        results = claude_integration.run_batch_processing(
            processable_pdfs_file=processable_pdfs_file,
            output_dir=args.output,
            resume=args.resume
        )
        
        # Print results summary
        logger.info("Claude batch processing completed!")
        logger.info(f"Total documents: {results['total_documents']}")
        logger.info(f"Successfully processed: {results['successful']}")
        logger.info(f"Failed: {results['failed']}")
        logger.info(f"Batches processed: {results['batches_processed']}")
        logger.info(f"Output directory: {results['output_directory']}")
        
        if results['failed'] > 0:
            logger.warning(f"{results['failed']} documents failed processing")
            return 1
        
        return 0
        
    except Exception as e:
        logger.error(f"Claude batch processing failed: {e}")
        if args.verbose:
            import traceback
            logger.error(traceback.format_exc())
        return 1


def handle_semantic_analysis(args, config: Dict, logger, processable_pdfs_file: Path) -> int:
    """Handle semantic analysis operations.
    
    Args:
        args: Command line arguments
        config: Configuration dictionary
        logger: Logger instance
        processable_pdfs_file: Path to processable PDFs file
        
    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        from .semantic_analyzer import SemanticAnalyzer
        from .extractor import PDFExtractor
        import json
        
        logger.info("Starting semantic analysis...")
        
        # Load processable PDFs
        with open(processable_pdfs_file, 'r') as f:
            pdf_data = json.load(f)
        
        # Initialize PDF extractor to get document texts
        extractor = PDFExtractor(config)
        
        # Extract texts and prepare documents dictionary
        documents = {}
        metadata = {}
        
        for pdf_info in pdf_data:
            doc_id = pdf_info['filename']
            file_path = Path(pdf_info['path'])
            
            try:
                # Extract text
                text = extractor.extract_text(file_path)
                if text.strip():  # Only include documents with content
                    documents[doc_id] = text
                    metadata[doc_id] = {
                        'filename': pdf_info['filename'],
                        'path': pdf_info['path'],
                        'size_mb': pdf_info.get('size_mb', 0),
                        'page_count': pdf_info.get('page_count', 0),
                        'title': pdf_info.get('filename', '').replace('.pdf', '')
                    }
                    logger.debug(f"Loaded document: {doc_id}")
                else:
                    logger.warning(f"Skipping empty document: {doc_id}")
                    
            except Exception as e:
                logger.warning(f"Failed to extract text from {doc_id}: {e}")
                continue
        
        if not documents:
            logger.error("No valid documents found for semantic analysis")
            return 1
        
        logger.info(f"Loaded {len(documents)} documents for semantic analysis")
        
        # Configure semantic analyzer
        semantic_config = config.setdefault('semantic', {})
        semantic_config['similarity_threshold'] = args.similarity_threshold
        semantic_config['max_concepts'] = args.max_concepts
        semantic_config['min_concept_frequency'] = args.min_concept_frequency
        
        # Initialize semantic analyzer
        semantic_analyzer = SemanticAnalyzer(semantic_config)
        
        # Run semantic analysis
        results = semantic_analyzer.analyze_document_collection(documents, metadata)
        
        # Save semantic analysis results
        output_dir = Path(args.output)
        output_dir.mkdir(exist_ok=True)
        
        semantic_results_file = output_dir / "semantic_analysis_results.json"
        with open(semantic_results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        logger.info(f"Semantic analysis results saved to: {semantic_results_file}")
        
        # Handle specific semantic analysis requests
        if args.knowledge_graph:
            logger.info("Generating knowledge graph...")
            export_formats = args.export_formats.split(',') if args.export_formats else ['json']
            
            for format_type in export_formats:
                if format_type == 'html':
                    # Generate HTML visualization
                    html_file = output_dir / "knowledge_graph.html"
                    generate_html_visualization(semantic_analyzer.knowledge_graph, html_file)
                    logger.info(f"Knowledge graph HTML visualization saved to: {html_file}")
                else:
                    # Export graph in specified format
                    graph_file = output_dir / f"knowledge_graph.{format_type}"
                    semantic_analyzer.export_knowledge_graph(graph_file, format_type)
                    logger.info(f"Knowledge graph exported to: {graph_file}")
        
        if args.find_similar:
            logger.info(f"Finding documents similar to: {args.find_similar}")
            similar_docs = semantic_analyzer.find_similar_documents(args.find_similar)
            
            if similar_docs:
                logger.info("Similar documents found:")
                for doc_id, similarity in similar_docs:
                    logger.info(f"  - {doc_id}: {similarity:.3f}")
                
                # Save similarity results
                similarity_file = output_dir / f"similar_to_{args.find_similar.replace('.pdf', '')}.json"
                similarity_results = [
                    {'document': doc_id, 'similarity_score': float(similarity)}
                    for doc_id, similarity in similar_docs
                ]
                with open(similarity_file, 'w') as f:
                    json.dump(similarity_results, f, indent=2)
                logger.info(f"Similarity results saved to: {similarity_file}")
            else:
                logger.info("No similar documents found above the threshold")
        
        # Generate summary report
        generate_semantic_summary_report(results, output_dir / "semantic_summary.md", logger)
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("SEMANTIC ANALYSIS COMPLETE")
        logger.info("="*60)
        logger.info(f"Documents analyzed: {results['total_documents']}")
        logger.info(f"Document similarities found: {len(results.get('similarities', []))}")
        logger.info(f"Concepts extracted: {len(results.get('concepts', []))}")
        logger.info(f"Document clusters: {len(results.get('clusters', []))}")
        
        if 'graph_stats' in results:
            graph_stats = results['graph_stats']
            logger.info(f"Knowledge graph nodes: {graph_stats.get('nodes', 0)}")
            logger.info(f"Knowledge graph edges: {graph_stats.get('edges', 0)}")
        
        logger.info(f"Results saved in: {output_dir}")
        logger.info("="*60)
        
        return 0
        
    except Exception as e:
        logger.error(f"Semantic analysis failed: {e}")
        if args.verbose:
            import traceback
            logger.error(traceback.format_exc())
        return 1


def generate_html_visualization(knowledge_graph, output_file: Path):
    """Generate HTML visualization for the knowledge graph."""
    import networkx as nx
    import json
    
    # Convert graph to JSON format for D3.js
    graph_data = nx.node_link_data(knowledge_graph)
    
    html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>PDF Knowledge Extractor - Knowledge Graph</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .node { stroke: #fff; stroke-width: 1.5px; }
        .link { stroke: #999; stroke-opacity: 0.6; }
        .node text { pointer-events: none; font: 10px sans-serif; }
        #graph { border: 1px solid #ccc; }
        .controls { margin-bottom: 20px; }
        .legend { margin-top: 20px; }
        .legend-item { display: inline-block; margin-right: 20px; }
        .legend-color { width: 20px; height: 20px; display: inline-block; margin-right: 5px; }
    </style>
</head>
<body>
    <h1>PDF Knowledge Extractor - Knowledge Graph</h1>
    <div class="controls">
        <button onclick="resetZoom()">Reset Zoom</button>
        <button onclick="toggleLabels()">Toggle Labels</button>
    </div>
    <div id="graph"></div>
    <div class="legend">
        <div class="legend-item">
            <span class="legend-color" style="background-color: #ff7f0e;"></span>
            Documents
        </div>
        <div class="legend-item">
            <span class="legend-color" style="background-color: #1f77b4;"></span>
            Concepts
        </div>
    </div>
    
    <script>
        const graphData = """ + json.dumps(graph_data) + """;
        
        const width = 800;
        const height = 600;
        
        const svg = d3.select("#graph")
            .append("svg")
            .attr("width", width)
            .attr("height", height);
            
        const g = svg.append("g");
        
        // Add zoom behavior
        const zoom = d3.zoom()
            .on("zoom", (event) => {
                g.attr("transform", event.transform);
            });
        svg.call(zoom);
        
        // Color scale for node types
        const color = d3.scaleOrdinal()
            .domain(["document", "concept"])
            .range(["#ff7f0e", "#1f77b4"]);
        
        // Create simulation
        const simulation = d3.forceSimulation(graphData.nodes)
            .force("link", d3.forceLink(graphData.links).id(d => d.id))
            .force("charge", d3.forceManyBody().strength(-300))
            .force("center", d3.forceCenter(width / 2, height / 2));
        
        // Add links
        const link = g.append("g")
            .selectAll("line")
            .data(graphData.links)
            .enter().append("line")
            .attr("class", "link")
            .attr("stroke-width", d => Math.sqrt(d.weight || 1));
        
        // Add nodes
        const node = g.append("g")
            .selectAll("circle")
            .data(graphData.nodes)
            .enter().append("circle")
            .attr("class", "node")
            .attr("r", 8)
            .attr("fill", d => color(d.node_type || "concept"))
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));
        
        // Add labels
        const labels = g.append("g")
            .selectAll("text")
            .data(graphData.nodes)
            .enter().append("text")
            .text(d => d.label || d.id)
            .attr("font-size", "10px")
            .attr("dx", 12)
            .attr("dy", 4);
        
        // Add tooltips
        node.append("title")
            .text(d => d.label || d.id);
        
        // Update positions on simulation tick
        simulation.on("tick", () => {
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);
            
            node
                .attr("cx", d => d.x)
                .attr("cy", d => d.y);
                
            labels
                .attr("x", d => d.x)
                .attr("y", d => d.y);
        });
        
        // Drag functions
        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }
        
        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }
        
        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }
        
        // Control functions
        function resetZoom() {
            svg.transition().duration(500).call(zoom.transform, d3.zoomIdentity);
        }
        
        let labelsVisible = true;
        function toggleLabels() {
            labelsVisible = !labelsVisible;
            labels.style("opacity", labelsVisible ? 1 : 0);
        }
    </script>
</body>
</html>
    """
    
    with open(output_file, 'w') as f:
        f.write(html_template)


def generate_semantic_summary_report(results: Dict, output_file: Path, logger):
    """Generate a markdown summary report of semantic analysis results."""
    
    report_content = f"""# PDF Knowledge Extractor - Semantic Analysis Report

## Overview
- **Total Documents**: {results['total_documents']}
- **Analysis Date**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Document Similarities
Found **{len(results.get('similarities', []))}** document pairs with high similarity.

"""
    
    # Add top similarities
    similarities = results.get('similarities', [])
    if similarities:
        report_content += "### Top Document Similarities\n\n"
        top_similarities = sorted(similarities, key=lambda x: x['similarity_score'], reverse=True)[:10]
        
        for sim in top_similarities:
            report_content += f"- **{sim['doc1_id']}** ↔ **{sim['doc2_id']}**: {sim['similarity_score']:.3f}\n"
            if sim.get('shared_concepts'):
                report_content += f"  - Shared concepts: {', '.join(sim['shared_concepts'][:5])}\n"
        report_content += "\n"
    
    # Add concept analysis
    concepts = results.get('concepts', [])
    if concepts:
        report_content += f"## Key Concepts\nExtracted **{len(concepts)}** key concepts across all documents.\n\n"
        report_content += "### Most Important Concepts\n\n"
        
        top_concepts = sorted(concepts, key=lambda x: x['importance_score'], reverse=True)[:15]
        for concept in top_concepts:
            report_content += f"- **{concept['text']}** ({concept['concept_type']})\n"
            report_content += f"  - Frequency: {concept['frequency']}\n"
            report_content += f"  - Importance: {concept['importance_score']:.3f}\n"
            report_content += f"  - Documents: {len(concept['document_ids'])}\n\n"
    
    # Add cluster analysis
    clusters = results.get('clusters', [])
    if clusters:
        report_content += f"## Document Clusters\nIdentified **{len(clusters)}** thematic clusters.\n\n"
        
        for cluster in clusters:
            report_content += f"### {cluster['cluster_label']}\n"
            report_content += f"- **Documents**: {len(cluster['document_ids'])}\n"
            report_content += f"- **Coherence Score**: {cluster['coherence_score']:.3f}\n"
            report_content += f"- **Main Topics**: {', '.join(cluster['main_topics'])}\n"
            report_content += f"- **Documents in cluster**:\n"
            for doc_id in cluster['document_ids']:
                report_content += f"  - {doc_id}\n"
            report_content += "\n"
    
    # Add graph statistics
    graph_stats = results.get('graph_stats', {})
    if graph_stats:
        report_content += "## Knowledge Graph Statistics\n\n"
        report_content += f"- **Nodes**: {graph_stats.get('nodes', 0)}\n"
        report_content += f"- **Edges**: {graph_stats.get('edges', 0)}\n"
        report_content += f"- **Density**: {graph_stats.get('density', 0):.4f}\n"
        report_content += f"- **Connected Components**: {graph_stats.get('connected_components', 0)}\n\n"
    
    report_content += """## How to Use This Analysis

1. **Similar Documents**: Use the similarity pairs to find related content and potential duplicates.
2. **Key Concepts**: Leverage the extracted concepts to understand main themes across your document collection.
3. **Document Clusters**: Use clusters to organize documents by theme and identify content gaps.
4. **Knowledge Graph**: Explore the interactive knowledge graph visualization to understand document relationships.

## Files Generated
- `semantic_analysis_results.json`: Complete analysis results in JSON format
- `knowledge_graph.*`: Knowledge graph in various formats (if requested)
- `semantic_summary.md`: This summary report

---
*Generated by PDF Knowledge Extractor v2.1*
"""
    
    with open(output_file, 'w') as f:
        f.write(report_content)
    
    logger.info(f"Semantic summary report saved to: {output_file}")


def main() -> int:
    """Main entry point for the CLI."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Set up logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(log_level, args.log_file)
    
    logger = logging.getLogger(__name__)
    
    try:
        # Load configuration
        config = {}
        if Path(args.config).exists():
            config = load_config(args.config)
            logger.info(f"Loaded configuration from {args.config}")
        else:
            logger.info("No configuration file found, using defaults")
        
        # Override config with command line arguments
        if args.max_size is not None:
            config.setdefault('analysis', {})['max_size_mb'] = args.max_size
        if args.max_pages is not None:
            config.setdefault('analysis', {})['max_pages'] = args.max_pages
        
        # Claude integration settings
        if args.batch_size is not None:
            config.setdefault('claude', {})['batch_size'] = args.batch_size
        if args.max_retries is not None:
            config.setdefault('claude', {})['max_retries'] = args.max_retries
        if args.claude_timeout is not None:
            config.setdefault('claude', {})['timeout'] = args.claude_timeout
        if args.skip_failed:
            config.setdefault('claude', {})['skip_failed'] = args.skip_failed
        
        # Smart batch optimization settings
        if args.no_adaptive_batching:
            config.setdefault('claude', {})['adaptive_batching'] = False
        elif args.adaptive_batching:
            config.setdefault('claude', {})['adaptive_batching'] = True
            
        if args.quality_threshold is not None:
            config.setdefault('claude', {})['quality_threshold'] = args.quality_threshold
            
        if args.fast_mode:
            # Fast mode optimizations
            config.setdefault('claude', {})['adaptive_batching'] = False
            config.setdefault('claude', {})['quality_threshold'] = 0.2  # Lower threshold
            config.setdefault('claude', {})['batch_size'] = max(args.batch_size or 5, 8)  # Larger batches
            config.setdefault('claude', {})['max_retries'] = 2  # Fewer retries
            logger.info("Fast mode enabled: Using aggressive processing settings")
        
        # Progress settings
        if args.no_progress:
            config.setdefault('progress', {})['enabled'] = False
        
        # Semantic analysis settings
        semantic_config = config.setdefault('semantic', {})
        if args.similarity_threshold is not None:
            semantic_config['similarity_threshold'] = args.similarity_threshold
        if args.max_concepts is not None:
            semantic_config['max_concepts'] = args.max_concepts
        if args.min_concept_frequency is not None:
            semantic_config['min_concept_frequency'] = args.min_concept_frequency
        
        # Enable semantic analysis if any semantic flags are set
        enable_semantic = any([
            args.generate_connections,
            args.topic_clustering,
            args.extract_concepts,
            args.knowledge_graph,
            args.find_similar
        ])
        
        if enable_semantic:
            config.setdefault('analyzer', {})['enable_semantic_analysis'] = True
        
        # Handle test-claude flag
        if args.test_claude:
            return test_claude_cli(logger)
        
        # Handle preview mode
        if args.preview:
            return handle_preview_mode(args, config, logger)
        
        # Check if path is required and provided
        if not args.path:
            logger.error("Path argument is required for this operation")
            logger.error("Use --help to see available options")
            return 1
        
        # Handle Claude batch processing mode
        if args.mode == "claude-batch":
            result = handle_claude_batch_processing(args, config, logger)
            
            # Run semantic analysis if requested
            if enable_semantic and result == 0:  # Only run if batch processing succeeded
                logger.info("Running semantic analysis after Claude batch processing...")
                
                # Determine processable PDFs file
                if args.processable_pdfs:
                    processable_pdfs_file = Path(args.processable_pdfs)
                else:
                    path = Path(args.path)
                    if path.is_file():
                        processable_pdfs_file = path.parent / "processable_pdfs.json"
                    else:
                        processable_pdfs_file = path / "processable_pdfs.json"
                
                if processable_pdfs_file.exists():
                    semantic_result = handle_semantic_analysis(args, config, logger, processable_pdfs_file)
                    if semantic_result != 0:
                        logger.warning("Semantic analysis failed, but Claude batch processing succeeded")
                else:
                    logger.warning("Could not find processable_pdfs.json file for semantic analysis")
            
            return result
        
        # Handle standalone semantic analysis (for find-similar)
        if args.find_similar and not args.path:
            logger.error("Path argument is required when using --find-similar")
            return 1
        
        # Determine if path is file or directory
        path = Path(args.path)
        if not path.exists():
            logger.error(f"Path does not exist: {args.path}")
            return 1
        
        is_directory = path.is_dir()
        
        # Initialize PDF extractor with full config
        extractor = PDFExtractor(config)
        
        # Setup resume if requested
        if args.resume or args.resume_file:
            resume_file = args.resume_file or Path(args.output) / ".pdf_analysis_resume.json"
            extractor.setup_resume(resume_file)
            logger.info(f"Resume capability enabled: {resume_file}")
        
        # Perform analysis based on mode and path type
        if is_directory:
            logger.info(f"Analyzing directory: {path}")
            logger.info(f"Recursive search: {args.recursive}")
            
            # Directory analysis (main functionality from original pdf_analyzer.py)
            results = extractor.analyze_directory(path, recursive=args.recursive)
            
            # Save results
            saved_files = extractor.save_results(args.output)
            extractor.print_summary()
            
            logger.info(f"Analysis complete! Results saved:")
            for result_type, file_path in saved_files.items():
                logger.info(f"  {result_type}: {file_path}")
        
        else:
            # Single file processing
            logger.info(f"Processing single file: {path}")
            
            if args.mode in ["analyze", "both"]:
                # Analyze single file
                analysis = extractor.analyze_file(path)
                logger.info(f"Analysis result: {analysis}")
            
            if args.mode in ["extract", "both"] or args.extract_text:
                # Extract text from single file
                try:
                    text = extractor.extract_text(path)
                    logger.info(f"Extracted {len(text)} characters of text")
                    
                    if args.process_text:
                        # Process the text
                        processor = TextProcessor(config.get("processor", {}))
                        cleaned_text = processor.clean_text(text)
                        chunks = processor.split_into_chunks(cleaned_text)
                        logger.info(f"Processed text into {len(chunks)} chunks")
                    
                    if args.analyze_content:
                        # Analyze the content
                        analyzer = KnowledgeAnalyzer(config.get("analyzer", {}))
                        analysis = analyzer.analyze_content(text)
                        insights = analyzer.generate_insights(analysis)
                        
                        logger.info("Content Analysis Results:")
                        for insight in insights:
                            logger.info(f"  - {insight}")
                    
                    # Save single file results
                    output_file = Path(args.output) / f"{path.stem}_analysis.json"
                    import json
                    result_data = {
                        "file_path": str(path),
                        "analysis": analysis if 'analysis' in locals() else None,
                        "text_length": len(text),
                        "has_text": bool(text.strip())
                    }
                    
                    if args.process_text and 'chunks' in locals():
                        result_data["chunks_count"] = len(chunks)
                    
                    if args.analyze_content and 'insights' in locals():
                        result_data["insights"] = insights
                    
                    with open(output_file, 'w') as f:
                        json.dump(result_data, f, indent=2)
                    
                    logger.info(f"Results saved to: {output_file}")
                    
                except Exception as e:
                    logger.error(f"Failed to extract text: {e}")
                    return 1
        
        logger.info("Processing completed successfully!")
        return 0
        
    except Exception as e:
        logger.error(f"Error: {e}")
        if args.verbose:
            import traceback
            logger.error(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())