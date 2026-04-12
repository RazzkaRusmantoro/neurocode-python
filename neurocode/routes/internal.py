import os
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Depends

from neurocode.models.schemas import QueueIndexRequest, QueueKGBuildRequest, UpdateRepoBranchCommitsRequest
from neurocode.worker import enqueue_build_kg, enqueue_index_repo
from neurocode.config import github_fetcher, mongodb_service


router = APIRouter(prefix="/internal", tags=["internal"])


def require_internal_key(x_internal_key: Optional[str] = Header(None, alias="X-Internal-Key")) -> None:
    
    key = os.getenv("INTERNAL_API_KEY")
    if not key:
        return                         
    if x_internal_key != key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Internal-Key")


def _use_default_branch(branch: Optional[str]) -> bool:
    
    if not branch or not branch.strip():
        return True
    b = branch.strip().lower()
    return b in ("main", "master")


@router.post("/queue-index")
async def queue_index(request: QueueIndexRequest, _: None = Depends(require_internal_key)):
    
    print(f"[queue-index] Received request: repo_full_name={request.repo_full_name} repository_id={request.repository_id}")

                                                                                              
    if mongodb_service and request.organization_id and request.repository_id:
        try:
            branch_commits = await github_fetcher.list_branches_with_latest_commit(
                request.repo_full_name,
                request.github_token,
            )
            if branch_commits:
                mongodb_service.upsert_repository_branch_commits(
                    organization_id=request.organization_id,
                    repository_id=request.repository_id,
                    branch_latest_commits=branch_commits,
                    repo_full_name=request.repo_full_name,
                )
                print(f"[queue-index] Stored branch commits for {len(branch_commits)} branch(es)")
            else:
                print(f"[queue-index] No branches returned from GitHub for {request.repo_full_name}")
        except Exception as e:
            print(f"[queue-index] Failed to store branch commits (continuing to enqueue): {e}")

    branch = request.branch or "main"
    if _use_default_branch(request.branch):
        resolved = await github_fetcher.get_default_branch(request.repo_full_name, request.github_token)
        if resolved:
            branch = resolved
            print(f"[queue-index] Using repo default branch: {branch}")
    job_id = await enqueue_index_repo(
        github_token=request.github_token,
        repo_full_name=request.repo_full_name,
        branch=branch,
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


@router.post("/queue-kg-build")
async def queue_kg_build(request: QueueKGBuildRequest, _: None = Depends(require_internal_key)):
    
    from neurocode.services.neo4j_service import Neo4jService
    import redis as _redis

    print(
        f"[queue-kg-build] repo_full_name={request.repo_full_name} repo_id={request.repo_id}",
        flush=True,
    )

                                                                                 
    try:
        neo4j = Neo4jService()
        try:
            already_built = await neo4j.graph_exists(request.repo_id)
        finally:
            await neo4j.close()
        if already_built:
            print(f"[queue-kg-build] Graph already exists in Neo4j — skipping.", flush=True)
            return {"status": "already_built"}
    except Exception:
        pass                                                 

                                                                                
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    lock_key = f"kg_building:{request.repo_id}"
    try:
        r = _redis.from_url(redis_url, decode_responses=True)
        already_queued = not r.set(lock_key, "1", nx=True, ex=900)                               
        r.close()
        if already_queued:
            print(f"[queue-kg-build] Build already in-flight — skipping duplicate.", flush=True)
            return {"status": "queued", "job_id": "in-flight"}
    except Exception:
        pass                                             

    branch = request.branch or "main"
    if not branch.strip() or branch.strip().lower() in ("main", "master"):
        resolved = await github_fetcher.get_default_branch(
            request.repo_full_name, request.github_token
        )
        if resolved:
            branch = resolved

    job_id = await enqueue_build_kg(
        github_token=request.github_token,
        repo_full_name=request.repo_full_name,
        repo_id=request.repo_id,
        branch=branch,
    )
    if job_id is None:
        raise HTTPException(status_code=503, detail="Failed to enqueue KG build job")

    print(f"[queue-kg-build] Enqueued job_id={job_id}", flush=True)
    return {"status": "queued", "job_id": job_id}


@router.post("/update-repo-branch-commits")
async def update_repo_branch_commits(
    request: UpdateRepoBranchCommitsRequest,
    _: None = Depends(require_internal_key),
):
    
    if not mongodb_service:
        raise HTTPException(status_code=503, detail="MongoDB service not available")
    branch_commits = await github_fetcher.list_branches_with_latest_commit(
        request.repo_full_name,
        request.github_token,
    )
    if not branch_commits:
        return {
            "success": False,
            "message": "No branches found or GitHub request failed",
            "branch_latest_commits": {},
        }
    result = mongodb_service.upsert_repository_branch_commits(
        organization_id=request.organization_id,
        repository_id=request.repository_id,
        branch_latest_commits=branch_commits,
        repo_full_name=request.repo_full_name,
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to store branch commits"))
    return {
        "success": True,
        "branch_latest_commits": branch_commits,
        "branch_count": result.get("branch_count", 0),
    }
