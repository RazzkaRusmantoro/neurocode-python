"""
Regenerate a single documentation or UML diagram (sync flow).
Used by the sync job after re-vectorizing: load doc, vector search with stored prompt,
same LLM as create, write to S3 and MongoDB, clear flags.
"""
from typing import Dict, Any, List, Optional
import json
from datetime import datetime

from neurocode.config import (
    vectorizer,
    llm_service,
    mongodb_service,
    s3_service,
)
from neurocode.services.index_pipeline import build_collection_name
from neurocode.services.agent_docs_validation import validate_agent_docs_bundle
from neurocode.routes.documentation import _agent_bundle_to_documentation


def _file_paths_from_search_results(search_results: List[Dict[str, Any]]) -> List[str]:
    """Extract unique sorted file paths from search result chunks."""
    paths = sorted(
        set(
            (c.get("metadata") or {}).get("file_path", "").strip()
            for c in search_results
        )
    )
    return [p for p in paths if p]


async def regenerate_documentation(documentation_id: str) -> Dict[str, Any]:
    """
    Regenerate one textual documentation: load doc, vector search with stored prompt,
    same LLM as create, overwrite S3, update MongoDB (filePaths, clear flags).
    Returns { "success": True } or { "success": False, "error": "..." }.
    """
    if not mongodb_service:
        return {"success": False, "error": "MongoDB not available"}
    if not llm_service:
        return {"success": False, "error": "LLM service not available"}
    if not vectorizer:
        return {"success": False, "error": "Vectorizer not available"}

    doc_result = mongodb_service.get_documentation_by_id(documentation_id)
    if not doc_result.get("success"):
        return {"success": False, "error": doc_result.get("error", "Doc not found")}
    doc = doc_result["documentation"]

    org_id = doc["organizationId"]
    repo_id = doc["repositoryId"]
    branch = (doc.get("branch") or "main").strip() or "main"
    prompt = (doc.get("prompt") or "").strip()
    if not prompt:
        return {"success": False, "error": "Documentation has no stored prompt"}

    names_result = mongodb_service.get_organization_and_repo_for_collection(org_id, repo_id)
    if not names_result.get("success"):
        return {"success": False, "error": names_result.get("error", "Org/repo not found")}
    try:
        collection_name = build_collection_name(
            organization_name=names_result.get("organization_name"),
            organization_short_id=names_result.get("organization_short_id"),
            repository_name=names_result.get("repository_name"),
            branch=branch,
        )
    except ValueError as e:
        return {"success": False, "error": str(e)}

    repo_name = names_result.get("repo_full_name") or names_result.get("repository_name") or "repository"
    s3_key = (doc.get("s3Key") or "").strip()
    if s3_service and not s3_key:
        return {"success": False, "error": "Documentation has no s3Key"}

    mongodb_service.set_documentation_is_updating(documentation_id, True)
    try:
        search_results = vectorizer.search(
            collection_name=collection_name,
            query=prompt,
            top_k=20,
        )
        if not search_results:
            return {"success": False, "error": f"No chunks in collection '{collection_name}'"}

        file_paths = _file_paths_from_search_results(search_results)
        doc_type = (doc.get("documentationType") or "").strip()

        documentation = None
        code_reference_ids: List[str] = []
        arch_title: Optional[str] = None

        if doc_type == "aiAgent":
            raw_bundle = llm_service.generate_agent_docs_bundle(
                prompt=prompt,
                context_chunks=search_results,
                repo_name=repo_name,
                extra_instructions=None,
            )
            if raw_bundle.get("error"):
                return {"success": False, "error": raw_bundle.get("error", "Agent bundle failed")}
            ok, bundle, err = validate_agent_docs_bundle(raw_bundle)
            if not ok or bundle is None:
                return {"success": False, "error": err or "Agent bundle validation failed"}
            documentation = _agent_bundle_to_documentation(bundle)
        elif doc_type == "architecture":
            arch_result = llm_service.generate_architecture_documentation(
                prompt=prompt,
                context_chunks=search_results,
                repo_name=repo_name,
            )
            arch_title = arch_result.get("title")
            documentation = {
                "description": arch_result.get("description", "").strip(),
                "sections": arch_result.get("sections", []),
            }
        else:
            structured = llm_service.generate_structured_documentation(
                prompt=prompt,
                context_chunks=search_results,
                repo_name=repo_name,
            )
            documentation = structured.get("documentation", {"sections": []})
            code_reference_ids = structured.get("code_reference_ids", [])[:15]

        if not documentation or not documentation.get("sections"):
            return {"success": False, "error": "LLM returned empty documentation"}

        doc_title = arch_title or (doc.get("title") or "Documentation").strip()
        documentation_json = {
            "version": "1.0",
            "metadata": {
                "title": doc_title,
                "generated_at": datetime.utcnow().isoformat(),
                "prompt": prompt,
                "repository": repo_name,
                "branch": branch,
                "scope": "custom",
                "documentation_type": doc_type or None,
                "regenerated": True,
            },
            "documentation": documentation,
            "code_references": code_reference_ids,
            "file_paths": file_paths,
        }

        if s3_service and s3_key:
            s3_result = s3_service.upload_documentation(
                content=json.dumps(documentation_json, indent=2),
                s3_key=s3_key,
                content_type="application/json",
            )
            if not s3_result.get("success"):
                return {"success": False, "error": s3_result.get("error", "S3 upload failed")}

        mongodb_service.clear_documentation_sync_flags(documentation_id, file_paths=file_paths)
        return {"success": True}
    except Exception as e:
        mongodb_service.set_documentation_is_updating(documentation_id, False)
        return {"success": False, "error": str(e)}


