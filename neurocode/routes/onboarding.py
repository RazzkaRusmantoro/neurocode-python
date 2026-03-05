"""
Onboarding suggested learning paths: RAG retrieval per repo + LLM generation.
Generate full path doc: RAG per repo + LLM (same pipeline as generate-docs-rag).
"""
from fastapi import APIRouter, HTTPException

from neurocode.models.schemas import (
    OnboardingSuggestedPathsRequest,
    GenerateOnboardingPathDocRequest,
)
from neurocode.config import (
    github_fetcher,
    vectorizer,
    llm_service,
    s3_service,
)
from neurocode.services.index_pipeline import run_index_pipeline, build_collection_name

router = APIRouter()

ONBOARDING_QUERY = (
    "onboarding getting started setup documentation architecture "
    "how to run install develop conventions README contribution"
)
TOP_K_PER_REPO = 15
MAX_CHUNK_CHARS = 600


def _log(msg: str) -> None:
    print(msg, flush=True)


def _format_chunk(hit: dict) -> str:
    content = (hit.get("content") or "")[:MAX_CHUNK_CHARS]
    meta = hit.get("metadata") or {}
    path = meta.get("file_path") or ""
    fn = meta.get("function_name") or ""
    cls = meta.get("class_name") or ""
    summary = (meta.get("summary") or "").strip()
    parts = [f"File: {path}"]
    if cls:
        parts.append(f"Class: {cls}")
    if fn:
        parts.append(f"Function: {fn}")
    if summary:
        parts.append(f"Summary: {summary}")
    parts.append("Content:")
    parts.append(content)
    return "\n".join(parts)


@router.post("/api/onboarding/suggested-paths")
async def generate_suggested_paths(request: OnboardingSuggestedPathsRequest):
    """
    Generate suggested onboarding learning paths using RAG per repo.
    For each repo: index if needed, retrieve chunks with onboarding query, then LLM generates paths + modules.
    """
    if not llm_service:
        raise HTTPException(
            status_code=503,
            detail="LLM service not available. Set ANTHROPIC_API_KEY.",
        )
    if not request.repositories:
        return {"success": True, "paths": []}

    organization_name = request.organization_name or ""
    organization_short_id = request.organization_short_id or ""
    default_branch = (request.branch or "main").strip() or "main"
    repo_contexts = []

    for repo in request.repositories:
        repo_full_name = repo.repo_full_name
        repository_name = repo.repository_name
        github_token = repo.github_token
        _log(f"[onboarding] Processing repo: {repository_name} ({repo_full_name})")

        if not organization_short_id or not repository_name:
            _log(f"[onboarding] Skip {repo_full_name}: missing org_short_id or repository_name")
            continue

        try:
            branch = default_branch
            if not branch or branch.lower() in ("main", "master"):
                resolved = await github_fetcher.get_default_branch(repo_full_name, github_token)
                if resolved:
                    branch = resolved
            collection_name = build_collection_name(
                organization_name,
                organization_short_id,
                repository_name,
                branch,
            )
            existing = vectorizer.vector_db.get_collection_count(collection_name)
            if existing == 0:
                _log(f"[onboarding] Indexing {repository_name}...")
                result = await run_index_pipeline(
                    github_token=github_token,
                    repo_full_name=repo_full_name,
                    branch=branch,
                    target=None,
                    organization_id=request.organization_id,
                    organization_short_id=organization_short_id,
                    organization_name=organization_name,
                    repository_id=repo.repository_id,
                    repository_name=repository_name,
                )
                if not result.get("success"):
                    _log(f"[onboarding] Index failed for {repository_name}: {result.get('message')}")
                    repo_contexts.append(f"## Repository: {repository_name}\n(Index failed or no files.)\n")
                    continue
            else:
                _log(f"[onboarding] Using existing collection for {repository_name} ({existing} chunks)")

            search_results = vectorizer.search(
                collection_name=collection_name,
                query=ONBOARDING_QUERY,
                top_k=TOP_K_PER_REPO,
            )
            if not search_results:
                repo_contexts.append(f"## Repository: {repository_name}\n(No relevant chunks found.)\n")
                continue
            chunks_text = "\n\n---\n\n".join(_format_chunk(h) for h in search_results)
            repo_contexts.append(f"## Repository: {repository_name}\n\n{chunks_text}\n")
        except Exception as e:
            _log(f"[onboarding] Error for {repository_name}: {e}")
            repo_contexts.append(f"## Repository: {repository_name}\n(Error: {e})\n")

    if not repo_contexts:
        return {"success": True, "paths": []}

    repo_contexts_text = "\n\n".join(repo_contexts)
    result = llm_service.generate_onboarding_suggested_paths(
        organization_name=organization_name,
        repo_contexts_text=repo_contexts_text,
    )
    paths = result.get("paths") or []
    return {"success": True, "paths": paths}


