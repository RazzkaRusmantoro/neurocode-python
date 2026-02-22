"""
Chat API: organization-scoped vector search (all repos) + LLM with conversation history.
Chunks are labeled with their repository; the model is instructed to use the relevant repo's chunks.
Enhanced: query expansion for retrieval, repo-scoped search when user names a repo.
"""
from typing import Optional, List

from fastapi import APIRouter, HTTPException

from neurocode.models.schemas import ChatRequest
from neurocode.config import vectorizer, llm_service


# Terms to append to the query when embedding for retrieval (improves recall on code chunks)
_QUERY_EXPANSION_TERMS = [
    ("semantic search", ["vector", "embedding", "retrieval", "similarity", "qdrant"]),
    ("rag", ["retrieval", "chunk", "embed", "context"]),
    ("documentation", ["doc", "generate", "markdown", "docs"]),
    ("storage", ["save", "persist", "file", "path", "s3", "mongodb"]),
    ("auth", ["authentication", "login", "token", "session"]),
    ("pipeline", ["flow", "step", "chunk", "index", "vectorize"]),
    ("how does", ["implementation", "code", "function", "class"]),
    ("how do ", ["implementation", "code", "function", "class"]),
    ("where is", ["file", "path", "storage", "config"]),
    ("where are", ["file", "path", "storage", "config"]),
]


def _expand_query_for_retrieval(message: str) -> str:
    """Expand user message with code-related terms for better semantic retrieval."""
    if not message or not message.strip():
        return message
    msg_lower = message.lower().strip()
    extra: List[str] = []
    for phrase, terms in _QUERY_EXPANSION_TERMS:
        if phrase in msg_lower:
            extra.extend(terms)
    if extra:
        return message + " " + " ".join(extra)
    return message


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


def _collections_for_mentioned_repo(message: str, collection_names: List[str]) -> List[str]:
    """
    If the user message clearly mentions a repo (e.g. neurocode-python, 2sc8s-neurocode),
    return only collections that match that repo so we search only there. Otherwise return all.
    """
    if not message or not collection_names:
        return list(collection_names)
    msg_lower = message.lower().strip()
    matched: List[str] = []
    for coll in collection_names:
        label = _repo_label_from_collection_name(coll).lower()  # e.g. neurocode-python
        label_underscore = label.replace("-", "_")  # neurocode_python
        if label and (label in msg_lower or label_underscore in msg_lower):
            matched.append(coll)
    return matched if matched else list(collection_names)


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
PER_COLLECTION_TOP_K = 8
# When user names one repo, we search only that repo and take this many chunks
SINGLE_REPO_TOP_K = 12


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

    # When user mentions a specific repo, search only that repo for better relevance
    collections_to_search = _collections_for_mentioned_repo(message, collection_names)
    single_repo = len(collections_to_search) == 1
    per_coll_k = SINGLE_REPO_TOP_K if single_repo else PER_COLLECTION_TOP_K
    global_k = SINGLE_REPO_TOP_K if single_repo else GLOBAL_TOP_K

    print(f"[chat] User message: {message[:200]}{'...' if len(message) > 200 else ''}")
    print(f"[chat] Scope: {'single repo' if single_repo else 'all repos'} | collections: {[ _repo_label_from_collection_name(c) for c in collections_to_search ]}")

    # Expand query with code-related terms to improve semantic retrieval
    query_for_search = _expand_query_for_retrieval(message)
    if query_for_search != message:
        print(f"[chat] Query expansion: \"{query_for_search[:250]}{'...' if len(query_for_search) > 250 else ''}\"")
    else:
        print(f"[chat] Query (no expansion): \"{message[:150]}{'...' if len(message) > 150 else ''}\"")

    all_results: list = []
    for coll in collections_to_search:
        try:
            count = vectorizer.vector_db.get_collection_count(coll)
            if count == 0:
                continue
            results = vectorizer.search(
                collection_name=coll,
                query=query_for_search,
                top_k=per_coll_k,
            )
            for r in results:
                r["_score"] = r.get("score") or 0.0
                r["_collection"] = coll
                all_results.append(r)
        except Exception as e:
            print(f"[chat] Search failed for collection {coll}: {e}")
            continue

    all_results.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
    results = all_results[:global_k]

    print(f"[chat] Retrieved {len(all_results)} total hits, sending top {len(results)} to LLM")
    for i, hit in enumerate(results, 1):
        meta = hit.get("metadata", {})
        repo = _repo_label_from_collection_name(hit.get("_collection", ""))
        file_path = meta.get("file_path", "")
        chunk_type = meta.get("type", "")
        fn = meta.get("function_name", "") or meta.get("class_name", "") or "(none)"
        score = hit.get("score")
        score_str = f"{score:.4f}" if score is not None else "n/a"
        raw = (hit.get("content") or "").replace("\n", " ")
        preview = (raw[:80] + "...") if len(raw) > 80 else raw
        print(f"[chat]   Chunk {i}: repo={repo} file={file_path} type={chunk_type} name={fn} score={score_str} | \"{preview}\"")

    context = _format_chunks_for_prompt(results) if results else ""

    system = f"""You are a helpful coding assistant for this organization's codebase. Each code chunk below is labeled with its **Repository** (e.g. neurocode-python).

**CRITICAL RULES:**
- Answer ONLY from the retrieved code chunks below. If the chunks do not contain enough information to answer the question, say clearly: "I don't have that in the retrieved context" and do not infer or guess from general knowledge.
- If the user asked about a **specific repository** (by name), use ONLY code chunks from that repository. Ignore chunks from any other repository.
- If the user did not specify a repository, you may use any chunk but clearly state which repository each part of your answer refers to (e.g. "In neurocode-python, ...").
- Do not mix up repositories: do not describe or cite code from one repo when the user asked about another.

**Relevant code from the codebase:**
{context}

Answer based on the code above when possible. Keep answers clear and concise. Reference file paths and function/class names from the context. Always respect the repository boundary."""

    reply = llm_service.chat_with_context(system, history_for_llm, message)
    return {"reply": reply}
