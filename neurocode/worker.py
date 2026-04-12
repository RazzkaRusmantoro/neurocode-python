import os
from typing import Any, Dict, List, Optional, Set

import arq
from arq import cron
from arq.worker import create_worker
from dotenv import load_dotenv

load_dotenv()

from neurocode.config import github_fetcher, mongodb_service, vectorizer
from neurocode.services.index_pipeline import build_collection_name, run_index_pipeline
from neurocode.services.kg_pipeline import build_kg_for_repo
from neurocode.services.neo4j_service import Neo4jService
from neurocode.services.doc_regeneration import (
    regenerate_documentation,
    regenerate_uml_diagram,
)


                                                                                 

def _qdrant_collection_count(collection_name: str) -> int:
    
    try:
        vdb = getattr(vectorizer, "vector_db", None)                                 
        if vdb and hasattr(vdb, "get_collection_count"):
            result = vdb.get_collection_count(collection_name)
            return result if isinstance(result, int) else -1
    except Exception:
        pass
    return -1


async def _neo4j_graph_exists(repo_id: str) -> bool:
    
    try:
        neo4j = Neo4jService()
        try:
            return await neo4j.graph_exists(repo_id)
        finally:
            await neo4j.close()
    except Exception:
        return False


                                                                                 

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
    
    print(
        f"[Worker] ▶ index_repo_job: {repo_full_name} branch={branch} repository_id={repository_id}",
        flush=True,
    )

                                                                                 
    rag_result: Dict[str, Any] = {}
    skip_rag = False

    if organization_short_id and repository_name:
        collection_name = build_collection_name(
            organization_name, organization_short_id, repository_name, branch
        )
        count = _qdrant_collection_count(collection_name)
        if count > 0:
            print(
                f"[Worker] Qdrant collection '{collection_name}' already has {count} vectors — "
                "skipping RAG pipeline.",
                flush=True,
            )
            skip_rag = True

    if not skip_rag:
        rag_result = await run_index_pipeline(
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
        print(
            f"[Worker] RAG pipeline finished: success={rag_result.get('success')}",
            flush=True,
        )

                                                                                
                                                                              
    kg_result: Dict[str, Any] = {}
    if repository_id:
        if await _neo4j_graph_exists(repository_id):
            print(
                f"[Worker] Neo4j graph already exists for repo_id={repository_id} — "
                "skipping KG build.",
                flush=True,
            )
        else:
            print(f"[Worker] Building knowledge graph for repo_id={repository_id}...", flush=True)
            try:
                kg_result = await build_kg_for_repo(
                    repo_id=repository_id,
                    repo_full_name=repo_full_name,
                    github_token=github_token,
                    branch=branch,
                )
            except Exception as e:
                print(f"[Worker] KG build failed: {e}", flush=True)
                kg_result = {"success": False, "error": str(e)}
    else:
        print("[Worker] No repository_id — skipping KG build.", flush=True)

    print(
        f"[Worker] ✓ index_repo_job done: {repo_full_name} "
        f"skip_rag={skip_rag} kg_success={kg_result.get('success', 'skipped')}",
        flush=True,
    )
    return {
        "rag": rag_result or {"skipped": True},
        "kg": kg_result or {"skipped": True},
    }


async def build_kg_job(
    ctx: Dict[str, Any],
    *,
    github_token: str,
    repo_full_name: str,
    repo_id: str,
    branch: str = "main",
) -> Dict[str, Any]:
    
    print(f"[Worker] ▶ build_kg_job: {repo_full_name} repo_id={repo_id}", flush=True)
    try:
        result = await build_kg_for_repo(
            repo_id=repo_id,
            repo_full_name=repo_full_name,
            github_token=github_token,
            branch=branch,
        )
        print(f"[Worker] ✓ build_kg_job done: success={result.get('success')}", flush=True)
        return result
    except Exception as e:
        print(f"[Worker] build_kg_job failed: {e}", flush=True)
        return {"success": False, "error": str(e)}


async def sync_docs_job(ctx: Dict[str, Any]) -> Dict[str, Any]:
    
    if not mongodb_service:
        return {"success": False, "error": "MongoDB not available"}
    list_result = mongodb_service.list_all_repository_branch_commits()
    if not list_result.get("success"):
        return {"success": False, "error": list_result.get("error", "Failed to list repos")}
    repos = list_result.get("repos") or []
    if not repos:
        return {"success": True, "repos_processed": 0, "message": "No tracked repos"}

    pool = ctx.get("redis_pool")
    total_docs_enqueued = 0
    total_uml_enqueued = 0
    repos_processed = 0

    for doc in repos:
        organization_id = doc.get("organizationId")
        repository_id = doc.get("repositoryId")
        repo_full_name = (doc.get("repoFullName") or "").strip()
        if not organization_id or not repository_id or not repo_full_name:
            continue
        token_result = mongodb_service.get_github_token_for_repo(organization_id, repository_id)
        if not token_result.get("success"):
            print(f"[Sync] No GitHub token for repo {repo_full_name}, skipping", flush=True)
            continue
        token = token_result["token"]
        try:
            current_branches = await github_fetcher.list_branches_with_latest_commit(
                repo_full_name, token
            )
        except Exception as e:
            print(f"[Sync] list_branches failed for {repo_full_name}: {e}", flush=True)
            continue
        stored = doc.get("branchLatestCommits") or {}
        names_result = mongodb_service.get_organization_and_repo_for_collection(
            organization_id, repository_id
        )
        if not names_result.get("success"):
            print(f"[Sync] Org/repo names not found for {repo_full_name}, skipping", flush=True)
            continue
        org_name = names_result.get("organization_name")
        org_short = names_result.get("organization_short_id")
        repo_name = names_result.get("repository_name")

        branches_with_new_commits: List[str] = []
        for branch, current_sha in current_branches.items():
            if stored.get(branch) != current_sha:
                branches_with_new_commits.append(branch)

        for branch in branches_with_new_commits:
            current_sha = current_branches[branch]
            stored_sha = (stored.get(branch) or "").strip()
            try:
                await run_index_pipeline(
                    github_token=token,
                    repo_full_name=repo_full_name,
                    branch=branch,
                    organization_id=organization_id,
                    organization_short_id=org_short,
                    organization_name=org_name,
                    repository_id=repository_id,
                    repository_name=repo_name,
                )
            except Exception as e:
                print(f"[Sync] index_pipeline failed {repo_full_name} branch={branch}: {e}", flush=True)
                continue

            if stored_sha:
                try:
                    changed_paths: List[str] = await github_fetcher.get_changed_file_paths(
                        repo_full_name, token, stored_sha, current_sha
                    )
                except Exception as e:
                    print(f"[Sync] get_changed_file_paths failed: {e}", flush=True)
                    changed_paths = []
            else:
                changed_paths = []

            changed_set: Set[str] = set(changed_paths)

            docs_result = mongodb_service.list_documentations_by_repository_and_branch(
                repository_id, branch
            )
            uml_result = mongodb_service.list_uml_diagrams_by_repository_and_branch(
                repository_id, branch
            )
            doc_list = docs_result.get("documentations", []) if docs_result.get("success") else []
            uml_list = uml_result.get("uml_diagrams", []) if uml_result.get("success") else []

            affected_doc_ids: List[str] = []
            for d in doc_list:
                file_paths = d.get("filePaths") or []
                if not isinstance(file_paths, list):
                    file_paths = []
                if changed_set and set(file_paths) & changed_set:
                    affected_doc_ids.append(str(d.get("_id", "")))
            affected_uml_ids: List[str] = []
            for u in uml_list:
                file_paths = u.get("filePaths") or []
                if not isinstance(file_paths, list):
                    file_paths = []
                if changed_set and set(file_paths) & changed_set:
                    affected_uml_ids.append(str(u.get("_id", "")))

            if affected_doc_ids:
                mongodb_service.set_documentations_needs_sync(affected_doc_ids)
            if affected_uml_ids:
                mongodb_service.set_uml_diagrams_needs_sync(affected_uml_ids)

            if pool:
                for did in affected_doc_ids:
                    await pool.enqueue_job("regenerate_documentation_job", documentation_id=did)
                    total_docs_enqueued += 1
                for uid in affected_uml_ids:
                    await pool.enqueue_job("regenerate_uml_diagram_job", diagram_id=uid)
                    total_uml_enqueued += 1

        mongodb_service.upsert_repository_branch_commits(
            organization_id,
            repository_id,
            current_branches,
            repo_full_name=repo_full_name,
        )
        repos_processed += 1

    return {
        "success": True,
        "repos_processed": repos_processed,
        "documentations_enqueued": total_docs_enqueued,
        "uml_diagrams_enqueued": total_uml_enqueued,
    }


async def regenerate_documentation_job(
    ctx: Dict[str, Any],
    *,
    documentation_id: str,
) -> Dict[str, Any]:
    
    result = await regenerate_documentation(documentation_id)
    return result


async def regenerate_uml_diagram_job(
    ctx: Dict[str, Any],
    *,
    diagram_id: str,
) -> Dict[str, Any]:
    
    result = await regenerate_uml_diagram(diagram_id)
    return result


async def startup(ctx: Dict[str, Any]) -> None:
    
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        ctx["redis_pool"] = await arq.create_pool(get_redis_settings())
    except Exception as e:
        print(f"[Worker] Warning: could not create Redis pool for enqueue: {e}", flush=True)
        ctx["redis_pool"] = None
    print("", flush=True)
    print("=" * 70, flush=True)
    print("[Worker] ARQ worker started. Jobs: index_repo_job, sync_docs_job, regenerate_documentation_job, regenerate_uml_diagram_job.", flush=True)
    print(f"[Worker] REDIS_URL = {_mask_redis_url(redis_url)}", flush=True)
    print("", flush=True)
    print("  >>> If you add a repo and NOTHING appears here, the job is going to", flush=True)
    print("      a DIFFERENT Redis (e.g. your app is calling the deployed Python API).", flush=True)
    print("      To see jobs in THIS terminal:", flush=True)
    print("        1. Run the Python API locally:  python run.py", flush=True)
    print("        2. In Next.js .env set:  PYTHON_SERVICE_URL=http://localhost:8000", flush=True)
    print("        3. Use the SAME REDIS_URL for both API and this worker (e.g. localhost).", flush=True)
    print("=" * 70, flush=True)
    print("", flush=True)


async def shutdown(ctx: Dict[str, Any]) -> None:
    
    pool = ctx.get("redis_pool")
    if pool:
        await pool.close()
        ctx["redis_pool"] = None
    print("[Worker] ARQ worker shutting down.", flush=True)


def get_redis_settings() -> arq.connections.RedisSettings:
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    return arq.connections.RedisSettings.from_dsn(url)


def _mask_redis_url(url: str) -> str:
    
    if "@" in url and "://" in url:
        try:
            pre, rest = url.split("://", 1)
            if "@" in rest:
                _, host_part = rest.split("@", 1)
                return f"{pre}://***@{host_part}"
        except Exception:
            pass
    return url


def _cron_jobs() -> list:
    
    return [cron(sync_docs_job, minute={0, 15, 30, 45})]


class WorkerSettings:
    functions = [
        index_repo_job,
        build_kg_job,
        sync_docs_job,
        regenerate_documentation_job,
        regenerate_uml_diagram_job,
    ]
    cron_jobs = _cron_jobs()
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = get_redis_settings()


def main():
    
    worker = create_worker(WorkerSettings)
    worker.run()


async def enqueue_build_kg(
    github_token: str,
    repo_full_name: str,
    repo_id: str,
    branch: str = "main",
) -> Optional[str]:
    
    try:
        pool = await arq.create_pool(get_redis_settings())
        job = await pool.enqueue_job(
            "build_kg_job",
            github_token=github_token,
            repo_full_name=repo_full_name,
            repo_id=repo_id,
            branch=branch,
        )
        await pool.close()
        return job.job_id if job else None
    except Exception as e:
        print(f"[Queue] Failed to enqueue KG build job: {e}")
        return None


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
