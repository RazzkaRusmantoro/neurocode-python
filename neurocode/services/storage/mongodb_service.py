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

    def upsert_repository_branch_commits(
        self,
        organization_id: str,
        repository_id: str,
        branch_latest_commits: Dict[str, str],
        *,
        repo_full_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Store or update the latest commit SHA per branch for a repository.
        Used when adding a repo or when syncing; keyed by organization_id + repository_id.
        branch_latest_commits: e.g. {"main": "abc123", "develop": "def456"}.
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
                "branchLatestCommits": branch_latest_commits,
                "updatedAt": now,
            }
            if repo_full_name:
                document["repoFullName"] = repo_full_name
            self.db.repository_branch_commits.update_one(
                {
                    "organizationId": org_obj_id,
                    "repositoryId": repo_obj_id,
                },
                {"$set": document},
                upsert=True,
            )
            return {
                "success": True,
                "branch_count": len(branch_latest_commits),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_all_repository_branch_commits(self) -> Dict[str, Any]:
        """
        List all repos we track (for the sync job). Returns documents from
        repository_branch_commits with organizationId, repositoryId, repoFullName,
        branchLatestCommits, updatedAt (ObjectIds as strings).
        """
        try:
            cursor = self.db.repository_branch_commits.find({})
            docs = []
            for doc in cursor:
                doc["_id"] = str(doc["_id"])
                doc["organizationId"] = str(doc["organizationId"])
                doc["repositoryId"] = str(doc["repositoryId"])
                if doc.get("updatedAt"):
                    doc["updatedAt"] = doc["updatedAt"]
                docs.append(doc)
            return {"success": True, "repos": docs}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_github_token_for_repo(
        self,
        organization_id: str,
        repository_id: str,
    ) -> Dict[str, Any]:
        """
        Resolve a GitHub token for a repo using the same logic as Next.js:
        1. Try the user who added the repo (repository.addedBy -> user.github.accessToken).
        2. Fallback to the organization owner (organization.ownerId -> user.github.accessToken).
        Requires the same MongoDB to have users, repositories, and organizations collections.
        Returns { "success": True, "token": "..." } or { "success": False, "error": "..." }.
        """
        try:
            repo_obj_id = ObjectId(repository_id)
            org_obj_id = ObjectId(organization_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid id: {str(e)}"}

        def _token_from_user(user_doc: Optional[Dict[str, Any]]) -> Optional[str]:
            if not user_doc:
                return None
            github = user_doc.get("github") or {}
            if github.get("status") != "active":
                return None
            token = github.get("accessToken")
            if token and isinstance(token, str) and token.strip():
                return token.strip()
            return None

        try:
            # 1. Repository -> addedBy
            repo = self.db.repositories.find_one({"_id": repo_obj_id})
            if repo and repo.get("addedBy"):
                added_by_id = repo["addedBy"]
                user = self.db.users.find_one({"_id": added_by_id})
                token = _token_from_user(user)
                if token:
                    return {"success": True, "token": token, "source": "addedBy"}

            # 2. Organization -> ownerId
            org = self.db.organizations.find_one({"_id": org_obj_id})
            if org and org.get("ownerId"):
                owner_id = org["ownerId"]
                user = self.db.users.find_one({"_id": owner_id})
                token = _token_from_user(user)
                if token:
                    return {"success": True, "token": token, "source": "owner"}

            return {"success": False, "error": "No GitHub token found for this repo"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_repository_branch_commits(
        self,
        organization_id: str,
        repository_id: str,
    ) -> Dict[str, Any]:
        """
        Get the stored branch -> latest commit mapping for a repository.
        Returns { "success": True, "branchLatestCommits": { "main": "sha", ... } } or error.
        """
        try:
            try:
                org_obj_id = ObjectId(organization_id)
                repo_obj_id = ObjectId(repository_id)
            except (InvalidId, TypeError) as e:
                return {"success": False, "error": f"Invalid ObjectId format: {str(e)}"}
            doc = self.db.repository_branch_commits.find_one(
                {"organizationId": org_obj_id, "repositoryId": repo_obj_id}
            )
            if not doc:
                return {"success": True, "branchLatestCommits": {}}
            return {
                "success": True,
                "branchLatestCommits": doc.get("branchLatestCommits", {}),
                "updatedAt": doc.get("updatedAt"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_documentations_by_repository_and_branch(
        self,
        repository_id: str,
        branch: str,
    ) -> Dict[str, Any]:
        """
        List all textual documentation records for a repository and branch.
        Returns list with _id, filePaths, s3Key, title, prompt, needsSync, isUpdating, etc.
        """
        try:
            repo_obj_id = ObjectId(repository_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid repository id: {str(e)}"}
        try:
            cursor = self.db.documentation.find(
                {"repositoryId": repo_obj_id, "branch": branch}
            )
            docs = []
            for doc in cursor:
                doc["_id"] = str(doc["_id"])
                doc["organizationId"] = str(doc["organizationId"])
                doc["repositoryId"] = str(doc["repositoryId"])
                docs.append(doc)
            return {"success": True, "documentations": docs}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_uml_diagrams_by_repository_and_branch(
        self,
        repository_id: str,
        branch: str,
    ) -> Dict[str, Any]:
        """
        List all UML diagram records for a repository and branch.
        Returns list with _id, filePaths, diagramData, type, prompt, needsSync, isUpdating, etc.
        """
        try:
            repo_obj_id = ObjectId(repository_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid repository id: {str(e)}"}
        try:
            cursor = self.db.uml_diagrams.find(
                {"repositoryId": repo_obj_id, "branch": branch}
            )
            docs = []
            for doc in cursor:
                doc["_id"] = str(doc["_id"])
                doc["organizationId"] = str(doc["organizationId"])
                doc["repositoryId"] = str(doc["repositoryId"])
                docs.append(doc)
            return {"success": True, "uml_diagrams": docs}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_existing_uml_titles_descriptions(self, repository_id: str) -> Dict[str, Any]:
        """
        Get existing name and description for all UML diagrams in a repository.
        Used to generate unique title/description for new diagrams.
        """
        try:
            repo_obj_id = ObjectId(repository_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": str(e), "titles_descriptions": []}
        try:
            cursor = self.db.uml_diagrams.find(
                {"repositoryId": repo_obj_id},
                projection={"name": 1, "description": 1, "slug": 1},
            )
            titles_descriptions = [
                {
                    "name": doc.get("name") or "",
                    "description": doc.get("description") or "",
                    "slug": doc.get("slug") or "",
                }
                for doc in cursor
            ]
            return {"success": True, "titles_descriptions": titles_descriptions}
        except Exception as e:
            return {"success": False, "error": str(e), "titles_descriptions": []}

    def set_documentations_needs_sync(
        self,
        documentation_ids: List[str],
    ) -> Dict[str, Any]:
        """
        Set needsSync=true and updatedAt for the given documentation _ids.
        Used by the sync job after detecting changed files that affect these docs.
        """
        if not documentation_ids:
            return {"success": True, "modified_count": 0}
        try:
            obj_ids = [ObjectId(did) for did in documentation_ids]
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid id: {str(e)}"}
        try:
            now = datetime.utcnow()
            result = self.db.documentation.update_many(
                {"_id": {"$in": obj_ids}},
                {"$set": {"needsSync": True, "updatedAt": now}},
            )
            return {"success": True, "modified_count": result.modified_count}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_uml_diagrams_needs_sync(
        self,
        diagram_ids: List[str],
    ) -> Dict[str, Any]:
        """
        Set needsSync=true and updatedAt for the given UML diagram _ids.
        Used by the sync job after detecting changed files that affect these diagrams.
        """
        if not diagram_ids:
            return {"success": True, "modified_count": 0}
        try:
            obj_ids = [ObjectId(did) for did in diagram_ids]
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid id: {str(e)}"}
        try:
            now = datetime.utcnow()
            result = self.db.uml_diagrams.update_many(
                {"_id": {"$in": obj_ids}},
                {"$set": {"needsSync": True, "updatedAt": now}},
            )
            return {"success": True, "modified_count": result.modified_count}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_documentation_is_updating(
        self,
        documentation_id: str,
        is_updating: bool,
    ) -> Dict[str, Any]:
        """
        Set isUpdating (and updatedAt) for a single documentation. Use when starting or
        finishing regeneration so the UI can show "Updating..." and avoid double-sync.
        """
        try:
            obj_id = ObjectId(documentation_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid id: {str(e)}"}
        try:
            now = datetime.utcnow()
            self.db.documentation.update_one(
                {"_id": obj_id},
                {"$set": {"isUpdating": is_updating, "updatedAt": now}},
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_uml_diagram_is_updating(
        self,
        diagram_id: str,
        is_updating: bool,
    ) -> Dict[str, Any]:
        """
        Set isUpdating (and updatedAt) for a single UML diagram. Use when starting or
        finishing regeneration.
        """
        try:
            obj_id = ObjectId(diagram_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid id: {str(e)}"}
        try:
            now = datetime.utcnow()
            self.db.uml_diagrams.update_one(
                {"_id": obj_id},
                {"$set": {"isUpdating": is_updating, "updatedAt": now}},
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_documentation_by_id(self, documentation_id: str) -> Dict[str, Any]:
        """
        Get a single documentation record by _id. Used by regeneration.
        Returns doc with _id, organizationId, repositoryId, branch, s3Key, title, prompt,
        filePaths, documentationType, needsSync, isUpdating as strings where needed.
        """
        try:
            obj_id = ObjectId(documentation_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid id: {str(e)}"}
        try:
            doc = self.db.documentation.find_one({"_id": obj_id})
            if not doc:
                return {"success": False, "error": "Documentation not found"}
            doc["_id"] = str(doc["_id"])
            doc["organizationId"] = str(doc["organizationId"])
            doc["repositoryId"] = str(doc["repositoryId"])
            return {"success": True, "documentation": doc}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_organization_and_repo_for_collection(
        self,
        organization_id: str,
        repository_id: str,
    ) -> Dict[str, Any]:
        """
        Get organization and repository names for building vector collection name
        and repo_name for LLM. Returns organization_name, organization_short_id,
        repository_name, repo_full_name (from repo url if GitHub).
        """
        try:
            org_obj_id = ObjectId(organization_id)
            repo_obj_id = ObjectId(repository_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid id: {str(e)}"}
        try:
            org = self.db.organizations.find_one({"_id": org_obj_id})
            repo = self.db.repositories.find_one({"_id": repo_obj_id})
            if not org:
                return {"success": False, "error": "Organization not found"}
            if not repo:
                return {"success": False, "error": "Repository not found"}
            org_name = (org.get("name") or "").strip() or org.get("shortId", "")
            org_short_id = (org.get("shortId") or "").strip()
            repo_name = (repo.get("name") or repo.get("urlName") or "").strip()
            repo_full_name = ""
            url = (repo.get("url") or "").strip()
            if url and "github.com" in url:
                try:
                    from urllib.parse import urlparse
                    path = urlparse(url).path.strip("/")
                    parts = path.split("/")
                    if len(parts) >= 2:
                        repo_full_name = f"{parts[0]}/{parts[1]}"
                except Exception:
                    pass
            if not repo_full_name:
                repo_full_name = repo_name
            return {
                "success": True,
                "organization_name": org_name,
                "organization_short_id": org_short_id,
                "repository_name": repo_name,
                "repo_full_name": repo_full_name,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def clear_documentation_sync_flags(
        self,
        documentation_id: str,
        file_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Set needsSync=false, isUpdating=false, and updatedAt for a documentation.
        Optionally update filePaths (e.g. after regeneration). Call after regeneration completes.
        """
        try:
            obj_id = ObjectId(documentation_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid id: {str(e)}"}
        try:
            now = datetime.utcnow()
            update = {"needsSync": False, "isUpdating": False, "updatedAt": now}
            if file_paths is not None:
                update["filePaths"] = file_paths
            result = self.db.documentation.update_one(
                {"_id": obj_id},
                {"$set": update},
            )
            if result.matched_count == 0:
                return {"success": False, "error": "Documentation not found"}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def clear_uml_diagram_sync_flags(
        self,
        diagram_id: str,
        diagram_data: Optional[Dict[str, Any]] = None,
        file_paths: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Set needsSync=false, isUpdating=false, and updatedAt for a UML diagram.
        Optionally update diagramData and filePaths after regeneration.
        """
        try:
            obj_id = ObjectId(diagram_id)
        except (InvalidId, TypeError) as e:
            return {"success": False, "error": f"Invalid id: {str(e)}"}
        try:
            now = datetime.utcnow()
            update = {"needsSync": False, "isUpdating": False, "updatedAt": now}
            if diagram_data is not None:
                update["diagramData"] = diagram_data
            if file_paths is not None:
                update["filePaths"] = file_paths
            result = self.db.uml_diagrams.update_one(
                {"_id": obj_id},
                {"$set": update},
            )
            if result.matched_count == 0:
                return {"success": False, "error": "Diagram not found"}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def insert_documentation(
        self,
        organization_id: str,
        repository_id: str,
        branch: str,
        s3_key: str,
        title: str,
        file_paths: List[str],
        *,
        documentation_type: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Insert a textual documentation record (same idea as UML: filePaths, needsSync, isUpdating).
        Used so the worker can find docs by repo+branch and check file path overlap.
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
                "branch": branch,
                "s3Key": s3_key,
                "title": title,
                "filePaths": file_paths,
                "needsSync": False,
                "isUpdating": False,
                "createdAt": now,
                "updatedAt": now,
            }
            if documentation_type:
                document["documentationType"] = documentation_type
            if prompt:
                document["prompt"] = prompt
            result = self.db.documentation.insert_one(document)
            return {
                "success": True,
                "documentation_id": str(result.inserted_id),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

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
        file_paths: Optional[List[str]] = None,
        branch: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Insert a new UML diagram into uml_diagrams collection.

        Args:
            organization_id: Organization ID (MongoDB ObjectId string)
            repository_id: Repository ID (MongoDB ObjectId string)
            diagram_type: Type of diagram (e.g. "class")
            name: Display name (e.g. LLM-generated title)
            slug: URL-safe slug, unique per repo (e.g. "class-auth-module")
            prompt: User prompt used to generate the diagram
            diagram_data: Full diagram JSON (classes, relationships, etc.)
            s3_key: Optional S3 key for backup
            file_paths: Optional list of file paths from chunks used in generation (for sync tracking)
            branch: Branch this diagram was generated for (for worker repo+branch filtering)
            description: Optional LLM-generated detailed description for the diagram

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
                "needsSync": False,
                "isUpdating": False,
                "updatedAt": now,
                "createdAt": now,
            }
            if description is not None:
                document["description"] = description
            if s3_key:
                document["s3Key"] = s3_key
            if file_paths is not None:
                document["filePaths"] = file_paths
            if branch is not None:
                document["branch"] = branch

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

    # ---- Chat persistence (onboarding chatbot) ----
    def create_chat(
        self,
        user_id: str,
        title: str = "New chat",
        context_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new chat for a user, optionally scoped to a context (e.g. per-documentation). Returns { success, chat_id, chat }."""
        try:
            now = datetime.utcnow()
            # Initial welcome message so the chat has at least one message
            welcome = {
                "id": "welcome",
                "role": "assistant",
                "content": "Hi! I'm your AI assistant. How can I help you with onboarding today?",
                "createdAt": now,
            }
            doc = {
                "userId": user_id,
                "title": title,
                "messages": [welcome],
                "createdAt": now,
                "updatedAt": now,
            }
            if context_id is not None:
                doc["contextId"] = context_id
            result = self.db.chats.insert_one(doc)
            chat_id = str(result.inserted_id)
            return {
                "success": True,
                "chat_id": chat_id,
                "chat": self._chat_doc_to_response(doc, chat_id),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _chat_doc_to_response(self, doc: Dict[str, Any], chat_id: Optional[str] = None) -> Dict[str, Any]:
        """Convert MongoDB chat document to API response shape (id, title, messages, createdAt, updatedAt)."""
        mid = chat_id or str(doc.get("_id", ""))
        messages = []
        for m in doc.get("messages") or []:
            ts = m.get("createdAt")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat() + "Z"
            messages.append({
                "id": m.get("id", ""),
                "role": "assistant" if m.get("role") == "assistant" else "user",
                "sender": "bot" if m.get("role") == "assistant" else "user",
                "content": m.get("content", ""),
                "text": m.get("content", ""),
                "createdAt": ts,
            })
        created = doc.get("createdAt")
        updated = doc.get("updatedAt")
        if hasattr(created, "isoformat"):
            created = created.isoformat() + "Z"
        if hasattr(updated, "isoformat"):
            updated = updated.isoformat() + "Z"
        return {
            "id": mid,
            "title": doc.get("title", "New chat"),
            "messages": messages,
            "createdAt": created,
            "updatedAt": updated,
        }

    def list_chats_by_user(self, user_id: str, context_id: Optional[str] = None) -> Dict[str, Any]:
        """List chats for a user, optionally filtered by context_id (per-documentation scope). Most recently updated first."""
        try:
            query: Dict[str, Any] = {"userId": user_id}
            if context_id is not None:
                query["contextId"] = context_id
            cursor = self.db.chats.find(query).sort("updatedAt", -1)
            chats = []
            for doc in cursor:
                chat_id = str(doc["_id"])
                chats.append({
                    "id": chat_id,
                    "title": doc.get("title", "New chat"),
                    "updatedAt": doc.get("updatedAt"),
                    "messageCount": len(doc.get("messages") or []),
                })
            return {"success": True, "chats": chats}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_chat(self, chat_id: str, user_id: str) -> Dict[str, Any]:
        """Get a single chat by id; verify userId. Returns { success, chat } or { success: False }."""
        try:
            obj_id = ObjectId(chat_id)
        except (InvalidId, TypeError):
            return {"success": False, "error": "Invalid chat id"}
        doc = self.db.chats.find_one({"_id": obj_id, "userId": user_id})
        if not doc:
            return {"success": False, "error": "Chat not found"}
        return {
            "success": True,
            "chat": self._chat_doc_to_response(doc, str(doc["_id"])),
        }

    def append_chat_messages(
        self,
        chat_id: str,
        user_id: str,
        user_content: str,
        assistant_content: str,
        *,
        title_if_first_user: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append user and assistant messages; optionally set title if this is the first user message."""
        try:
            obj_id = ObjectId(chat_id)
        except (InvalidId, TypeError):
            return {"success": False, "error": "Invalid chat id"}
        try:
            doc = self.db.chats.find_one({"_id": obj_id, "userId": user_id})
            if not doc:
                return {"success": False, "error": "Chat not found"}
            messages = list(doc.get("messages") or [])
            now = datetime.utcnow()
            has_user = any(m.get("role") == "user" for m in messages)
            user_msg = {
                "id": f"user-{now.timestamp()}",
                "role": "user",
                "content": user_content,
                "createdAt": now,
            }
            assistant_msg = {
                "id": f"assistant-{now.timestamp()}",
                "role": "assistant",
                "content": assistant_content,
                "createdAt": now,
            }
            messages.append(user_msg)
            messages.append(assistant_msg)
            update: Dict[str, Any] = {"$set": {"messages": messages, "updatedAt": now}}
            if title_if_first_user and not has_user:
                update["$set"]["title"] = title_if_first_user
            self.db.chats.update_one({"_id": obj_id, "userId": user_id}, update)
            return {
                "success": True,
                "chat": self._chat_doc_to_response(
                    {**doc, "messages": messages, "title": update["$set"].get("title", doc.get("title")), "updatedAt": now},
                    chat_id,
                ),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            print("[MongoDBService] MongoDB connection closed")

