"""
Documentation generation endpoints
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, List, Dict, Any
import re
import json
from datetime import datetime

from neurocode.models.schemas import (
    GenerateDocumentationRequest,
    GenerateDocsRAGRequest,
    GetDocumentationRequest,
    GenerateUmlRequest,
)
from neurocode.config import (
    github_fetcher,
    storage_service,
    vectorizer,
    llm_service,
    s3_service,
    mongodb_service
)
from neurocode.services.index_pipeline import run_index_pipeline, build_collection_name
from neurocode.services.agent_docs_validation import validate_agent_docs_bundle
from neurocode.models.agent_docs import AgentDocsBundle

router = APIRouter()


def _agent_bundle_to_documentation(bundle: AgentDocsBundle) -> Dict[str, Any]:
    """
    Convert a validated agent docs bundle into the standard documentation shape,
    where **each generated .md file is shown as a copyable code snippet**.

    - Section 1 is the main GUIDE.md
    - Sections 2..N are individual rule .md files
    """

    guide = bundle.guide

    def _frontmatter_block(role: Optional[str], context: Optional[str]) -> str:
        lines: List[str] = ["----"]
        if role:
            lines.append(f"role: {role}")
        if context:
            lines.append(f"context: {context}")
        lines.append("----")
        return "\n".join(lines)

    sections: List[Dict[str, Any]] = []

    # Section 1: GUIDE.md as a full .md file inside a code block
    guide_role = "Main AI guide for this repository (load this first)."
    guide_context = guide.when_to_use.strip()

    guide_lines: List[str] = []
    guide_lines.append(_frontmatter_block(guide_role, guide_context))
    guide_lines.append("")
    guide_lines.append("# GUIDE")
    guide_lines.append("")
    guide_lines.append("## What this is for")
    guide_lines.append("")
    guide_lines.append(guide.description.strip())
    guide_lines.append("")
    guide_lines.append("## When to use")
    guide_lines.append("")
    guide_lines.append(guide.when_to_use.strip())
    guide_lines.append("")

    if guide.topic_pointers:
        guide_lines.append("## Topic pointers")
        guide_lines.append("")
        for ptr in guide.topic_pointers:
            guide_lines.append(f"### {ptr.title}")
            guide_lines.append("")
            guide_lines.append(ptr.body.strip())
            guide_lines.append("")
            guide_lines.append(f"Reference rule file: `{ptr.rule_path}`")
            guide_lines.append("")

    guide_lines.append("## How to use")
    guide_lines.append("")
    for item in guide.how_to_use:
        guide_lines.append(f"- `{item.path}` – {item.description}")

    guide_md_content = "\n".join(guide_lines).strip()
    guide_md_code_block = f"```md\n{guide_md_content}\n```"

    sections.append(
        {
            "id": "1",
            "title": "GUIDE.md",
            "description": guide_md_code_block,
            "code_references": [],
            "subsections": [],
        }
    )

    # Sections 2..N: Each rule as its own .md file inside a code block
    for idx, rule in enumerate(bundle.rules, start=2):
        rule_role = rule.role or f"Rule for {rule.name}"
        rule_context = rule.description.strip()

        rule_lines: List[str] = []
        rule_lines.append(_frontmatter_block(rule_role, rule_context))
        rule_lines.append("")
        rule_lines.append(f"# {rule.name.replace('-', ' ').title()}")
        rule_lines.append("")

        if rule.prerequisites:
            rule_lines.append("## Prerequisites")
            rule_lines.append("")
            for p in rule.prerequisites:
                rule_lines.append(f"- {p}")
            rule_lines.append("")

        # Main playbook body (already markdown)
        rule_lines.append(rule.body.strip())

        if rule.input:
            rule_lines.append("")
            rule_lines.append("## Input")
            rule_lines.append("")
            rule_lines.append(rule.input.strip())

        if rule.output:
            rule_lines.append("")
            rule_lines.append("## Output")
            rule_lines.append("")
            rule_lines.append(rule.output.strip())

        rule_md_content = "\n".join(rule_lines).strip()
        rule_md_code_block = f"```md\n{rule_md_content}\n```"

        sections.append(
            {
                "id": str(idx),
                "title": f"{rule.name}.md",
                "description": rule_md_code_block,
                "code_references": [],
                "subsections": [],
            }
        )

    return {
        "description": guide.description,
        "sections": sections,
    }


@router.post("/api/generate-documentation")
async def generate_documentation(request: GenerateDocumentationRequest):
    """
    Generate documentation for a GitHub repository
    
    Full pipeline:
    1. Fetch files from GitHub
    2. Parse code (extract symbols, dependencies, calls)
    3. Chunk code (create semantic chunks for vectorization)
    4. Save results locally
    
    Args:
        request: GenerateDocumentationRequest with:
            - github_token: GitHub access token
            - repo_full_name: Repository full name (e.g., "owner/repo")
            - branch: Branch name (default: "main")
            - scope: Documentation scope (default: "repository")
            - target: Optional target path/module
    
    Returns:
        Documentation generation results with saved file paths
    """
    try:
        print("\n" + "="*60)
        print("DOCUMENTATION GENERATION PIPELINE")
        print("="*60)
        print(f"Repository: {request.repo_full_name}")
        print(f"Branch: {request.branch}")
        print(f"Scope: {request.scope}")
        print(f"Target: {request.target or 'N/A'}")
        print("="*60)
        result = await run_index_pipeline(
            github_token=request.github_token,
            repo_full_name=request.repo_full_name,
            branch=request.branch or "main",
            target=request.target,
            organization_id=request.organization_id,
            organization_short_id=request.organization_short_id,
            organization_name=request.organization_name,
            repository_id=request.repository_id,
            repository_name=request.repository_name,
        )
        if not result.get("success"):
            return result
        result["scope"] = request.scope
        result["target"] = request.target
        result["message"] = "Analysis complete. Results saved locally and vectorized."
        print("="*60 + "\n")
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"\n[ERROR] Failed to generate documentation: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate documentation: {str(e)}"
        )


@router.post("/api/generate-docs-rag")
async def generate_docs_rag(request: GenerateDocsRAGRequest):
    """
    Generate documentation using RAG (Retrieval Augmented Generation)
    
    Full pipeline (same as generate-documentation, then RAG):
    1. Fetch files from GitHub
    2. Parse code (extract symbols, dependencies, calls)
    3. Chunk code (create semantic chunks for vectorization)
    4. Save results locally
    5. Vectorize chunks (if not already done)
    6. Search vector DB for relevant chunks based on user prompt
    7. Generate documentation with Claude using retrieved chunks
    8. Return generated documentation
    """
    try:
        if not llm_service:
            raise HTTPException(
                status_code=500,
                detail="LLM service not available. Please set ANTHROPIC_API_KEY environment variable."
            )

        print("\n" + "="*60)
        print("RAG DOCUMENTATION GENERATION (FULL PIPELINE)")
        print("="*60)
        print(f"Repository: {request.repo_full_name}")
        print(f"Branch: {request.branch or 'main'}")
        print(f"Prompt: {request.prompt}")
        print("="*60)

        if not request.organization_short_id or not request.repository_name:
            raise HTTPException(
                status_code=400,
                detail="organization_short_id and repository_name are required for collection naming",
            )

        # Resolve branch (same as index pipeline) so collection name matches
        branch = request.branch or "main"
        if not branch.strip() or branch.strip().lower() in ("main", "master"):
            resolved = await github_fetcher.get_default_branch(
                request.repo_full_name, request.github_token
            )
            if resolved:
                branch = resolved
                print(f"[generate-docs-rag] Using repo default branch: {branch}")

        collection_name = build_collection_name(
            request.organization_name,
            request.organization_short_id,
            request.repository_name,
            branch,
        )
        existing_count = vectorizer.vector_db.get_collection_count(collection_name)

        if existing_count > 0:
            # Collection already exists: skip index pipeline, use existing vectors
            print(f"\n[Skip] Collection '{collection_name}' exists ({existing_count} chunks). Retrieving only.")
            result = {
                "success": True,
                "branch": branch,
                "metadata": {
                    "totalChunks": existing_count,
                    "totalFiles": 0,
                    "totalFunctions": 0,
                    "totalClasses": 0,
                    "languages": [],
                    "parseErrors": 0,
                },
                "vectorization": {
                    "success": True,
                    "collection_name": collection_name,
                },
            }
        else:
            # Steps 1–5: Run full index pipeline (fetch → parse → chunk → enrich → save → vectorize)
            result = await run_index_pipeline(
                github_token=request.github_token,
                repo_full_name=request.repo_full_name,
                branch=request.branch or "main",
                target=None,
                organization_id=request.organization_id,
                organization_short_id=request.organization_short_id,
                organization_name=request.organization_name,
                repository_id=request.repository_id,
                repository_name=request.repository_name,
            )
            if not result.get("success"):
                raise HTTPException(
                    status_code=400 if "required" in str(result.get("message", "")).lower() else 500,
                    detail=result.get("message", "Index pipeline failed"),
                )
            vectorization = result.get("vectorization")
            if not vectorization or not vectorization.get("success"):
                raise HTTPException(
                    status_code=500,
                    detail="Index pipeline completed but vectorization failed.",
                )
            collection_name = vectorization["collection_name"]
            branch = result.get("branch", request.branch or "main")

        index_metadata = result.get("metadata", {})

        # Step 6: Search vector DB for relevant chunks based on prompt
        print(f"\n[Step 6/10] Searching vector DB for relevant chunks...")
        print(f"Query: {request.prompt}")
        
        # Search vector DB for relevant chunks
        search_results = vectorizer.search(
            collection_name=collection_name,
            query=request.prompt,
            top_k=request.top_k or 20
        )
        
        if not search_results:
            raise HTTPException(
                status_code=404,
                detail=f"No chunks found in collection '{collection_name}'"
            )
        
        print(f"✓ Found {len(search_results)} relevant chunks")
        
        # Step 7: Generate documentation (branch: AI-Agent custom vs standard)
        documentation = None
        code_reference_ids_from_llm = []
        code_reference_details = []
        arch_result = None  # used for architecture doc title when type is architecture

        if request.documentation_type == "aiAgent" and (request.ai_agent_doc_kind or "") == "custom":
            print(f"\n[Step 7/10] Generating AI-Agent docs bundle (guide + rules) with Claude...")
            raw_bundle = llm_service.generate_agent_docs_bundle(
                prompt=request.prompt,
                context_chunks=search_results,
                repo_name=request.repository_name or request.repo_full_name,
                extra_instructions=(request.ai_agent_extra_instructions or "").strip(),
            )
            if raw_bundle.get("error"):
                raise HTTPException(
                    status_code=422,
                    detail=f"AI-Agent bundle generation failed: {raw_bundle.get('error')}",
                )
            ok, bundle, err = validate_agent_docs_bundle(raw_bundle)
            if not ok or bundle is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"AI-Agent bundle validation failed: {err}",
                )
            documentation = _agent_bundle_to_documentation(bundle)
            code_reference_ids_from_llm = []
            code_reference_details = []
            print(f"✓ Generated guide + {len(bundle.rules)} rules")
        elif request.documentation_type == "architecture":
            print(f"\n[Step 7/10] Generating System Architecture documentation with Claude...")
            arch_result = llm_service.generate_architecture_documentation(
                prompt=request.prompt,
                context_chunks=search_results,
                repo_name=request.repository_name or request.repo_full_name,
            )
            documentation = {
                "description": arch_result.get("description", "").strip(),
                "sections": arch_result.get("sections", []),
            }
            code_reference_ids_from_llm = []
            code_reference_details = []
            print(f"✓ Generated System Architecture documentation ({len(documentation['sections'])} sections)")
        else:
            print(f"\n[Step 7/10] Generating structured documentation with Claude...")
            structured_result = llm_service.generate_structured_documentation(
                prompt=request.prompt,
                context_chunks=search_results,
                repo_name=request.repository_name or request.repo_full_name
            )
            documentation = structured_result.get("documentation", {"sections": []})
            code_reference_ids_from_llm = structured_result.get("code_reference_ids", [])
        
        # Validate limits
        if len(code_reference_ids_from_llm) > 15:
            print(f"  ⚠ Warning: {len(code_reference_ids_from_llm)} code references found, limiting to 15")
            code_reference_ids_from_llm = code_reference_ids_from_llm[:15]
        
        # Extract code reference details
        code_reference_details = []
        
        for ref_id in code_reference_ids_from_llm:
            matched = False
            for chunk in search_results:
                metadata = chunk.get("metadata", {})
                function_name = metadata.get("function_name", "")
                class_name = metadata.get("class_name", "")
                method_name = metadata.get("method_name", "")
                file_path = metadata.get("file_path", "")
                content = chunk.get("content", "")
                
                # Match by name
                matched_name = None
                ref_type = None
                
                if function_name and (ref_id.lower() == function_name.lower() or ref_id.lower().replace("_", "") == function_name.lower().replace("_", "")):
                    matched_name = function_name
                    ref_type = "function"
                elif class_name and (ref_id.lower() == class_name.lower() or ref_id.lower().replace("_", "") == class_name.lower().replace("_", "")):
                    matched_name = class_name
                    ref_type = "class"
                elif method_name and (ref_id.lower() == method_name.lower() or ref_id.lower().replace("_", "") == method_name.lower().replace("_", "")):
                    matched_name = method_name
                    ref_type = "method"
                
                if matched_name:
                    # Extract the actual code snippet (raw code)
                    code_snippet = None
                    start_line = metadata.get("start_line", 0)
                    end_line = metadata.get("end_line", 0)
                    
                    if start_line and end_line and start_line > 0:
                        lines = content.split('\n')
                        if len(lines) >= end_line:
                            code_snippet = '\n'.join(lines[start_line-1:end_line])
                    
                    # If line-based extraction didn't work, try pattern matching
                    if not code_snippet or len(code_snippet.strip()) < 10:
                        if ref_type in ["function", "method"]:
                            func_patterns = [
                                r'(?:function|const|async\s+function)\s+' + re.escape(matched_name) + r'[^{]*\{[^}]*\}',
                                r'def\s+' + re.escape(matched_name) + r'\([^)]*\):.*?(?=\n\s*(?:def|class|\Z))',
                            ]
                            for pattern in func_patterns:
                                match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
                                if match:
                                    code_snippet = match.group(0).strip()
                                    break
                        elif ref_type == "class":
                            class_patterns = [
                                r'class\s+' + re.escape(matched_name) + r'[^{]*\{[^}]*\}',
                                r'class\s+' + re.escape(matched_name) + r'.*?(?=\n\s*(?:class|def|\Z))',
                            ]
                            for pattern in class_patterns:
                                match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
                                if match:
                                    code_snippet = match.group(0).strip()
                                    break
                    
                    # If still no code, use the entire chunk content as fallback
                    if not code_snippet or len(code_snippet.strip()) < 10:
                        code_snippet = content[:5000]  # Limit to 5000 chars
                    
                    # Extract parameters for functions/methods
                    parameters = []
                    if ref_type in ["function", "method"]:
                        sig_patterns = [
                            r'function\s+' + re.escape(matched_name) + r'\s*\(([^)]*)\)',
                            r'const\s+' + re.escape(matched_name) + r'\s*=\s*(?:async\s+)?\(([^)]*)\)',
                            r'def\s+' + re.escape(matched_name) + r'\s*\(([^)]*)\)',
                            r'(?:public|private|protected)?\s*(?:async\s+)?' + re.escape(matched_name) + r'\s*\(([^)]*)\)',
                        ]
                        
                        for pattern in sig_patterns:
                            match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
                            if match:
                                params_str = match.group(1).strip()
                                if params_str:
                                    param_list = []
                                    current_param = ""
                                    depth = 0
                                    for char in params_str:
                                        if char in '([{':
                                            depth += 1
                                        elif char in ')]}':
                                            depth -= 1
                                        elif char == ',' and depth == 0:
                                            if current_param.strip():
                                                param_list.append(current_param.strip())
                                            current_param = ""
                                            continue
                                        current_param += char
                                    if current_param.strip():
                                        param_list.append(current_param.strip())
                                    
                                    for param in param_list:
                                        param = param.strip()
                                        if not param or param in ['...', '...rest', '...args']:
                                            continue
                                        
                                        param_name = param.split(':')[0].split('=')[0].split('?')[0].strip()
                                        
                                        default_value = None
                                        if '=' in param:
                                            default_part = param.split('=', 1)[1].strip()
                                            default_part = re.sub(r'^[^=]*=', '', default_part, count=1) if ':' in param else default_part
                                            default_value = default_part.split(',')[0].strip() if default_part else None
                                        
                                        if param_name:
                                            try:
                                                param_prompt = f"""Given this function parameter from the code:

