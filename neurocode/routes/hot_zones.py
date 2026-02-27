"""
Hot Zones helpers: semantic recommendations for code areas (files/classes/functions) by task query.

This complements the Next.js Hot Zones page by letting users type a task like "login" and
getting suggested files/symbols from the org-scoped vector index.
"""

from typing import List, Dict, Any, Optional, Tuple

from fastapi import APIRouter, HTTPException

from neurocode.models.schemas import HotZonesRecommendAreasRequest
from neurocode.config import vectorizer


router = APIRouter(prefix="/api/hot-zones", tags=["hot-zones"])


def _repo_slug_from_collection_name(collection_name: str) -> str:
    """
    Collection name format: {orgName}_{orgShortId}_{repoName}_{branch}
    Return the repo segment (repoName) which may contain underscores.
    """
    parts = (collection_name or "").split("_")
    if len(parts) > 3:
        return "_".join(parts[2:-1]).lower()
    if len(parts) >= 3:
        return parts[2].lower()
    return (collection_name or "").lower()


def _canonical_repo_token(repo_url_name: str) -> str:
    """
    Normalize repo urlName (typically hyphenated) to match collection repo segment (underscore).
    """
    token = (repo_url_name or "").strip().lower()
    token = token.replace("-", "_").replace("/", "_").replace(".", "_")
    token = "".join(c if c.isalnum() or c == "_" else "_" for c in token)
    token = "_".join([p for p in token.split("_") if p])
    return token


def _filter_collections_by_repo_url_names(collections: List[str], repo_url_names: List[str]) -> List[str]:
    if not repo_url_names:
        return list(collections)
    wanted = {_canonical_repo_token(r) for r in repo_url_names if r and r.strip()}
    if not wanted:
        return list(collections)

    matched: List[str] = []
    for coll in collections:
        repo_seg = _repo_slug_from_collection_name(coll)
        if repo_seg in wanted:
            matched.append(coll)
            continue
        # fallback: substring match if repo name token is part of segment
        if any(w in repo_seg for w in wanted):
            matched.append(coll)
    return matched if matched else list(collections)


def _aggregate_suggestions(hits: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Aggregate chunk hits into suggested files and symbols with a simple score sum.
    """
    file_scores: Dict[str, float] = {}
    symbol_scores: Dict[str, float] = {}

    for h in hits:
        score = float(h.get("score") or 0.0)
        meta = h.get("metadata") or {}
        file_path = (meta.get("file_path") or "").strip()
        fn = (meta.get("function_name") or "").strip()
        cls = (meta.get("class_name") or "").strip()

        if file_path:
            file_scores[file_path] = file_scores.get(file_path, 0.0) + score

        symbol_name = cls or fn
        if file_path and symbol_name:
            key = f"{file_path}::{symbol_name}"
            symbol_scores[key] = symbol_scores.get(key, 0.0) + score

    files_sorted = sorted(file_scores.items(), key=lambda x: x[1], reverse=True)
    symbols_sorted = sorted(symbol_scores.items(), key=lambda x: x[1], reverse=True)

    file_results = [{"file_path": fp, "score": sc} for fp, sc in files_sorted]
    symbol_results = []
    for key, sc in symbols_sorted:
        fp, sym = key.split("::", 1)
        symbol_results.append({"file_path": fp, "symbol": sym, "score": sc})

    return file_results, symbol_results


@router.post("/recommend")
async def recommend_areas(request: HotZonesRecommendAreasRequest) -> dict:
    if not vectorizer:
        raise HTTPException(status_code=503, detail="Vector search service not initialized")

    org_short_id = (request.org_short_id or "").strip()
    query = (request.query or "").strip()
    if not org_short_id:
        raise HTTPException(status_code=400, detail="org_short_id is required")
    if not query:
        return {"files": [], "symbols": []}

    all_collections = vectorizer.vector_db.list_collections_by_org_short_id(org_short_id)
    if not all_collections:
        return {"files": [], "symbols": []}

    collections = _filter_collections_by_repo_url_names(all_collections, request.repo_url_names or [])

    # Bound work: search each collection, merge, then aggregate by file/symbol
    per_coll_k = 8
    global_k = 30

    all_hits: List[Dict[str, Any]] = []
    for coll in collections:
        try:
            count = vectorizer.vector_db.get_collection_count(coll)
            if count == 0:
                continue
            hits = vectorizer.search(collection_name=coll, query=query, top_k=per_coll_k)
            for h in hits:
                h["_collection"] = coll
                all_hits.append(h)
        except Exception:
            continue

    all_hits.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    all_hits = all_hits[:global_k]

    files, symbols = _aggregate_suggestions(all_hits)

    top_n = int(request.top_n or 10)
    top_n = max(1, min(top_n, 30))

    return {
        "files": files[:top_n],
        "symbols": symbols[:top_n],
    }

