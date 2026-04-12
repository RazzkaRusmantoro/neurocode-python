import json
import httpx
from typing import List, Dict, Any, Optional

_SYSTEM_PROMPT = """You are a senior engineering lead analyzing a developer task against a codebase.
Given a task description, retrieved code chunks, and contributor data from the repository,
produce a structured JSON analysis that helps a developer understand context BEFORE they start coding.

You MUST return ONLY valid JSON (no markdown fences, no extra text) with this exact shape:

{
  "area": "<short area label, e.g. 'Authentication', 'Payments', 'Task Compass UI'>",
  "riskLevel": "<low | medium | high>",
  "cautionAreas": [
    {
      "file": "<file path>",
      "reason": "<1 sentence why this file is sensitive>",
      "label": "<caution | manual approval>"
    }
  ],
  "relevantFiles": [
    {
      "file": "<file path>",
      "reason": "<1 sentence why this file matters for the task>",
      "badge": "<core | helper | config | UI | route | service | schema | test>"
    }
  ],
  "entryPoints": [
    {
      "target": "<function name, file, or class to start reading>",
      "reason": "<1 sentence why start here>"
    }
  ],
  "ownership": [
    {
      "name": "<FULL real name of the person, e.g. 'John Smith', not initials>",
      "role": "<what they do or own, e.g. 'Primary maintainer of auth module', 'Frequent contributor to API routes'>",
      "type": "<owner | contributor | reviewer>"
    }
  ]
}

Rules:
- "cautionAreas": 1-4 items. Files that are sensitive, stable, or need approval. Use "manual approval" for files touching auth, secrets, or storage credentials. Use "caution" for stable/shared code.
- "relevantFiles": 3-6 items. Most relevant files for the task based on the code chunks. badge should reflect the file's role in the codebase.
- "entryPoints": 2-4 items. Suggest where to start reading code, not what to do. Best starting points for understanding.
- "ownership": USE THE CONTRIBUTOR DATA PROVIDED. List 1-4 people who are most relevant to the task's files. Use their FULL REAL NAME (not username, not initials). Assign types:
  * "owner" = top contributor or maintainer for the relevant files
  * "contributor" = someone who frequently pushes to those files
  * "reviewer" = someone who reviews PRs in that area (if identifiable)
  The "role" field should describe their relationship to the specific files/area (e.g. "Most active contributor to the API routes", "Maintains the LLM service module"). If no contributor data is available, return an empty array [].
- "riskLevel": "high" if task touches auth, payments, storage credentials, or critical shared code. "medium" if it changes shared components or APIs. "low" for isolated UI or docs.
- Keep reasons to 1 short sentence each. Be specific, reference actual file paths from the chunks.
- Do NOT invent file paths. Only use paths that appear in the code chunks provided.
- Do NOT invent people. Only use names from the contributor data provided.
- Do NOT add tutorials, checklists, or step-by-step instructions. This is context, not a plan."""


def _repo_label_from_collection(collection_name: str) -> str:
    parts = (collection_name or "").split("_")
    if len(parts) > 3:
        return "_".join(parts[2:-1]).replace("_", "-")
    if len(parts) >= 3:
        return parts[2].replace("_", "-")
    return collection_name


def _canonical_repo_token(repo_url_name: str) -> str:
    token = (repo_url_name or "").strip().lower()
    token = token.replace("-", "_").replace("/", "_").replace(".", "_")
    token = "_".join([p for p in token.split("_") if p])
    return token


def _filter_collections(collections: List[str], repo_url_names: Optional[List[str]]) -> List[str]:
    if not repo_url_names:
        return list(collections)
    wanted = {_canonical_repo_token(r) for r in repo_url_names if r and r.strip()}
    if not wanted:
        return list(collections)
    matched = []
    for coll in collections:
        seg = _canonical_repo_token(_repo_label_from_collection(coll))
        if seg in wanted or any(w in seg for w in wanted):
            matched.append(coll)
    return matched if matched else list(collections)


def _format_chunks(chunks: List[Dict[str, Any]]) -> str:
    parts = []
    for i, hit in enumerate(chunks, 1):
        meta = hit.get("metadata", {})
        file_path = meta.get("file_path", "unknown")
        chunk_type = meta.get("type", "")
        fn = meta.get("function_name", "")
        cls = meta.get("class_name", "")
        lines = f"{meta.get('start_line', '?')}-{meta.get('end_line', '?')}"
        repo = _repo_label_from_collection(hit.get("_collection", ""))

        header = f"--- Chunk {i} | repo: {repo} | file: {file_path}"
        if chunk_type:
            header += f" | type: {chunk_type}"
        if cls:
            header += f" | class: {cls}"
        if fn:
            header += f" | function: {fn}"
        header += f" | lines: {lines} ---"
        parts.append(header + "\n" + (hit.get("content") or ""))
    return "\n\n".join(parts)