Parameter: {param_name}
Full parameter definition: {param}
Function: {matched_name}
Code context:
{content[:2000]}

Generate a clear, documentation-style description for this parameter (1-2 sentences). Describe what the parameter is used for and its purpose in the function. Write it in a professional documentation format, similar to scikit-learn or Python documentation.

Example format:
"The number of samples to draw from the dataset. Must be greater than 0."

Description:"""
                                                
                                                param_response = llm_service.client.messages.create(
                                                    model=llm_service.model,
                                                    max_tokens=150,
                                                    messages=[{
                                                        "role": "user",
                                                        "content": param_prompt
                                                    }]
                                                )
                                                
                                                if param_response.content and len(param_response.content) > 0:
                                                    param_description = param_response.content[0].text.strip()
                                                    param_description = param_description.split('\n')[0].strip()
                                                    param_description = param_description.strip('"').strip("'")
                                                else:
                                                    param_description = f"The {param_name.replace('_', ' ')} parameter."
                                            except Exception as e:
                                                param_description = f"The {param_name.replace('_', ' ')} parameter."
                                            
                                            parameters.append({
                                                "name": param_name,
                                                "description": param_description,
                                                "default": default_value
                                            })
                                break
                    
                    # Extract description from docstrings/comments
                    description = None
                    
                    doc_patterns = [
                        (r'/\*\*([\s\S]*?)\*/', lambda m: m.group(1)),  # JSDoc
                        (r'"""([\s\S]*?)"""', lambda m: m.group(1)),  # Python docstring
                        (r"'''([\s\S]*?)'''", lambda m: m.group(1)),  # Python docstring
                    ]
                    
                    for pattern, extractor in doc_patterns:
                        matches = re.findall(pattern, content, re.MULTILINE | re.DOTALL)
                        if matches:
                            doc = matches[0] if isinstance(matches[0], str) else extractor(matches[0]) if matches[0] else ""
                            if doc:
                                doc = re.sub(r'^\s*\*\s*', '', doc, flags=re.MULTILINE)
                                doc = doc.strip()
                                if doc and len(doc) > 20:
                                    description = doc[:800]
                                    break
                    
                    # If no docstring or description is too short, generate a proper description
                    if not description or len(description) < 50:
                        try:
                            description_prompt = f"""Generate a concise but detailed description for this {ref_type} from the codebase.

