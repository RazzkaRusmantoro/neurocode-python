"""
Pydantic models for API requests
"""
from pydantic import BaseModel
from typing import Optional


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


class GetDocumentationRequest(BaseModel):
    """Request model for retrieving documentation from S3"""
    s3_key: str
    s3_bucket: Optional[str] = None


class GenerateVisualTreeRequest(BaseModel):
    """Request model for generating a visual repository tree"""
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    organization_id: Optional[str] = None
    organization_short_id: Optional[str] = None
    organization_name: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None


class QueueIndexRequest(BaseModel):
    """Request model for queuing a repo index job (background RAG pipeline)"""
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    target: Optional[str] = None
    organization_id: Optional[str] = None
    organization_short_id: Optional[str] = None
    organization_name: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None


class AnalyzePullRequestRequest(BaseModel):
    """Request model for analyzing a pull request"""
    github_token: str
    repo_full_name: str
    pr_number: int
    organization_id: Optional[str] = None
    organization_short_id: Optional[str] = None
    organization_name: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None
