"""
Pydantic models for API requests
"""
from pydantic import BaseModel
from typing import Optional, List


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
    top_k: Optional[int] = 20  # Number of chunks to retrieve
    documentation_type: Optional[str] = None  # api | architecture | aiAgent | endUser | test | onboarding
    ai_agent_doc_kind: Optional[str] = None  # context | playbook | custom (when documentation_type == 'aiAgent')
    ai_agent_extra_instructions: Optional[str] = None  # Required when documentation_type == 'aiAgent'


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


class UpdateRepoBranchCommitsRequest(BaseModel):
    """Request model for storing latest commit per branch when adding/updating a repo"""
    github_token: str
    repo_full_name: str
    organization_id: str
    repository_id: str


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


class OrgContext(BaseModel):
    """Organization context for chat (search all repos in the org)"""
    org_short_id: str


class ChatMessage(BaseModel):
    """Single message in chat history"""
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    """Request model for RAG chat (organization-scoped)"""
    message: str
    history: Optional[List[ChatMessage]] = []
    org_context: Optional[OrgContext] = None


class HotZonesRecommendAreasRequest(BaseModel):
    """Request model to recommend relevant code areas for a task query."""
    org_short_id: str
    query: str
    repo_url_names: Optional[List[str]] = None  # optional scope to specific repos (urlName slugs)
    top_n: Optional[int] = 10


class GenerateUmlRequest(BaseModel):
    """Request model for RAG-based UML diagram generation (e.g. class diagram)."""
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    prompt: str
    diagram_type: str = "class"  # only "class" supported for now
    organization_id: Optional[str] = None
    organization_short_id: Optional[str] = None
    organization_name: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None
    top_k: Optional[int] = 20


class GetUmlDiagramRequest(BaseModel):
    """Request model for retrieving a UML diagram by slug or id."""
    organization_id: Optional[str] = None
    repository_id: Optional[str] = None
    slug: Optional[str] = None
    diagram_id: Optional[str] = None


class TaskCompassRequest(BaseModel):
    """Request model for Task Compass analysis."""
    org_short_id: str
    task_id: str
    task_title: str
    task_description: Optional[str] = None
    task_type: Optional[str] = None
    repositories: Optional[List[str]] = None
    top_k: Optional[int] = 15
    github_token: Optional[str] = None
    repo_full_names: Optional[List[str]] = None


class OnboardingRepoInput(BaseModel):
    """One repository for onboarding suggested-paths (RAG + LLM in Python)."""
    repo_full_name: str
    repository_name: str
    repository_id: Optional[str] = None
    github_token: str


class OnboardingSuggestedPathsRequest(BaseModel):
    """Request to generate suggested onboarding learning paths using RAG per repo."""
    organization_name: str
    organization_short_id: str
    organization_id: Optional[str] = None
    repositories: List[OnboardingRepoInput]
    branch: Optional[str] = "main"


class OnboardingPathModuleInput(BaseModel):
    """One module in an onboarding path (for RAG doc generation)."""
    id: str
    name: str
    summary_description: str
    order: int


class OnboardingPathInput(BaseModel):
    """One learning path to generate full RAG documentation for."""
    path_id: str
    title: str
    summary_description: str
    modules: List[OnboardingPathModuleInput]


class GenerateOnboardingPathDocRequest(BaseModel):
    """Request to generate full RAG documentation for one onboarding path (like generate-docs-rag)."""
    organization_name: str
    organization_short_id: str
    organization_id: Optional[str] = None
    repositories: List[OnboardingRepoInput]
    branch: Optional[str] = "main"
    path: OnboardingPathInput
