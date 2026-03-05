"""
Task Compass route: analyzes a task against indexed code to produce
structured context for developers (summary, caution areas, relevant files,
entry points, ownership).
"""

from fastapi import APIRouter, HTTPException

from neurocode.models.schemas import TaskCompassRequest
from neurocode.config import vectorizer, llm_service
from neurocode.services.task_compass_service import analyze_task


router = APIRouter(prefix="/task-compass", tags=["task-compass"])


@router.post("/analyze")
async def analyze(request: TaskCompassRequest) -> dict:
    """
    Analyze a task: search the org's indexed repos for relevant code, then
    ask the LLM to produce structured compass context.
    """
    if not llm_service:
        raise HTTPException(
            status_code=503,
            detail="LLM service not configured (ANTHROPIC_API_KEY)",
        )

    org_short_id = (request.org_short_id or "").strip()
    if not org_short_id:
        raise HTTPException(status_code=400, detail="org_short_id is required")

    task_title = (request.task_title or "").strip()
    if not task_title:
        raise HTTPException(status_code=400, detail="task_title is required")

    result = await analyze_task(
        vectorizer=vectorizer,
        llm_service=llm_service,
        org_short_id=org_short_id,
        task_id=request.task_id,
        task_title=task_title,
        task_description=request.task_description,
        task_type=request.task_type,
        repositories=request.repositories,
        top_k=request.top_k or 15,
        github_token=request.github_token,
        repo_full_names=request.repo_full_names,
    )

    return result
