"""
Shared RAG index pipeline: fetch → parse → chunk → save → vectorize.
Used by the documentation API and by the background worker.
"""
from typing import Dict, Any, Optional

from neurocode.config import (
    github_fetcher,
    code_analyzer,
    storage_service,
    vectorizer,
)


def _log(msg: str) -> None:
    """Print with flush so logs appear immediately in worker terminal."""
    print(msg, flush=True)


def _sanitize_name(name: str) -> str:
    """Sanitize name for use in collection name."""
    if not name:
        return ""
    sanitized = name.replace(" ", "_").replace("/", "_").replace(".", "_").replace("-", "_")
    sanitized = "".join(c if c.isalnum() or c == "_" else "_" for c in sanitized)
    sanitized = "_".join(filter(None, sanitized.split("_")))
    return sanitized.lower()


async def run_index_pipeline(
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
    Run the full RAG index pipeline: fetch files → parse → chunk → save → vectorize.
    Raises ValueError if required fields for collection naming are missing.
    """
    _log("")
    _log("=" * 60)
    _log("INDEX PIPELINE (RAG)")
    _log("=" * 60)
    _log(f"Repository: {repo_full_name}")
    # Use repo's default branch when none specified or when main/master was used as placeholder
    if not branch or branch.strip().lower() in ("main", "master"):
        resolved_branch = await github_fetcher.get_default_branch(repo_full_name, github_token)
        if resolved_branch:
            branch = resolved_branch
            _log(f"Branch: {branch} (repo default)")
        else:
            _log(f"Branch: {branch or 'main'} (fallback; could not fetch default)")
    else:
        _log(f"Branch: {branch}")
    _log(f"Target: {target or 'N/A'}")
    _log("=" * 60)
    path = target or ""

    # Step 1: Fetch repository files
    _log("")
    _log("[Step 1/5] Fetching files from GitHub...")
    files = await github_fetcher.fetch_repository_files(
        repo_full_name=repo_full_name,
        access_token=github_token,
        branch=branch,
        path=path,
    )
    _log(f"✓ Fetched {len(files)} files")

    if len(files) == 0:
        return {
            "success": False,
            "message": "No files found in repository",
            "repository": repo_full_name,
            "branch": branch,
        }

    # Step 2 & 3: Parse and chunk
    _log("")
    _log("[Step 2/5] Parsing code structure...")
    _log("[Step 3/5] Creating semantic chunks...")
    files_for_analysis = [
        {"path": f["path"], "content": f["content"], "language": f.get("language")}
        for f in files
    ]
    analysis_results = await code_analyzer.analyze_and_chunk(
        files_for_analysis,
        chunking_strategy="hybrid",
    )
    meta = analysis_results["metadata"]
    total_fns = meta.get("totalFunctions", 0)
    total_cls = meta.get("totalClasses", 0)
    total_chunks = meta.get("totalChunks", 0)
    _log(f"✓ Parsed {total_fns} functions, {total_cls} classes")
    _log(f"✓ Created {total_chunks} chunks")
    # Log what got chunked (per-file summary from chunks)
    chunks_list = analysis_results.get("chunks", [])
    if chunks_list:
        by_file: Dict[str, list] = {}
        for c in chunks_list:
            fp = c.get("metadata", {}).get("file_path", "")
            if fp not in by_file:
                by_file[fp] = []
            by_file[fp].append(c.get("metadata", {}).get("function_name") or c.get("metadata", {}).get("class_name") or "?")
        _log("Chunked symbols:")
        for fp in sorted(by_file.keys()):
            symbols = by_file[fp]
            _log(f"  {fp}: {len(symbols)} chunks ({', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''})")

    # Step 4: Save locally
    _log("")
    _log("[Step 4/5] Saving results to local storage...")
    saved_paths = storage_service.save_analysis_results(
        repo_full_name=repo_full_name,
        branch=branch,
        results=analysis_results,
    )
    _log(f"✓ Results saved to: {saved_paths.get('directory', 'N/A')}")

    # Step 5: Build collection name and vectorize
    if not organization_short_id:
        raise ValueError("organization_short_id is required for collection naming")
    if not repository_name:
        raise ValueError("repository_name is required for collection naming")

    org_name_safe = _sanitize_name(organization_name or organization_short_id)
    org_slug_safe = _sanitize_name(organization_short_id)
    repo_name_safe = _sanitize_name(repository_name)
    collection_name = f"{org_name_safe}_{org_slug_safe}_{repo_name_safe}_{branch}"

    collection_metadata: Dict[str, Any] = {
        "repo_full_name": repo_full_name,
        "branch": branch,
    }
    if organization_id:
        collection_metadata["organization_id"] = organization_id
    if organization_short_id:
        collection_metadata["organization_short_id"] = organization_short_id
    if repository_id:
        collection_metadata["repository_id"] = repository_id

    _log("")
    _log("[Step 5/5] Vectorizing chunks...")
    _log(f"  Collection: {collection_name}")
    vectorization_result = vectorizer.vectorize_chunks_from_file(
        chunks_file_path=saved_paths["files"]["chunks"],
        collection_name=collection_name,
        metadata=collection_metadata,
    )

    if vectorization_result.get("success"):
        _log(f"✓ Vectorized {vectorization_result['chunks_vectorized']} chunks")
        _log(f"✓ Total in collection: {vectorization_result.get('total_in_collection', 'N/A')}")
    else:
        _log(f"⚠ Vectorization: {vectorization_result.get('message')}")
    _log("=" * 60)
    _log("")

    return {
        "success": True,
        "repository": repo_full_name,
        "branch": branch,
        "files_count": len(files),
        "metadata": analysis_results["metadata"],
        "saved_paths": saved_paths,
        "vectorization": vectorization_result if vectorization_result.get("success") else None,
        "message": "Index pipeline complete.",
    }
