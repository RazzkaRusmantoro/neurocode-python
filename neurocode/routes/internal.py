"""
Internal API routes (e.g. queue index job). Protect with INTERNAL_API_KEY in production.
"""
import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Depends

from neurocode.models.schemas import QueueIndexRequest
from neurocode.worker import enqueue_index_repo


router = APIRouter(prefix="/internal", tags=["internal"])


def require_internal_key(x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key")) -> None:
    """Optional: require X-Internal-Key header to match INTERNAL_API_KEY env."""
    key = os.getenv("INTERNAL_API_KEY")
    if not key:
        return  # No key set = no check
    if x_internal_key != key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Internal-Key")


@router.post("/queue-index")
async def queue_index(request: QueueIndexRequest, _: None = Depends(require_internal_key)):
    """
    Enqueue a background job to run the RAG index pipeline for a repository.
    Next.js (or other services) can call this after adding a repo.
    """
    print(f"[queue-index] Received request: repo_full_name={request.repo_full_name} repository_id={request.repository_id}")
    job_id = await enqueue_index_repo(
        github_token=request.github_token,
        repo_full_name=request.repo_full_name,
        branch=request.branch or "main",
        target=request.target,
        organization_id=request.organization_id,
        organization_short_id=request.organization_short_id,
        organization_name=request.organization_name,
        repository_id=request.repository_id,
        repository_name=request.repository_name,
    )
    if job_id is None:
        print(f"[queue-index] Failed to enqueue: repo_full_name={request.repo_full_name}")
        raise HTTPException(status_code=503, detail="Failed to enqueue index job")
    print(f"[queue-index] Enqueued job_id={job_id} repo_full_name={request.repo_full_name} repository_id={request.repository_id}")
    return {"enqueued": True, "job_id": job_id}
