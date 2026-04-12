from fastapi import APIRouter, HTTPException
from neurocode.models.schemas import FetchRepositoryRequest
from neurocode.config import github_fetcher

router = APIRouter()


@router.post("/api/github/fetch-files")
async def fetch_repository_files(request: FetchRepositoryRequest):
    
    from neurocode.config import github_fetcher
    
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

