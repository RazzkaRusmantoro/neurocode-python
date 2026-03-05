"""
Visual tree generation endpoints
"""
import json
import asyncio
from datetime import datetime
from fastapi import APIRouter, HTTPException

from neurocode.models.schemas import GenerateVisualTreeRequest
from neurocode.config import (
    github_fetcher,
    s3_service,
    tree_builder,
)

router = APIRouter()


@router.post("/api/generate-visual-tree")
async def generate_visual_tree(request: GenerateVisualTreeRequest):
    """
    Generate a visual repository tree.

    Pipeline:
    1. Fetch files from GitHub
    2. Parse code with tree-sitter (symbols, imports)
    3. Generate AI feature tree (high-level → code-level)
    4. Enrich files with AI descriptions
    5. Merge trees and upload JSON to S3

    Returns:
        Tree metadata including S3 location
    """
    try:
        print("\n" + "=" * 60, flush=True)
        print("VISUAL TREE GENERATION PIPELINE", flush=True)
        print("=" * 60, flush=True)
        print(f"Repository: {request.repo_full_name}", flush=True)
        print(f"Branch: {request.branch}", flush=True)
        print(f"organization_id: {request.organization_id or '(missing)'}", flush=True)
        print(f"repository_id: {request.repository_id or '(missing)'}", flush=True)
        has_token = bool(getattr(request, "github_token", None) and (request.github_token or "").strip())
        print(f"github_token: {'present' if has_token else 'MISSING or empty'}", flush=True)
        print("=" * 60, flush=True)

        if not request.organization_id or not request.repository_id:
            raise HTTPException(
                status_code=400,
                detail="organization_id and repository_id are required",
            )

        # Step 1: Fetch repository files
        print("\n[Step 1/4] Fetching files from GitHub...", flush=True)
        files = await github_fetcher.fetch_repository_files(
            repo_full_name=request.repo_full_name,
            access_token=request.github_token or "",
            branch=request.branch,
            path="",
        )
        print(f"✓ Fetched {len(files)} files", flush=True)

        if len(files) == 0:
            print("[VisualTree] No files returned. Check logs above for GitHubFetcher (branch SHA, tree, token).", flush=True)
            return {
                "success": False,
                "message": "No files found in repository",
                "repository": request.repo_full_name,
            }

        # Try to find README for context
        readme_content = ""
        for f in files:
            if f.get("path", "").lower() in ("readme.md", "readme.txt", "readme.rst"):
                readme_content = f.get("content", "")[:8000]
                break

        repo_display_name = request.repository_name or request.repo_full_name.split("/")[-1]

        # Step 2-3: Build tree (parsing + AI) — run in thread pool (synchronous LLM calls)
        if tree_builder is None:
            raise HTTPException(status_code=503, detail="Tree builder service not available")

        print("\n[Step 2/4] Building visual tree (parse + AI)...")
        tree_data = await asyncio.to_thread(
            tree_builder.build_tree,
            files,
            repo_display_name,
            readme_content,
        )
        print("✓ Visual tree built")

        # Step 4: Upload to S3
        if s3_service is None:
            raise HTTPException(status_code=503, detail="S3 service not available")

        print("\n[Step 3/4] Uploading tree to S3...")
        doc_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        s3_key = s3_service.generate_s3_key(
            organization_id=request.organization_id,
            repository_id=request.repository_id,
            branch=request.branch,
            scope="visual-tree",
            documentation_id=doc_id,
            file_extension="json",
        )

        tree_json_str = json.dumps(tree_data, indent=2, ensure_ascii=False)

        s3_result = s3_service.upload_documentation(
            content=tree_json_str,
            s3_key=s3_key,
            content_type="application/json",
        )

        if not s3_result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=f"S3 upload failed: {s3_result.get('error')}",
            )

        print(f"✓ Tree uploaded to S3: {s3_result['s3_key']}")
        print(f"  Size: {s3_result['content_size']} bytes")
        print("[Step 4/4] Done!")
        print("=" * 60 + "\n")

        return {
            "success": True,
            "repository": request.repo_full_name,
            "branch": request.branch,
            "files_count": len(files),
            "s3": {
                "s3_key": s3_result["s3_key"],
                "s3_bucket": s3_service.bucket_name,
                "s3_url": s3_result.get("s3_url", ""),
                "content_size": s3_result["content_size"],
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"\n[ERROR] Visual tree generation failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate visual tree: {str(e)}",
        )
