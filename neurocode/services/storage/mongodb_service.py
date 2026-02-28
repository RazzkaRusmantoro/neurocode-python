"""
MongoDB service for storing and retrieving documentation metadata,
code references, and glossary terms
"""
import os
from typing import Optional, Dict, List, Any
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class MongoDBService:
    """Service for MongoDB operations"""
    
    def __init__(self):
        """
        Initialize MongoDB service with connection string from environment variables
        """
        self.mongodb_uri = os.getenv("MONGODB_URI")
        self.database_name = os.getenv("MONGODB_DATABASE", "NeuroCode")
        
        if not self.mongodb_uri:
            raise ValueError(
                "Missing required MongoDB connection string. "
                "Please set MONGODB_URI in environment variables."
            )
        
        # Initialize MongoDB client
        try:
            self.client = MongoClient(self.mongodb_uri)
            self.db = self.client[self.database_name]
            # Test connection
            self.client.admin.command('ping')
            print(f"[MongoDBService] ✓ Connected to MongoDB database: {self.database_name}")
        except ConnectionFailure as e:
            raise ConnectionFailure(f"Failed to connect to MongoDB: {str(e)}")
        except Exception as e:
            raise Exception(f"MongoDB initialization error: {str(e)}")
    
    def check_connection(self) -> Dict[str, Any]:
        """
        Check if MongoDB connection is working
        
        Returns:
            Dictionary with connection status
        """
        try:
            # Ping the database
            self.client.admin.command('ping')
            
            # Get database stats
            stats = self.db.command("dbstats")
            
            return {
                "success": True,
                "message": f"Successfully connected to MongoDB database: {self.database_name}",
                "database": self.database_name,
                "collections": self.db.list_collection_names(),
                "stats": {
                    "collections": stats.get("collections", 0),
                    "dataSize": stats.get("dataSize", 0),
                    "storageSize": stats.get("storageSize", 0)
                }
            }
        except ConnectionFailure as e:
            return {
                "success": False,
                "error": f"MongoDB connection failed: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to check MongoDB connection: {str(e)}"
            }
    
    def upsert_code_reference(
        self,
        organization_id: str,
        repository_id: str,
        reference_id: str,
        name: str,
        reference_type: str,
        description: str,
        module: Optional[str] = None,
        file_path: Optional[str] = None,
        signature: Optional[str] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
        returns: Optional[Dict[str, Any]] = None,
        examples: Optional[List[Dict[str, Any]]] = None,
        see_also: Optional[List[str]] = None,
        similar_to: Optional[List[str]] = None,
        similarity_score: Optional[float] = None,
        code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Upsert a code reference (insert if new, update if exists)
        
        Args:
            organization_id: Organization ID (MongoDB ObjectId string)
            repository_id: Repository ID (MongoDB ObjectId string)
            reference_id: Unique identifier for the reference (e.g., "processCitation")
            name: Function/class name
            reference_type: Type ('function', 'class', 'method', 'module')
            description: Description of the reference
            module: Optional module path
            file_path: Optional file path in repository
            signature: Optional function/class signature
            parameters: Optional list of parameter dictionaries
            returns: Optional return type and description
            examples: Optional list of example dictionaries
            see_also: Optional list of other reference IDs
            similar_to: Optional list of similar reference IDs
            similarity_score: Optional similarity score
            
        Returns:
            Dictionary with success status and reference data
        """
        try:
            # Convert string IDs to ObjectId
            try:
                org_obj_id = ObjectId(organization_id)
                repo_obj_id = ObjectId(repository_id)
            except (InvalidId, TypeError) as e:
                return {
                    "success": False,
                    "error": f"Invalid ObjectId format: {str(e)}"
                }
            
            # Build document
            now = datetime.utcnow()
            document = {
                "organizationId": org_obj_id,
                "repositoryId": repo_obj_id,
                "referenceId": reference_id,
                "name": name,
                "type": reference_type,
                "description": description,
                "updatedAt": now
            }
            
            # Add optional fields
            if module:
                document["module"] = module
            if file_path:
                document["filePath"] = file_path
            if signature:
                document["signature"] = signature
            if parameters:
                document["parameters"] = parameters
            if returns:
                document["returns"] = returns
            if examples:
                document["examples"] = examples
            if see_also:
                document["seeAlso"] = see_also
            if similar_to:
                document["similarTo"] = similar_to
            if similarity_score is not None:
                document["similarityScore"] = similarity_score
            if code:
                document["code"] = code  # Raw code snippet
            
            # Check if reference already exists
            existing = self.db.code_references.find_one({
                "organizationId": org_obj_id,
                "repositoryId": repo_obj_id,
                "referenceId": reference_id
            })
            
            if existing:
                # Update existing document
                document["createdAt"] = existing.get("createdAt", now)
                result = self.db.code_references.update_one(
                    {
                        "organizationId": org_obj_id,
                        "repositoryId": repo_obj_id,
                        "referenceId": reference_id
                    },
                    {"$set": document}
                )
                return {
                    "success": True,
                    "action": "updated",
                    "referenceId": reference_id,
                    "reference_id": str(existing["_id"])
                }
            else:
                # Insert new document
                document["createdAt"] = now
                result = self.db.code_references.insert_one(document)
                return {
                    "success": True,
                    "action": "created",
                    "referenceId": reference_id,
                    "reference_id": str(result.inserted_id)
                }
                
        except OperationFailure as e:
            return {
                "success": False,
                "error": f"MongoDB operation failed: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to upsert code reference: {str(e)}"
            }
    
    def upsert_glossary_term(
        self,
        organization_id: str,
        repository_id: str,
        term_id: str,
        term: str,
        definition: str,
        related_terms: Optional[List[str]] = None,
        similar_to: Optional[List[str]] = None,
        similarity_score: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Upsert a glossary term (insert if new, update if exists)
        
        Args:
            organization_id: Organization ID (MongoDB ObjectId string)
            repository_id: Repository ID (MongoDB ObjectId string)
            term_id: Unique identifier for the term (e.g., "citation-pipeline")
            term: Term name
            definition: Full definition
            related_terms: Optional list of related term IDs
            similar_to: Optional list of similar term IDs
            similarity_score: Optional similarity score
            
        Returns:
            Dictionary with success status and term data
        """
        try:
            # Convert string IDs to ObjectId
            try:
                org_obj_id = ObjectId(organization_id)
                repo_obj_id = ObjectId(repository_id)
            except (InvalidId, TypeError) as e:
                return {
                    "success": False,
                    "error": f"Invalid ObjectId format: {str(e)}"
                }
            
            # Build document
            now = datetime.utcnow()
            document = {
                "organizationId": org_obj_id,
                "repositoryId": repo_obj_id,
                "termId": term_id,
                "term": term,
                "definition": definition,
                "updatedAt": now
            }
            
            # Add optional fields
            if related_terms:
                document["relatedTerms"] = related_terms
            if similar_to:
                document["similarTo"] = similar_to
            if similarity_score is not None:
                document["similarityScore"] = similarity_score
            
            # Check if term already exists
            existing = self.db.glossaries.find_one({
                "organizationId": org_obj_id,
                "repositoryId": repo_obj_id,
                "termId": term_id
            })
            
            if existing:
                # Update existing document
                document["createdAt"] = existing.get("createdAt", now)
                result = self.db.glossaries.update_one(
                    {
                        "organizationId": org_obj_id,
                        "repositoryId": repo_obj_id,
                        "termId": term_id
                    },
                    {"$set": document}
                )
                return {
                    "success": True,
                    "action": "updated",
                    "termId": term_id,
                    "term_id": str(existing["_id"])
                }
            else:
                # Insert new document
                document["createdAt"] = now
                result = self.db.glossaries.insert_one(document)
                return {
                    "success": True,
                    "action": "created",
                    "termId": term_id,
                    "term_id": str(result.inserted_id)
                }
                
        except OperationFailure as e:
            return {
                "success": False,
                "error": f"MongoDB operation failed: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to upsert glossary term: {str(e)}"
            }
    
    def get_code_references_by_repository(
        self,
        organization_id: str,
        repository_id: str
    ) -> Dict[str, Any]:
        """
        Get all code references for a repository
        
        Args:
            organization_id: Organization ID (MongoDB ObjectId string)
            repository_id: Repository ID (MongoDB ObjectId string)
            
        Returns:
            Dictionary with success status and list of code references
        """
        try:
            # Convert string IDs to ObjectId
            try:
                org_obj_id = ObjectId(organization_id)
                repo_obj_id = ObjectId(repository_id)
            except (InvalidId, TypeError) as e:
                return {
                    "success": False,
                    "error": f"Invalid ObjectId format: {str(e)}"
                }
            
            # Find all references for this repository
            references = list(self.db.code_references.find({
                "organizationId": org_obj_id,
                "repositoryId": repo_obj_id
            }))
            
            # Convert ObjectIds to strings for JSON serialization
            for ref in references:
                ref["_id"] = str(ref["_id"])
                ref["organizationId"] = str(ref["organizationId"])
                ref["repositoryId"] = str(ref["repositoryId"])
            
            return {
                "success": True,
                "references": references,
                "count": len(references)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get code references: {str(e)}"
            }
    
    def get_glossary_by_repository(
        self,
        organization_id: str,
        repository_id: str
    ) -> Dict[str, Any]:
        """
        Get all glossary terms for a repository
        
        Args:
            organization_id: Organization ID (MongoDB ObjectId string)
            repository_id: Repository ID (MongoDB ObjectId string)
            
        Returns:
            Dictionary with success status and list of glossary terms
        """
        try:
            # Convert string IDs to ObjectId
            try:
                org_obj_id = ObjectId(organization_id)
                repo_obj_id = ObjectId(repository_id)
            except (InvalidId, TypeError) as e:
                return {
                    "success": False,
                    "error": f"Invalid ObjectId format: {str(e)}"
                }
            
            # Find all terms for this repository
            terms = list(self.db.glossaries.find({
                "organizationId": org_obj_id,
                "repositoryId": repo_obj_id
            }))
            
            # Convert ObjectIds to strings for JSON serialization
            for term in terms:
                term["_id"] = str(term["_id"])
                term["organizationId"] = str(term["organizationId"])
                term["repositoryId"] = str(term["repositoryId"])
            
            return {
                "success": True,
                "terms": terms,
                "count": len(terms)
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get glossary terms: {str(e)}"
            }
    
    def find_similar_code_references(
        self,
        organization_id: str,
        repository_id: str,
        reference_id: str,
        name: str,
        description: str,
        threshold: float = 0.7
    ) -> Dict[str, Any]:
        """
        Find similar code references (for deduplication)
        This is a placeholder - actual similarity would use embeddings
        
        Args:
            organization_id: Organization ID
            repository_id: Repository ID
            reference_id: Current reference ID
            name: Function/class name
            description: Description text
            threshold: Similarity threshold (0.0 to 1.0)
            
        Returns:
            Dictionary with similar references found
        """
        # TODO: Implement actual similarity search using embeddings
        # For now, return empty list
        return {
            "success": True,
            "similar_references": [],
            "message": "Similarity search not yet implemented"
        }
    
    def insert_uml_diagram(
        self,
        organization_id: str,
        repository_id: str,
        diagram_type: str,
        name: str,
        slug: str,
        prompt: str,
        diagram_data: Dict[str, Any],
        s3_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Insert a new UML diagram into uml_diagrams collection.

        Args:
            organization_id: Organization ID (MongoDB ObjectId string)
            repository_id: Repository ID (MongoDB ObjectId string)
            diagram_type: Type of diagram (e.g. "class")
            name: Display name (e.g. "class-auth-module")
            slug: URL-safe slug, unique per repo (e.g. "class-auth-module")
            prompt: User prompt used to generate the diagram
            diagram_data: Full diagram JSON (classes, relationships, etc.)
            s3_key: Optional S3 key for backup

        Returns:
            Dictionary with success status and diagram _id
        """
        try:
            try:
                org_obj_id = ObjectId(organization_id)
                repo_obj_id = ObjectId(repository_id)
            except (InvalidId, TypeError) as e:
                return {"success": False, "error": f"Invalid ObjectId format: {str(e)}"}

            now = datetime.utcnow()
            document = {
                "organizationId": org_obj_id,
                "repositoryId": repo_obj_id,
                "type": diagram_type,
                "name": name,
                "slug": slug,
                "prompt": prompt,
                "diagramData": diagram_data,
                "updatedAt": now,
                "createdAt": now,
            }
            if s3_key:
                document["s3Key"] = s3_key

            result = self.db.uml_diagrams.insert_one(document)
            return {
                "success": True,
                "diagram_id": str(result.inserted_id),
                "slug": slug,
                "name": name,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_uml_diagram_by_id(self, diagram_id: str) -> Dict[str, Any]:
        """Get a single UML diagram by its _id."""
        try:
            obj_id = ObjectId(diagram_id)
        except (InvalidId, TypeError):
            return {"success": False, "error": "Invalid diagram id"}
        doc = self.db.uml_diagrams.find_one({"_id": obj_id})
        if not doc:
            return {"success": False, "error": "Diagram not found"}
        doc["_id"] = str(doc["_id"])
        doc["organizationId"] = str(doc["organizationId"])
        doc["repositoryId"] = str(doc["repositoryId"])
        return {"success": True, "diagram": doc}

    def get_uml_diagram_by_slug(
        self,
        organization_id: str,
        repository_id: str,
        slug: str,
    ) -> Dict[str, Any]:
        """Get a single UML diagram by organization, repository, and slug."""
        try:
            org_obj_id = ObjectId(organization_id)
            repo_obj_id = ObjectId(repository_id)
        except (InvalidId, TypeError):
            return {"success": False, "error": "Invalid organization or repository id"}
        doc = self.db.uml_diagrams.find_one(
            {
                "organizationId": org_obj_id,
                "repositoryId": repo_obj_id,
                "slug": slug,
            }
        )
        if not doc:
            return {"success": False, "error": "Diagram not found"}
        doc["_id"] = str(doc["_id"])
        doc["organizationId"] = str(doc["organizationId"])
        doc["repositoryId"] = str(doc["repositoryId"])
        return {"success": True, "diagram": doc}

    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            print("[MongoDBService] MongoDB connection closed")

