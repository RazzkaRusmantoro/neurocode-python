"""
ARQ background worker: processes index-repo jobs (RAG pipeline).
Run as: python -m neurocode.worker
"""
import os
from typing import Any, Dict, Optional

import arq
from arq.worker import create_worker
from dotenv import load_dotenv

load_dotenv()

from neurocode.services.index_pipeline import run_index_pipeline


async def index_repo_job(
    ctx: Dict[str, Any],
    *,
    github_token: str,
    repo_full_name: str,
    branch: str = "main",
    target: Optional[str] = None,
    organization_id: Optional[str] = None,
    organization_short_id: Optional[str] = None,
    organization_name: Optional[str] = None,
    repository_id: Optional[str] = None,
    repository_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    ARQ job: run the RAG index pipeline for a repository.
    All arguments (except ctx) must be JSON-serializable.
    """
    print(f"[Worker] Starting index job: {repo_full_name} @ {branch}")
    result = await run_index_pipeline(
        github_token=github_token,
        repo_full_name=repo_full_name,
        branch=branch,
        target=target,
        organization_id=organization_id,
        organization_short_id=organization_short_id,
        organization_name=organization_name,
        repository_id=repository_id,
        repository_name=repository_name,
    )
    print(f"[Worker] Index job finished: success={result.get('success')}")
    return result


async def startup(ctx: Dict[str, Any]) -> None:
    """ARQ worker startup (optional)."""
    print("[Worker] ARQ worker started.")


async def shutdown(ctx: Dict[str, Any]) -> None:
    """ARQ worker shutdown (optional)."""
    print("[Worker] ARQ worker shutting down.")


def get_redis_settings() -> arq.connections.RedisSettings:
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    return arq.connections.RedisSettings.from_dsn(url)


class WorkerSettings:
    functions = [index_repo_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()


def main():
    """Entrypoint for running the worker. Worker owns the event loop (no asyncio.run)."""
    worker = create_worker(WorkerSettings)
    worker.run()


async def enqueue_index_repo(
    github_token: str,
    repo_full_name: str,
    branch: str = "main",
    target: Optional[str] = None,
    organization_id: Optional[str] = None,
    organization_short_id: Optional[str] = None,
    organization_name: Optional[str] = None,
    repository_id: Optional[str] = None,
    repository_name: Optional[str] = None,
) -> Optional[str]:
    """
    Enqueue an index-repo job. Returns job_id if enqueued, None on failure.
    """
    try:
        pool = await arq.create_pool(get_redis_settings())
        job = await pool.enqueue_job(
            "index_repo_job",
            github_token=github_token,
            repo_full_name=repo_full_name,
            branch=branch,
            target=target,
            organization_id=organization_id,
            organization_short_id=organization_short_id,
            organization_name=organization_name,
            repository_id=repository_id,
            repository_name=repository_name,
        )
        await pool.close()
        return job.job_id if job else None
    except Exception as e:
        print(f"[Queue] Failed to enqueue index job: {e}")
        return None


if __name__ == "__main__":
    main()