async def _fetch_repo_contributors(
    repo_full_name: str,
    github_token: str,
) -> List[Dict[str, str]]:
    
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json",
    }
    contributors: List[Dict[str, str]] = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo_full_name}/contributors",
                headers=headers,
                params={"per_page": 10},
            )
            if resp.status_code != 200:
                print(f"[task-compass] GitHub contributors API returned {resp.status_code} for {repo_full_name}")
                return []

            data = resp.json()
            for item in data:
                if item.get("type") != "User":
                    continue
                login = item.get("login", "")
                contributions = item.get("contributions", 0)

                name = login
                try:
                    user_resp = await client.get(
                        f"https://api.github.com/users/{login}",
                        headers=headers,
                    )
                    if user_resp.status_code == 200:
                        user_data = user_resp.json()
                        name = user_data.get("name") or login
                except Exception:
                    pass

                contributors.append({
                    "name": name,
                    "login": login,
                    "contributions": str(contributions),
                    "repo": repo_full_name.split("/")[-1] if "/" in repo_full_name else repo_full_name,
                })
    except Exception as e:
        print(f"[task-compass] Failed to fetch contributors for {repo_full_name}: {e}")
    return contributors


def _format_contributors_context(all_contributors: List[Dict[str, str]]) -> str:
    if not all_contributors:
        return ""
    lines = ["**Repository Contributors (from Git history):**"]
    for c in all_contributors:
        lines.append(
            f"- {c['name']} (@{c['login']}) — {c['contributions']} commits to {c['repo']}"
        )
    return "\n".join(lines)


async def analyze_task(
    vectorizer,
    llm_service,
    org_short_id: str,
    task_id: str,
    task_title: str,
    task_description: Optional[str],
    task_type: Optional[str],
    repositories: Optional[List[str]],
    top_k: int = 15,
    github_token: Optional[str] = None,
    repo_full_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    
    collection_names = vectorizer.vector_db.list_collections_by_org_short_id(org_short_id)
    if not collection_names:
        return _empty_context(task_title)

    collections_to_search = _filter_collections(collection_names, repositories)
    if not collections_to_search:
        collections_to_search = list(collection_names)

    query = task_title
    if task_description:
        query += " " + task_description
    if task_type:
        query += f" ({task_type})"

    per_coll_k = max(4, top_k // max(len(collections_to_search), 1))
    all_results: List[Dict[str, Any]] = []

    for coll in collections_to_search:
        try:
            count = vectorizer.vector_db.get_collection_count(coll)
            if count == 0:
                continue
            results = vectorizer.search(
                collection_name=coll,
                query=query,
                top_k=per_coll_k,
            )
            for r in results:
                r["_score"] = r.get("score", 0.0)
                r["_collection"] = coll
                all_results.append(r)
        except Exception as e:
            print(f"[task-compass] Search failed for {coll}: {e}")
            continue

    all_results.sort(key=lambda x: x.get("_score", 0.0), reverse=True)
    top_chunks = all_results[:top_k]

    if not top_chunks:
        return _empty_context(task_title)

    all_contributors: List[Dict[str, str]] = []
    if github_token and repo_full_names:
        for repo_name in repo_full_names:
            contribs = await _fetch_repo_contributors(repo_name, github_token)
            all_contributors.extend(contribs)

    context_text = _format_chunks(top_chunks)
    contributors_text = _format_contributors_context(all_contributors)

    user_message = f"""Task ID: {task_id}
Task Title: {task_title}
Task Type: {task_type or 'unknown'}
Description: {task_description or 'No description provided.'}
Repositories: {', '.join(repositories) if repositories else 'all indexed'}

Analyze the task above using the code chunks and contributor data below and return the structured JSON."""

    system = _SYSTEM_PROMPT + "\n\n**Code chunks from the codebase:**\n" + context_text
    if contributors_text:
        system += "\n\n" + contributors_text

    raw = llm_service.chat_with_context(system, [], user_message, max_tokens=3000)

    return _parse_llm_response(raw, task_title)


def _parse_llm_response(raw: str, task_title: str) -> Dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return _empty_context(task_title)
        else:
            return _empty_context(task_title)

    return {
        "area": data.get("area", "Unknown"),
        "riskLevel": data.get("riskLevel", "medium"),
        "cautionAreas": data.get("cautionAreas", []),
        "relevantFiles": data.get("relevantFiles", []),
        "entryPoints": data.get("entryPoints", []),
        "ownership": data.get("ownership", []),
    }


def _empty_context(task_title: str) -> Dict[str, Any]:
    return {
        "area": "Unknown",
        "riskLevel": "low",
        "cautionAreas": [],
        "relevantFiles": [],
        "entryPoints": [],
        "ownership": [],
    }