async def regenerate_uml_diagram(diagram_id: str) -> Dict[str, Any]:
    """
    Regenerate one UML diagram: load diagram, vector search with stored prompt,
    same UML LLM as create, update MongoDB (diagramData, filePaths, clear flags), overwrite S3.
    Returns { "success": True } or { "success": False, "error": "..." }.
    """
    if not mongodb_service:
        return {"success": False, "error": "MongoDB not available"}
    if not llm_service:
        return {"success": False, "error": "LLM service not available"}
    if not vectorizer:
        return {"success": False, "error": "Vectorizer not available"}

    diagram_result = mongodb_service.get_uml_diagram_by_id(diagram_id)
    if not diagram_result.get("success"):
        return {"success": False, "error": diagram_result.get("error", "Diagram not found")}
    diagram = diagram_result["diagram"]

    org_id = diagram["organizationId"]
    repo_id = diagram["repositoryId"]
    branch = (diagram.get("branch") or "main").strip() or "main"
    prompt = (diagram.get("prompt") or "").strip()
    if not prompt:
        return {"success": False, "error": "Diagram has no stored prompt"}

    names_result = mongodb_service.get_organization_and_repo_for_collection(org_id, repo_id)
    if not names_result.get("success"):
        return {"success": False, "error": names_result.get("error", "Org/repo not found")}
    try:
        collection_name = build_collection_name(
            organization_name=names_result.get("organization_name"),
            organization_short_id=names_result.get("organization_short_id"),
            repository_name=names_result.get("repository_name"),
            branch=branch,
        )
    except ValueError as e:
        return {"success": False, "error": str(e)}

    repo_name = names_result.get("repo_full_name") or names_result.get("repository_name") or "repository"
    diagram_type = (diagram.get("type") or "class").lower()
    if diagram_type == "usecase":
        diagram_type = "use_case"
    s3_key = (diagram.get("s3Key") or "").strip()

    mongodb_service.set_uml_diagram_is_updating(diagram_id, True)
    try:
        search_results = vectorizer.search(
            collection_name=collection_name,
            query=prompt,
            top_k=20,
        )
        if not search_results:
            return {"success": False, "error": f"No chunks in collection '{collection_name}'"}

        file_paths = _file_paths_from_search_results(search_results)

        if diagram_type == "class":
            uml_result = llm_service.generate_uml_class_diagram(
                prompt=prompt,
                context_chunks=search_results,
                repo_name=repo_name,
            )
            if uml_result.get("error"):
                return {"success": False, "error": uml_result.get("error")}
            diagram_data = {
                "classes": uml_result.get("classes") or [],
                "relationships": uml_result.get("relationships") or [],
            }
        elif diagram_type == "sequence":
            uml_result = llm_service.generate_uml_sequence_diagram(
                prompt=prompt,
                context_chunks=search_results,
                repo_name=repo_name,
            )
            if uml_result.get("error"):
                return {"success": False, "error": uml_result.get("error")}
            diagram_data = {
                "lifelines": uml_result.get("lifelines") or [],
                "messages": uml_result.get("messages") or [],
                "steps": uml_result.get("steps") or [],
                "fragments": uml_result.get("fragments") or [],
            }
        elif diagram_type == "use_case":
            uml_result = llm_service.generate_uml_use_case_diagram(
                prompt=prompt,
                context_chunks=search_results,
                repo_name=repo_name,
            )
            if uml_result.get("error"):
                return {"success": False, "error": uml_result.get("error")}
            diagram_data = {
                "systemBoundary": uml_result.get("systemBoundary") or {},
                "actors": uml_result.get("actors") or [],
                "useCases": uml_result.get("useCases") or [],
                "relationships": uml_result.get("relationships") or [],
            }
        else:
            return {"success": False, "error": f"Unknown diagram type: {diagram_type}"}

        mongodb_service.clear_uml_diagram_sync_flags(
            diagram_id,
            diagram_data=diagram_data,
            file_paths=file_paths,
        )

        if s3_service and s3_key:
            payload = {**diagram_data, "file_paths": file_paths}
            s3_service.upload_documentation(
                content=json.dumps(payload),
                s3_key=s3_key,
                content_type="application/json",
            )

        return {"success": True}
    except Exception as e:
        mongodb_service.set_uml_diagram_is_updating(diagram_id, False)
        return {"success": False, "error": str(e)}
