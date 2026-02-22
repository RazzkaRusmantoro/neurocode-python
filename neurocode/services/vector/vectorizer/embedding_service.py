"""
Embedding service using sentence-transformers
"""
from typing import List, Union
from sentence_transformers import SentenceTransformer
import numpy as np


class EmbeddingService:
    """Service for generating embeddings using sentence-transformers"""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedding service
        
        Args:
            model_name: Model name (HuggingFace or sentence-transformers). Examples:
                - "all-MiniLM-L6-v2" (default): Fast, 384 dims, general text
                - "all-mpnet-base-v2": Better quality, 768 dims, slower
                - "microsoft/codebert-base": Code-specific, 768 dims (set EMBEDDING_MODEL in .env)
        """
        print(f"[EmbeddingService] Loading model: {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name
        self.dimension = self.model.get_sentence_embedding_dimension()
        print(f"[EmbeddingService] ✓ Model loaded: {model_name} ({self.dimension} dimensions)")
    
    def embed_text(self, text: str) -> List[float]:
        """
        Embed a single text string
        
        Args:
            text: Text to embed
        
        Returns:
            Embedding vector as list of floats
        """
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    def embed_batch(self, texts: List[str], batch_size: int = 32, show_progress: bool = True) -> List[List[float]]:
        """
        Embed multiple texts in batches
        
        Args:
            texts: List of texts to embed
            batch_size: Batch size for processing
            show_progress: Show progress bar
        
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        print(f"[EmbeddingService] Embedding {len(texts)} texts in batches of {batch_size}...")
        
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True
        )
        
        print(f"[EmbeddingService] ✓ Generated {len(embeddings)} embeddings")
        
        return embeddings.tolist()
    
    def get_dimension(self) -> int:
        """Get the dimension of embeddings"""
        return self.dimension

