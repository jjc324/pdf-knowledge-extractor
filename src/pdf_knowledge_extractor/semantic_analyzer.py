"""
Semantic Analysis Module for PDF Knowledge Extractor v2.1

This module provides advanced semantic analysis capabilities including:
- Document similarity analysis using TF-IDF and cosine similarity
- Concept and entity extraction
- Topic clustering and theme detection
- Cross-document relationship mapping
- Knowledge graph generation
"""

import logging
import json
import pickle
from typing import Dict, List, Optional, Tuple, Set, Any
from pathlib import Path
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict
import numpy as np

# Core ML and NLP libraries
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans, AgglomerativeClustering
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.metrics import silhouette_score
import networkx as nx

# Text processing
import re
import string
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.corpus import stopwords
from nltk.stem import WordNetLemmatizer
from nltk.tag import pos_tag
from nltk.chunk import ne_chunk
from nltk.tree import Tree

logger = logging.getLogger(__name__)


@dataclass
class DocumentSimilarity:
    """Represents similarity between two documents."""
    doc1_id: str
    doc2_id: str
    similarity_score: float
    similarity_type: str  # 'cosine', 'jaccard', etc.
    shared_concepts: List[str]


@dataclass
class ExtractedConcept:
    """Represents an extracted concept or entity."""
    text: str
    concept_type: str  # 'entity', 'keyword', 'topic', 'phrase'
    frequency: int
    importance_score: float
    document_ids: List[str]
    context_sentences: List[str]


@dataclass
class DocumentCluster:
    """Represents a cluster of related documents."""
    cluster_id: str
    cluster_label: str
    document_ids: List[str]
    centroid_features: Dict[str, float]
    coherence_score: float
    main_topics: List[str]


@dataclass
class KnowledgeGraphNode:
    """Represents a node in the knowledge graph."""
    node_id: str
    node_type: str  # 'document', 'concept', 'entity', 'topic'
    label: str
    properties: Dict[str, Any]


@dataclass
class KnowledgeGraphEdge:
    """Represents an edge in the knowledge graph."""
    source_id: str
    target_id: str
    edge_type: str  # 'similarity', 'contains', 'related_to', 'cites'
    weight: float
    properties: Dict[str, Any]


