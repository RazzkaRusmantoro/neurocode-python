"""
Chat API: organization-scoped vector search (all repos) + LLM with conversation history.
Chunks are labeled with their repository; the model is instructed to use the relevant repo's chunks.
"""
from typing import Optional

from fastapi import APIRouter, HTTPException

from neurocode.models.schemas import ChatRequest
from neurocode.config import vectorizer, llm_service


def _repo_slug_from_collection_name(collection_name: str) -> str:
    """Collection name is org_org_repo_name_branch; return repo segment (may contain _)."""
    parts = collection_name.split("_")
    # org_org_repo_part1_part2_main -> repo = repo_part1_part2
    if len(parts) > 3:
        return "_".join(parts[2:-1]).lower()
    if len(parts) >= 3:
        return parts[2].lower()
    return collection_name.lower()


def _repo_label_from_collection_name(collection_name: str) -> str:
    """Human-readable repo label (e.g. neurocode_python -> neurocode-python)."""
    slug = _repo_slug_from_collection_name(collection_name)
    return slug.replace("_", "-") if slug else collection_name


def _format_chunks_for_prompt(chunks: list) -> str:
    """Format retrieved chunks with Repository label so the model can scope answers."""
    parts = []
    for i, hit in enumerate(chunks, 1):
        meta = hit.get("metadata", {})
        file_path = meta.get("file_path", "")
        chunk_type = meta.get("type", "")
        fn = meta.get("function_name", "")
        cls = meta.get("class_name", "")
        lines = f"{meta.get('start_line', 0)}-{meta.get('end_line', 0)}"
        repo_label = _repo_label_from_collection_name(hit.get("_collection", ""))
        header = f"--- Code chunk {i} | Repository: {repo_label} | file: {file_path}, type: {chunk_type}"
        if cls:
            header += f", class: {cls}"
        if fn:
            header += f", name: {fn}"
        header += f", lines: {lines} ---\n"
        parts.append(header + (hit.get("content") or ""))
    return "\n\n".join(parts)


router = APIRouter(prefix="/chat", tags=["chat"])

# Global top_k sent to the LLM (keeps cost unchanged regardless of number of org repos)
GLOBAL_TOP_K = 10
# Per-collection limit when merging from multiple repos
PER_COLLECTION_TOP_K = 5


@router.post("")
async def chat(request: ChatRequest) -> dict:
    """
    RAG chat: vector search across all repositories in the organization + LLM with conversation history.
    Returns { "reply": "..." }.
    """
    if not llm_service:
        raise HTTPException(status_code=503, detail="LLM service not configured (ANTHROPIC_API_KEY)")

    message = (request.message or "").strip()
    if not message:
        return {"reply": "Please send a non-empty message."}

    history = request.history or []
    history_for_llm = [{"role": m.role, "content": m.content} for m in history if m.role in ("user", "assistant") and m.content]

    # No org context: answer without codebase
    if not request.org_context or not (request.org_context.org_short_id or "").strip():
        system = (
            "You are a helpful coding assistant. The user has not selected an organization, "
            "so you cannot search their codebase. Answer generally and suggest they open an organization "
            "to ask questions about their code."
        )
        reply = llm_service.chat_with_context(system, history_for_llm, message)
        return {"reply": reply}

    org_short_id = (request.org_context.org_short_id or "").strip()
    collection_names = vectorizer.vector_db.list_collections_by_org_short_id(org_short_id)

    if not collection_names:
        system = (
            "You are a helpful coding assistant. This organization has no indexed repositories yet, "
            "or no collections were found. Answer generally and suggest they index their repositories."
        )
        reply = llm_service.chat_with_context(system, history_for_llm, message)
        return {"reply": reply}

    # Search each collection, tag with collection name, merge by score, take global top_k
    all_results: list = []
    for coll in collection_names:
        try:
            count = vectorizer.vector_db.get_collection_count(coll)
            if count == 0:
                continue
            results = vectorizer.search(collection_name=coll, query=message, top_k=PER_COLLECTION_TOP_K)
            for r in results:
                r["_score"] = r.get("score") or 0.0
                r["_collection"] = coll
                all_results.append(r)
        except Exception as e:
            print(f"[chat] Search failed for collection {coll}: {e}")
            continue

    all_results.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
    results = all_results[:GLOBAL_TOP_K]

    context = _format_chunks_for_prompt(results) if results else ""

    system = f"""You are a helpful coding assistant for this organization's codebase. Each code chunk below is labeled with its **Repository** (e.g. neurocode-python).

**CRITICAL RULES:**
- If the user asked about a **specific repository** (by name), use ONLY code chunks from that repository. Ignore chunks from any other repository.
- If the user did not specify a repository, you may use any chunk but clearly state which repository each part of your answer refers to (e.g. "In neurocode-python, ...").
- Do not mix up repositories: do not describe or cite code from one repo when the user asked about another.

**Relevant code from the codebase:**
{context}

Answer based on the code above when possible. Keep answers clear and concise. Reference file paths and function/class names from the context. Always respect the repository boundary."""

    reply = llm_service.chat_with_context(system, history_for_llm, message)
    return {"reply": reply}
