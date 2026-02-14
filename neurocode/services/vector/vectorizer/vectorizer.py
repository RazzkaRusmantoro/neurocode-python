"""
Main vectorizer service
Combines embedding and vector DB operations
"""
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
from neurocode.services.vector.vectorizer.embedding_service import EmbeddingService
from neurocode.services.vector.vectorizer.vector_db_service import VectorDBService


class Vectorizer:
    """Main service for vectorizing code chunks"""
    
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        qdrant_url: Optional[str] = None,
        qdrant_api_key: Optional[str] = None,
        persist_directory: str = "data/vector_db"
    ):
        """
        Initialize vectorizer
        
        Args:
            model_name: Sentence transformer model name
            qdrant_url: Qdrant server URL (None for local)
            qdrant_api_key: Qdrant API key (for cloud)
            persist_directory: Directory for local Qdrant persistence
        """
        self.embedding_service = EmbeddingService(model_name=model_name)
        self.vector_db = VectorDBService(
            url=qdrant_url,
            api_key=qdrant_api_key,
            persist_directory=persist_directory if not qdrant_url else None
        )
    
    def vectorize_chunks_from_file(
        self,
        chunks_file_path: str,
        collection_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Load chunks from JSON file and vectorize them
        
        Args:
            chunks_file_path: Path to chunks.json file
            collection_name: Name for the collection (defaults to repo name from path)
        
        Returns:
            Dictionary with vectorization results
        """
        chunks_path = Path(chunks_file_path)
        if not chunks_path.exists():
            raise FileNotFoundError(f"Chunks file not found: {chunks_file_path}")
        
        print(f"[Vectorizer] Loading chunks from {chunks_path}...")
        
        with open(chunks_path, 'r', encoding='utf-8') as f:
            chunks = json.load(f)
        
        if not chunks:
            print("[Vectorizer] No chunks found in file")
            return {"success": False, "message": "No chunks to vectorize"}
        
        # Generate collection name from file path if not provided
        if not collection_name:
            # Extract repo name from path: data/owner_repo/branch/timestamp/chunks.json
            parts = chunks_path.parts
            if len(parts) >= 3:
                collection_name = f"{parts[-4]}_{parts[-3]}"  # owner_repo_branch
            else:
                collection_name = "default_collection"
        
        return self.vectorize_chunks(chunks, collection_name, metadata=metadata)
    
    def vectorize_chunks(
        self,
        chunks: List[Dict[str, Any]],
        collection_name: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Vectorize chunks and store in vector DB
        
        Args:
            chunks: List of chunk dictionaries
            collection_name: Name for the collection
        
        Returns:
            Dictionary with vectorization results
        """
        print(f"[Vectorizer] Vectorizing {len(chunks)} chunks for collection '{collection_name}'...")
        
        # Prepare texts for embedding (content + metadata context)
        texts_to_embed = []
        for chunk in chunks:
            text = self._prepare_text_for_embedding(chunk)
            texts_to_embed.append(text)
        
        # Generate embeddings
        embeddings = self.embedding_service.embed_batch(
            texts_to_embed,
            batch_size=32,
            show_progress=True
        )
        
        # Ensure collection exists with metadata (if provided)
        if metadata:
            embedding_dimension = len(embeddings[0]) if embeddings else 384
            self.vector_db.get_or_create_collection(collection_name, embedding_dimension, metadata=metadata)
        
        # Store in vector DB
        self.vector_db.add_chunks(
            collection_name=collection_name,
            chunks=chunks,
            embeddings=embeddings,
            batch_size=100
        )
        
        count = self.vector_db.get_collection_count(collection_name)
        
        return {
            "success": True,
            "collection_name": collection_name,
            "chunks_vectorized": len(chunks),
            "total_in_collection": count,
            "embedding_dimension": self.embedding_service.get_dimension()
        }
    
    def _prepare_text_for_embedding(self, chunk: Dict[str, Any]) -> str:
        """
        Prepare chunk text for embedding by combining content and metadata
        
        Args:
            chunk: Chunk dictionary
        
        Returns:
            Combined text for embedding
        """
        content = chunk.get("content", "")
        metadata = chunk.get("metadata", {})
        
        # Build context string from metadata
        context_parts = []
        
        if metadata.get("function_name"):
            context_parts.append(f"Function: {metadata['function_name']}")
        if metadata.get("class_name"):
            context_parts.append(f"Class: {metadata['class_name']}")
        if metadata.get("file_path"):
            context_parts.append(f"File: {metadata['file_path']}")
        if metadata.get("subsystem"):
            context_parts.append(f"Subsystem: {metadata['subsystem']}")
        if metadata.get("calls"):
            context_parts.append(f"Calls: {', '.join(metadata['calls'])}")
        if metadata.get("dependencies"):
            deps = metadata['dependencies'][:5]  # Limit to first 5
            context_parts.append(f"Dependencies: {', '.join(deps)}")
        
        context = " | ".join(context_parts)
        
        # Combine content and context
        if context:
            return f"{context}\n\n{content}"
        return content
    
    def search(
        self,
        collection_name: str,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks
        
        Args:
            collection_name: Name of the collection
            query: Search query text
            top_k: Number of results to return
            filter_metadata: Optional metadata filters (e.g., {"language": "typescript"})
        
        Returns:
            List of search results with chunks and scores
        """
        # Embed query
        query_embedding = self.embedding_service.embed_text(query)
        
        # Search vector DB
        results = self.vector_db.search(
            collection_name=collection_name,
            query_embedding=query_embedding,
            top_k=top_k,
            filter_metadata=filter_metadata
        )
        
        return results