class SemanticAnalyzer:
    """Advanced semantic analysis for document collections."""
    
    def __init__(self, config: Optional[Dict] = None):
        """Initialize the semantic analyzer."""
        self.config = config or {}
        self.similarity_threshold = self.config.get('similarity_threshold', 0.7)
        self.max_concepts = self.config.get('max_concepts', 100)
        self.min_concept_frequency = self.config.get('min_concept_frequency', 2)
        
        # Initialize components
        self.tfidf_vectorizer = None
        self.document_vectors = None
        self.document_texts = {}
        self.document_metadata = {}
        self.lemmatizer = WordNetLemmatizer()
        self.stop_words = set(stopwords.words('english'))
        
        # Analysis results
        self.similarities = []
        self.concepts = []
        self.clusters = []
        self.knowledge_graph = nx.Graph()
        
        # Caching and performance optimization
        self.cache_dir = Path(self.config.get('cache_dir', '.semantic_cache'))
        self.cache_dir.mkdir(exist_ok=True)
        self.enable_caching = self.config.get('enable_caching', True)
        self.use_sparse_matrices = self.config.get('use_sparse_matrices', True)
        self.parallel_processing = self.config.get('parallel_processing', True)
        self.incremental_processing = self.config.get('incremental_processing', True)
        
        # Memory optimization settings
        self.max_features = self.config.get('max_features', 5000)
        self.batch_size = self.config.get('batch_size', 100)
        
        # Cache for reused computations
        self._similarity_cache = {}
        self._concept_cache = {}
        self._cluster_cache = {}
        
    def analyze_document_collection(self, documents: Dict[str, str], 
                                  metadata: Optional[Dict[str, Dict]] = None) -> Dict[str, Any]:
        """
        Perform comprehensive semantic analysis on a collection of documents.
        
        Args:
            documents: Dict mapping document_id -> document_text
            metadata: Optional metadata for each document
            
        Returns:
            Dict containing all analysis results
        """
        logger.info(f"Starting semantic analysis of {len(documents)} documents")
        
        self.document_texts = documents
        self.document_metadata = metadata or {}
        
        # 1. Document similarity analysis
        logger.info("Computing document similarities...")
        self.similarities = self._compute_document_similarities()
        
        # 2. Concept extraction
        logger.info("Extracting concepts and entities...")
        self.concepts = self._extract_concepts()
        
        # 3. Topic clustering
        logger.info("Performing topic clustering...")
        self.clusters = self._perform_clustering()
        
        # 4. Knowledge graph generation
        logger.info("Building knowledge graph...")
        self._build_knowledge_graph()
        
        # 5. Generate analysis report
        analysis_results = {
            'total_documents': len(documents),
            'similarities': [asdict(sim) for sim in self.similarities],
            'concepts': [asdict(concept) for concept in self.concepts],
            'clusters': [asdict(cluster) for cluster in self.clusters],
            'graph_stats': {
                'nodes': self.knowledge_graph.number_of_nodes(),
                'edges': self.knowledge_graph.number_of_edges(),
                'density': nx.density(self.knowledge_graph),
                'connected_components': nx.number_connected_components(self.knowledge_graph)
            }
        }
        
        # Cache results if enabled
        if self.enable_caching:
            cache_file = self.cache_dir / f"analysis_cache_{len(documents)}docs.pkl"
            try:
                self.save_analysis_cache(cache_file)
                logger.debug(f"Analysis results cached to {cache_file}")
            except Exception as e:
                logger.warning(f"Failed to save cache: {e}")
        
        logger.info("Semantic analysis completed successfully")
        return analysis_results
    
    def analyze_document_collection_incremental(self, documents: Dict[str, str], 
                                              metadata: Optional[Dict[str, Dict]] = None,
                                              existing_results: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Perform incremental semantic analysis, reusing existing results where possible.
        
        Args:
            documents: Dict mapping document_id -> document_text
            metadata: Optional metadata for each document
            existing_results: Previous analysis results to build upon
            
        Returns:
            Dict containing updated analysis results
        """
        logger.info(f"Starting incremental semantic analysis of {len(documents)} documents")
        
        # Load existing results if available
        if existing_results is None and self.enable_caching:
            cache_file = self.cache_dir / f"analysis_cache_{len(documents)}docs.pkl"
            if cache_file.exists():
                try:
                    logger.info("Loading cached analysis results...")
                    if self.load_analysis_cache(cache_file):
                        logger.info("Successfully loaded cached results")
                        return self._build_analysis_results(documents)
                except Exception as e:
                    logger.warning(f"Failed to load cache: {e}")
        
        # Determine which documents are new
        if existing_results:
            existing_doc_ids = set(existing_results.get('document_ids', []))
            new_doc_ids = set(documents.keys()) - existing_doc_ids
            
            if not new_doc_ids:
                logger.info("No new documents to analyze")
                return existing_results
            
            logger.info(f"Found {len(new_doc_ids)} new documents to analyze incrementally")
            
            # For incremental processing, we need to recompute similarities
            # but can reuse some concept extractions
            return self.analyze_document_collection(documents, metadata)
        else:
            # No existing results, perform full analysis
            return self.analyze_document_collection(documents, metadata)
    
    def _build_analysis_results(self, documents: Dict[str, str]) -> Dict[str, Any]:
        """Build analysis results from cached data."""
        return {
            'total_documents': len(documents),
            'similarities': [asdict(sim) for sim in self.similarities],
            'concepts': [asdict(concept) for concept in self.concepts],
            'clusters': [asdict(cluster) for cluster in self.clusters],
            'graph_stats': {
                'nodes': self.knowledge_graph.number_of_nodes(),
                'edges': self.knowledge_graph.number_of_edges(),
                'density': nx.density(self.knowledge_graph) if self.knowledge_graph.number_of_nodes() > 0 else 0,
                'connected_components': nx.number_connected_components(self.knowledge_graph)
            },
            'document_ids': list(documents.keys())
        }
    
    def _compute_document_similarities(self) -> List[DocumentSimilarity]:
        """Compute pairwise similarities between all documents with optimizations."""
        cache_key = f"similarities_{len(self.document_texts)}_{hash(tuple(sorted(self.document_texts.keys())))}"
        
        # Check cache first
        if self.enable_caching and cache_key in self._similarity_cache:
            logger.debug("Using cached similarity results")
            return self._similarity_cache[cache_key]
        
        # Preprocess texts in batches for memory efficiency
        processed_texts = []
        doc_ids = list(self.document_texts.keys())
        
        logger.debug(f"Preprocessing {len(doc_ids)} documents...")
        
        # Process in batches to manage memory
        if len(doc_ids) > self.batch_size:
            for i in range(0, len(doc_ids), self.batch_size):
                batch_ids = doc_ids[i:i + self.batch_size]
                batch_texts = []
                for doc_id in batch_ids:
                    text = self.document_texts[doc_id]
                    processed_text = self._preprocess_text(text)
                    batch_texts.append(processed_text)
                processed_texts.extend(batch_texts)
        else:
            for doc_id in doc_ids:
                text = self.document_texts[doc_id]
                processed_text = self._preprocess_text(text)
                processed_texts.append(processed_text)
        
        # Compute TF-IDF vectors with optimized parameters
        # Adjust parameters for small document collections
        min_df_val = min(2, max(1, len(doc_ids) // 10)) if len(doc_ids) > 2 else 1
        max_df_val = min(0.95, (len(doc_ids) - 1) / len(doc_ids)) if len(doc_ids) <= 5 else 0.95
        
        self.tfidf_vectorizer = TfidfVectorizer(
            max_features=min(self.max_features, len(doc_ids) * 100),  # Adjust for small collections
            ngram_range=(1, 2) if len(doc_ids) > 100 else (1, 3),  # Reduce n-grams for large collections
            min_df=min_df_val,  # Adaptive min_df
            max_df=max_df_val,  # Adaptive max_df for small collections
            stop_words='english',
            use_idf=True,
            sublinear_tf=True,  # Use sublinear TF scaling for better performance
            lowercase=True,
            token_pattern=r'\b\w+\b'  # Simple token pattern
        )
        
        logger.debug("Computing TF-IDF vectors...")
        self.document_vectors = self.tfidf_vectorizer.fit_transform(processed_texts)
        
        # Use sparse matrices for memory efficiency if enabled
        if self.use_sparse_matrices and len(doc_ids) > 50:
            # Compute similarities in chunks to manage memory
            similarities = self._compute_similarities_chunked(doc_ids)
        else:
            # Standard similarity computation for smaller collections
            similarity_matrix = cosine_similarity(self.document_vectors)
            similarities = self._extract_similarities_from_matrix(similarity_matrix, doc_ids)
        
        # Cache results
        if self.enable_caching:
            self._similarity_cache[cache_key] = similarities
        
        return similarities
    
    def _compute_similarities_chunked(self, doc_ids: List[str]) -> List[DocumentSimilarity]:
        """Compute similarities in chunks for large document collections."""
        similarities = []
        chunk_size = min(50, len(doc_ids) // 4 + 1)  # Adaptive chunk size
        
        logger.debug(f"Computing similarities in chunks of {chunk_size}")
        
        for i in range(0, len(doc_ids), chunk_size):
            end_i = min(i + chunk_size, len(doc_ids))
            chunk_vectors_i = self.document_vectors[i:end_i]
            
            for j in range(i, len(doc_ids), chunk_size):
                end_j = min(j + chunk_size, len(doc_ids))
                chunk_vectors_j = self.document_vectors[j:end_j]
                
                # Compute similarity for this chunk pair
                chunk_similarities = cosine_similarity(chunk_vectors_i, chunk_vectors_j)
                
                # Extract similarities above threshold
                for local_i in range(chunk_similarities.shape[0]):
                    global_i = i + local_i
                    start_j = local_i if i == j else 0  # Avoid duplicate pairs
                    
                    for local_j in range(start_j, chunk_similarities.shape[1]):
                        global_j = j + local_j
                        
                        if global_i >= global_j:  # Avoid duplicates and self-similarity
                            continue
                        
                        similarity_score = chunk_similarities[local_i, local_j]
                        
                        if similarity_score >= self.similarity_threshold:
                            # Find shared concepts (expensive, so do lazily)
                            shared_concepts = []  # Will compute on demand
                            
                            similarity = DocumentSimilarity(
                                doc1_id=doc_ids[global_i],
                                doc2_id=doc_ids[global_j],
                                similarity_score=float(similarity_score),
                                similarity_type='cosine',
                                shared_concepts=shared_concepts
                            )
                            similarities.append(similarity)
        
        return similarities
    
    def _extract_similarities_from_matrix(self, similarity_matrix: np.ndarray, 
                                        doc_ids: List[str]) -> List[DocumentSimilarity]:
        """Extract similarities from a precomputed similarity matrix."""
        similarities = []
        
        for i in range(len(doc_ids)):
            for j in range(i + 1, len(doc_ids)):
                similarity_score = similarity_matrix[i][j]
                
                if similarity_score >= self.similarity_threshold:
                    # Find shared concepts (compute lazily for performance)
                    shared_concepts = []  # Will compute on demand
                    
                    similarity = DocumentSimilarity(
                        doc1_id=doc_ids[i],
                        doc2_id=doc_ids[j],
                        similarity_score=float(similarity_score),
                        similarity_type='cosine',
                        shared_concepts=shared_concepts
                    )
                    similarities.append(similarity)
        
        return similarities
    
    def _extract_concepts(self) -> List[ExtractedConcept]:
        """Extract key concepts, entities, and keywords from documents."""
        concepts = {}
        
        for doc_id, text in self.document_texts.items():
            # Extract entities using NLTK
            entities = self._extract_entities(text)
            
            # Extract keywords using TF-IDF
            keywords = self._extract_keywords(text)
            
            # Extract important phrases
            phrases = self._extract_phrases(text)
            
            # Combine all concepts
            all_concepts = entities + keywords + phrases
            
            for concept_text, concept_type, importance in all_concepts:
                concept_key = (concept_text.lower(), concept_type)
                
                if concept_key not in concepts:
                    concepts[concept_key] = {
                        'text': concept_text,
                        'type': concept_type,
                        'frequency': 0,
                        'importance_scores': [],
                        'document_ids': [],
                        'context_sentences': []
                    }
                
                concepts[concept_key]['frequency'] += 1
                concepts[concept_key]['importance_scores'].append(importance)
                concepts[concept_key]['document_ids'].append(doc_id)
                
                # Extract context
                context = self._extract_context(text, concept_text)
                if context:
                    concepts[concept_key]['context_sentences'].append(context)
        
        # Convert to ExtractedConcept objects
        extracted_concepts = []
        for (concept_text, concept_type), data in concepts.items():
            if data['frequency'] >= self.min_concept_frequency:
                avg_importance = np.mean(data['importance_scores'])
                
                concept = ExtractedConcept(
                    text=concept_text,
                    concept_type=concept_type,
                    frequency=data['frequency'],
                    importance_score=float(avg_importance),
                    document_ids=list(set(data['document_ids'])),
                    context_sentences=data['context_sentences'][:5]  # Limit context
                )
                extracted_concepts.append(concept)
        
        # Sort by importance and frequency
        extracted_concepts.sort(key=lambda x: (x.importance_score, x.frequency), reverse=True)
        return extracted_concepts[:self.max_concepts]
    
    def _perform_clustering(self) -> List[DocumentCluster]:
        """Perform document clustering to identify thematic groups."""
        if self.document_vectors is None:
            logger.warning("Document vectors not computed, skipping clustering")
            return []
        
        doc_ids = list(self.document_texts.keys())
        n_docs = len(doc_ids)
        
        if n_docs < 3:
            logger.warning("Too few documents for clustering")
            return []
        
        # Determine optimal number of clusters
        optimal_k = self._find_optimal_clusters(self.document_vectors.toarray())
        
        # Perform K-means clustering
        kmeans = KMeans(n_clusters=optimal_k, random_state=42, n_init=10)
        cluster_labels = kmeans.fit_predict(self.document_vectors)
        
        # Create cluster objects
        clusters = []
        for cluster_id in range(optimal_k):
            cluster_doc_indices = np.where(cluster_labels == cluster_id)[0]
            cluster_doc_ids = [doc_ids[i] for i in cluster_doc_indices]
            
            if len(cluster_doc_ids) == 0:
                continue
            
            # Compute cluster centroid features
            centroid = kmeans.cluster_centers_[cluster_id]
            feature_names = self.tfidf_vectorizer.get_feature_names_out()
            
            # Get top features for this cluster
            top_indices = np.argsort(centroid)[-10:][::-1]
            centroid_features = {
                feature_names[i]: float(centroid[i]) 
                for i in top_indices if centroid[i] > 0
            }
            
            # Generate cluster label from top features
            cluster_label = self._generate_cluster_label(centroid_features)
            
            # Calculate coherence score
            coherence_score = self._calculate_cluster_coherence(cluster_doc_indices)
            
            # Extract main topics
            main_topics = list(centroid_features.keys())[:5]
            
            cluster = DocumentCluster(
                cluster_id=f"cluster_{cluster_id}",
                cluster_label=cluster_label,
                document_ids=cluster_doc_ids,
                centroid_features=centroid_features,
                coherence_score=float(coherence_score),
                main_topics=main_topics
            )
            clusters.append(cluster)
        
        return clusters
    
    def _build_knowledge_graph(self):
        """Build a knowledge graph from documents, concepts, and relationships."""
        self.knowledge_graph.clear()
        
        # Add document nodes
        for doc_id in self.document_texts.keys():
            metadata = self.document_metadata.get(doc_id, {})
            node = KnowledgeGraphNode(
                node_id=doc_id,
                node_type='document',
                label=metadata.get('title', doc_id),
                properties={
                    'filename': metadata.get('filename', ''),
                    'size_mb': metadata.get('size_mb', 0),
                    'page_count': metadata.get('page_count', 0)
                }
            )
            self.knowledge_graph.add_node(doc_id, **asdict(node))
        
        # Add concept nodes
        for concept in self.concepts:
            concept_id = f"concept_{concept.text.replace(' ', '_')}"
            node = KnowledgeGraphNode(
                node_id=concept_id,
                node_type='concept',
                label=concept.text,
                properties={
                    'concept_type': concept.concept_type,
                    'frequency': concept.frequency,
                    'importance_score': concept.importance_score
                }
            )
            self.knowledge_graph.add_node(concept_id, **asdict(node))
            
            # Add edges from documents to concepts
            for doc_id in concept.document_ids:
                edge = KnowledgeGraphEdge(
                    source_id=doc_id,
                    target_id=concept_id,
                    edge_type='contains',
                    weight=concept.importance_score,
                    properties={'concept_type': concept.concept_type}
                )
                self.knowledge_graph.add_edge(doc_id, concept_id, **asdict(edge))
        
        # Add similarity edges between documents
        for similarity in self.similarities:
            edge = KnowledgeGraphEdge(
                source_id=similarity.doc1_id,
                target_id=similarity.doc2_id,
                edge_type='similar_to',
                weight=similarity.similarity_score,
                properties={
                    'similarity_type': similarity.similarity_type,
                    'shared_concepts': len(similarity.shared_concepts)
                }
            )
            self.knowledge_graph.add_edge(
                similarity.doc1_id, 
                similarity.doc2_id, 
                **asdict(edge)
            )
    
    def find_similar_documents(self, target_doc_id: str, 
                             num_similar: int = 5) -> List[Tuple[str, float]]:
        """Find documents similar to a target document."""
        similar_docs = []
        
        for similarity in self.similarities:
            if similarity.doc1_id == target_doc_id:
                similar_docs.append((similarity.doc2_id, similarity.similarity_score))
            elif similarity.doc2_id == target_doc_id:
                similar_docs.append((similarity.doc1_id, similarity.similarity_score))
        
        # Sort by similarity score and return top N
        similar_docs.sort(key=lambda x: x[1], reverse=True)
        return similar_docs[:num_similar]
    
    def get_document_concepts(self, doc_id: str) -> List[ExtractedConcept]:
        """Get all concepts associated with a specific document."""
        return [concept for concept in self.concepts if doc_id in concept.document_ids]
    
    def export_knowledge_graph(self, output_path: Path, format_type: str = 'graphml'):
        """Export knowledge graph in various formats."""
        if format_type == 'graphml':
            nx.write_graphml(self.knowledge_graph, output_path)
        elif format_type == 'json':
            graph_data = nx.node_link_data(self.knowledge_graph)
            with open(output_path, 'w') as f:
                json.dump(graph_data, f, indent=2)
        elif format_type == 'gexf':
            nx.write_gexf(self.knowledge_graph, output_path)
        else:
            raise ValueError(f"Unsupported format: {format_type}")
    
    def _preprocess_text(self, text: str) -> str:
        """Preprocess text for analysis."""
        # Convert to lowercase
        text = text.lower()
        
        # Remove punctuation and special characters
        text = re.sub(r'[^\w\s]', ' ', text)
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Tokenize and lemmatize
        tokens = word_tokenize(text)
        tokens = [self.lemmatizer.lemmatize(token) for token in tokens 
                 if token not in self.stop_words and len(token) > 2]
        
        return ' '.join(tokens)
    
    def _extract_entities(self, text: str) -> List[Tuple[str, str, float]]:
        """Extract named entities from text."""
        entities = []
        
        # Use NLTK for basic entity extraction
        tokens = word_tokenize(text)
        pos_tags = pos_tag(tokens)
        chunks = ne_chunk(pos_tags)
        
        for chunk in chunks:
            if isinstance(chunk, Tree):
                entity_text = ' '.join([token for token, pos in chunk.leaves()])
                entity_type = chunk.label()
                
                # Simple importance score based on entity type
                importance_scores = {
                    'PERSON': 0.8,
                    'ORGANIZATION': 0.7,
                    'GPE': 0.6,  # Geo-political entity
                    'LOCATION': 0.6,
                    'DATE': 0.4,
                    'MONEY': 0.5
                }
                importance = importance_scores.get(entity_type, 0.3)
                
                entities.append((entity_text, 'entity', importance))
        
        return entities
    
    def _extract_keywords(self, text: str) -> List[Tuple[str, str, float]]:
        """Extract keywords using TF-IDF."""
        if self.tfidf_vectorizer is None:
            return []
        
        # Transform text using the fitted vectorizer
        processed_text = self._preprocess_text(text)
        text_vector = self.tfidf_vectorizer.transform([processed_text])
        
        # Get feature scores
        feature_names = self.tfidf_vectorizer.get_feature_names_out()
        scores = text_vector.toarray()[0]
        
        # Get top keywords
        keyword_scores = [(feature_names[i], scores[i]) for i in range(len(scores)) if scores[i] > 0]
        keyword_scores.sort(key=lambda x: x[1], reverse=True)
        
        keywords = []
        for keyword, score in keyword_scores[:20]:  # Top 20 keywords
            keywords.append((keyword, 'keyword', float(score)))
        
        return keywords
    
    def _extract_phrases(self, text: str) -> List[Tuple[str, str, float]]:
        """Extract important phrases from text."""
        phrases = []
        
        # Simple phrase extraction using POS patterns
        tokens = word_tokenize(text)
        pos_tags = pos_tag(tokens)
        
        # Look for noun phrases (simplified)
        phrase_patterns = [
            ['JJ', 'NN'],  # Adjective + Noun
            ['NN', 'NN'],  # Noun + Noun
            ['JJ', 'JJ', 'NN'],  # Adjective + Adjective + Noun
        ]
        
        for i in range(len(pos_tags) - 1):
            for pattern in phrase_patterns:
                if i + len(pattern) <= len(pos_tags):
                    phrase_pos = [pos for _, pos in pos_tags[i:i+len(pattern)]]
                    if phrase_pos == pattern:
                        phrase_text = ' '.join([token for token, _ in pos_tags[i:i+len(pattern)]])
                        # Simple importance based on phrase length and frequency
                        importance = 0.4 + (len(pattern) * 0.1)
                        phrases.append((phrase_text, 'phrase', importance))
        
        return phrases
    
    def _extract_context(self, text: str, concept_text: str) -> Optional[str]:
        """Extract context sentence for a concept."""
        sentences = sent_tokenize(text)
        
        for sentence in sentences:
            if concept_text.lower() in sentence.lower():
                return sentence
        
        return None
    
    def _find_shared_concepts(self, doc1_id: str, doc2_id: str) -> List[str]:
        """Find concepts shared between two documents."""
        doc1_concepts = set()
        doc2_concepts = set()
        
        for concept in self.concepts:
            if doc1_id in concept.document_ids:
                doc1_concepts.add(concept.text)
            if doc2_id in concept.document_ids:
                doc2_concepts.add(concept.text)
        
        return list(doc1_concepts.intersection(doc2_concepts))
    
    def _find_optimal_clusters(self, vectors: np.ndarray) -> int:
        """Find optimal number of clusters using silhouette analysis."""
        max_k = min(10, len(vectors) // 2)
        if max_k < 2:
            return 2
        
        best_k = 2
        best_score = -1
        
        for k in range(2, max_k + 1):
            try:
                kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
                cluster_labels = kmeans.fit_predict(vectors)
                score = silhouette_score(vectors, cluster_labels)
                
                if score > best_score:
                    best_score = score
                    best_k = k
            except:
                continue
        
        return best_k
    
    def _generate_cluster_label(self, centroid_features: Dict[str, float]) -> str:
        """Generate a human-readable label for a cluster."""
        top_features = sorted(centroid_features.items(), key=lambda x: x[1], reverse=True)
        top_words = [word for word, score in top_features[:3]]
        return " & ".join(top_words).title()
    
    def _calculate_cluster_coherence(self, doc_indices: np.ndarray) -> float:
        """Calculate coherence score for a cluster."""
        if len(doc_indices) < 2:
            return 1.0
        
        # Calculate average pairwise similarity within cluster
        cluster_vectors = self.document_vectors[doc_indices]
        similarity_matrix = cosine_similarity(cluster_vectors)
        
        # Get upper triangle (excluding diagonal)
        upper_tri = np.triu(similarity_matrix, k=1)
        non_zero_similarities = upper_tri[upper_tri > 0]
        
        if len(non_zero_similarities) == 0:
            return 0.0
        
        return float(np.mean(non_zero_similarities))
    
    def save_analysis_cache(self, cache_file: Path):
        """Save analysis results to cache for faster future loading."""
        cache_data = {
            'similarities': [asdict(sim) for sim in self.similarities],
            'concepts': [asdict(concept) for concept in self.concepts],
            'clusters': [asdict(cluster) for cluster in self.clusters],
            'graph_data': nx.node_link_data(self.knowledge_graph) if self.knowledge_graph.number_of_nodes() > 0 else None
        }
        
        with open(cache_file, 'wb') as f:
            pickle.dump(cache_data, f)
    
    def load_analysis_cache(self, cache_file: Path) -> bool:
        """Load analysis results from cache."""
        try:
            with open(cache_file, 'rb') as f:
                cache_data = pickle.load(f)
            
            # Reconstruct objects from cached data
            self.similarities = [DocumentSimilarity(**sim) for sim in cache_data['similarities']]
            self.concepts = [ExtractedConcept(**concept) for concept in cache_data['concepts']]
            self.clusters = [DocumentCluster(**cluster) for cluster in cache_data['clusters']]
            
            # Reconstruct knowledge graph
            if cache_data['graph_data']:
                self.knowledge_graph = nx.node_link_graph(cache_data['graph_data'])
            
            return True
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            return False