# RAG query for path doc: path title + module names so we get relevant chunks
def _path_doc_query(path) -> str:
    parts = [path.title, path.summary_description or ""]
    for m in sorted(path.modules, key=lambda x: x.order):
        parts.append(m.name)
        parts.append(getattr(m, "summary_description", None) or getattr(m, "summaryDescription", "") or "")
    return " ".join(p for p in parts if p).strip() or "onboarding setup documentation"


TOP_K_PER_REPO_PATH_DOC = 12
MAX_CHUNKS_PATH_DOC = 40


@router.post("/api/onboarding/generate-path-doc")
async def generate_path_doc(request: GenerateOnboardingPathDocRequest):
    """
    Generate full RAG documentation for one onboarding path (like generate-docs-rag).
    For each org repo: index if needed, retrieve chunks, then merge and run LLM.
    Upload result to S3. Returns s3_key, s3_bucket, content_size for Next to store.
    """
    if not llm_service:
        raise HTTPException(status_code=503, detail="LLM service not available. Set ANTHROPIC_API_KEY.")
    if not s3_service:
        raise HTTPException(status_code=503, detail="S3 service not available.")
    if not request.repositories:
        raise HTTPException(status_code=400, detail="repositories required")

    path = request.path
    organization_name = request.organization_name or ""
    organization_short_id = request.organization_short_id or ""
    organization_id = request.organization_id or ""
    default_branch = (request.branch or "main").strip() or "main"
    query = _path_doc_query(path)

    all_chunks = []
    for repo in request.repositories:
        repo_full_name = repo.repo_full_name
        repository_name = repo.repository_name
        github_token = repo.github_token
        _log(f"[onboarding path-doc] {repository_name} ({path.title})")

        if not organization_short_id or not repository_name:
            continue
        try:
            branch = default_branch
            if branch.lower() in ("main", "master"):
                resolved = await github_fetcher.get_default_branch(repo_full_name, github_token)
                if resolved:
                    branch = resolved
            collection_name = build_collection_name(
                organization_name,
                organization_short_id,
                repository_name,
                branch,
            )
            existing = vectorizer.vector_db.get_collection_count(collection_name)
            if existing == 0:
                _log(f"[onboarding path-doc] Indexing {repository_name}...")
                result = await run_index_pipeline(
                    github_token=github_token,
                    repo_full_name=repo_full_name,
                    branch=branch,
                    target=None,
                    organization_id=request.organization_id,
                    organization_short_id=organization_short_id,
                    organization_name=organization_name,
                    repository_id=repo.repository_id,
                    repository_name=repository_name,
                )
                if not result.get("success"):
                    continue
            search_results = vectorizer.search(
                collection_name=collection_name,
                query=query,
                top_k=TOP_K_PER_REPO_PATH_DOC,
            )
            for h in search_results or []:
                h["_collection"] = collection_name
            all_chunks.extend(search_results or [])
        except Exception as e:
            _log(f"[onboarding path-doc] Error {repository_name}: {e}")

    if not all_chunks:
        raise HTTPException(
            status_code=404,
            detail="No RAG chunks found for any repository. Index repos first.",
        )

    # Limit total chunks for LLM
    all_chunks = all_chunks[:MAX_CHUNKS_PATH_DOC]
    modules_for_llm = [
        {
            "name": m.name,
            "summary_description": getattr(m, "summary_description", None) or getattr(m, "summaryDescription", ""),
            "order": m.order,
        }
        for m in sorted(path.modules, key=lambda x: x.order)
    ]

    _log(f"[onboarding path-doc] Generating doc for '{path.title}' with {len(all_chunks)} chunks")
    result = llm_service.generate_onboarding_path_documentation(
        path_title=path.title,
        path_summary=path.summary_description or "",
        modules=modules_for_llm,
        context_chunks=all_chunks,
    )
    documentation = result.get("documentation") or {}
    code_ref_ids = result.get("code_reference_ids") or []

    import json
    from datetime import datetime
    doc_id = path.path_id
    s3_key = s3_service.generate_onboarding_path_key(
        organization_id=organization_id or "unknown",
        path_id=doc_id,
    )
    documentation_json = {
        "version": "1.0",
        "metadata": {
            "title": path.title,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "documentation_type": "onboarding",
            "path_id": path.path_id,
        },
        "documentation": documentation,
        "code_references": code_ref_ids,
    }
    documentation_json_str = json.dumps(documentation_json, indent=2)
    s3_result = s3_service.upload_documentation(
        content=documentation_json_str,
        s3_key=s3_key,
        content_type="application/json",
    )
    if not s3_result.get("success"):
        raise HTTPException(status_code=500, detail=s3_result.get("error", "S3 upload failed"))

    _log(f"[onboarding path-doc] Uploaded {s3_key}")
    return {
        "success": True,
        "s3_key": s3_result["s3_key"],
        "s3_bucket": s3_service.bucket_name,
        "content_size": s3_result.get("content_size", 0),
    }