{ref_type.capitalize()} name: {matched_name}
File: {file_path}

Code:
{content[:2000]}
Generate a description similar to scikit-learn documentation style. Be specific about what it does, its purpose, and key functionality. Keep it concise but informative (2-4 sentences max).

**CRITICAL INSTRUCTIONS - READ CAREFULLY:**
1. Do NOT include the {ref_type} name at the beginning. Just describe what it does.
2. **ABSOLUTELY FORBIDDEN: DO NOT copy ANY text from the code, including:**
   - Prompt strings (f-strings with instructions like "You are an expert...")
   - Docstrings or comments
   - Instruction text
   - Any string literals
   - Template text
3. **YOU MUST: Analyze the FUNCTION'S BEHAVIOR, not its text content:**
   - What API does it call? (e.g., "calls OpenAI API")
   - What does it process? (e.g., "processes metadata")
   - What does it return? (e.g., "returns formatted citations")
   - What is its purpose? (e.g., "generates academic citations")
4. **If you see prompt strings in the code, they are DATA the function uses, NOT the function's description.**
   - Example: If code has `prompt = "You are an expert..."`, DO NOT copy that.
   - Instead, say: "Generates formatted citations using AI based on metadata"
5. Write COMPLETELY ORIGINAL descriptions based on code logic analysis, never copy text from code.

