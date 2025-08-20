"""
Learning & Memory Export Formats
Support for Anki, Quizlet, and custom flashcard formats
"""

import logging
import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Any, Optional
from pathlib import Path
from datetime import datetime
import time
import csv
import random
import re

from .base import BaseExporter, TemplateExporter, ExportConfig, ExportResult

logger = logging.getLogger(__name__)


class AnkiExporter(TemplateExporter):
    """Export to Anki flashcard deck format (.apkg compatible)."""
    
    @property
    def supported_formats(self) -> List[str]:
        return ['anki']
    
    @property
    def file_extension(self) -> str:
        return '.txt'  # Anki import format
    
    @property
    def default_templates(self) -> Dict[str, str]:
        return {
            'concept_card': "{concept_text}\t{concept_definition}\t{document_context}",
            'relationship_card': "How are '{doc1}' and '{doc2}' related?\tThey share {similarity:.1%} similarity with common concepts: {shared_concepts}\t{relationship_context}",
            'summary_card': "Summarize the key points of '{document_title}'\t{document_summary}\t{document_metadata}",
            'cluster_card': "What documents belong to the '{cluster_label}' cluster?\t{cluster_documents}\t{cluster_topics}"
        }
    
    def export(self, analysis_data: Dict[str, Any], documents: Dict[str, str]) -> ExportResult:
        """Export to Anki-compatible text format."""
        start_time = time.time()
        
        try:
            errors = self.validate_config()
            if errors:
                return self.create_export_result(False, self.config.output_path, [], 0, errors=errors)
            
            output_path = self.prepare_output_path()
            
            cards = []
            exported_docs = []
            total_concepts = 0
            
            semantic_data = analysis_data.get('semantic_analysis', {})
            
            # Create concept cards
            if self.config.include_concepts and semantic_data.get('concepts'):
                concept_cards = self._create_concept_cards(semantic_data['concepts'], documents)
                cards.extend(concept_cards)
                total_concepts = len(semantic_data['concepts'])
            
            # Create document summary cards
            for doc_id, doc_text in documents.items():
                doc_analysis = analysis_data.get('individual_analyses', {}).get(doc_id, {})
                summary_card = self._create_summary_card(doc_id, doc_text, doc_analysis)
                cards.append(summary_card)
                exported_docs.append(doc_id)
            
            # Create relationship cards
            if self.config.include_relationships and semantic_data.get('similarities'):
                relationship_cards = self._create_relationship_cards(semantic_data['similarities'], documents)
                cards.extend(relationship_cards)
            
            # Create cluster cards
            if self.config.include_clusters and semantic_data.get('clusters'):
                cluster_cards = self._create_cluster_cards(semantic_data['clusters'])
                cards.extend(cluster_cards)
            
            # Write Anki import file
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write("#separator:Tab\n")
                f.write("#html:true\n")
                f.write("#tags:pdf-analysis knowledge-extraction\n\n")
                
                for card in cards:
                    f.write(card + "\n")
            
            execution_time = time.time() - start_time
            
            return self.create_export_result(
                success=True,
                output_path=output_path,
                exported_docs=exported_docs,
                execution_time=execution_time,
                exported_concepts=total_concepts,
                stats={'anki_cards': len(cards)}
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Anki export failed: {e}")
            return self.create_export_result(
                False, self.config.output_path, [], execution_time, errors=[str(e)]
            )
    
    def _create_concept_cards(self, concepts: List[Dict], documents: Dict[str, str]) -> List[str]:
        """Create flashcards for concepts."""
        cards = []
        
        # Filter and sort concepts
        filtered_concepts = self.filter_concepts(concepts)
        sorted_concepts = sorted(filtered_concepts, key=lambda x: x.get('importance_score', 0), reverse=True)
        
        for concept in sorted_concepts[:100]:  # Limit to top 100 concepts
            concept_text = concept.get('text', '')
            
            # Generate definition from context
            context_sentences = concept.get('context_sentences', [])
            definition = self._generate_concept_definition(concept_text, context_sentences)
            
            # Get document context
            doc_ids = concept.get('document_ids', [])
            doc_context = f"Found in {len(doc_ids)} document(s): {', '.join(doc_ids[:3])}"
            if len(doc_ids) > 3:
                doc_context += f" (+{len(doc_ids) - 3} more)"
            
            # Create card
            card = self.render_template('concept_card', {
                'concept_text': self._escape_anki(concept_text),
                'concept_definition': self._escape_anki(definition),
                'document_context': self._escape_anki(doc_context)
            })
            
            cards.append(card)
        
        return cards
    
    def _create_summary_card(self, doc_id: str, doc_text: str, doc_analysis: Dict) -> str:
        """Create summary flashcard for a document."""
        
        # Generate summary
        sentences = doc_text.split('.')[:3]
        summary = '. '.join(sentences).strip()
        if len(summary) > 300:
            summary = summary[:300] + "..."
        
        # Create metadata
        metadata = f"Word count: {doc_analysis.get('word_count', 0)}, " \
                  f"Analysis date: {datetime.now().strftime('%Y-%m-%d')}"
        
        return self.render_template('summary_card', {
            'document_title': self._escape_anki(doc_id),
            'document_summary': self._escape_anki(summary),
            'document_metadata': self._escape_anki(metadata)
        })
    
    def _create_relationship_cards(self, similarities: List[Dict], documents: Dict[str, str]) -> List[str]:
        """Create flashcards for document relationships."""
        cards = []
        
        # Filter relationships
        filtered_sims = self.filter_relationships(similarities)
        sorted_sims = sorted(filtered_sims, key=lambda x: x.get('similarity_score', 0), reverse=True)
        
        for sim in sorted_sims[:20]:  # Top 20 relationships
            doc1_id = sim.get('doc1_id', '')
            doc2_id = sim.get('doc2_id', '')
            similarity = sim.get('similarity_score', 0)
            shared_concepts = sim.get('shared_concepts', [])
            
            # Create context
            context = f"Both documents discuss similar topics with {similarity:.1%} content overlap."
            
            card = self.render_template('relationship_card', {
                'doc1': self._escape_anki(doc1_id),
                'doc2': self._escape_anki(doc2_id),
                'similarity': similarity,
                'shared_concepts': self._escape_anki(', '.join(shared_concepts[:5])),
                'relationship_context': self._escape_anki(context)
            })
            
            cards.append(card)
        
        return cards
    
    def _create_cluster_cards(self, clusters: List[Dict]) -> List[str]:
        """Create flashcards for document clusters."""
        cards = []
        
        for cluster in clusters:
            cluster_label = cluster.get('cluster_label', 'Unnamed Cluster')
            doc_ids = cluster.get('document_ids', [])
            main_topics = cluster.get('main_topics', [])
            
            # Format documents list
            documents_text = ', '.join(doc_ids)
            
            # Format topics
            topics_text = f"Main topics: {', '.join(main_topics[:5])}"
            
            card = self.render_template('cluster_card', {
                'cluster_label': self._escape_anki(cluster_label),
                'cluster_documents': self._escape_anki(documents_text),
                'cluster_topics': self._escape_anki(topics_text)
            })
            
            cards.append(card)
        
        return cards
    
    def _generate_concept_definition(self, concept_text: str, context_sentences: List[str]) -> str:
        """Generate definition for a concept from context."""
        if not context_sentences:
            return f"A concept identified in the document analysis: {concept_text}"
        
        # Use the first context sentence as a base definition
        definition = context_sentences[0]
        
        # Clean and truncate
        definition = definition.strip()
        if len(definition) > 200:
            definition = definition[:200] + "..."
        
        return definition
    
    def _escape_anki(self, text: str) -> str:
        """Escape text for Anki format."""
        if not text:
            return ""
        
        # Replace tabs and newlines that might break the format
        text = text.replace('\t', '    ')  # Replace tabs with spaces
        text = text.replace('\n', '<br>')  # Replace newlines with HTML breaks
        text = text.replace('\r', '')      # Remove carriage returns
        
        return text


class QuizletExporter(BaseExporter):
    """Export to Quizlet study set format."""
    
    @property
    def supported_formats(self) -> List[str]:
        return ['quizlet']
    
    @property
    def file_extension(self) -> str:
        return '.csv'
    
    def export(self, analysis_data: Dict[str, Any], documents: Dict[str, str]) -> ExportResult:
        """Export to Quizlet CSV format."""
        start_time = time.time()
        
        try:
            errors = self.validate_config()
            if errors:
                return self.create_export_result(False, self.config.output_path, [], 0, errors=errors)
            
            output_path = self.prepare_output_path()
            
            # Quizlet uses simple CSV: Term, Definition
            cards_data = []
            exported_docs = []
            total_concepts = 0
            
            semantic_data = analysis_data.get('semantic_analysis', {})
            
            # Create concept cards
            if self.config.include_concepts and semantic_data.get('concepts'):
                concept_cards = self._create_concept_cards_quizlet(semantic_data['concepts'])
                cards_data.extend(concept_cards)
                total_concepts = len(semantic_data['concepts'])
            
            # Create document summary cards
            for doc_id, doc_text in documents.items():
                doc_analysis = analysis_data.get('individual_analyses', {}).get(doc_id, {})
                summary_cards = self._create_summary_cards_quizlet(doc_id, doc_text, doc_analysis)
                cards_data.extend(summary_cards)
                exported_docs.append(doc_id)
            
            # Create relationship cards
            if self.config.include_relationships and semantic_data.get('similarities'):
                relationship_cards = self._create_relationship_cards_quizlet(semantic_data['similarities'])
                cards_data.extend(relationship_cards)
            
            # Write Quizlet CSV
            with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Term', 'Definition'])  # Quizlet headers
                writer.writerows(cards_data)
            
            execution_time = time.time() - start_time
            
            return self.create_export_result(
                success=True,
                output_path=output_path,
                exported_docs=exported_docs,
                execution_time=execution_time,
                exported_concepts=total_concepts,
                stats={'quizlet_cards': len(cards_data)}
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Quizlet export failed: {e}")
            return self.create_export_result(
                False, self.config.output_path, [], execution_time, errors=[str(e)]
            )
    
    def _create_concept_cards_quizlet(self, concepts: List[Dict]) -> List[List[str]]:
        """Create Quizlet cards for concepts."""
        cards = []
        
        # Filter and sort concepts
        filtered_concepts = self.filter_concepts(concepts)
        sorted_concepts = sorted(filtered_concepts, key=lambda x: x.get('importance_score', 0), reverse=True)
        
        for concept in sorted_concepts[:50]:  # Top 50 concepts for Quizlet
            concept_text = concept.get('text', '')
            
            # Generate definition
            context_sentences = concept.get('context_sentences', [])
            if context_sentences:
                definition = context_sentences[0][:200]
                if len(context_sentences[0]) > 200:
                    definition += "..."
            else:
                definition = f"Key concept with importance score: {concept.get('importance_score', 0):.2f}"
            
            cards.append([concept_text, definition])
        
        return cards
    
    def _create_summary_cards_quizlet(self, doc_id: str, doc_text: str, doc_analysis: Dict) -> List[List[str]]:
        """Create summary cards for documents."""
        cards = []
        
        # Main summary card
        sentences = doc_text.split('.')[:2]
        summary = '. '.join(sentences).strip()
        if len(summary) > 250:
            summary = summary[:250] + "..."
        
        cards.append([f"Summary of {doc_id}", summary])
        
        # Word count card
        word_count = doc_analysis.get('word_count', 0)
        cards.append([f"Word count of {doc_id}", str(word_count)])
        
        # Topics card
        topics = doc_analysis.get('topics', [])
        if topics:
            top_topics = ', '.join([t.get('topic', '') for t in topics[:3]])
            cards.append([f"Main topics in {doc_id}", top_topics])
        
        return cards
    
    def _create_relationship_cards_quizlet(self, similarities: List[Dict]) -> List[List[str]]:
        """Create relationship cards."""
        cards = []
        
        # Filter relationships
        filtered_sims = self.filter_relationships(similarities)
        sorted_sims = sorted(filtered_sims, key=lambda x: x.get('similarity_score', 0), reverse=True)
        
        for sim in sorted_sims[:15]:  # Top 15 relationships
            doc1_id = sim.get('doc1_id', '')
            doc2_id = sim.get('doc2_id', '')
            similarity = sim.get('similarity_score', 0)
            
            term = f"Relationship: {doc1_id} ↔ {doc2_id}"
            definition = f"These documents have {similarity:.1%} similarity in content and themes."
            
            cards.append([term, definition])
        
        return cards


class FlashcardExporter(BaseExporter):
    """Export to custom flashcard formats (JSON, XML)."""
    
    @property
    def supported_formats(self) -> List[str]:
        return ['flashcards-json', 'flashcards-xml']
    
    @property
    def file_extension(self) -> str:
        format_type = self.config.format_type
        if 'json' in format_type:
            return '.json'
        elif 'xml' in format_type:
            return '.xml'
        return '.json'
    
    def export(self, analysis_data: Dict[str, Any], documents: Dict[str, str]) -> ExportResult:
        """Export to custom flashcard format."""
        start_time = time.time()
        
        try:
            errors = self.validate_config()
            if errors:
                return self.create_export_result(False, self.config.output_path, [], 0, errors=errors)
            
            output_path = self.prepare_output_path()
            
            # Create flashcard data structure
            flashcard_data = self._create_flashcard_data(analysis_data, documents)
            
            if 'json' in self.config.format_type:
                self._export_json_flashcards(output_path, flashcard_data)
            elif 'xml' in self.config.format_type:
                self._export_xml_flashcards(output_path, flashcard_data)
            
            execution_time = time.time() - start_time
            
            return self.create_export_result(
                success=True,
                output_path=output_path,
                exported_docs=list(documents.keys()),
                execution_time=execution_time,
                exported_concepts=len(flashcard_data.get('concept_cards', [])),
                stats={'total_cards': len(flashcard_data.get('all_cards', []))}
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Flashcard export failed: {e}")
            return self.create_export_result(
                False, self.config.output_path, [], execution_time, errors=[str(e)]
            )
    
    def _create_flashcard_data(self, analysis_data: Dict[str, Any], documents: Dict[str, str]) -> Dict[str, Any]:
        """Create comprehensive flashcard data structure."""
        
        flashcard_data = {
            'metadata': {
                'title': 'PDF Knowledge Flashcards',
                'created': datetime.now().isoformat(),
                'source': 'PDF Knowledge Extractor v2.2',
                'total_documents': len(documents),
                'format': self.config.format_type
            },
            'concept_cards': [],
            'summary_cards': [],
            'relationship_cards': [],
            'cluster_cards': [],
            'quiz_cards': [],
            'all_cards': []
        }
        
        semantic_data = analysis_data.get('semantic_analysis', {})
        
        # Create concept cards
        if self.config.include_concepts and semantic_data.get('concepts'):
            concept_cards = self._create_detailed_concept_cards(semantic_data['concepts'])
            flashcard_data['concept_cards'] = concept_cards
            flashcard_data['all_cards'].extend(concept_cards)
        
        # Create summary cards
        for doc_id, doc_text in documents.items():
            doc_analysis = analysis_data.get('individual_analyses', {}).get(doc_id, {})
            summary_cards = self._create_detailed_summary_cards(doc_id, doc_text, doc_analysis)
            flashcard_data['summary_cards'].extend(summary_cards)
            flashcard_data['all_cards'].extend(summary_cards)
        
        # Create relationship cards
        if self.config.include_relationships and semantic_data.get('similarities'):
            relationship_cards = self._create_detailed_relationship_cards(semantic_data['similarities'])
            flashcard_data['relationship_cards'] = relationship_cards
            flashcard_data['all_cards'].extend(relationship_cards)
        
        # Create cluster cards
        if self.config.include_clusters and semantic_data.get('clusters'):
            cluster_cards = self._create_detailed_cluster_cards(semantic_data['clusters'])
            flashcard_data['cluster_cards'] = cluster_cards
            flashcard_data['all_cards'].extend(cluster_cards)
        
        # Create quiz cards (multiple choice questions)
        quiz_cards = self._create_quiz_cards(analysis_data, documents)
        flashcard_data['quiz_cards'] = quiz_cards
        flashcard_data['all_cards'].extend(quiz_cards)
        
        return flashcard_data
    
    def _create_detailed_concept_cards(self, concepts: List[Dict]) -> List[Dict]:
        """Create detailed concept flashcards."""
        cards = []
        
        filtered_concepts = self.filter_concepts(concepts)
        sorted_concepts = sorted(filtered_concepts, key=lambda x: x.get('importance_score', 0), reverse=True)
        
        for concept in sorted_concepts[:75]:  # Top 75 concepts
            card = {
                'id': f"concept_{hash(concept.get('text', ''))}",
                'type': 'concept',
                'front': concept.get('text', ''),
                'back': self._generate_concept_definition(concept),
                'metadata': {
                    'importance_score': concept.get('importance_score', 0),
                    'frequency': concept.get('frequency', 0),
                    'concept_type': concept.get('concept_type', 'unknown'),
                    'document_count': len(concept.get('document_ids', [])),
                    'documents': concept.get('document_ids', [])
                },
                'tags': ['concept', concept.get('concept_type', 'unknown')],
                'difficulty': self._assess_concept_difficulty(concept),
                'context': concept.get('context_sentences', [])[:2]  # First 2 context sentences
            }
            cards.append(card)
        
        return cards
    
    def _create_detailed_summary_cards(self, doc_id: str, doc_text: str, doc_analysis: Dict) -> List[Dict]:
        """Create detailed summary flashcards."""
        cards = []
        
        # Main summary card
        sentences = doc_text.split('.')[:3]
        summary = '. '.join(sentences).strip()
        if len(summary) > 400:
            summary = summary[:400] + "..."
        
        summary_card = {
            'id': f"summary_{hash(doc_id)}",
            'type': 'summary',
            'front': f"Summarize: {doc_id}",
            'back': summary,
            'metadata': {
                'document': doc_id,
                'word_count': doc_analysis.get('word_count', 0),
                'character_count': doc_analysis.get('character_count', 0),
                'analysis_date': datetime.now().isoformat()
            },
            'tags': ['summary', 'document'],
            'difficulty': 'medium'
        }
        cards.append(summary_card)
        
        # Topics card
        topics = doc_analysis.get('topics', [])
        if topics:
            topics_card = {
                'id': f"topics_{hash(doc_id)}",
                'type': 'topics',
                'front': f"What are the main topics in {doc_id}?",
                'back': ', '.join([t.get('topic', '') for t in topics[:5]]),
                'metadata': {
                    'document': doc_id,
                    'topic_count': len(topics)
                },
                'tags': ['topics', 'document'],
                'difficulty': 'easy'
            }
            cards.append(topics_card)
        
        return cards
    
    def _create_detailed_relationship_cards(self, similarities: List[Dict]) -> List[Dict]:
        """Create detailed relationship flashcards."""
        cards = []
        
        filtered_sims = self.filter_relationships(similarities)
        sorted_sims = sorted(filtered_sims, key=lambda x: x.get('similarity_score', 0), reverse=True)
        
        for i, sim in enumerate(sorted_sims[:25]):  # Top 25 relationships
            doc1_id = sim.get('doc1_id', '')
            doc2_id = sim.get('doc2_id', '')
            similarity = sim.get('similarity_score', 0)
            shared_concepts = sim.get('shared_concepts', [])
            
            card = {
                'id': f"relationship_{i}",
                'type': 'relationship',
                'front': f"How are '{doc1_id}' and '{doc2_id}' related?",
                'back': f"They share {similarity:.1%} similarity with common concepts: {', '.join(shared_concepts[:5])}",
                'metadata': {
                    'doc1': doc1_id,
                    'doc2': doc2_id,
                    'similarity_score': similarity,
                    'shared_concepts': shared_concepts
                },
                'tags': ['relationship', 'similarity'],
                'difficulty': self._assess_relationship_difficulty(similarity)
            }
            cards.append(card)
        
        return cards
    
    def _create_detailed_cluster_cards(self, clusters: List[Dict]) -> List[Dict]:
        """Create detailed cluster flashcards."""
        cards = []
        
        for i, cluster in enumerate(clusters):
            cluster_label = cluster.get('cluster_label', f'Cluster {i+1}')
            doc_ids = cluster.get('document_ids', [])
            main_topics = cluster.get('main_topics', [])
            
            card = {
                'id': f"cluster_{cluster.get('cluster_id', i)}",
                'type': 'cluster',
                'front': f"What documents belong to the '{cluster_label}' cluster?",
                'back': f"Documents: {', '.join(doc_ids[:5])}{'...' if len(doc_ids) > 5 else ''}. Main topics: {', '.join(main_topics[:3])}",
                'metadata': {
                    'cluster_id': cluster.get('cluster_id'),
                    'cluster_label': cluster_label,
                    'document_count': len(doc_ids),
                    'coherence_score': cluster.get('coherence_score', 0),
                    'documents': doc_ids,
                    'topics': main_topics
                },
                'tags': ['cluster', 'grouping'],
                'difficulty': 'medium'
            }
            cards.append(card)
        
        return cards
    
    def _create_quiz_cards(self, analysis_data: Dict, documents: Dict) -> List[Dict]:
        """Create multiple choice quiz cards."""
        cards = []
        
        semantic_data = analysis_data.get('semantic_analysis', {})
        
        # Quiz: Which document has the most concepts?
        if semantic_data.get('concepts'):
            doc_concept_counts = {}
            for concept in semantic_data['concepts']:
                for doc_id in concept.get('document_ids', []):
                    doc_concept_counts[doc_id] = doc_concept_counts.get(doc_id, 0) + 1
            
            if doc_concept_counts:
                max_doc = max(doc_concept_counts.items(), key=lambda x: x[1])
                all_docs = list(documents.keys())
                wrong_options = random.sample([d for d in all_docs if d != max_doc[0]], min(3, len(all_docs) - 1))
                
                card = {
                    'id': 'quiz_most_concepts',
                    'type': 'multiple_choice',
                    'front': 'Which document contains the most extracted concepts?',
                    'back': max_doc[0],
                    'options': [max_doc[0]] + wrong_options,
                    'metadata': {
                        'correct_answer': max_doc[0],
                        'concept_count': max_doc[1],
                        'explanation': f"This document has {max_doc[1]} extracted concepts."
                    },
                    'tags': ['quiz', 'statistics'],
                    'difficulty': 'medium'
                }
                # Shuffle options
                random.shuffle(card['options'])
                cards.append(card)
        
        return cards
    
    def _export_json_flashcards(self, output_path: Path, flashcard_data: Dict):
        """Export flashcards to JSON format."""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(flashcard_data, f, indent=2, ensure_ascii=False)
    
    def _export_xml_flashcards(self, output_path: Path, flashcard_data: Dict):
        """Export flashcards to XML format."""
        root = ET.Element('flashcard_deck')
        
        # Add metadata
        metadata_elem = ET.SubElement(root, 'metadata')
        for key, value in flashcard_data['metadata'].items():
            elem = ET.SubElement(metadata_elem, key)
            elem.text = str(value)
        
        # Add cards
        for card in flashcard_data['all_cards']:
            card_elem = ET.SubElement(root, 'card')
            card_elem.set('id', card['id'])
            card_elem.set('type', card['type'])
            
            front_elem = ET.SubElement(card_elem, 'front')
            front_elem.text = card['front']
            
            back_elem = ET.SubElement(card_elem, 'back')
            back_elem.text = card['back']
            
            if 'options' in card:
                options_elem = ET.SubElement(card_elem, 'options')
                for option in card['options']:
                    option_elem = ET.SubElement(options_elem, 'option')
                    option_elem.text = option
            
            # Add metadata
            if card.get('metadata'):
                card_metadata_elem = ET.SubElement(card_elem, 'metadata')
                for key, value in card['metadata'].items():
                    elem = ET.SubElement(card_metadata_elem, key)
                    elem.text = str(value)
            
            # Add tags
            if card.get('tags'):
                tags_elem = ET.SubElement(card_elem, 'tags')
                for tag in card['tags']:
                    tag_elem = ET.SubElement(tags_elem, 'tag')
                    tag_elem.text = tag
        
        # Write XML file
        tree = ET.ElementTree(root)
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
    
    def _generate_concept_definition(self, concept: Dict) -> str:
        """Generate definition for a concept."""
        context_sentences = concept.get('context_sentences', [])
        if context_sentences:
            definition = context_sentences[0]
            if len(definition) > 200:
                definition = definition[:200] + "..."
        else:
            definition = f"A {concept.get('concept_type', 'concept')} with importance score {concept.get('importance_score', 0):.2f}"
        
        # Add frequency information
        if concept.get('frequency', 0) > 1:
            definition += f" (appears {concept.get('frequency')} times)"
        
        return definition
    
    def _assess_concept_difficulty(self, concept: Dict) -> str:
        """Assess the difficulty level of a concept."""
        importance = concept.get('importance_score', 0)
        frequency = concept.get('frequency', 0)
        
        if importance > 0.8 and frequency > 5:
            return 'easy'
        elif importance > 0.5 and frequency > 2:
            return 'medium'
        else:
            return 'hard'
    
    def _assess_relationship_difficulty(self, similarity_score: float) -> str:
        """Assess the difficulty level of a relationship."""
        if similarity_score > 0.8:
            return 'easy'
        elif similarity_score > 0.6:
            return 'medium'
        else:
            return 'hard'