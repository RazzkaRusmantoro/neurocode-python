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
    path = target or ""

    # Step 1: Fetch repository files
    print("\n[Index pipeline] Fetching files from GitHub...")
    files = await github_fetcher.fetch_repository_files(
        repo_full_name=repo_full_name,
        access_token=github_token,
        branch=branch,
        path=path,
    )
    print(f"✓ Fetched {len(files)} files")

    if len(files) == 0:
        return {
            "success": False,
            "message": "No files found in repository",
            "repository": repo_full_name,
            "branch": branch,
        }

    # Step 2 & 3: Parse and chunk
    print("[Index pipeline] Parsing and chunking...")
    files_for_analysis = [
        {"path": f["path"], "content": f["content"], "language": f.get("language")}
        for f in files
    ]
    analysis_results = await code_analyzer.analyze_and_chunk(
        files_for_analysis,
        chunking_strategy="hybrid",
    )
    print(f"✓ Created {analysis_results['metadata']['totalChunks']} chunks")

    # Step 4: Save locally
    print("[Index pipeline] Saving results...")
    saved_paths = storage_service.save_analysis_results(
        repo_full_name=repo_full_name,
        branch=branch,
        results=analysis_results,
    )

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

    print(f"[Index pipeline] Vectorizing into collection: {collection_name}")
    vectorization_result = vectorizer.vectorize_chunks_from_file(
        chunks_file_path=saved_paths["files"]["chunks"],
        collection_name=collection_name,
        metadata=collection_metadata,
    )

    if vectorization_result.get("success"):
        print(f"✓ Vectorized {vectorization_result['chunks_vectorized']} chunks")
    else:
        print(f"⚠ Vectorization: {vectorization_result.get('message')}")

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
