"""
Knowledge analysis and insights generation with semantic analysis integration.
"""

import logging
import json
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from dataclasses import asdict

from .semantic_analyzer import SemanticAnalyzer, ExtractedConcept, DocumentCluster

logger = logging.getLogger(__name__)


class KnowledgeAnalyzer:
    """Analyze extracted text to generate insights and knowledge with semantic capabilities."""
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize the knowledge analyzer with optional configuration."""
        self.config = config or {}
        self.enable_semantic_analysis = self.config.get('enable_semantic_analysis', False)
        
        # Initialize semantic analyzer if enabled
        if self.enable_semantic_analysis:
            self.semantic_analyzer = SemanticAnalyzer(self.config.get('semantic', {}))
        else:
            self.semantic_analyzer = None
        
    def analyze_content(self, text: str) -> Dict:
        """Perform comprehensive analysis of text content."""
        analysis = {
            "word_count": len(text.split()),
            "character_count": len(text),
            "topics": self.extract_topics(text),
            "entities": self.extract_entities(text),
            "sentiment": self.analyze_sentiment(text)
        }
        return analysis
    
    def analyze_document_collection(self, documents: Dict[str, str], 
                                  metadata: Optional[Dict[str, Dict]] = None,
                                  enable_semantic: bool = True) -> Dict[str, Any]:
        """
        Perform comprehensive analysis on a collection of documents.
        
        Args:
            documents: Dict mapping document_id -> document_text
            metadata: Optional metadata for each document
            enable_semantic: Whether to run semantic analysis
            
        Returns:
            Dict containing comprehensive analysis results
        """
        logger.info(f"Analyzing collection of {len(documents)} documents")
        
        results = {
            'total_documents': len(documents),
            'individual_analyses': {},
            'collection_stats': self._calculate_collection_stats(documents),
            'semantic_analysis': None
        }
        
        # Analyze each document individually
        for doc_id, text in documents.items():
            individual_analysis = self.analyze_content(text)
            results['individual_analyses'][doc_id] = individual_analysis
        
        # Perform semantic analysis if enabled and analyzer is available
        if enable_semantic and self.semantic_analyzer:
            logger.info("Running semantic analysis on document collection...")
            semantic_results = self.semantic_analyzer.analyze_document_collection(
                documents, metadata
            )
            results['semantic_analysis'] = semantic_results
        
        return results
    
    def find_similar_documents(self, target_doc_id: str, documents: Dict[str, str],
                             similarity_threshold: float = 0.7) -> List[Tuple[str, float]]:
        """Find documents similar to a target document."""
        if not self.semantic_analyzer:
            logger.warning("Semantic analyzer not initialized, cannot find similar documents")
            return []
        
        # Ensure semantic analysis has been performed
        if not hasattr(self.semantic_analyzer, 'similarities') or not self.semantic_analyzer.similarities:
            logger.info("Running semantic analysis for similarity search...")
            self.semantic_analyzer.analyze_document_collection(documents)
        
        return self.semantic_analyzer.find_similar_documents(target_doc_id)
    
    def get_document_concepts(self, doc_id: str) -> List[ExtractedConcept]:
        """Get concepts extracted for a specific document."""
        if not self.semantic_analyzer:
            logger.warning("Semantic analyzer not initialized")
            return []
        
        return self.semantic_analyzer.get_document_concepts(doc_id)
    
    def get_document_clusters(self) -> List[DocumentCluster]:
        """Get document clusters from semantic analysis."""
        if not self.semantic_analyzer:
            logger.warning("Semantic analyzer not initialized")
            return []
        
        return self.semantic_analyzer.clusters
    
    def generate_cross_references(self, doc_id: str, documents: Dict[str, str]) -> Dict[str, Any]:
        """Generate cross-references for a document based on semantic analysis."""
        if not self.semantic_analyzer:
            return {'similar_documents': [], 'shared_concepts': [], 'clusters': []}
        
        # Get similar documents
        similar_docs = self.find_similar_documents(doc_id, documents)
        
        # Get concepts for this document
        doc_concepts = self.get_document_concepts(doc_id)
        
        # Find which cluster this document belongs to
        doc_clusters = []
        for cluster in self.get_document_clusters():
            if doc_id in cluster.document_ids:
                doc_clusters.append({
                    'cluster_id': cluster.cluster_id,
                    'cluster_label': cluster.cluster_label,
                    'main_topics': cluster.main_topics,
                    'other_documents': [did for did in cluster.document_ids if did != doc_id]
                })
        
        return {
            'similar_documents': [{'doc_id': doc_id, 'similarity': score} 
                                for doc_id, score in similar_docs],
            'document_concepts': [asdict(concept) for concept in doc_concepts],
            'clusters': doc_clusters
        }
    
    def export_knowledge_graph(self, output_path: Path, format_type: str = 'graphml'):
        """Export the knowledge graph in various formats."""
        if not self.semantic_analyzer:
            logger.warning("Semantic analyzer not initialized, cannot export knowledge graph")
            return
        
        self.semantic_analyzer.export_knowledge_graph(output_path, format_type)
        
    def extract_topics(self, text: str, num_topics: int = 5) -> List[Dict]:
        """Extract main topics from the text using semantic analysis if available."""
        if self.semantic_analyzer:
            # Use semantic analyzer to extract concepts as topics
            concepts = self.semantic_analyzer._extract_concepts()
            topic_concepts = [concept for concept in concepts 
                            if concept.concept_type in ['keyword', 'topic']][:num_topics]
            
            return [{'topic': concept.text, 'importance': concept.importance_score} 
                   for concept in topic_concepts]
        else:
            # Basic topic extraction (placeholder)
            words = text.lower().split()
            word_freq = {}
            for word in words:
                if len(word) > 3:  # Skip short words
                    word_freq[word] = word_freq.get(word, 0) + 1
            
            # Get top words as basic topics
            top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:num_topics]
            return [{'topic': word, 'frequency': freq} for word, freq in top_words]
        
    def extract_entities(self, text: str) -> List[Dict]:
        """Extract named entities from the text."""
        if self.semantic_analyzer:
            # Use semantic analyzer for entity extraction
            entities = self.semantic_analyzer._extract_entities(text)
            return [{'entity': entity[0], 'type': entity[1], 'importance': entity[2]} 
                   for entity in entities]
        else:
            # Basic entity extraction (placeholder)
            logger.warning("Advanced entity extraction requires semantic analysis to be enabled")
            return []
        
    def analyze_sentiment(self, text: str) -> Dict:
        """Analyze sentiment of the text."""
        # Basic sentiment analysis (placeholder)
        positive_words = ['good', 'great', 'excellent', 'positive', 'beneficial', 'effective']
        negative_words = ['bad', 'poor', 'negative', 'harmful', 'ineffective', 'problematic']
        
        words = text.lower().split()
        positive_count = sum(1 for word in words if word in positive_words)
        negative_count = sum(1 for word in words if word in negative_words)
        
        total_sentiment_words = positive_count + negative_count
        if total_sentiment_words == 0:
            sentiment = 'neutral'
            score = 0.0
        elif positive_count > negative_count:
            sentiment = 'positive'
            score = positive_count / total_sentiment_words
        elif negative_count > positive_count:
            sentiment = 'negative'
            score = negative_count / total_sentiment_words
        else:
            sentiment = 'neutral'
            score = 0.0
        
        return {
            'sentiment': sentiment,
            'score': score,
            'positive_indicators': positive_count,
            'negative_indicators': negative_count
        }
        
    def find_relationships(self, entities: List[Dict]) -> List[Tuple]:
        """Find relationships between extracted entities."""
        relationships = []
        
        # Simple co-occurrence based relationships
        for i, entity1 in enumerate(entities):
            for j, entity2 in enumerate(entities[i+1:], i+1):
                # Basic relationship scoring based on entity types and importance
                if entity1.get('type') != entity2.get('type'):
                    relationship_strength = (entity1.get('importance', 0) + 
                                           entity2.get('importance', 0)) / 2
                    if relationship_strength > 0.5:
                        relationships.append((
                            entity1.get('entity'),
                            entity2.get('entity'),
                            'related_to',
                            relationship_strength
                        ))
        
        return relationships
        
    def generate_insights(self, analysis: Dict) -> List[str]:
        """Generate human-readable insights from analysis results."""
        insights = []
        
        # Basic insights
        if analysis.get("word_count", 0) > 10000:
            insights.append("This is a lengthy document that may require chunked processing.")
            
        if analysis.get("topics"):
            insights.append(f"Document covers {len(analysis['topics'])} main topics.")
        
        # Sentiment insights
        sentiment_data = analysis.get("sentiment", {})
        if sentiment_data.get("sentiment") == "positive":
            insights.append(f"Document has a positive tone (score: {sentiment_data.get('score', 0):.2f}).")
        elif sentiment_data.get("sentiment") == "negative":
            insights.append(f"Document has a negative tone (score: {sentiment_data.get('score', 0):.2f}).")
        
        # Entity insights
        entities = analysis.get("entities", [])
        if entities:
            entity_types = set(entity.get('type') for entity in entities)
            insights.append(f"Document mentions {len(entities)} entities of {len(entity_types)} types.")
        
        return insights
    
    def _calculate_collection_stats(self, documents: Dict[str, str]) -> Dict[str, Any]:
        """Calculate statistics for the document collection."""
        total_words = sum(len(text.split()) for text in documents.values())
        total_chars = sum(len(text) for text in documents.values())
        
        word_counts = [len(text.split()) for text in documents.values()]
        char_counts = [len(text) for text in documents.values()]
        
        return {
            'total_documents': len(documents),
            'total_words': total_words,
            'total_characters': total_chars,
            'avg_words_per_doc': total_words / len(documents) if documents else 0,
            'avg_chars_per_doc': total_chars / len(documents) if documents else 0,
            'min_words': min(word_counts) if word_counts else 0,
            'max_words': max(word_counts) if word_counts else 0,
            'min_chars': min(char_counts) if char_counts else 0,
            'max_chars': max(char_counts) if char_counts else 0
        }