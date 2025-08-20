"""
Enterprise & Collaboration Export Formats
Support for Confluence, Microsoft Teams, and SharePoint
"""

import logging
import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import time
import html
import re

from .base import BaseExporter, TemplateExporter, ExportConfig, ExportResult

logger = logging.getLogger(__name__)


class ConfluenceExporter(TemplateExporter):
    """Export to Confluence wiki format with spaces and templates."""
    
    @property
    def supported_formats(self) -> List[str]:
        return ['confluence']
    
    @property
    def file_extension(self) -> str:
        return '.xml'
    
    @property
    def default_templates(self) -> Dict[str, str]:
        return {
            'space_template': """<?xml version="1.0" encoding="UTF-8"?>
<confluence xmlns="http://www.atlassian.com/confluence/export">
    <space>
        <name>PDF Knowledge Base</name>
        <key>PDFKB</key>
        <description>Knowledge extracted from PDF documents using semantic analysis</description>
    </space>
    <pages>
{pages_content}
    </pages>
</confluence>""",
            'page_template': """        <page>
            <id>{page_id}</id>
            <title>{title}</title>
            <space>PDFKB</space>
            <creator>pdf-extractor</creator>
            <created>{created}</created>
            <modified>{modified}</modified>
            <version>1</version>
            <content>
                <![CDATA[
<h1>{title}</h1>

<ac:structured-macro ac:name="info">
    <ac:parameter ac:name="title">Document Information</ac:parameter>
    <ac:rich-text-body>
        <p><strong>Source:</strong> {filename}</p>
        <p><strong>Word Count:</strong> {word_count}</p>
        <p><strong>Concepts Identified:</strong> {concept_count}</p>
        <p><strong>Analysis Date:</strong> {analysis_date}</p>
    </ac:rich-text-body>
</ac:structured-macro>

<h2>Executive Summary</h2>
<p>{summary}</p>

<h2>Key Concepts</h2>
<ac:structured-macro ac:name="expand">
    <ac:parameter ac:name="title">View All Concepts</ac:parameter>
    <ac:rich-text-body>
        <table>
            <thead>
                <tr>
                    <th>Concept</th>
                    <th>Type</th>
                    <th>Importance</th>
                    <th>Context</th>
                </tr>
            </thead>
            <tbody>
{concepts_table}
            </tbody>
        </table>
    </ac:rich-text-body>
</ac:structured-macro>

<h2>Related Documents</h2>
{related_content}

<h2>Document Clusters</h2>
{clusters_content}

<ac:structured-macro ac:name="metadata-list">
    <ac:parameter ac:name="orientation">horizontal</ac:parameter>
    <ac:rich-text-body>
        <ul>
            <li><ac:link><ri:page ri:content-title="Knowledge Extraction Process" /></ac:link></li>
            <li><ac:link><ri:page ri:content-title="Concept Index" /></ac:link></li>
        </ul>
    </ac:rich-text-body>
</ac:structured-macro>
                ]]>
            </content>
        </page>""",
            'concept_row': """                <tr>
                    <td><strong>{concept_text}</strong></td>
                    <td>{concept_type}</td>
                    <td>{importance:.2f}</td>
                    <td>{context}</td>
                </tr>""",
            'index_page': """        <page>
            <id>concept_index</id>
            <title>Concept Index</title>
            <space>PDFKB</space>
            <creator>pdf-extractor</creator>
            <created>{created}</created>
            <modified>{modified}</modified>
            <version>1</version>
            <content>
                <![CDATA[
<h1>Concept Index</h1>

<ac:structured-macro ac:name="toc">
    <ac:parameter ac:name="maxLevel">3</ac:parameter>
</ac:structured-macro>

<ac:structured-macro ac:name="info">
    <ac:parameter ac:name="title">Index Statistics</ac:parameter>
    <ac:rich-text-body>
        <p><strong>Total Concepts:</strong> {total_concepts}</p>
        <p><strong>Total Documents:</strong> {total_documents}</p>
        <p><strong>Generated:</strong> {generation_date}</p>
    </ac:rich-text-body>
</ac:structured-macro>

{concept_sections}
                ]]>
            </content>
        </page>"""
        }
    
    def export(self, analysis_data: Dict[str, Any], documents: Dict[str, str]) -> ExportResult:
        """Export to Confluence XML format."""
        start_time = time.time()
        
        try:
            errors = self.validate_config()
            if errors:
                return self.create_export_result(False, self.config.output_path, [], 0, errors=errors)
            
            output_path = self.prepare_output_path()
            
            pages_content = ""
            exported_docs = []
            total_concepts = 0
            
            semantic_data = analysis_data.get('semantic_analysis', {})
            
            # Create pages for each document
            for doc_id, doc_text in documents.items():
                doc_analysis = analysis_data.get('individual_analyses', {}).get(doc_id, {})
                
                page_content = self._create_confluence_page(doc_id, doc_text, doc_analysis, semantic_data)
                pages_content += page_content + "\n"
                
                exported_docs.append(doc_id)
                
                # Count concepts for this document
                if semantic_data and semantic_data.get('concepts'):
                    doc_concepts = [c for c in semantic_data['concepts'] 
                                  if doc_id in c.get('document_ids', [])]
                    total_concepts += len(doc_concepts)
            
            # Create concept index page
            if self.config.include_concepts and semantic_data.get('concepts'):
                index_page = self._create_concept_index_page(semantic_data['concepts'], len(documents))
                pages_content += index_page + "\n"
            
            # Create final Confluence export
            confluence_content = self.render_template('space_template', {
                'pages_content': pages_content
            })
            
            # Write Confluence XML
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(confluence_content)
            
            execution_time = time.time() - start_time
            
            return self.create_export_result(
                success=True,
                output_path=output_path,
                exported_docs=exported_docs,
                execution_time=execution_time,
                exported_concepts=total_concepts,
                stats={'confluence_pages': len(exported_docs) + 1}  # +1 for index
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Confluence export failed: {e}")
            return self.create_export_result(
                False, self.config.output_path, [], execution_time, errors=[str(e)]
            )
    
    def _create_confluence_page(self, doc_id: str, doc_text: str, doc_analysis: Dict, semantic_data: Dict) -> str:
        """Create a Confluence page for a document."""
        
        # Get concepts for this document
        doc_concepts = []
        if semantic_data and semantic_data.get('concepts'):
            doc_concepts = [c for c in semantic_data['concepts'] 
                          if doc_id in c.get('document_ids', [])]
            doc_concepts = self.filter_concepts(doc_concepts, doc_id)
        
        # Build concepts table
        concepts_table = ""
        for concept in doc_concepts:
            context = concept.get('context_sentences', [''])[0][:100] if concept.get('context_sentences') else ''
            if len(context) > 100:
                context += "..."
            
            concept_row = self.render_template('concept_row', {
                'concept_text': html.escape(concept.get('text', '')),
                'concept_type': concept.get('concept_type', 'unknown'),
                'importance': concept.get('importance_score', 0),
                'context': html.escape(context)
            })
            concepts_table += concept_row + "\n"
        
        # Build related documents content
        related_content = self._create_related_content_confluence(doc_id, semantic_data)
        
        # Build clusters content
        clusters_content = self._create_clusters_content_confluence(doc_id, semantic_data)
        
        # Generate summary
        summary = self._generate_summary(doc_text, doc_analysis)
        
        return self.render_template('page_template', {
            'page_id': str(hash(doc_id)),
            'title': html.escape(doc_id),
            'filename': html.escape(doc_id),
            'word_count': doc_analysis.get('word_count', 0),
            'concept_count': len(doc_concepts),
            'analysis_date': datetime.now().strftime('%Y-%m-%d'),
            'created': datetime.now().isoformat(),
            'modified': datetime.now().isoformat(),
            'summary': html.escape(summary),
            'concepts_table': concepts_table,
            'related_content': related_content,
            'clusters_content': clusters_content
        })
    
    def _create_related_content_confluence(self, doc_id: str, semantic_data: Dict) -> str:
        """Create related documents content."""
        if not semantic_data or not semantic_data.get('similarities'):
            return "<p>No related documents identified.</p>"
        
        content = "<ul>\n"
        for sim in semantic_data['similarities']:
            if (sim.get('doc1_id') == doc_id or sim.get('doc2_id') == doc_id) and \
               sim.get('similarity_score', 0) >= self.config.min_similarity_score:
                other_doc = sim.get('doc2_id') if sim.get('doc1_id') == doc_id else sim.get('doc1_id')
                similarity = sim.get('similarity_score', 0)
                
                content += f'    <li><ac:link><ri:page ri:content-title="{html.escape(other_doc)}" /></ac:link> '
                content += f'(similarity: {similarity:.1%})</li>\n'
        
        content += "</ul>"
        return content if "<li>" in content else "<p>No related documents found.</p>"
    
    def _create_clusters_content_confluence(self, doc_id: str, semantic_data: Dict) -> str:
        """Create clusters content."""
        if not semantic_data or not semantic_data.get('clusters'):
            return "<p>No document clusters identified.</p>"
        
        content = ""
        for cluster in semantic_data['clusters']:
            if doc_id in cluster.get('document_ids', []):
                cluster_label = cluster.get('cluster_label', 'Unnamed Cluster')
                other_docs = [did for did in cluster.get('document_ids', []) if did != doc_id]
                main_topics = cluster.get('main_topics', [])
                
                content += f'<ac:structured-macro ac:name="panel">\n'
                content += f'    <ac:parameter ac:name="title">{html.escape(cluster_label)}</ac:parameter>\n'
                content += f'    <ac:rich-text-body>\n'
                content += f'        <p><strong>Other documents in this cluster:</strong></p>\n'
                content += f'        <ul>\n'
                
                for other_doc in other_docs[:5]:  # Show max 5 other documents
                    content += f'            <li><ac:link><ri:page ri:content-title="{html.escape(other_doc)}" /></ac:link></li>\n'
                
                content += f'        </ul>\n'
                
                if main_topics:
                    content += f'        <p><strong>Main topics:</strong> {html.escape(", ".join(main_topics[:3]))}</p>\n'
                
                content += f'    </ac:rich-text-body>\n'
                content += f'</ac:structured-macro>\n'
                break
        
        return content if content else "<p>This document is not part of any cluster.</p>"
    
    def _create_concept_index_page(self, concepts: List[Dict], total_documents: int) -> str:
        """Create concept index page."""
        
        # Group concepts by type
        concepts_by_type = {}
        for concept in concepts:
            concept_type = concept.get('concept_type', 'unknown')
            if concept_type not in concepts_by_type:
                concepts_by_type[concept_type] = []
            concepts_by_type[concept_type].append(concept)
        
        concept_sections = ""
        for concept_type, type_concepts in concepts_by_type.items():
            concept_sections += f"<h2>{concept_type.title()}s</h2>\n"
            concept_sections += "<table>\n"
            concept_sections += "    <thead>\n"
            concept_sections += "        <tr><th>Concept</th><th>Importance</th><th>Documents</th></tr>\n"
            concept_sections += "    </thead>\n"
            concept_sections += "    <tbody>\n"
            
            # Sort by importance
            type_concepts.sort(key=lambda x: x.get('importance_score', 0), reverse=True)
            
            for concept in type_concepts[:20]:  # Top 20 per type
                doc_links = []
                for doc_id in concept.get('document_ids', [])[:5]:  # Max 5 document links
                    doc_links.append(f'<ac:link><ri:page ri:content-title="{html.escape(doc_id)}" /></ac:link>')
                
                concept_sections += "        <tr>\n"
                concept_sections += f"            <td><strong>{html.escape(concept.get('text', ''))}</strong></td>\n"
                concept_sections += f"            <td>{concept.get('importance_score', 0):.2f}</td>\n"
                concept_sections += f"            <td>{', '.join(doc_links)}</td>\n"
                concept_sections += "        </tr>\n"
            
            concept_sections += "    </tbody>\n"
            concept_sections += "</table>\n\n"
        
        return self.render_template('index_page', {
            'created': datetime.now().isoformat(),
            'modified': datetime.now().isoformat(),
            'total_concepts': len(concepts),
            'total_documents': total_documents,
            'generation_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'concept_sections': concept_sections
        })
    
    def _generate_summary(self, doc_text: str, analysis: Dict) -> str:
        """Generate document summary."""
        sentences = doc_text.split('.')[:2]
        summary = '. '.join(sentences).strip()
        return summary[:400] + "..." if len(summary) > 400 else summary


class TeamsExporter(TemplateExporter):
    """Export to Microsoft Teams shared documents format."""
    
    @property
    def supported_formats(self) -> List[str]:
        return ['teams']
    
    @property
    def file_extension(self) -> str:
        return '.html'
    
    @property
    def default_templates(self) -> Dict[str, str]:
        return {
            'teams_template': """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>PDF Knowledge Analysis - Teams Document</title>
    <style>
        body {{ 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            margin: 20px; 
            line-height: 1.6; 
            color: #242424;
        }}
        .header {{
            background: linear-gradient(90deg, #5A5FC2 0%, #4B4EFC 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }}
        .card {{
            background: #F3F2F1;
            border: 1px solid #EDEBE9;
            border-radius: 8px;
            padding: 16px;
            margin-bottom: 16px;
        }}
        .concept-tag {{
            background: #E1DFDD;
            border-radius: 16px;
            padding: 4px 12px;
            font-size: 12px;
            margin: 2px;
            display: inline-block;
        }}
        .importance-high {{ background: #FFE6CC; }}
        .importance-medium {{ background: #FFF4CE; }}
        .importance-low {{ background: #E6F2FF; }}
        .teams-mention {{ color: #6264A7; font-weight: bold; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #EDEBE9; padding: 8px; text-align: left; }}
        th {{ background: #F3F2F1; font-weight: 600; }}
        .action-item {{ background: #FFF1CE; padding: 8px; border-radius: 4px; margin: 8px 0; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📄 PDF Knowledge Analysis Report</h1>
        <p>Generated on {timestamp} | {total_documents} documents analyzed</p>
    </div>

    <div class="card">
        <h2>📋 Executive Summary</h2>
        <p>{executive_summary}</p>
        
        <div class="action-item">
            <strong>💡 Action Items:</strong>
            <ul>
                <li>Review document clusters for potential consolidation</li>
                <li>Validate extracted concepts with subject matter experts</li>
                <li>Consider creating training materials from high-importance concepts</li>
            </ul>
        </div>
    </div>

    <div class="card">
        <h2>📊 Key Metrics</h2>
        <table>
            <tr>
                <td><strong>Total Documents</strong></td>
                <td>{total_documents}</td>
            </tr>
            <tr>
                <td><strong>Total Concepts</strong></td>
                <td>{total_concepts}</td>
            </tr>
            <tr>
                <td><strong>Document Relationships</strong></td>
                <td>{total_relationships}</td>
            </tr>
            <tr>
                <td><strong>Document Clusters</strong></td>
                <td>{total_clusters}</td>
            </tr>
        </table>
    </div>

    {document_sections}

    <div class="card">
        <h2>🔗 Document Relationships</h2>
        {relationships_section}
    </div>

    <div class="card">
        <h2>📚 Concept Overview</h2>
        {concepts_overview}
    </div>

    <div class="card">
        <h2>👥 Team Collaboration Notes</h2>
        <p><span class="teams-mention">@team</span> Please review the extracted concepts and provide feedback on:</p>
        <ul>
            <li>Accuracy of concept identification</li>
            <li>Relevance of document relationships</li>
            <li>Suggestions for additional analysis</li>
        </ul>
        
        <p><strong>Next Steps:</strong></p>
        <ul>
            <li>Schedule review meeting with <span class="teams-mention">@stakeholders</span></li>
            <li>Create action items based on findings</li>
            <li>Update knowledge base with validated concepts</li>
        </ul>
    </div>

    <footer style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #EDEBE9; color: #605E5C;">
        <p><em>Generated by PDF Knowledge Extractor v2.2 | For more information, contact <span class="teams-mention">@data-team</span></em></p>
    </footer>
</body>
</html>""",
            'document_section': """    <div class="card">
        <h3>📄 {title}</h3>
        <p><strong>Word Count:</strong> {word_count} | <strong>Concepts:</strong> {concept_count}</p>
        
        <h4>Summary</h4>
        <p>{summary}</p>
        
        <h4>Key Concepts</h4>
        <div>
{concept_tags}
        </div>
        
        <h4>Related Documents</h4>
        {related_docs}
    </div>""",
            'concept_tag': '<span class="concept-tag {importance_class}" title="Importance: {importance:.2f}">{concept_text}</span>'
        }
    
    def export(self, analysis_data: Dict[str, Any], documents: Dict[str, str]) -> ExportResult:
        """Export to Microsoft Teams format."""
        start_time = time.time()
        
        try:
            errors = self.validate_config()
            if errors:
                return self.create_export_result(False, self.config.output_path, [], 0, errors=errors)
            
            output_path = self.prepare_output_path()
            
            document_sections = ""
            exported_docs = []
            total_concepts = 0
            total_relationships = 0
            total_clusters = 0
            
            semantic_data = analysis_data.get('semantic_analysis', {})
            
            # Process each document
            for doc_id, doc_text in documents.items():
                doc_analysis = analysis_data.get('individual_analyses', {}).get(doc_id, {})
                
                doc_section = self._create_teams_document_section(doc_id, doc_text, doc_analysis, semantic_data)
                document_sections += doc_section + "\n"
                
                exported_docs.append(doc_id)
                
                # Count concepts for this document
                if semantic_data and semantic_data.get('concepts'):
                    doc_concepts = [c for c in semantic_data['concepts'] 
                                  if doc_id in c.get('document_ids', [])]
                    total_concepts += len(doc_concepts)
            
            # Count relationships and clusters
            if semantic_data:
                total_relationships = len(semantic_data.get('similarities', []))
                total_clusters = len(semantic_data.get('clusters', []))
            
            # Create relationships section
            relationships_section = self._create_relationships_section_teams(semantic_data.get('similarities', []))
            
            # Create concepts overview
            concepts_overview = self._create_concepts_overview_teams(semantic_data.get('concepts', []))
            
            # Generate executive summary
            executive_summary = self._generate_executive_summary_teams(analysis_data, documents)
            
            # Create Teams document
            teams_content = self.render_template('teams_template', {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'total_documents': len(documents),
                'total_concepts': total_concepts,
                'total_relationships': total_relationships,
                'total_clusters': total_clusters,
                'executive_summary': executive_summary,
                'document_sections': document_sections,
                'relationships_section': relationships_section,
                'concepts_overview': concepts_overview
            })
            
            # Write Teams HTML
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(teams_content)
            
            execution_time = time.time() - start_time
            
            return self.create_export_result(
                success=True,
                output_path=output_path,
                exported_docs=exported_docs,
                execution_time=execution_time,
                exported_concepts=total_concepts,
                exported_relationships=total_relationships,
                stats={'teams_sections': len(exported_docs)}
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Teams export failed: {e}")
            return self.create_export_result(
                False, self.config.output_path, [], execution_time, errors=[str(e)]
            )
    
    def _create_teams_document_section(self, doc_id: str, doc_text: str, doc_analysis: Dict, semantic_data: Dict) -> str:
        """Create Teams document section."""
        
        # Get concepts for this document
        doc_concepts = []
        if semantic_data and semantic_data.get('concepts'):
            doc_concepts = [c for c in semantic_data['concepts'] 
                          if doc_id in c.get('document_ids', [])]
            doc_concepts = self.filter_concepts(doc_concepts, doc_id)
        
        # Create concept tags
        concept_tags = ""
        for concept in doc_concepts[:15]:  # Limit to 15 concepts for readability
            importance = concept.get('importance_score', 0)
            importance_class = self._get_importance_class(importance)
            
            concept_tag = self.render_template('concept_tag', {
                'concept_text': html.escape(concept.get('text', '')),
                'importance': importance,
                'importance_class': importance_class
            })
            concept_tags += concept_tag + "\n"
        
        # Create related documents list
        related_docs = self._create_related_docs_teams(doc_id, semantic_data)
        
        # Generate summary
        summary = self._generate_summary(doc_text, doc_analysis)
        
        return self.render_template('document_section', {
            'title': html.escape(doc_id),
            'word_count': doc_analysis.get('word_count', 0),
            'concept_count': len(doc_concepts),
            'summary': html.escape(summary),
            'concept_tags': concept_tags,
            'related_docs': related_docs
        })
    
    def _create_related_docs_teams(self, doc_id: str, semantic_data: Dict) -> str:
        """Create related documents section for Teams."""
        if not semantic_data or not semantic_data.get('similarities'):
            return "<p>No related documents identified.</p>"
        
        content = "<ul>\n"
        found_related = False
        
        for sim in semantic_data['similarities']:
            if (sim.get('doc1_id') == doc_id or sim.get('doc2_id') == doc_id) and \
               sim.get('similarity_score', 0) >= self.config.min_similarity_score:
                other_doc = sim.get('doc2_id') if sim.get('doc1_id') == doc_id else sim.get('doc1_id')
                similarity = sim.get('similarity_score', 0)
                
                content += f"    <li><strong>{html.escape(other_doc)}</strong> "
                content += f"<span style='color: #6264A7;'>({similarity:.1%} similarity)</span></li>\n"
                found_related = True
        
        content += "</ul>"
        return content if found_related else "<p>No related documents found.</p>"
    
    def _create_relationships_section_teams(self, similarities: List[Dict]) -> str:
        """Create relationships section for Teams."""
        if not similarities:
            return "<p>No document relationships identified.</p>"
        
        content = "<table>\n"
        content += "    <tr><th>Document 1</th><th>Document 2</th><th>Similarity</th><th>Status</th></tr>\n"
        
        # Sort by similarity
        sorted_sims = sorted(similarities, key=lambda x: x.get('similarity_score', 0), reverse=True)
        
        for sim in sorted_sims[:15]:  # Top 15 relationships
            similarity = sim.get('similarity_score', 0)
            status = "🔴 Low" if similarity < 0.5 else "🟡 Medium" if similarity < 0.8 else "🟢 High"
            
            content += "    <tr>\n"
            content += f"        <td>{html.escape(sim.get('doc1_id', ''))}</td>\n"
            content += f"        <td>{html.escape(sim.get('doc2_id', ''))}</td>\n"
            content += f"        <td>{similarity:.1%}</td>\n"
            content += f"        <td>{status}</td>\n"
            content += "    </tr>\n"
        
        content += "</table>"
        return content
    
    def _create_concepts_overview_teams(self, concepts: List[Dict]) -> str:
        """Create concepts overview for Teams."""
        if not concepts:
            return "<p>No concepts extracted.</p>"
        
        # Group by concept type
        concepts_by_type = {}
        for concept in concepts:
            concept_type = concept.get('concept_type', 'unknown')
            if concept_type not in concepts_by_type:
                concepts_by_type[concept_type] = []
            concepts_by_type[concept_type].append(concept)
        
        content = ""
        for concept_type, type_concepts in concepts_by_type.items():
            content += f"<h4>{concept_type.title()}s ({len(type_concepts)})</h4>\n"
            
            # Sort by importance and take top concepts
            type_concepts.sort(key=lambda x: x.get('importance_score', 0), reverse=True)
            
            for concept in type_concepts[:10]:  # Top 10 per type
                importance = concept.get('importance_score', 0)
                importance_class = self._get_importance_class(importance)
                
                content += f'<span class="concept-tag {importance_class}" title="Importance: {importance:.2f}, '
                content += f'Found in {len(concept.get("document_ids", []))} documents">'
                content += f'{html.escape(concept.get("text", ""))}</span>\n'
            
            content += "<br><br>\n"
        
        return content
    
    def _generate_executive_summary_teams(self, analysis_data: Dict, documents: Dict) -> str:
        """Generate executive summary for Teams."""
        summary = f"Analysis completed on {len(documents)} PDF documents using semantic analysis. "
        
        semantic_data = analysis_data.get('semantic_analysis', {})
        if semantic_data:
            if semantic_data.get('concepts'):
                summary += f"Extracted {len(semantic_data['concepts'])} unique concepts "
            
            if semantic_data.get('clusters'):
                summary += f"and organized documents into {len(semantic_data['clusters'])} thematic clusters. "
            
            if semantic_data.get('similarities'):
                high_sim_count = len([s for s in semantic_data['similarities'] 
                                    if s.get('similarity_score', 0) > 0.7])
                summary += f"Identified {high_sim_count} strong relationships between documents."
        
        return summary
    
    def _get_importance_class(self, importance: float) -> str:
        """Get CSS class based on importance score."""
        if importance > 0.8:
            return "importance-high"
        elif importance > 0.5:
            return "importance-medium"
        else:
            return "importance-low"
    
    def _generate_summary(self, doc_text: str, analysis: Dict) -> str:
        """Generate document summary."""
        sentences = doc_text.split('.')[:2]
        summary = '. '.join(sentences).strip()
        return summary[:300] + "..." if len(summary) > 300 else summary


class SharePointExporter(TemplateExporter):
    """Export to SharePoint knowledge base structure."""
    
    @property
    def supported_formats(self) -> List[str]:
        return ['sharepoint']
    
    @property
    def file_extension(self) -> str:
        return '.json'
    
    @property
    def default_templates(self) -> Dict[str, str]:
        return {
            'site_template': """{
    "sharepoint_site": {
        "title": "PDF Knowledge Base",
        "description": "Centralized knowledge extracted from PDF documents",
        "template": "SITEPAGEPUBLISHING#0",
        "lists": {lists_config},
        "pages": {pages_config},
        "document_libraries": {libraries_config}
    }
}""",
            'list_config': """{
    "Documents": {
        "template": "documentLibrary",
        "columns": [
            {"name": "Title", "type": "Text", "required": true},
            {"name": "SourceFile", "type": "Text"},
            {"name": "WordCount", "type": "Number"},
            {"name": "ConceptCount", "type": "Number"},
            {"name": "AnalysisDate", "type": "DateTime"},
            {"name": "KeyConcepts", "type": "Note"},
            {"name": "DocumentCluster", "type": "Choice", "choices": {cluster_choices}},
            {"name": "RelatedDocuments", "type": "Text"}
        ]
    },
    "Concepts": {
        "template": "genericList",
        "columns": [
            {"name": "Title", "type": "Text", "required": true},
            {"name": "ConceptType", "type": "Choice", "choices": ["Entity", "Keyword", "Topic", "Phrase"]},
            {"name": "ImportanceScore", "type": "Number"},
            {"name": "Frequency", "type": "Number"},
            {"name": "Context", "type": "Note"},
            {"name": "RelatedDocuments", "type": "Lookup", "lookupList": "Documents"}
        ]
    }
}""",
            'page_template': """{
    "title": "{title}",
    "content": [
        {
            "webPartType": "Text",
            "properties": {
                "text": "<h1>{title}</h1><p><strong>Source:</strong> {filename}</p><p><strong>Analysis Date:</strong> {analysis_date}</p>"
            }
        },
        {
            "webPartType": "QuickChart",
            "properties": {
                "chartType": "bar",
                "title": "Concept Distribution",
                "data": {concept_chart_data}
            }
        },
        {
            "webPartType": "Text",
            "properties": {
                "text": "<h2>Summary</h2><p>{summary}</p>"
            }
        },
        {
            "webPartType": "List",
            "properties": {
                "listId": "Concepts",
                "viewId": "DocumentConcepts",
                "filter": "RelatedDocuments eq '{doc_id}'"
            }
        }
    ],
    "metadata": {
        "source_file": "{filename}",
        "word_count": {word_count},
        "concept_count": {concept_count},
        "analysis_date": "{analysis_date}"
    }
}"""
        }
    
    def export(self, analysis_data: Dict[str, Any], documents: Dict[str, str]) -> ExportResult:
        """Export to SharePoint configuration format."""
        start_time = time.time()
        
        try:
            errors = self.validate_config()
            if errors:
                return self.create_export_result(False, self.config.output_path, [], 0, errors=errors)
            
            output_path = self.prepare_output_path()
            
            semantic_data = analysis_data.get('semantic_analysis', {})
            
            # Create SharePoint site configuration
            sharepoint_config = {
                "site": {
                    "title": "PDF Knowledge Base",
                    "description": "Centralized knowledge extracted from PDF documents",
                    "created": datetime.now().isoformat(),
                    "generator": "PDF Knowledge Extractor v2.2"
                },
                "lists": self._create_sharepoint_lists(analysis_data, documents),
                "pages": self._create_sharepoint_pages(analysis_data, documents),
                "document_libraries": self._create_document_libraries(),
                "site_columns": self._create_site_columns(),
                "content_types": self._create_content_types()
            }
            
            # Write SharePoint configuration
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(sharepoint_config, f, indent=2, ensure_ascii=False)
            
            execution_time = time.time() - start_time
            
            return self.create_export_result(
                success=True,
                output_path=output_path,
                exported_docs=list(documents.keys()),
                execution_time=execution_time,
                exported_concepts=len(semantic_data.get('concepts', [])),
                stats={
                    'sharepoint_lists': len(sharepoint_config['lists']),
                    'sharepoint_pages': len(sharepoint_config['pages'])
                }
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"SharePoint export failed: {e}")
            return self.create_export_result(
                False, self.config.output_path, [], execution_time, errors=[str(e)]
            )
    
    def _create_sharepoint_lists(self, analysis_data: Dict, documents: Dict) -> Dict[str, Any]:
        """Create SharePoint lists configuration."""
        semantic_data = analysis_data.get('semantic_analysis', {})
        
        # Get cluster choices
        cluster_choices = []
        if semantic_data and semantic_data.get('clusters'):
            cluster_choices = [cluster.get('cluster_label', f'Cluster {i+1}') 
                             for i, cluster in enumerate(semantic_data['clusters'])]
        
        # Documents list
        documents_list = {
            "title": "Documents",
            "template": "documentLibrary",
            "description": "PDF documents with extracted metadata",
            "columns": [
                {"name": "Title", "type": "Text", "required": True, "description": "Document title"},
                {"name": "SourceFile", "type": "Text", "description": "Original file path"},
                {"name": "WordCount", "type": "Number", "description": "Number of words in document"},
                {"name": "ConceptCount", "type": "Number", "description": "Number of extracted concepts"},
                {"name": "AnalysisDate", "type": "DateTime", "description": "Date of analysis"},
                {"name": "KeyConcepts", "type": "Note", "description": "Top concepts from document"},
                {"name": "DocumentCluster", "type": "Choice", "choices": cluster_choices or ["Uncategorized"]},
                {"name": "RelatedDocuments", "type": "Text", "description": "IDs of related documents"}
            ],
            "items": []
        }
        
        # Add document items
        for doc_id, doc_text in documents.items():
            doc_analysis = analysis_data.get('individual_analyses', {}).get(doc_id, {})
            
            # Get concepts for this document
            doc_concepts = []
            if semantic_data and semantic_data.get('concepts'):
                doc_concepts = [c for c in semantic_data['concepts'] 
                              if doc_id in c.get('document_ids', [])][:5]  # Top 5 concepts
            
            # Get cluster
            cluster_name = "Uncategorized"
            if semantic_data and semantic_data.get('clusters'):
                for cluster in semantic_data['clusters']:
                    if doc_id in cluster.get('document_ids', []):
                        cluster_name = cluster.get('cluster_label', 'Unnamed Cluster')
                        break
            
            # Get related documents
            related_docs = []
            if semantic_data and semantic_data.get('similarities'):
                for sim in semantic_data['similarities']:
                    if (sim.get('doc1_id') == doc_id or sim.get('doc2_id') == doc_id) and \
                       sim.get('similarity_score', 0) >= self.config.min_similarity_score:
                        other_doc = sim.get('doc2_id') if sim.get('doc1_id') == doc_id else sim.get('doc1_id')
                        related_docs.append(other_doc)
            
            documents_list["items"].append({
                "Title": doc_id,
                "SourceFile": doc_id,
                "WordCount": doc_analysis.get('word_count', 0),
                "ConceptCount": len(doc_concepts),
                "AnalysisDate": datetime.now().isoformat(),
                "KeyConcepts": "; ".join([c.get('text', '') for c in doc_concepts]),
                "DocumentCluster": cluster_name,
                "RelatedDocuments": "; ".join(related_docs[:5])  # Max 5 related docs
            })
        
        # Concepts list
        concepts_list = {
            "title": "Concepts",
            "template": "genericList",
            "description": "Extracted concepts from all documents",
            "columns": [
                {"name": "Title", "type": "Text", "required": True, "description": "Concept text"},
                {"name": "ConceptType", "type": "Choice", "choices": ["Entity", "Keyword", "Topic", "Phrase"]},
                {"name": "ImportanceScore", "type": "Number", "description": "Importance score (0-1)"},
                {"name": "Frequency", "type": "Number", "description": "Frequency across documents"},
                {"name": "Context", "type": "Note", "description": "Context sentence"},
                {"name": "DocumentCount", "type": "Number", "description": "Number of documents containing this concept"}
            ],
            "items": []
        }
        
        # Add concept items
        if semantic_data and semantic_data.get('concepts'):
            for concept in semantic_data['concepts']:
                concepts_list["items"].append({
                    "Title": concept.get('text', ''),
                    "ConceptType": concept.get('concept_type', 'Unknown'),
                    "ImportanceScore": concept.get('importance_score', 0),
                    "Frequency": concept.get('frequency', 0),
                    "Context": concept.get('context_sentences', [''])[0][:255] if concept.get('context_sentences') else '',
                    "DocumentCount": len(concept.get('document_ids', []))
                })
        
        return {
            "Documents": documents_list,
            "Concepts": concepts_list
        }
    
    def _create_sharepoint_pages(self, analysis_data: Dict, documents: Dict) -> Dict[str, Any]:
        """Create SharePoint pages configuration."""
        pages = {}
        
        # Create overview page
        pages["Overview"] = {
            "title": "Knowledge Base Overview",
            "layout": "Article",
            "content": [
                {
                    "webPartType": "Text",
                    "properties": {
                        "text": f"<h1>PDF Knowledge Base Overview</h1><p>This knowledge base contains analysis of {len(documents)} PDF documents, with {len(analysis_data.get('semantic_analysis', {}).get('concepts', []))} extracted concepts.</p>"
                    }
                },
                {
                    "webPartType": "List",
                    "properties": {
                        "listId": "Documents",
                        "viewId": "AllItems"
                    }
                }
            ]
        }
        
        # Create concept index page
        pages["ConceptIndex"] = {
            "title": "Concept Index",
            "layout": "Article", 
            "content": [
                {
                    "webPartType": "Text",
                    "properties": {
                        "text": "<h1>Concept Index</h1><p>Browse all extracted concepts by type and importance.</p>"
                    }
                },
                {
                    "webPartType": "List",
                    "properties": {
                        "listId": "Concepts",
                        "viewId": "GroupedByType"
                    }
                }
            ]
        }
        
        return pages
    
    def _create_document_libraries(self) -> Dict[str, Any]:
        """Create document libraries configuration."""
        return {
            "PDF_Archive": {
                "title": "PDF Archive",
                "description": "Original PDF files",
                "template": "documentLibrary",
                "versioning": True,
                "contentApproval": False
            }
        }
    
    def _create_site_columns(self) -> List[Dict[str, Any]]:
        """Create site columns configuration."""
        return [
            {
                "name": "ConceptImportance",
                "type": "Number",
                "description": "Concept importance score",
                "min": 0,
                "max": 1
            },
            {
                "name": "DocumentCluster",
                "type": "Choice",
                "description": "Document cluster assignment"
            },
            {
                "name": "AnalysisDate",
                "type": "DateTime",
                "description": "Date when analysis was performed"
            }
        ]
    
    def _create_content_types(self) -> List[Dict[str, Any]]:
        """Create content types configuration."""
        return [
            {
                "name": "AnalyzedDocument",
                "description": "Document that has been analyzed for concepts",
                "parent": "Document",
                "columns": ["ConceptImportance", "DocumentCluster", "AnalysisDate"]
            },
            {
                "name": "ExtractedConcept", 
                "description": "Concept extracted from document analysis",
                "parent": "Item",
                "columns": ["ConceptImportance", "AnalysisDate"]
            }
        ]