Example format (correct):
"A sequence of data transformers with an optional final predictor. Pipeline allows you to sequentially apply a list of transformers to preprocess the data and, if desired, conclude the sequence with a final predictor for predictive modeling."

Example format (wrong - do NOT do this):
"Pipeline: A sequence of data transformers..."

Example of what NOT to do (copying prompt strings):
If the code has: `prompt = "You are an expert..."` - DO NOT copy that prompt. Instead, describe that the function generates citations using AI.

Description:"""
                            
                            llm_response = llm_service.client.messages.create(
                                model=llm_service.model,
                                max_tokens=300,
                                system="You are a technical documentation expert. You analyze code behavior and write original descriptions. You NEVER copy text from code - you analyze what functions DO and describe their purpose and behavior.",
                                messages=[{
                                    "role": "user",
                                    "content": description_prompt
                                }]
                            )
                            
                            if llm_response.content and len(llm_response.content) > 0:
                                generated_desc = llm_response.content[0].text.strip()
                                if generated_desc and len(generated_desc) > 30:
                                    description = generated_desc
                        except Exception as e:
                            print(f"  ⚠ Failed to generate LLM description for {matched_name}: {e}")
                        
                        if not description or len(description) < 30:
                            if ref_type == "class":
                                description = "A class that provides functionality for managing operations and state within the application."
                            elif ref_type == "function":
                                description = "A function that processes input data and returns transformed output according to its implementation."
                            else:
                                description = "A method that performs operations on the class instance."
                    
                    # Clean description - remove name prefix if present
                    if description:
                        description = re.sub(r'^' + re.escape(matched_name) + r'[:\s]+', '', description, flags=re.IGNORECASE)
                        description = re.sub(r'^' + re.escape(matched_name) + r'\s+is\s+', '', description, flags=re.IGNORECASE)
                        description = description.strip()
                    
                    # Generate signature string
                    module_path = file_path.replace("\\", "/").rsplit("/", 1)[0] if "/" in file_path or "\\" in file_path else None
                    signature_parts = []
                    
                    if module_path:
                        module_path = module_path.replace("app/", "").replace("src/", "").replace("lib/", "")
                        signature_parts.append(module_path.replace("/", "."))
                    
                    signature_parts.append(matched_name)
                    
                    param_strings = []
                    if parameters:
                        for param in parameters:
                            param_name = param.get("name", "")
                            default_val = param.get("default")
                            
                            if default_val:
                                param_strings.append(f"{param_name}={default_val}")
                            else:
                                if 'id' in param_name.lower() or 'key' in param_name.lower():
                                    sample_val = "'example_id'"
                                elif 'data' in param_name.lower() or 'input' in param_name.lower():
                                    sample_val = "data"
                                elif 'config' in param_name.lower() or 'options' in param_name.lower():
                                    sample_val = "None"
                                elif 'callback' in param_name.lower() or 'handler' in param_name.lower():
                                    sample_val = "callback"
                                elif 'count' in param_name.lower() or 'num' in param_name.lower() or 'size' in param_name.lower():
                                    sample_val = "5"
                                elif 'flag' in param_name.lower() or 'enable' in param_name.lower() or 'is_' in param_name.lower():
                                    sample_val = "True"
                                else:
                                    sample_val = "None"
                                
                                param_strings.append(f"{param_name}={sample_val}")
                    
                    signature_str = ".".join(signature_parts)
                    if param_strings:
                        signature_str += f"({', '.join(param_strings)})"
                    else:
                        signature_str += "()"
                    
                    code_reference_details.append({
                        "referenceId": ref_id,
                        "name": matched_name,
                        "type": ref_type,
                        "description": description,
                        "filePath": file_path,
                        "module": file_path.replace("\\", "/").rsplit("/", 1)[0] if "/" in file_path or "\\" in file_path else None,
                        "parameters": parameters if parameters else None,
                        "code": code_snippet,
                        "signature": signature_str
                    })
                    matched = True
                    break
            
            # If not found, try to find it in code context (might be an import, instance, or library function)
            if not matched:
                # Search through all chunks for any mention of this reference
                found_context = None
                found_file = None
                for chunk in search_results:
                    content = chunk.get("content", "")
                    metadata = chunk.get("metadata", {})
                    file_path = metadata.get("file_path", "")
                    
                    # Check if ref_id appears in the content (import, usage, assignment, etc.)
                    if ref_id in content or ref_id.replace("_", "") in content.replace("_", ""):
                        # Try to find the context around it
                        lines = content.split('\n')
                        for i, line in enumerate(lines):
                            if ref_id in line or ref_id.replace("_", "") in line.replace("_", ""):
                                # Get context (5 lines before and after)
                                start = max(0, i - 5)
                                end = min(len(lines), i + 6)
                                found_context = '\n'.join(lines[start:end])
                                found_file = file_path
                                break
                        if found_context:
                            break
                
                # Generate a better description using LLM with context
                description = None
                if found_context:
                    try:
                        # Extract how it's used from the documentation
                        doc_context = ""
                        for section in documentation.get("sections", []):
                            desc = section.get("description", "")
                            if f"[[{ref_id}]]" in desc or ref_id in desc:
                                # Extract the sentence mentioning it
                                sentences = desc.split('.')
                                for sent in sentences:
                                    if ref_id in sent or f"[[{ref_id}]]" in sent:
                                        doc_context = sent.strip()
                                        break
                                if doc_context:
                                    break
                        
                        description_prompt = f"""Generate a concise but detailed description for this code reference: {ref_id}

