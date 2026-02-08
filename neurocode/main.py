"""
FastAPI server for NeuroCode Python backend
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from neurocode.services.github_fetcher import GitHubFetcher
from neurocode.services.code_analyzer import CodeAnalyzer
from neurocode.services.storage import StorageService
from neurocode.services.vectorizer import Vectorizer
from neurocode.services.llm_service import LLMService
from neurocode.services.s3_service import S3Service

app = FastAPI(
    title="NeuroCode Python API",
    description="Python backend service for NeuroCode",
    version="0.1.0"
)

# Configure CORS to allow requests from Next.js
# Get CORS origins from environment or use defaults
cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in cors_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
github_fetcher = GitHubFetcher()
code_analyzer = CodeAnalyzer()
storage_service = StorageService(base_dir="data")

# Initialize S3 service (will fail if AWS credentials not set)
try:
    s3_service = S3Service()
    print("[S3Service] ✓ S3 service initialized")
except ValueError as e:
    print(f"[Warning] S3 service not initialized: {e}")
    s3_service = None
except Exception as e:
    print(f"[Warning] S3 service initialization failed: {e}")
    s3_service = None

# Load Qdrant configuration from environment
qdrant_url = os.getenv("QDRANT_URL") or None
qdrant_api_key = os.getenv("QDRANT_API_KEY") or None
qdrant_local_path = os.getenv("QDRANT_LOCAL_PATH", "data/vector_db")
embedding_model = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

vectorizer = Vectorizer(
    model_name=embedding_model,
    qdrant_url=qdrant_url,
    qdrant_api_key=qdrant_api_key,
    persist_directory=qdrant_local_path if not qdrant_url else None
)

# Initialize LLM service (will fail if ANTHROPIC_API_KEY not set)
try:
    llm_service = LLMService()
    print("[LLMService] ✓ Claude initialized")
except ValueError as e:
    print(f"[Warning] LLM service not initialized: {e}")
    llm_service = None
except Exception as e:
    print(f"[Warning] LLM service initialization failed: {e}")
    llm_service = None


class FetchRepositoryRequest(BaseModel):
    """Request model for fetching repository files"""
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    path: Optional[str] = ""


class GenerateDocumentationRequest(BaseModel):
    """Request model for generating documentation"""
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    scope: Optional[str] = "repository"
    target: Optional[str] = None
    organization_id: Optional[str] = None  # MongoDB ObjectId for organization
    organization_short_id: Optional[str] = None  # Alternative: org short ID
    organization_name: Optional[str] = None  # Organization name from NeuroCode platform
    repository_id: Optional[str] = None  # MongoDB ObjectId for repository
    repository_name: Optional[str] = None  # Repository name from NeuroCode platform


class GenerateDocsRAGRequest(BaseModel):
    """Request model for RAG-based documentation generation"""
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    prompt: str  # User's query/prompt
    organization_id: Optional[str] = None
    organization_short_id: Optional[str] = None
    organization_name: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None
    top_k: Optional[int] = 10  # Number of chunks to retrieve


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "ok", "service": "neurocode-python"}


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.post("/api/github/fetch-files")
async def fetch_repository_files(request: FetchRepositoryRequest):
    """
    Fetch all files from a GitHub repository
    
    Args:
        request: FetchRepositoryRequest with:
            - github_token: GitHub access token
            - repo_full_name: Repository full name (e.g., "owner/repo")
            - branch: Branch name (default: "main")
            - path: Starting path (default: "" for root)
    
    Returns:
        List of files with path, content, and language
    """
    try:
        files = await github_fetcher.fetch_repository_files(
            repo_full_name=request.repo_full_name,
            access_token=request.github_token,
            branch=request.branch,
            path=request.path,
        )
        
        return {
            "success": True,
            "files": files,
            "count": len(files),
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch repository files: {str(e)}"
        )


@app.post("/api/generate-documentation")
async def generate_documentation(request: GenerateDocumentationRequest):
    """
    Generate documentation for a GitHub repository
    
    Full pipeline:
    1. Fetch files from GitHub
    2. Parse code (extract symbols, dependencies, calls)
    3. Chunk code (create semantic chunks for vectorization)
    4. Save results locally
    
    Args:
        request: GenerateDocumentationRequest with:
            - github_token: GitHub access token
            - repo_full_name: Repository full name (e.g., "owner/repo")
            - branch: Branch name (default: "main")
            - scope: Documentation scope (default: "repository")
            - target: Optional target path/module
    
    Returns:
        Documentation generation results with saved file paths
    """
    try:
        print("\n" + "="*60)
        print("DOCUMENTATION GENERATION PIPELINE")
        print("="*60)
        print(f"Repository: {request.repo_full_name}")
        print(f"Branch: {request.branch}")
        print(f"Scope: {request.scope}")
        print(f"Target: {request.target or 'N/A'}")
        print("="*60)
        
        # Step 1: Determine path based on scope and target
        path = ""
        if request.target:
            path = request.target
        
        # Step 2: Fetch repository files
        print("\n[Step 1/5] Fetching files from GitHub...")
        files = await github_fetcher.fetch_repository_files(
            repo_full_name=request.repo_full_name,
            access_token=request.github_token,
            branch=request.branch,
            path=path,
        )
        print(f"✓ Fetched {len(files)} files")
        
        if len(files) == 0:
            return {
                "success": False,
                "message": "No files found in repository",
                "repository": request.repo_full_name,
                "branch": request.branch,
            }
        
        # Step 3: Parse and chunk code
        print("\n[Step 2/5] Parsing code structure...")
        print("[Step 3/5] Creating semantic chunks...")
        
        # Prepare files for analyzer
        files_for_analysis = [
            {
                "path": file["path"],
                "content": file["content"],
                "language": file.get("language")
            }
            for file in files
        ]
        
        # Analyze and chunk
        analysis_results = await code_analyzer.analyze_and_chunk(
            files_for_analysis,
            chunking_strategy="hybrid"  # Use hybrid strategy for best results
        )
        
        print(f"✓ Parsed {analysis_results['metadata']['totalFunctions']} functions")
        print(f"✓ Created {analysis_results['metadata']['totalChunks']} chunks")
        
        # Step 4: Save results locally
        print("\n[Step 4/5] Saving results to local storage...")
        saved_paths = storage_service.save_analysis_results(
            repo_full_name=request.repo_full_name,
            branch=request.branch,
            results=analysis_results
        )
        
        print(f"✓ Results saved to: {saved_paths['directory']}")
        
        # Step 5: Vectorize chunks
        print("\n[Step 5/5] Vectorizing chunks...")
        # Create collection name using NeuroCode platform org and repo names
        # Format: {org_name}_{org_slug_id}_{repo_name}_{branch}
        # MUST use platform names, NOT GitHub names!
        
        # Sanitize names for collection name (remove special chars, spaces, etc.)
        def sanitize_name(name: str) -> str:
            """Sanitize name for use in collection name"""
            if not name:
                return ""
            # Replace spaces, slashes, dots, hyphens with underscores
            sanitized = name.replace(' ', '_').replace('/', '_').replace('.', '_').replace('-', '_')
            # Remove any remaining special characters except alphanumeric and underscore
            sanitized = ''.join(c if c.isalnum() or c == '_' else '_' for c in sanitized)
            # Remove multiple consecutive underscores
            sanitized = '_'.join(filter(None, sanitized.split('_')))
            return sanitized.lower()
        
        # Build collection name: {org_name}_{org_slug_id}_{repo_name}_{branch}
        # REQUIRED: Must have org_slug_id and repo_name from platform, otherwise raise error
        
        # Get org name (prefer organization_name, fallback to short_id)
        org_name_safe = ""
        if request.organization_name:
            org_name_safe = sanitize_name(request.organization_name)
        elif request.organization_short_id:
            org_name_safe = sanitize_name(request.organization_short_id)
        else:
            # If no org name or short_id, we can't create proper collection name
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: organization_name or organization_short_id must be provided for collection naming"
            )
        
        # Get org slug ID (REQUIRED - must have short_id)
        org_slug_safe = ""
        if request.organization_short_id:
            org_slug_safe = sanitize_name(request.organization_short_id)
        else:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: organization_short_id must be provided for collection naming"
            )
        
        # Get repo name (REQUIRED - must have repository_name from platform)
        repo_name_safe = ""
        if request.repository_name:
            repo_name_safe = sanitize_name(request.repository_name)
        else:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: repository_name must be provided for collection naming. Cannot use GitHub repo name."
            )
        
        # Build collection name: {org_name}_{org_slug_id}_{repo_name}_{branch}
        collection_name = f"{org_name_safe}_{org_slug_safe}_{repo_name_safe}_{request.branch}"
        
        print(f"[Collection Name] Using platform names: {collection_name}")
        print(f"  - Org Name: {org_name_safe}")
        print(f"  - Org Slug: {org_slug_safe}")
        print(f"  - Repo Name: {repo_name_safe}")
        print(f"  - Branch: {request.branch}")
        
        # Prepare metadata to link collection to org and repo
        collection_metadata = {}
        if request.organization_id:
            collection_metadata["organization_id"] = request.organization_id
        if request.organization_short_id:
            collection_metadata["organization_short_id"] = request.organization_short_id
        if request.repository_id:
            collection_metadata["repository_id"] = request.repository_id
        collection_metadata["repo_full_name"] = request.repo_full_name
        collection_metadata["branch"] = request.branch
        
        vectorization_result = vectorizer.vectorize_chunks_from_file(
            chunks_file_path=saved_paths["files"]["chunks"],
            collection_name=collection_name,
            metadata=collection_metadata
        )
        
        if vectorization_result.get("success"):
            print(f"✓ Vectorized {vectorization_result['chunks_vectorized']} chunks")
            print(f"✓ Collection: {vectorization_result['collection_name']}")
            print(f"✓ Total in collection: {vectorization_result['total_in_collection']}")
        else:
            print(f"⚠ Vectorization had issues: {vectorization_result.get('message')}")
        
        print("="*60 + "\n")
        
        # Return results
        return {
            "success": True,
            "repository": request.repo_full_name,
            "branch": request.branch,
            "scope": request.scope,
            "target": request.target,
            "files_count": len(files),
            "metadata": analysis_results["metadata"],
            "saved_paths": saved_paths,
            "vectorization": vectorization_result if vectorization_result.get("success") else None,
            "message": "Analysis complete. Results saved locally and vectorized."
        }
    except Exception as e:
        print(f"\n[ERROR] Failed to generate documentation: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate documentation: {str(e)}"
        )


@app.post("/api/generate-docs-rag")
async def generate_docs_rag(request: GenerateDocsRAGRequest):
    """
    Generate documentation using RAG (Retrieval Augmented Generation)
    
    Full pipeline (same as generate-documentation, then RAG):
    1. Fetch files from GitHub
    2. Parse code (extract symbols, dependencies, calls)
    3. Chunk code (create semantic chunks for vectorization)
    4. Save results locally
    5. Vectorize chunks (if not already done)
    6. Search vector DB for relevant chunks based on user prompt
    7. Generate documentation with Claude using retrieved chunks
    8. Return generated documentation
    """
    try:
        if not llm_service:
            raise HTTPException(
                status_code=500,
                detail="LLM service not available. Please set ANTHROPIC_API_KEY environment variable."
            )
        
        print("\n" + "="*60)
        print("RAG DOCUMENTATION GENERATION (FULL PIPELINE)")
        print("="*60)
        print(f"Repository: {request.repo_full_name}")
        print(f"Branch: {request.branch}")
        print(f"Prompt: {request.prompt}")
        print("="*60)
        
        # Step 1: Fetch repository files (same as generate-documentation)
        print("\n[Step 1/7] Fetching files from GitHub...")
        files = await github_fetcher.fetch_repository_files(
            repo_full_name=request.repo_full_name,
            access_token=request.github_token,
            branch=request.branch,
            path="",
        )
        print(f"✓ Fetched {len(files)} files")
        
        if len(files) == 0:
            return {
                "success": False,
                "message": "No files found in repository",
                "repository": request.repo_full_name,
                "branch": request.branch,
            }
        
        # Step 2 & 3: Parse and chunk code (same as generate-documentation)
        print("\n[Step 2/7] Parsing code structure...")
        print("[Step 3/7] Creating semantic chunks...")
        
        # Prepare files for analyzer
        files_for_analysis = [
            {
                "path": file["path"],
                "content": file["content"],
                "language": file.get("language")
            }
            for file in files
        ]
        
        # Analyze and chunk
        analysis_results = await code_analyzer.analyze_and_chunk(
            files_for_analysis,
            chunking_strategy="hybrid"  # Use hybrid strategy for best results
        )
        
        print(f"✓ Parsed {analysis_results['metadata']['totalFunctions']} functions")
        print(f"✓ Created {analysis_results['metadata']['totalChunks']} chunks")
        
        # Step 4: Save results locally (same as generate-documentation)
        print("\n[Step 4/7] Saving results to local storage...")
        saved_paths = storage_service.save_analysis_results(
            repo_full_name=request.repo_full_name,
            branch=request.branch,
            results=analysis_results
        )
        print(f"✓ Results saved to: {saved_paths['directory']}")
        
        # Step 5: Vectorize chunks (same as generate-documentation)
        print("\n[Step 5/7] Vectorizing chunks...")
        # Build collection name using NeuroCode platform org and repo names
        def sanitize_name(name: str) -> str:
            if not name:
                return ""
            sanitized = name.replace(' ', '_').replace('/', '_').replace('.', '_').replace('-', '_')
            sanitized = ''.join(c if c.isalnum() or c == '_' else '_' for c in sanitized)
            sanitized = '_'.join(filter(None, sanitized.split('_')))
            return sanitized.lower()
        
        # Build collection name
        if not request.organization_short_id:
            raise HTTPException(
                status_code=400,
                detail="organization_short_id is required for collection naming"
            )
        if not request.repository_name:
            raise HTTPException(
                status_code=400,
                detail="repository_name is required for collection naming"
            )
        
        org_name_safe = sanitize_name(request.organization_name or request.organization_short_id)
        org_slug_safe = sanitize_name(request.organization_short_id)
        repo_name_safe = sanitize_name(request.repository_name)
        collection_name = f"{org_name_safe}_{org_slug_safe}_{repo_name_safe}_{request.branch}"
        
        # Prepare metadata to link collection to org and repo
        collection_metadata = {}
        if request.organization_id:
            collection_metadata["organization_id"] = request.organization_id
        if request.organization_short_id:
            collection_metadata["organization_short_id"] = request.organization_short_id
        if request.repository_id:
            collection_metadata["repository_id"] = request.repository_id
        collection_metadata["repo_full_name"] = request.repo_full_name
        collection_metadata["branch"] = request.branch
        
        # Vectorize chunks (will create collection if doesn't exist, or update if exists)
        vectorization_result = vectorizer.vectorize_chunks_from_file(
            chunks_file_path=saved_paths["files"]["chunks"],
            collection_name=collection_name,
            metadata=collection_metadata
        )
        
        if vectorization_result.get("success"):
            print(f"✓ Vectorized {vectorization_result['chunks_vectorized']} chunks")
            print(f"✓ Collection: {vectorization_result['collection_name']}")
        else:
            print(f"⚠ Vectorization had issues: {vectorization_result.get('message')}")
        
        # Step 6: Search vector DB for relevant chunks based on prompt
        print(f"\n[Step 6/7] Searching vector DB for relevant chunks...")
        print(f"Query: {request.prompt}")
        
        # Search vector DB for relevant chunks
        search_results = vectorizer.search(
            collection_name=collection_name,
            query=request.prompt,
            top_k=request.top_k or 10
        )
        
        if not search_results:
            raise HTTPException(
                status_code=404,
                detail=f"No chunks found in collection '{collection_name}'"
            )
        
        print(f"✓ Found {len(search_results)} relevant chunks")
        
        # Step 7: Generate documentation using LLM
        print(f"\n[Step 7/7] Generating documentation with Claude...")
        documentation = llm_service.generate_documentation(
            prompt=request.prompt,
            context_chunks=search_results,
            repo_name=request.repository_name or request.repo_full_name
        )
        
        print(f"✓ Documentation generated ({len(documentation)} characters)")
        
        # Extract title from documentation content
        def extract_title(doc_content: str, prompt: str) -> str:
            """Extract a title from documentation content"""
            import re
            
            # Try to find the first heading (# or ##)
            heading_match = re.search(r'^#+\s+(.+)$', doc_content, re.MULTILINE)
            if heading_match:
                title = heading_match.group(1).strip()
                # Remove markdown formatting from title
                title = re.sub(r'\*\*|__|`', '', title)
                if len(title) > 0 and len(title) <= 100:
                    return title
            
            # If no heading, try to extract first sentence from first paragraph
            lines = doc_content.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('```'):
                    # Remove markdown formatting
                    line = re.sub(r'\*\*|__|`|#', '', line)
                    # Get first sentence (up to 100 chars)
                    sentences = re.split(r'[.!?]\s+', line)
                    if sentences and sentences[0]:
                        title = sentences[0].strip()
                        if len(title) > 0:
                            return title[:100]
            
            # Fallback: use a shortened version of the prompt
            if prompt:
                # Take first 60 chars of prompt
                title = prompt[:60].strip()
                if len(title) < len(prompt):
                    title += "..."
                return title
            
            return "Documentation"
        
        doc_title = extract_title(documentation, request.prompt)
        print(f"✓ Extracted title: {doc_title}")
        
        # Step 8: Save documentation locally (for backup/reference)
        print(f"\n[Step 8/9] Saving documentation to local storage...")
        doc_metadata = {
            "collection_name": collection_name,
            "chunks_used": len(search_results),
            "chunks": [
                {
                    "file_path": chunk.get("metadata", {}).get("file_path", ""),
                    "function_name": chunk.get("metadata", {}).get("function_name", ""),
                    "score": chunk.get("score", 0)
                }
                for chunk in search_results
            ]
        }
        
        doc_saved_paths = storage_service.save_documentation(
            repo_full_name=request.repo_full_name,
            branch=request.branch,
            prompt=request.prompt,
            documentation=documentation,
            metadata=doc_metadata
        )
        
        print(f"✓ Documentation saved to: {doc_saved_paths['documentation_file']}")
        
        # Step 9: Upload documentation to S3
        s3_result = None
        s3_key = None
        if s3_service:
            print(f"\n[Step 9/9] Uploading documentation to S3...")
            
            # Generate S3 key
            # Use organization_id and repository_id from request
            if not request.organization_id or not request.repository_id:
                print("⚠ Missing organization_id or repository_id, skipping S3 upload")
            else:
                # Generate unique documentation ID (use timestamp)
                from datetime import datetime
                import json
                doc_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                s3_key = s3_service.generate_s3_key(
                    organization_id=request.organization_id,
                    repository_id=request.repository_id,
                    branch=request.branch,
                    scope="custom",  # RAG docs are always custom
                    documentation_id=doc_id,
                    file_extension="json"  # Store as JSON
                )
                
                # Wrap documentation in JSON structure
                documentation_json = {
                    "content": documentation,  # Raw documentation output
                    "generated_at": datetime.now().isoformat(),
                    "prompt": request.prompt,
                    "repository": request.repo_full_name,
                    "branch": request.branch,
                    "scope": "custom"
                }
                
                # Convert to JSON string
                documentation_json_str = json.dumps(documentation_json, indent=2)
                
                # Upload to S3
                s3_result = s3_service.upload_documentation(
                    content=documentation_json_str,
                    s3_key=s3_key,
                    content_type="application/json"
                )
                
                if s3_result.get("success"):
                    print(f"✓ Documentation uploaded to S3: {s3_result['s3_key']}")
                    print(f"  Size: {s3_result['content_size']} bytes")
                else:
                    print(f"⚠ S3 upload failed: {s3_result.get('error')}")
        else:
            print(f"\n[Step 9/9] S3 service not available, skipping S3 upload")
        
        print("="*60 + "\n")
        
        # Return results
        result = {
            "success": True,
            "prompt": request.prompt,
            "title": doc_title,  # Include extracted title
            "repository": request.repo_full_name,
            "branch": request.branch,
            "collection_name": collection_name,
            "chunks_used": len(search_results),
            "metadata": analysis_results["metadata"],
            "saved_paths": doc_saved_paths,
            "chunks": doc_metadata["chunks"]
        }
        
        # Include S3 information if upload was successful
        if s3_result and s3_result.get("success"):
            result["s3"] = {
                "s3_key": s3_result["s3_key"],
                "s3_bucket": s3_service.bucket_name,  # Use bucket name from service
                "s3_url": s3_result["s3_url"],
                "content_size": s3_result["content_size"]
            }
            # Don't include full documentation in response if S3 upload succeeded
            # Frontend will fetch from S3 using the key
        else:
            # If S3 upload failed, include documentation in response as fallback
            result["documentation"] = documentation
        
        return result
        
    except HTTPException as e:
        print(f"[ERROR] RAG generation failed: {e.detail}")
        raise e
    except Exception as e:
        print(f"[ERROR] RAG generation failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate documentation: {str(e)}"
        )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("ENV", "development") == "development"
    
    uvicorn.run(
        "neurocode.main:app",
        host=host,
        port=port,
        reload=reload
    )

