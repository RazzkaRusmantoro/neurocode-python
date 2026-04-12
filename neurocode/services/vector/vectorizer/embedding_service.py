from typing import List, Union
from sentence_transformers import SentenceTransformer
import numpy as np


class EmbeddingService:
    
    
    def __init__(self, model_name: str = "google/embeddinggemma-300m"):
        
        print(f"[EmbeddingService] Loading model: {model_name}...")
        self.model = SentenceTransformer(model_name)
        self.model_name = model_name
        self.dimension = self.model.get_sentence_embedding_dimension()
        print(f"[EmbeddingService] ✓ Model loaded: {model_name} ({self.dimension} dimensions)")
    
    def embed_text(self, text: str) -> List[float]:
        
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    def embed_batch(self, texts: List[str], batch_size: int = 32, show_progress: bool = True) -> List[List[float]]:
        
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
        
        return self.dimension

