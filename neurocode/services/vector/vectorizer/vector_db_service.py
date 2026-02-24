"""
Vector database service using Qdrant
"""
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import uuid


class VectorDBService:
    """Service for managing vector database operations"""
    
    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None, persist_directory: Optional[str] = None):
        """
        Initialize vector database service
        
        Args:
            url: Qdrant server URL (None for local)
            api_key: Qdrant API key (for cloud)
            persist_directory: Directory to persist local Qdrant data (if local)
        """
        if url:
            # Remote Qdrant instance
            print(f"[VectorDBService] Connecting to Qdrant at {url}...")
            self.client = QdrantClient(url=url, api_key=api_key)
            self.is_local = False
        else:
            # Local Qdrant instance
            if persist_directory:
                persist_path = Path(persist_directory)
                persist_path.mkdir(parents=True, exist_ok=True)
                print(f"[VectorDBService] Initializing local Qdrant at {persist_path}...")
                self.client = QdrantClient(path=str(persist_path))
            else:
                print(f"[VectorDBService] Initializing in-memory Qdrant...")
                self.client = QdrantClient(":memory:")
            self.is_local = True
        
        print(f"[VectorDBService] ✓ Qdrant initialized")
    
    def get_or_create_collection(
        self,
        collection_name: str,
        embedding_dimension: int,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Get or create a collection with metadata linking to org and repo
        
        Args:
            collection_name: Name of the collection
            embedding_dimension: Dimension of embeddings
            metadata: Optional metadata to store with collection (e.g., org_id, repo_id)
        """
        try:
            # Check if collection exists
            collections = self.client.get_collections()
            collection_names = [col.name for col in collections.collections]
            
            if collection_name not in collection_names:
                # Create collection with metadata
                self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=embedding_dimension,
                        distance=Distance.COSINE
                    ),
                    # Store metadata for linking to org and repo
                    on_disk_payload=True  # Store payload on disk for better performance
                )
                
                # Store metadata as a special tracking point in the collection
                # This allows us to query which org/repo a collection belongs to
                if metadata:
                    try:
                        # Create a special metadata point with fixed UUID
                        metadata_point_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{collection_name}_metadata")
                        metadata_point = PointStruct(
                            id=metadata_point_id,
                            vector=[0.0] * embedding_dimension,  # Zero vector for metadata point
                            payload={
                                "type": "collection_metadata",
                                **metadata
                            }
                        )
                        self.client.upsert(
                            collection_name=collection_name,
                            points=[metadata_point]
                        )
                        print(f"[VectorDBService] Stored collection metadata: {metadata}")
                    except Exception as e:
                        print(f"[VectorDBService] Warning: Could not store collection metadata: {e}")
                
                print(f"[VectorDBService] Created new collection: {collection_name}")
            else:
                print(f"[VectorDBService] Using existing collection: {collection_name}")
        except Exception as e:
            print(f"[VectorDBService] Error managing collection: {e}")
            raise
    
    def add_chunks(
        self,
        collection_name: str,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
        batch_size: int = 100
    ):
        """
        Add chunks with embeddings to vector DB
        
        Args:
            collection_name: Name of the collection
            chunks: List of chunk dictionaries
            embeddings: List of embedding vectors
            batch_size: Batch size for adding chunks
        """
        if len(chunks) != len(embeddings):
            raise ValueError(f"Chunks ({len(chunks)}) and embeddings ({len(embeddings)}) must have same length")
        
        if not chunks:
            return
        
        # Get embedding dimension
        embedding_dimension = len(embeddings[0])
        
        # Ensure collection exists
        self.get_or_create_collection(collection_name, embedding_dimension)
        
        print(f"[VectorDBService] Adding {len(chunks)} chunks to collection '{collection_name}'...")
        
        # Prepare points for Qdrant
        # Qdrant requires point IDs to be integers or UUIDs
        # Convert string chunk IDs to UUIDs deterministically
        points = []
        for i, chunk in enumerate(chunks):
            chunk_id_str = chunk["id"]
            # Generate deterministic UUID from chunk ID string
            # Using UUID5 with a fixed namespace ensures same chunk ID always gets same UUID
            point_id = uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id_str)
            
            point = PointStruct(
                id=point_id,  # Use UUID instead of string ID
                vector=embeddings[i],
                payload={
                    "content": chunk["content"],
                    "chunk_id": chunk_id_str,  # Keep original string ID in payload
                    "type": chunk["type"],
                    "file_path": chunk["metadata"]["file_path"],
                    "language": chunk["metadata"]["language"],
                    "function_name": chunk["metadata"].get("function_name") or "",
                    "class_name": chunk["metadata"].get("class_name") or "",
                    "subsystem": chunk["metadata"].get("subsystem") or "",
                    "start_line": chunk["metadata"].get("start_line", 0),
                    "end_line": chunk["metadata"].get("end_line", 0),
                    "summary": chunk["metadata"].get("summary") or "",
                    "keywords": ", ".join(chunk["metadata"]["keywords"]) if isinstance(chunk["metadata"].get("keywords"), list) else (chunk["metadata"].get("keywords") or ""),
                }
            )
            points.append(point)
        
        # Add in batches
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            self.client.upsert(
                collection_name=collection_name,
                points=batch
            )
            
            if (i + batch_size) % 100 == 0:
                print(f"[VectorDBService] Added {min(i + batch_size, len(chunks))}/{len(chunks)} chunks...")
        
        print(f"[VectorDBService] ✓ Added {len(chunks)} chunks to vector DB")
    
    def search(
        self,
        collection_name: str,
        query_embedding: List[float],
        top_k: int = 5,
        filter_metadata: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for similar chunks
        
        Args:
            collection_name: Name of the collection
            query_embedding: Query embedding vector
            top_k: Number of results to return
            filter_metadata: Optional metadata filters (e.g., {"language": "typescript"})
        
        Returns:
            List of search results with chunks and scores
        """
        # Build filter if provided
        query_filter = None
        if filter_metadata:
            conditions = []
            for key, value in filter_metadata.items():
                conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value))
                )
            if conditions:
                query_filter = Filter(must=conditions)
        
        # Use query_points (correct Qdrant API method)
        results = self.client.query_points(
            collection_name=collection_name,
            query=query_embedding,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True
        )
        
        # Format results
        search_results = []
        for result in results.points:
            search_results.append({
                "id": result.id,
                "content": result.payload.get("content", ""),
                "metadata": {
                    "chunk_id": result.payload.get("chunk_id", ""),
                    "type": result.payload.get("type", ""),
                    "file_path": result.payload.get("file_path", ""),
                    "language": result.payload.get("language", ""),
                    "function_name": result.payload.get("function_name", ""),
                    "class_name": result.payload.get("class_name", ""),
                    "subsystem": result.payload.get("subsystem", ""),
                    "start_line": result.payload.get("start_line", 0),
                    "end_line": result.payload.get("end_line", 0),
                    "summary": result.payload.get("summary", ""),
                    "keywords": result.payload.get("keywords", ""),
                },
                "score": result.score  # Qdrant returns similarity score directly
            })
        
        return search_results
    
    def get_collection_count(self, collection_name: str) -> int:
        """Get number of chunks in collection"""
        try:
            collection_info = self.client.get_collection(collection_name)
            return collection_info.points_count
        except Exception:
            return 0
    
    def get_collection_metadata(self, collection_name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve metadata for a collection (org_id, repo_id, etc.)
        
        Args:
            collection_name: Name of the collection
        
        Returns:
            Dictionary with metadata or None if not found
        """
        try:
            # Retrieve the metadata point
            metadata_point_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"{collection_name}_metadata")
            result = self.client.retrieve(
                collection_name=collection_name,
                ids=[metadata_point_id]
            )
            
            if result and len(result) > 0:
                payload = result[0].payload
                if payload and payload.get("type") == "collection_metadata":
                    # Remove the type field and return metadata
                    metadata = {k: v for k, v in payload.items() if k != "type"}
                    return metadata
            return None
        except Exception as e:
            print(f"[VectorDBService] Could not retrieve collection metadata: {e}")
            return None
    
    def list_collections_by_org(self, organization_id: str) -> List[str]:
        """
        List all collections for a specific organization
        
        Args:
            organization_id: Organization ID
        
        Returns:
            List of collection names
        """
        try:
            collections = self.client.get_collections()
            org_collections = []
            
            for col in collections.collections:
                metadata = self.get_collection_metadata(col.name)
                if metadata and metadata.get("organization_id") == organization_id:
                    org_collections.append(col.name)
            
            return org_collections
        except Exception as e:
            print(f"[VectorDBService] Error listing collections by org: {e}")
            return []

    def list_collections_by_org_short_id(self, organization_short_id: str) -> List[str]:
        """
        List all collections for an organization by its short ID (e.g. from URL).

        Args:
            organization_short_id: Organization short ID (e.g. "acme" or "org-acme")

        Returns:
            List of collection names
        """
        try:
            # Normalize: allow "org-acme" or "acme"
            short_id = (organization_short_id or "").strip()
            if short_id.startswith("org-"):
                short_id = short_id[4:]
            collections = self.client.get_collections()
            org_collections = []
            for col in collections.collections:
                metadata = self.get_collection_metadata(col.name)
                if not metadata:
                    continue
                meta_short = (metadata.get("organization_short_id") or "").strip()
                if meta_short.startswith("org-"):
                    meta_short = meta_short[4:]
                if meta_short and meta_short.lower() == short_id.lower():
                    org_collections.append(col.name)
            return org_collections
        except Exception as e:
            print(f"[VectorDBService] Error listing collections by org_short_id: {e}")
            return []