Code context where it appears:
{found_context[:1500]}

Documentation context (how it's described):
{doc_context if doc_context else "Not mentioned in documentation"}

Based on the code context and how it's used, describe what this code element does. Be specific about:
- What it is (function, class, module, instance, etc.)
- What it does or what it's used for
- Key functionality based on the code context

Keep it to 2-3 sentences. Write in scikit-learn documentation style.

**CRITICAL**: 
- If it's an import (like `from X import Y` or `import X`), describe what the imported module/function does
- If it's an instance (like `model = SomeModel()`), describe what the instance is used for
- If it's a library function (like `util.cos_sim`), describe what the library function does
- Analyze the code context to understand its purpose, don't just say "a code element"

Description:"""
                        
                        llm_response = llm_service.client.messages.create(
                            model=llm_service.model_fast,  # Use cheaper model
                            max_tokens=200,
                            system="You are a technical documentation expert. Analyze code context and write specific, helpful descriptions.",
                            messages=[{
                                "role": "user",
                                "content": description_prompt
                            }]
                        )
                        
                        if llm_response.content and len(llm_response.content) > 0:
                            generated_desc = llm_response.content[0].text.strip()
                            if generated_desc and len(generated_desc) > 30:
                                description = generated_desc
                    except Exception as e:
                        print(f"  ⚠ Failed to generate description for unmatched reference {ref_id}: {e}")
                
                # If still no description, try to infer from the name
                if not description or len(description) < 30:
                    # Infer type and purpose from name
                    name_lower = ref_id.lower()
                    if 'model' in name_lower:
                        if 'sbert' in name_lower or 'bert' in name_lower:
                            description = "A Sentence-BERT model instance used for generating sentence embeddings and computing semantic similarity between text."
                        elif 'kw' in name_lower or 'keyword' in name_lower:
                            description = "A keyword extraction model instance used for extracting relevant keywords and keyphrases from text."
                        else:
                            description = f"A model instance ({ref_id}) used for processing and analyzing data."
                    elif 'nlp' in name_lower:
                        description = "A natural language processing pipeline instance (likely spaCy) used for text analysis, tokenization, and linguistic feature extraction."
                    elif 'util' in name_lower or 'cos' in name_lower or 'sim' in name_lower:
                        description = "A utility function for computing cosine similarity between vectors, typically used for measuring semantic similarity between text embeddings."
                    elif 'client' in name_lower and 'chat' in name_lower:
                        description = "An OpenAI API client method for creating chat completions, used to interact with GPT models for text generation and analysis."
                    elif 'get_' in name_lower or 'fetch_' in name_lower or 'retrieve_' in name_lower:
                        description = f"A function ({ref_id}) that retrieves or fetches data from a source."
                    elif 'generate_' in name_lower or 'create_' in name_lower:
                        description = f"A function ({ref_id}) that generates or creates new content or data."
                    elif 'process_' in name_lower or 'handle_' in name_lower:
                        description = f"A function ({ref_id}) that processes or handles input data."
                    else:
                        description = f"A code element ({ref_id}) that performs operations as defined in the codebase."
                
                code_reference_details.append({
                    "referenceId": ref_id,
                    "name": ref_id,
                    "type": "function",
                    "description": description,
                    "filePath": found_file,
                    "module": found_file.replace("\\", "/").rsplit("/", 1)[0] if found_file and ("/" in found_file or "\\" in found_file) else None,
                    "parameters": None,
                    "code": found_context[:2000] if found_context else None
                })
        
        
        # Calculate documentation length for logging
        doc_length = len(json.dumps(documentation))
        print(f"✓ Documentation generated ({doc_length} characters)")
        print(f"✓ Sections: {len(documentation.get('sections', []))}")
        print(f"✓ Code references: {len(code_reference_ids_from_llm)}")
        
        # Extract title and description from documentation structure
        def extract_title(doc_data: dict, prompt: str) -> str:
            """Extract a title from documentation structure"""
            sections = doc_data.get("sections", [])
            if sections and len(sections) > 0:
                first_section = sections[0]
                title = first_section.get("title", "")
                if title and len(title) > 0 and len(title) <= 100:
                    return title
            
            if sections and len(sections) > 0:
                first_section = sections[0]
                description = first_section.get("description", "").strip()
                if description:
                    sentences = re.split(r'[.!?]\s+', description)
                    if sentences and sentences[0]:
                        title = sentences[0].strip()
                        if len(title) > 0:
                            return title[:100]
            
            if prompt:
                title = prompt[:60].strip()
                if len(title) < len(prompt):
                    title += "..."
                return title
            
            return "Documentation"
        
        doc_title = (
            arch_result.get("title", "System Architecture")
            if arch_result is not None
            else extract_title(documentation, request.prompt)
        )
        doc_description = documentation.get("description", "").strip()
        print(f"✓ Extracted title: {doc_title}")
        if doc_description:
            print(f"✓ Extracted description: {doc_description[:100]}...")
        
        # Step 8: Upsert code references to MongoDB
        code_reference_ids = []
        
        if mongodb_service and request.organization_id and request.repository_id:
            print(f"\n[Step 8/10] Upserting code references to MongoDB...")
            
            for ref in code_reference_details:
                ref_id = ref.get("referenceId")
                if not ref_id:
                    continue
                
                result = mongodb_service.upsert_code_reference(
                    organization_id=request.organization_id,
                    repository_id=request.repository_id,
                    reference_id=ref_id,
                    name=ref.get("name", ""),
                    reference_type=ref.get("type", "function"),
                    description=ref.get("description", ""),
                    module=ref.get("module"),
                    file_path=ref.get("filePath"),
                    signature=ref.get("signature"),
                    parameters=ref.get("parameters"),
                    returns=ref.get("returns"),
                    examples=ref.get("examples"),
                    see_also=ref.get("seeAlso"),
                    code=ref.get("code")
                )
                
                if result.get("success"):
                    if ref_id not in code_reference_ids:
                        code_reference_ids.append(ref_id)
                    action = result.get("action", "unknown")
                    print(f"  ✓ Code reference '{ref_id}': {action}")
                else:
                    print(f"  ⚠ Failed to upsert code reference '{ref_id}': {result.get('error')}")
            
            for ref_id in code_reference_ids_from_llm:
                if ref_id not in code_reference_ids:
                    code_reference_ids.append(ref_id)
                    if ref_id not in [r.get("referenceId") for r in code_reference_details]:
                        print(f"  ⚠ Code reference ID '{ref_id}' has no details - will not be stored in MongoDB")
            
            print(f"✓ Upserted {len(code_reference_ids)} code references")
        else:
            if not mongodb_service:
                print(f"\n[Step 8/10] MongoDB service not available, skipping code references")
            else:
                print(f"\n[Step 8/10] Missing organization_id or repository_id, skipping MongoDB upsert")
        
        # Step 9: Save documentation locally (for backup/reference)
        print(f"\n[Step 9/10] Saving documentation to local storage...")
        doc_metadata = {
            "collection_name": collection_name,
            "chunks_used": len(search_results),
            "chunks": [
                {
                    "file_path": chunk.get("metadata", {}).get("file_path", ""),
                    "function_name": chunk.get("metadata", {}).get("function_name", ""),
                    "score": chunk.get("score", 0)
                }
                for chunk in search_results
            ]
        }
        
        def documentation_to_markdown(doc_data: dict) -> str:
            """Convert documentation structure to markdown format"""
            markdown_parts = []
            sections = doc_data.get("sections", [])
            
            def process_section(section, level=1):
                section_id = section.get("id", "")
                title = section.get("title", "")
                description = section.get("description", "")
                code_refs = section.get("code_references", [])
                subsections = section.get("subsections", [])
                
                if title:
                    markdown_parts.append(f"{'#' * level} {section_id}. {title}\n")
                
                if description:
                    markdown_parts.append(description + "\n\n")
                
                if code_refs:
                    markdown_parts.append("**Code References:** " + ", ".join([f"`{ref}`" for ref in code_refs]) + "\n\n")
                
                for subsection in subsections:
                    process_section(subsection, level + 1)
            
            for section in sections:
                process_section(section)
            
            return "\n".join(markdown_parts)
        
        documentation_markdown = documentation_to_markdown(documentation)
        
        doc_saved_paths = storage_service.save_documentation(
            repo_full_name=request.repo_full_name,
            branch=branch,
            prompt=request.prompt,
            documentation=documentation_markdown,
            metadata=doc_metadata
        )
        
        print(f"✓ Documentation saved to: {doc_saved_paths['documentation_file']}")
        
        # Step 10: Upload documentation to S3
        s3_result = None
        s3_key = None
        if s3_service:
            print(f"\n[Step 10/10] Uploading documentation to S3...")
            
            if not request.organization_id or not request.repository_id:
                print("⚠ Missing organization_id or repository_id, skipping S3 upload")
            else:
                doc_id = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                s3_key = s3_service.generate_s3_key(
                    organization_id=request.organization_id,
                    repository_id=request.repository_id,
                    branch=branch,
                    scope="custom",
                    documentation_id=doc_id,
                    file_extension="json"
                )
                
                documentation_json = {
                    "version": "1.0",
                    "metadata": {
                        "title": doc_title,
                        "generated_at": datetime.now().isoformat(),
                        "prompt": request.prompt,
                        "repository": request.repo_full_name,
                        "branch": branch,
                        "scope": "custom",
                        "documentation_type": getattr(request, "documentation_type", None),
                        "ai_agent_doc_kind": getattr(request, "ai_agent_doc_kind", None),
                    },
                    "documentation": documentation,
                    "code_references": code_reference_ids
                }
                
                documentation_json_str = json.dumps(documentation_json, indent=2)
                
                s3_result = s3_service.upload_documentation(
                    content=documentation_json_str,
                    s3_key=s3_key,
                    content_type="application/json"
                )
                
                if s3_result.get("success"):
                    print(f"✓ Documentation uploaded to S3: {s3_result['s3_key']}")
                    print(f"  Size: {s3_result['content_size']} bytes")
                else:
                    print(f"⚠ S3 upload failed: {s3_result.get('error')}")
        else:
            print(f"\n[Step 10/10] S3 service not available, skipping S3 upload")
        
        print("="*60 + "\n")
        
        # Return results
        result = {
            "success": True,
            "prompt": request.prompt,
            "title": doc_title,
            "description": doc_description if doc_description else None,
            "repository": request.repo_full_name,
            "branch": branch,
            "collection_name": collection_name,
            "chunks_used": len(search_results),
            "metadata": index_metadata,
            "saved_paths": doc_saved_paths,
            "chunks": doc_metadata["chunks"],
            "code_reference_ids": code_reference_ids
        }
        
        if s3_result and s3_result.get("success"):
            result["s3"] = {
                "s3_key": s3_result["s3_key"],
                "s3_bucket": s3_service.bucket_name,
                "s3_url": s3_result["s3_url"],
                "content_size": s3_result["content_size"]
            }
            # Include documentation type in response so Next.js can store in MongoDB
            result["documentation_type"] = getattr(request, "documentation_type", None)
            result["ai_agent_doc_kind"] = getattr(request, "ai_agent_doc_kind", None)
        else:
            result["documentation"] = documentation
        
        return result
        
    except HTTPException as e:
        print(f"[ERROR] RAG generation failed: {e.detail}")
        raise e
    except Exception as e:
        print(f"[ERROR] RAG generation failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate documentation: {str(e)}"
        )


@router.post("/api/get-documentation")
async def get_documentation(request: GetDocumentationRequest):
    """
    Retrieve documentation content from S3
    
    Args:
        request: GetDocumentationRequest with:
            - s3_key: S3 object key/path
            - s3_bucket: Optional bucket name (uses default if not provided)
    
    Returns:
        Documentation content from S3
    """
    if s3_service is None:
        raise HTTPException(
            status_code=503,
            detail="S3 service not initialized. Please set AWS credentials in environment variables."
        )
    
    try:
        # Use provided bucket or default from service
        bucket = request.s3_bucket or s3_service.bucket_name
        
        # Get documentation from S3
        result = s3_service.get_documentation(request.s3_key)
        
        if result.get("success"):
            return {
                "success": True,
                "content": result["content"],
                "content_type": result.get("content_type", "application/json"),
                "content_size": result.get("content_size", 0),
                "last_modified": result.get("last_modified")
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=result.get("error", "Documentation not found")
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve documentation: {str(e)}"
        )


def _uml_slug_from_prompt(prompt: str, diagram_type: str = "class") -> str:
    """Build a URL-safe slug from user prompt and diagram type."""
    import re
    raw = (prompt or "").strip()[:60]
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-") or "diagram"
    return f"{diagram_type}-{slug}"


def _log_rag(msg: str) -> None:
    """Print RAG step so logs appear immediately."""
    print(msg, flush=True)


@router.post("/api/generate-uml")
async def generate_uml(request: GenerateUmlRequest):
    """
    Generate a UML diagram (e.g. class diagram) using RAG: vector search + LLM structured output.
    Saves to MongoDB (uml_diagrams) and uploads JSON to S3 for backup.
    """
    if not llm_service:
        raise HTTPException(
            status_code=500,
            detail="LLM service not available. Set ANTHROPIC_API_KEY.",
        )
    if not request.organization_short_id or not request.repository_name:
        raise HTTPException(
            status_code=400,
            detail="organization_short_id and repository_name are required",
        )

    diagram_type = (request.diagram_type or "class").lower()
    if diagram_type == "usecase":
        diagram_type = "use_case"
    _log_rag("")
    _log_rag("=" * 60)
    _log_rag(f"RAG UML GENERATION ({diagram_type.upper()} DIAGRAM)")
    _log_rag("=" * 60)
    _log_rag(f"Repository: {request.repo_full_name}")
    _log_rag(f"Prompt: {request.prompt}")
    _log_rag("=" * 60)

    branch = request.branch or "main"
    if not branch.strip() or branch.strip().lower() in ("main", "master"):
        try:
            resolved = await github_fetcher.get_default_branch(
                request.repo_full_name, request.github_token
            )
            if resolved:
                branch = resolved
                _log_rag(f"[generate-uml] Using repo default branch: {branch}")
        except Exception:
            pass

    collection_name = build_collection_name(
        request.organization_name,
        request.organization_short_id,
        request.repository_name,
        branch,
    )
    existing_count = vectorizer.vector_db.get_collection_count(collection_name)

    if existing_count > 0:
        _log_rag(f"\n[Skip] Collection '{collection_name}' exists ({existing_count} chunks). Retrieving only.")
        result = {
            "success": True,
            "branch": branch,
            "metadata": {"totalChunks": existing_count},
            "vectorization": {"success": True, "collection_name": collection_name},
        }
    else:
        _log_rag("\n[Step 1–5/7] Running index pipeline (fetch → parse → chunk → save → vectorize)...")
        result = await run_index_pipeline(
            github_token=request.github_token,
            repo_full_name=request.repo_full_name,
            branch=branch,
            target=None,
            organization_id=request.organization_id,
            organization_short_id=request.organization_short_id,
            organization_name=request.organization_name,
            repository_id=request.repository_id,
            repository_name=request.repository_name,
        )
        if not result.get("success"):
            raise HTTPException(
                status_code=400 if "required" in str(result.get("message", "")).lower() else 500,
                detail=result.get("message", "Index pipeline failed"),
            )
        vectorization = result.get("vectorization")
        if not vectorization or not vectorization.get("success"):
            raise HTTPException(
                status_code=500,
                detail="Vectorization failed.",
            )
        collection_name = vectorization["collection_name"]
        branch = result.get("branch", branch)
        _log_rag("✓ Index pipeline complete.")

    _log_rag(f"\n[Step 6/7] Searching vector DB for relevant chunks...")
    _log_rag(f"Query: {request.prompt}")

    search_results = vectorizer.search(
        collection_name=collection_name,
        query=request.prompt,
        top_k=request.top_k or 20,
    )
    if not search_results:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found in collection '{collection_name}'",
        )
    _log_rag(f"✓ Found {len(search_results)} relevant chunks")

    if diagram_type not in ("class", "sequence", "use_case"):
        raise HTTPException(
            status_code=400,
            detail="diagram_type must be 'class', 'sequence', or 'use_case'.",
        )

    if diagram_type == "class":
        _log_rag(f"\n[Step 7/7] Generating UML class diagram with Claude...")
        uml_result = llm_service.generate_uml_class_diagram(
            prompt=request.prompt,
            context_chunks=search_results,
            repo_name=request.repository_name or request.repo_full_name,
        )
        if uml_result.get("error"):
            raise HTTPException(
                status_code=422,
                detail=f"UML generation failed: {uml_result.get('error')}",
            )
        classes = uml_result.get("classes") or []
        relationships = uml_result.get("relationships") or []
        _log_rag(f"✓ Generated {len(classes)} classes, {len(relationships)} relationships")
        diagram_data = {"classes": classes, "relationships": relationships}
    elif diagram_type == "sequence":
        _log_rag(f"\n[Step 7/7] Generating UML sequence diagram with Claude...")
        uml_result = llm_service.generate_uml_sequence_diagram(
            prompt=request.prompt,
            context_chunks=search_results,
            repo_name=request.repository_name or request.repo_full_name,
        )
        if uml_result.get("error"):
            raise HTTPException(
                status_code=422,
                detail=f"UML generation failed: {uml_result.get('error')}",
            )
        lifelines = uml_result.get("lifelines") or []
        messages = uml_result.get("messages") or []
        steps = uml_result.get("steps") or []
        fragments = uml_result.get("fragments") or []
        _log_rag(f"✓ Generated {len(lifelines)} lifelines, {len(messages)} messages, {len(steps)} steps")
        diagram_data = {"lifelines": lifelines, "messages": messages, "steps": steps, "fragments": fragments}
    elif diagram_type == "use_case":
        _log_rag(f"\n[Step 7/7] Generating UML use case diagram with Claude...")
        uml_result = llm_service.generate_uml_use_case_diagram(
            prompt=request.prompt,
            context_chunks=search_results,
            repo_name=request.repository_name or request.repo_full_name,
        )
        if uml_result.get("error"):
            raise HTTPException(
                status_code=422,
                detail=f"UML generation failed: {uml_result.get('error')}",
            )
        system_boundary = uml_result.get("systemBoundary") or {}
        actors = uml_result.get("actors") or []
        use_cases = uml_result.get("useCases") or []
        relationships = uml_result.get("relationships") or []
        _log_rag(f"✓ Generated use case diagram: {len(actors)} actors, {len(use_cases)} use cases, {len(relationships)} relationships")
        diagram_data = {
            "systemBoundary": system_boundary,
            "actors": actors,
            "useCases": use_cases,
            "relationships": relationships,
        }

    name = _uml_slug_from_prompt(request.prompt, diagram_type)
    slug = name

    if mongodb_service and request.organization_id and request.repository_id:
        _log_rag("\n[Save] Saving diagram to MongoDB (uml_diagrams)...")

    s3_key = None
    if s3_service and request.organization_id and request.repository_id:
        _log_rag("\n[Backup] Uploading diagram JSON to S3...")
        s3_key = (
            f"organizations/{request.organization_id}/"
            f"repositories/{request.repository_id}/uml/{branch.replace('/', '_')}/{slug}.json"
        )
        upload_result = s3_service.upload_documentation(
            content=json.dumps(diagram_data),
            s3_key=s3_key,
            content_type="application/json",
        )
        if upload_result.get("success"):
            _log_rag(f"✓ Diagram uploaded to S3: {s3_key}")
        else:
            _log_rag(f"⚠ S3 UML upload failed: {upload_result.get('error')}")

    if not mongodb_service or not request.organization_id or not request.repository_id:
        raise HTTPException(
            status_code=500,
            detail="MongoDB and organization_id/repository_id are required to save the diagram.",
        )

    insert_result = mongodb_service.insert_uml_diagram(
        organization_id=request.organization_id,
        repository_id=request.repository_id,
        diagram_type=diagram_type,
        name=name,
        slug=slug,
        prompt=request.prompt,
        diagram_data=diagram_data,
        s3_key=s3_key,
    )
    if not insert_result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=insert_result.get("error", "Failed to save diagram to MongoDB"),
        )
    _log_rag(f"✓ Diagram saved to MongoDB (slug: {slug})")
    _log_rag("=" * 60)
    _log_rag("")

    return {
        "success": True,
        "diagramId": insert_result.get("diagram_id"),
        "slug": slug,
        "name": name,
        "s3Key": s3_key,
        "branch": branch,
    }


@router.get("/api/uml-diagram")
async def get_uml_diagram(
    organization_id: Optional[str] = None,
    repository_id: Optional[str] = None,
    slug: Optional[str] = None,
    diagram_id: Optional[str] = None,
):
    """
    Get a UML diagram by id or by organization_id + repository_id + slug.
    """
    if mongodb_service is None:
        raise HTTPException(status_code=503, detail="MongoDB service not available.")

    if diagram_id:
        result = mongodb_service.get_uml_diagram_by_id(diagram_id)
    elif organization_id and repository_id and slug:
        result = mongodb_service.get_uml_diagram_by_slug(
            organization_id=organization_id,
            repository_id=repository_id,
            slug=slug,
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either diagram_id or (organization_id, repository_id, slug).",
        )

    if not result.get("success"):
        raise HTTPException(
            status_code=404,
            detail=result.get("error", "Diagram not found"),
        )
    return {"success": True, "diagram": result["diagram"]}

