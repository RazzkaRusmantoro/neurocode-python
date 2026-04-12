from pydantic import BaseModel
from typing import Optional, List


class FetchRepositoryRequest(BaseModel):
    
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    path: Optional[str] = ""


class GenerateDocumentationRequest(BaseModel):
    
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    scope: Optional[str] = "repository"
    target: Optional[str] = None
    organization_id: Optional[str] = None                                     
    organization_short_id: Optional[str] = None                             
    organization_name: Optional[str] = None                                             
    repository_id: Optional[str] = None                                   
    repository_name: Optional[str] = None                                           


class GenerateDocsRAGRequest(BaseModel):
    
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    prompt: str                       
    organization_id: Optional[str] = None
    organization_short_id: Optional[str] = None
    organization_name: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None
    top_k: Optional[int] = 20                                
    documentation_type: Optional[str] = None                                                              
    ai_agent_doc_kind: Optional[str] = None                                                                      
    ai_agent_extra_instructions: Optional[str] = None                                                 


class GetDocumentationRequest(BaseModel):
    
    s3_key: str
    s3_bucket: Optional[str] = None


class GenerateVisualTreeRequest(BaseModel):
    
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    organization_id: Optional[str] = None
    organization_short_id: Optional[str] = None
    organization_name: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None


class QueueIndexRequest(BaseModel):
    
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
    
    github_token: str
    repo_full_name: str
    organization_id: str
    repository_id: str


class QueueKGBuildRequest(BaseModel):
    
    github_token: str
    repo_full_name: str
    repo_id: str                                                                         
    branch: Optional[str] = "main"


class AnalyzePullRequestRequest(BaseModel):
    
    github_token: str
    repo_full_name: str
    pr_number: int
    organization_id: Optional[str] = None
    organization_short_id: Optional[str] = None
    organization_name: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None


class OrgContext(BaseModel):
    
    org_short_id: str


class ChatMessage(BaseModel):
    
    role: str                        
    content: str


class ChatRequest(BaseModel):
    
    message: str
    history: Optional[List[ChatMessage]] = []
    org_context: Optional[OrgContext] = None
    documentation_content: Optional[str] = None                                              


class CreateChatRequest(BaseModel):
    
    user_id: str
    title: Optional[str] = "New chat"
    context_id: Optional[str] = None                                                                         


class SendMessageRequest(BaseModel):
    
    message: str
    user_id: str
    documentation_content: Optional[str] = None                                              


class HotZonesRecommendAreasRequest(BaseModel):
    
    org_short_id: str
    query: str
    repo_url_names: Optional[List[str]] = None                                                    
    top_n: Optional[int] = 10


class GenerateUmlRequest(BaseModel):
    
    github_token: str
    repo_full_name: str
    branch: Optional[str] = "main"
    prompt: str
    diagram_type: str = "class"                                  
    organization_id: Optional[str] = None
    organization_short_id: Optional[str] = None
    organization_name: Optional[str] = None
    repository_id: Optional[str] = None
    repository_name: Optional[str] = None
    top_k: Optional[int] = 20


class GetUmlDiagramRequest(BaseModel):
    
    organization_id: Optional[str] = None
    repository_id: Optional[str] = None
    slug: Optional[str] = None
    diagram_id: Optional[str] = None


class TaskCompassRequest(BaseModel):
    
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
    
    repo_full_name: str
    repository_name: str
    repository_id: Optional[str] = None
    github_token: str


class OnboardingSuggestedPathsRequest(BaseModel):
    
    organization_name: str
    organization_short_id: str
    organization_id: Optional[str] = None
    repositories: List[OnboardingRepoInput]
    branch: Optional[str] = "main"


class OnboardingPathModuleInput(BaseModel):
    
    id: str
    name: str
    summary_description: str
    order: int


class OnboardingPathInput(BaseModel):
    
    path_id: str
    title: str
    summary_description: str
    modules: List[OnboardingPathModuleInput]


class GenerateOnboardingPathDocRequest(BaseModel):
    
    organization_name: str
    organization_short_id: str
    organization_id: Optional[str] = None
    repositories: List[OnboardingRepoInput]
    branch: Optional[str] = "main"
    path: OnboardingPathInput
