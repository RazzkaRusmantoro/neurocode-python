from fastapi import APIRouter, HTTPException
from typing import Optional, List, Dict, Any
import re
from datetime import datetime

from neurocode.models.schemas import AnalyzePullRequestRequest
from neurocode.config import (
    github_fetcher,
    code_analyzer,
    vectorizer,
    llm_service,
    mongodb_service
)

router = APIRouter()


@router.post("/api/analyze-pull-request")
async def analyze_pull_request(request: AnalyzePullRequestRequest):
    
    try:
        if not llm_service:
            raise HTTPException(
                status_code=500,
                detail="LLM service not available. Please set ANTHROPIC_API_KEY environment variable."
            )
        
        print("\n" + "="*60)
        print("PULL REQUEST ANALYSIS PIPELINE")
        print("="*60)
        print(f"Repository: {request.repo_full_name}")
        print(f"PR Number: {request.pr_number}")
        print("="*60)
        
                                           
        print("\n[Step 1/6] Fetching PR data from GitHub...")
        pr_data = await fetch_pr_data(
            repo_full_name=request.repo_full_name,
            pr_number=request.pr_number,
            access_token=request.github_token
        )
        print(f"✓ Fetched PR: {pr_data['title']}")
        
                                     
        print("\n[Step 2/6] Fetching PR diff...")
        pr_files = await fetch_pr_files(
            repo_full_name=request.repo_full_name,
            pr_number=request.pr_number,
            access_token=request.github_token
        )
        print(f"✓ Found {len(pr_files)} changed files")
        
                                     
        print("\n[Step 3/6] Parsing changed files...")
        changed_files_analysis = []
        for file in pr_files:
            if file.get('patch'):
                                                             
                file_analysis = {
                    'filePath': file['filename'],
                    'status': file['status'],
                    'additions': file.get('additions', 0),
                    'deletions': file.get('deletions', 0),
                    'patch': file.get('patch', '')
                }
                changed_files_analysis.append(file_analysis)
        
        print(f"✓ Parsed {len(changed_files_analysis)} files with changes")
        
                                                                          
        print("\n[Step 4/6] Searching for related code...")
        related_code = []
        collection_name = None
        
                                                                
        def sanitize_name(name: str) -> str:
            if not name:
                return ""
            sanitized = name.replace(' ', '_').replace('/', '_').replace('.', '_').replace('-', '_')
            sanitized = ''.join(c if c.isalnum() or c == '_' else '_' for c in sanitized)
            sanitized = '_'.join(filter(None, sanitized.split('_')))
            return sanitized.lower()
        
        if request.organization_short_id and request.repository_name:
            org_name_safe = sanitize_name(request.organization_name or request.organization_short_id)
            org_slug_safe = sanitize_name(request.organization_short_id)
            repo_name_safe = sanitize_name(request.repository_name)
            branch = pr_data.get('baseBranch', 'main')
            collection_name = f"{org_name_safe}_{org_slug_safe}_{repo_name_safe}_{branch}"
            
                                                      
            try:
                                                     
                query_text = f"{pr_data.get('title', '')} {pr_data.get('description', '')}"
                if query_text.strip():
                    search_results = vectorizer.search(
                        collection_name=collection_name,
                        query=query_text,
                        top_k=5
                    )
                    related_code = search_results if search_results else []
                    print(f"✓ Found {len(related_code)} related code chunks")
            except Exception as e:
                print(f"⚠ Vector search failed (collection may not exist): {e}")
        
                                               
        print("\n[Step 5/6] Generating AI analysis...")
        analysis = await generate_pr_analysis(
            pr_data=pr_data,
            changed_files=changed_files_analysis,
            related_code=related_code
        )
        print(f"✓ Analysis generated")
        if analysis.get("issues"):
            print(f"✓ Found {len(analysis.get('issues', []))} issue(s)")
        
                                                                                
        print("\n[Step 6/6] Calculating risk assessment...")
        risk_assessment = calculate_risk_assessment(
            changed_files=changed_files_analysis,
            pr_data=pr_data,
            issues=analysis.get("issues", [])                                   
        )
        print(f"✓ Risk level: {risk_assessment['level']}")
        
                                          
        print("\n[Step 7/7] Generating review comments...")
        review_comments = await generate_review_comments(
            pr_data=pr_data,
            changed_files=changed_files_analysis,
            issues=analysis.get("issues", []),
            file_analysis=analysis.get("fileAnalysis", [])
        )
        print(f"✓ Generated {len(review_comments)} review comment(s)")
        
        print("="*60 + "\n")
        
                              
        result = {
            "success": True,
            "prNumber": request.pr_number,
            "description": analysis.get("description", {}),
            "issues": analysis.get("issues", []),
            "riskAssessment": risk_assessment,
            "dependencies": {
                "direct": [f['filePath'] for f in changed_files_analysis],
                "indirect": [],                                
                "affectedFiles": len(changed_files_analysis)
            },
            "fileAnalysis": analysis.get("fileAnalysis", []),
            "reviewComments": review_comments,
            "chunksUsed": len(related_code)
        }
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"\n[ERROR] PR analysis failed: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze pull request: {str(e)}"
        )


async def fetch_pr_data(repo_full_name: str, pr_number: int, access_token: str) -> Dict:
    
    import httpx
    
    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"
    headers = {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to fetch PR: {response.text}"
            )
        pr = response.json()
        
        return {
            "title": pr.get("title", ""),
            "description": pr.get("body", ""),
            "state": pr.get("state", "open"),
            "author": pr.get("user", {}).get("login", ""),
            "authorAvatar": pr.get("user", {}).get("avatar_url", ""),
            "baseBranch": pr.get("base", {}).get("ref", ""),
            "headBranch": pr.get("head", {}).get("ref", ""),
            "headCommitSha": pr.get("head", {}).get("sha", ""),
            "updatedAt": pr.get("updated_at", ""),
            "createdAt": pr.get("created_at", "")
        }


async def fetch_pr_files(repo_full_name: str, pr_number: int, access_token: str) -> List[Dict]:
    
    import httpx
    
    url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/files"
    headers = {
        "Authorization": f"token {access_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url, headers=headers)
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Failed to fetch PR files: {response.text}"
            )
        files = response.json()
        
        return [
            {
                "filename": f.get("filename", ""),
                "status": f.get("status", ""),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "changes": f.get("changes", 0),
                "patch": f.get("patch", "")
            }
            for f in files
        ]


async def generate_pr_analysis(
    pr_data: Dict,
    changed_files: List[Dict],
    related_code: List[Dict]
) -> Dict:
    
    
                                                
    changed_files_summary = ""
    file_patches = {}
    
    for f in changed_files[:15]:                           
        file_path = f.get('filePath', '')
        status = f.get('status', '')
        additions = f.get('additions', 0)
        deletions = f.get('deletions', 0)
        patch = f.get('patch', '')
        
        changed_files_summary += f"\n## {file_path} ({status}): +{additions}/-{deletions} lines\n"
        
                                                    
        if patch:
                                                                  
            patch_lines = patch.split('\n')
            if len(patch_lines) > 500:
                patch = '\n'.join(patch_lines[:500]) + "\n... (truncated)"
            file_patches[file_path] = patch
            changed_files_summary += f"```diff\n{patch[:2000]}\n```\n"                         
    
    related_code_summary = ""
    if related_code:
        related_code_summary = "\n\nRelated code patterns found:\n"
        for chunk in related_code[:3]:                        
            metadata = chunk.get("metadata", {})
            file_path = metadata.get("file_path", "")
            if file_path:
                related_code_summary += f"- {file_path}\n"
    
                                                  
    description = pr_data.get('description') or 'N/A'
    if description != 'N/A':
        description = description[:500]
    
    prompt = f"""You are a senior code reviewer analyzing a pull request. Provide a comprehensive, detailed analysis following these strict detection standards.

Pull Request:
Title: {pr_data.get('title', 'N/A')}
Description: {description}

Changed Files with Diffs:
{changed_files_summary}
{related_code_summary}

**IMPORTANT:** Use the code diffs provided above to extract relevant code snippets for your analysis. Show actual code changes in your code snippets, not just descriptions. Include both the old and new code when relevant, or highlight the specific changes made.

**DETECTION STANDARDS - YOU MUST FOLLOW THESE:**

**CRITICAL ISSUES (Must Flag - ONLY for things that WILL DEFINITELY break the codebase):**
1. Code-Breaking: Syntax errors that prevent compilation, type errors that cause runtime failures, missing critical imports that cause crashes, undefined variables that cause crashes, runtime crashes
2. Security: SQL injection, XSS vulnerabilities, exposed secrets/API keys in production code, missing authentication on protected routes, hardcoded credentials
3. Breaking Changes: Public API changes that WILL break existing code that depends on them, database schema changes that WILL cause runtime failures, removed/renamed public functions that other code actively uses, signature changes that break existing callers
4. PR Size: 2000+ lines = High risk (consider splitting), 3000+ lines = Critical (must split), 20+ files = High risk, 30+ files = Critical

**IMPORTANT NOTES:**
- Schema changes, config changes, prompt changes, and documentation updates are usually NOT critical
- Only flag schema/config changes as breaking if they WILL cause runtime failures or break existing code
- "No migration" or "no backwards compatibility" alone is NOT critical - only if it will actually break things
- Be VERY conservative - only flag as critical if you're CERTAIN it will break the codebase

**HIGH-SEVERITY ISSUES (Should Flag - Only if they cause real problems):**
5. Performance: N+1 queries that will cause slowdowns, missing indexes on frequently queried fields, inefficient algorithms that will impact performance, memory leaks, unnecessary API calls in loops
6. Logic Errors: Off-by-one errors that cause bugs, incorrect conditionals that break functionality, missing null checks that cause crashes, race conditions that cause data corruption, wrong calculations that produce incorrect results
7. Missing Error Handling: Unhandled exceptions that will crash the app, no try-catch for operations that commonly fail, missing validation that allows invalid data, no error logging for critical operations
8. Code Quality: Significant code duplication that makes maintenance hard, god objects that are hard to maintain, functions doing too much that are error-prone, deeply nested conditionals (>4 levels) that are hard to understand

**NOTE:** Be balanced - don't flag minor code quality issues as high severity. Only flag if they will cause real problems.

**MEDIUM-SEVERITY ISSUES (Consider Flagging):**
9. Code Smells: Magic numbers, long functions (>50 lines), long parameter lists (>5), dead code, commented code
10. Testing: No tests for new functionality, tests not updated, missing edge cases, flaky tests
11. Documentation: Missing function docs, outdated comments, no README updates, missing API docs
12. Architecture: Tight coupling, circular dependencies, SOLID violations, inconsistent patterns

**LOW-SEVERITY (Only if Significant):**
13. Style: Inconsistent naming, indentation, type hints, code style
14. Minor: Variable naming, readability, data structures, minor optimizations

**IGNORE THESE (Do NOT Flag):**
- PR description quality (missing, short, or poorly written descriptions)
- Minor style inconsistencies that don't affect functionality
- Documentation issues for very small changes
- Style-only changes without functional impact
- Schema/config changes that don't break existing functionality
- Prompt changes and template updates
- Small refactoring that doesn't change behavior
- Documentation-only changes

**PR SIZE GUIDELINES:**
- < 50 lines: Excellent
- 50-200 lines: Good
- 200-500 lines: Medium (needs careful review)
- 500-1000 lines: Medium-High (consider splitting if complex)
- 1000-2000 lines: High (should consider splitting)
- 2000+ lines: Very High (strongly recommend splitting)

**CRITICAL REQUIREMENTS:**

1. **Description Structure (Formal Format):**
   You must generate a comprehensive, formal description following this exact structure:
   
   **A. Pull Request Summary:**
   - **Title:** The PR title
   - **Overview (2-3 sentences):** A concise description of what this PR does and why, explaining the main purpose and high-level changes
   
   **B. Detailed Changes:**
   Organize by file/module. For EACH changed file, provide:
   - **File header:** "Updates to `filename.py`"
   - **Sub-sections** for each major change area:
     * **Sub-section title** (e.g., "Description Extraction and Inclusion")
     * **Key changes:** Bullet list of specific modifications
     * **Impact:** Explanation of what each change means and why it matters
     * **Code snippets:** Include relevant code snippets from the diff showing the actual changes (use proper code blocks with language tags)
   
   **C. Architectural Implications:**
   Structure this as a concise list with clear points, not long paragraphs:
   - **Approach:** Brief statement of the architectural approach (1-2 sentences max)
   - **Benefits:** Bullet list of key benefits (maintainability, scalability, separation of concerns, etc.)
   - **System Evolution:** Brief note on how this changes/improves the system (1-2 sentences)
   - **Layer Consistency:** Note how changes propagate across layers (if applicable, 1 sentence)
   
   **D. Overall Assessment:**
   Structure this as a concise summary with clear sections, not long paragraphs:
   - **PR Type:** What this PR represents (e.g., "structural refinement", "feature expansion", "bug fix")
   - **Key Benefits:** Bullet list of main benefits and improvements (3-5 points)
   - **Risk Level:** Brief note on implementation risk and scope (1-2 sentences)
   - **Breaking Changes:** Note any breaking changes or migration needs (if applicable)
   - **Issues Summary:** Brief mention of issues detected (e.g., "X issues detected - see issues section")

2. **Issue Detection (MANDATORY - Follow Standards Above):**
   - Analyze code changes against ALL detection standards listed above
   - For EACH issue found:
     * Clearly state what the issue is
     * Explain WHY it's a problem using the standards
     * Specify WHERE it occurs (file/function)
     * Explain the potential impact
     * Assign correct severity based on standards
   - DO NOT flag PR description issues (ignore them)
   - DO NOT flag minor style issues unless they're significant
   - If no issues found, explicitly state "No issues detected"

3. **File-by-File Analysis:**
   - For each changed file, explain what changed and why
   - Identify the purpose of changes in each file

Format your response as JSON with this structure:
{{
  "description": {{
    "title": "The PR title",
    "overview": "Brief 2-3 sentence overview of what this PR does and why",
    "detailedChanges": [
      {{
        "file": "path/to/file.py",
        "sections": [
          {{
            "title": "Sub-section title (e.g., 'Description Extraction and Inclusion')",
            "keyChanges": [
              "First specific change",
              "Second specific change",
              "Additional changes"
            ],
            "impact": "Explanation of what this change means and why it matters",
            "codeSnippets": [
              {{
                "code": "actual code snippet from the diff showing the change",
                "language": "python"
              }}
            ]
          }}
        ]
      }}
    ],
    "architecturalImplications": {{
      "approach": "Brief statement of architectural approach (1-2 sentences)",
      "benefits": ["Benefit 1", "Benefit 2", "Benefit 3"],
      "systemEvolution": "Brief note on system changes/improvements (1-2 sentences)",
      "layerConsistency": "Note on layer propagation (if applicable, 1 sentence)"
    }},
    "overallAssessment": {{
      "prType": "What this PR represents (e.g., structural refinement, feature expansion)",
      "keyBenefits": ["Benefit 1", "Benefit 2", "Benefit 3"],
      "riskLevel": "Brief note on implementation risk and scope (1-2 sentences)",
      "breakingChanges": "Note any breaking changes or migration needs (if applicable)",
      "issuesSummary": "Brief mention of issues detected"
    }}
  }},
  "issues": [
    {{
      "type": "bug|security|performance|code_smell|breaking_change|pr_size|logic_error|missing_error_handling|other",
      "severity": "low|medium|high|critical",
      "file": "path/to/file",
      "description": "Clear description of the issue",
      "explanation": "Detailed explanation of WHY this is a problem and what could go wrong",
      "location": "Specific function/line/area where issue occurs"
    }}
  ],
  "fileAnalysis": [
    {{
      "filePath": "path/to/file",
      "explanation": "Detailed explanation of what changed in this file and why",
      "riskLevel": "low|medium|high|very high|critical"
    }}
  ]
}}

**IMPORTANT - BE BALANCED:** 
- Be thorough but balanced - don't over-flag issues
- Only flag as CRITICAL if you're CERTAIN it will break the codebase
- Schema changes, config changes, and prompt changes are usually NOT critical
- Breaking changes are only critical if they WILL break existing code that depends on them
- Be conservative with severity - err on the side of lower severity unless certain
- DO NOT flag PR description issues
- DO NOT flag minor style issues unless significant
- DO NOT flag schema/config/prompt changes as breaking unless they actually break things
- If you find issues, explain them clearly using the standards
- The summary must be descriptive and explain what the PR actually does
- For PR size issues, use type: "pr_size" and severity based on line count (1000+ = high, 2000+ = critical)
"""
    
    try:
        response = llm_service.client.messages.create(
            model=llm_service.model,
            max_tokens=6000,                                                                
            system="You are a senior code reviewer and technical writer. You analyze pull requests thoroughly and create formal, comprehensive descriptions. You write in a professional, structured format that includes: (1) A clear summary with title and overview, (2) Detailed changes organized by file with sub-sections, key changes, impact explanations, and relevant code snippets, (3) Architectural implications discussing the overall approach, and (4) An overall assessment. You only flag issues as CRITICAL if you're CERTAIN they will break the codebase. Schema changes, config changes, and prompt changes are usually NOT critical unless they will definitely break existing functionality. You are balanced - don't over-flag issues. You identify real problems (code-breaking errors, security vulnerabilities, actual breaking changes, very large PRs), high-severity issues (performance problems, logic errors, missing error handling), and medium-severity issues (code smells, testing, documentation). You IGNORE PR description quality issues, minor style issues, and non-breaking schema/config changes. You are thorough, specific, balanced, and write in a formal, professional style.",
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        if response.content and len(response.content) > 0:
            content = response.content[0].text.strip()
            
                                             
            try:
                                                                   
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if json_match:
                    content = json_match.group(1)
                
                import json
                analysis = json.loads(content)
                
                                                               
                if analysis.get("issues"):
                    filtered_issues = []
                    for issue in analysis.get("issues", []):
                                                                 
                        issue_desc_lower = issue.get("description", "").lower()
                        issue_type_lower = issue.get("type", "").lower()
                        
                                                            
                        if any(keyword in issue_desc_lower for keyword in ["pr description", "pull request description", "description missing", "description is", "description could", "description should"]):
                            continue
                        
                                                                                        
                        if issue.get("severity") == "low" and issue_type_lower in ["style", "formatting", "naming"]:
                                                                   
                            if not any(keyword in issue_desc_lower for keyword in ["security", "performance", "bug", "error", "crash", "breaking"]):
                                continue
                        
                        filtered_issues.append(issue)
                    
                    analysis["issues"] = filtered_issues
                
                                                     
                if not analysis.get("description"):
                                                      
                    analysis["description"] = {
                        "title": pr_data.get('title', 'N/A'),
                        "overview": "Analysis generated successfully. Review the changes carefully.",
                        "detailedChanges": [],
                        "architecturalImplications": {},
                        "overallAssessment": {}
                    }
                
                                                               
                if analysis.get("description", {}).get("architecturalImplications"):
                    if isinstance(analysis["description"]["architecturalImplications"], str):
                                                                        
                        analysis["description"]["architecturalImplications"] = {
                            "approach": analysis["description"]["architecturalImplications"],
                            "benefits": [],
                            "systemEvolution": "",
                            "layerConsistency": ""
                        }
                elif not analysis.get("description", {}).get("architecturalImplications"):
                    analysis["description"]["architecturalImplications"] = {}
                
                                                       
                if analysis.get("description", {}).get("overallAssessment"):
                    if isinstance(analysis["description"]["overallAssessment"], str):
                                                                        
                        analysis["description"]["overallAssessment"] = {
                            "prType": "Analysis generated",
                            "keyBenefits": [],
                            "riskLevel": analysis["description"]["overallAssessment"],
                            "breakingChanges": "",
                            "issuesSummary": ""
                        }
                elif not analysis.get("description", {}).get("overallAssessment"):
                    analysis["description"]["overallAssessment"] = {}
                
                                                                             
                if analysis.get("issues") and len(analysis.get("issues", [])) > 0:
                    issues_count = len(analysis.get("issues", []))
                    critical_count = len([i for i in analysis.get("issues", []) if i.get("severity") == "critical"])
                    high_count = len([i for i in analysis.get("issues", []) if i.get("severity") == "high"])
                    
                    issues_note = "\n\n**Issues Detected:** "
                    if critical_count > 0:
                        issues_note += f"{critical_count} critical, "
                    if high_count > 0:
                        issues_note += f"{high_count} high-severity, "
                    issues_note += f"{issues_count} total issue(s) detected. Please review the issues section below."
                    
                                                               
                    if analysis.get("description", {}).get("overallAssessment"):
                        if isinstance(analysis["description"]["overallAssessment"], dict):
                            if analysis["description"]["overallAssessment"].get("issuesSummary"):
                                analysis["description"]["overallAssessment"]["issuesSummary"] += issues_note
                            else:
                                analysis["description"]["overallAssessment"]["issuesSummary"] = issues_note
                    elif analysis.get("description"):
                        if not analysis["description"].get("overallAssessment"):
                            analysis["description"]["overallAssessment"] = {}
                        analysis["description"]["overallAssessment"]["issuesSummary"] = issues_note
                
                return analysis
            except json.JSONDecodeError:
                                                                         
                                               
                summary_match = re.search(r'(?:summary|overview|description)[:\s]+(.+?)(?:\n\n|\n[A-Z]|$)', content, re.IGNORECASE | re.DOTALL)
                if summary_match:
                    summary_text = summary_match.group(1).strip()[:1000]
                else:
                    summary_text = content[:500]
                
                return {
                    "description": {
                        "title": pr_data.get('title', 'N/A'),
                        "overview": summary_text,
                        "detailedChanges": [],
                        "architecturalImplications": {},
                        "overallAssessment": {
                            "prType": "Analysis generated",
                            "keyBenefits": [],
                            "riskLevel": "Analysis generated with limited information. Please review manually.",
                            "breakingChanges": "",
                            "issuesSummary": ""
                        }
                    },
                    "issues": [],
                    "fileAnalysis": []
                }
        
        return {
            "description": {
                "title": pr_data.get('title', 'N/A'),
                "overview": "Analysis generated successfully. Review the changes carefully.",
                "detailedChanges": [],
                "architecturalImplications": {},
                "overallAssessment": {}
            },
            "issues": [],
            "fileAnalysis": []
        }
        
    except Exception as e:
        print(f"⚠ LLM generation error: {e}")
        return {
            "description": {
                "title": pr_data.get('title', 'N/A'),
                "overview": f"This PR modifies {len(changed_files)} file(s). Analysis generation encountered an error: {str(e)}. Please review the changes manually.",
                "detailedChanges": [],
                "architecturalImplications": {},
                "overallAssessment": {}
            },
            "issues": [],
            "fileAnalysis": []
        }


def extract_code_snippet(file_path: str, line_number: int, changed_files: List[Dict], context_lines: int = 5) -> str:
    
    for file_info in changed_files:
        if file_info.get('filePath') == file_path:
            patch = file_info.get('patch', '')
            if not patch:
                return ''
            
                                         
            lines = patch.split('\n')
            new_line_counter = 0                                      
            target_line = line_number
            target_index = -1
            in_relevant_hunk = False
            
                                    
            for i, line in enumerate(lines):
                                        
                if line.startswith(('diff --git', 'index ', '--- a/', '+++ b/')):
                    continue
                
                                                                                      
                if line.startswith('@@'):
                                                           
                    match = re.search(r'\+(\d+)(?:,(\d+))?', line)
                    if match:
                        hunk_start = int(match.group(1))
                        hunk_count = int(match.group(2)) if match.group(2) else 1
                                                                                        
                        in_relevant_hunk = hunk_start <= target_line <= (hunk_start + hunk_count + 20)
                        if in_relevant_hunk:
                            new_line_counter = hunk_start - 1                                            
                        else:
                                                                   
                            if new_line_counter > 0 and new_line_counter > target_line:
                                break
                    continue
                
                                                              
                if not in_relevant_hunk:
                    continue
                
                                    
                if line.startswith('+') and not line.startswith('+++'):
                                                             
                    new_line_counter += 1
                    if new_line_counter == target_line:
                        target_index = i
                        break
                elif line.startswith('-') and not line.startswith('---'):
                                                                                           
                    pass
                elif line and not line.startswith('\\'):
                                                                                                    
                    new_line_counter += 1
                    if new_line_counter == target_line:
                        target_index = i
                        break
            
                                                                    
            if target_index >= 0:
                start_idx = max(0, target_index - context_lines)
                end_idx = min(len(lines), target_index + context_lines + 1)
                snippet_lines = lines[start_idx:end_idx]
                
                                                                                        
                filtered_snippet = []
                for line in snippet_lines:
                    stripped = line.strip()
                    if not stripped or stripped.startswith(('diff --git', 'index ', '--- a/', '+++ b/', '@@')):
                        continue
                    filtered_snippet.append(line)
                
                if filtered_snippet:
                    return '\n'.join(filtered_snippet[:25])                     
            
                                                                                 
            if patch:
                patch_lines = patch.split('\n')
                                                            
                for i, line in enumerate(patch_lines):
                    if line.startswith('@@'):
                                                              
                        start = max(0, i - 2)
                        end = min(len(patch_lines), i + 15)
                        fallback_snippet = patch_lines[start:end]
                                                                 
                        filtered = []
                        for ln in fallback_snippet:
                            stripped = ln.strip()
                            if not stripped or stripped.startswith(('diff --git', 'index ', '--- a/', '+++ b/')):
                                continue
                            filtered.append(ln)
                        if filtered:
                            return '\n'.join(filtered[:20])
                        break
            
            return ''
    
    return ''


async def generate_review_comments(
    pr_data: Dict,
    changed_files: List[Dict],
    issues: List[Dict],
    file_analysis: List[Dict]
) -> List[Dict]:
    
    
    if not llm_service:
        return []
    
                                                 
    issues_summary = ""
    if issues:
        issues_summary = "\n\nIssues Detected:\n"
        for issue in issues[:10]:                          
            severity = issue.get("severity", "medium")
            issue_type = issue.get("type", "other")
            file_path = issue.get("file", "unknown")
            description = issue.get("description", "")
            explanation = issue.get("explanation", "")
            location = issue.get("location", "")
            
            issues_summary += f"- [{severity.upper()}] {issue_type}: {description}\n"
            issues_summary += f"  File: {file_path}"
            if location:
                issues_summary += f" ({location})"
            issues_summary += f"\n  Explanation: {explanation}\n\n"
    
    file_analysis_summary = ""
    if file_analysis:
        file_analysis_summary = "\n\nFile Analysis:\n"
        for file_info in file_analysis[:10]:                         
            file_path = file_info.get("filePath", "")
            risk_level = file_info.get("riskLevel", "medium")
            explanation = file_info.get("explanation", "")
            
            file_analysis_summary += f"- {file_path} (Risk: {risk_level})\n"
            file_analysis_summary += f"  {explanation}\n\n"
    
                                  
    file_patches_summary = ""
    for f in changed_files[:5]:                                      
        file_path = f.get('filePath', '')
        patch = f.get('patch', '')
        if patch:
                              
            patch_lines = patch.split('\n')
            if len(patch_lines) > 100:
                patch = '\n'.join(patch_lines[:100]) + "\n... (truncated)"
            file_patches_summary += f"\n### {file_path}\n```diff\n{patch[:1500]}\n```\n"
    
                                                  
    description = pr_data.get('description') or ''
    if description:
        description = description[:500]
    
    prompt = f"""You are a code reviewer generating GitHub PR review comments. Based on the PR analysis, create actionable review comments that can be posted directly to GitHub.

Pull Request:
Title: {pr_data.get('title', 'N/A')}
Description: {description}

{issues_summary}
{file_analysis_summary}

Changed Files (sample):
{file_patches_summary}

**TASK:** Generate GitHub PR review comments for the issues and concerns identified above.

**CRITICAL REQUIREMENTS:**
1. BRIEF AND CODE-SPECIFIC: Each comment must be short (1-3 sentences max) and directly reference specific code
2. NO MARKDOWN OR EMOJIS: Do NOT use **, ``, code blocks, emojis, or any markdown. Use plain text only.
3. CODE SUGGESTIONS: Provide actual code suggestions and improvements. Reference specific functions, variables, or code patterns from the diff.
4. HIGHLIGHTING: If you need to highlight code/variables, use double quotes "" instead of backticks. Example: "functionName" or "variableName"
5. CODE-FOCUSED: Reference actual code elements (function names, variables, line patterns) from the diff with specific suggestions
6. Actionable: Suggest what to fix or improve with specific code references and alternatives
7. For each comment, identify the specific file and approximate location from the diff
8. Prioritize critical and high-severity issues
9. Skip low-severity style issues unless they're significant

**OUTPUT FORMAT (JSON):**
{{
  "reviewComments": [
    {{
      "path": "path/to/file.py",
      "line": 42,  // Line number in the diff (optional, can be null)
      "side": "RIGHT",  // "LEFT" for deletions, "RIGHT" for additions, null for general comments
      "body": "Plain text comment without markdown. Reference specific code elements. Be brief and code-specific.",
      "severity": "high",  // "critical" | "high" | "medium"
      "issueType": "bug"  // Type of issue this comment addresses
    }}
  ]
}}

**IMPORTANT:**
- Only generate comments for real issues (medium severity and above)
- Be specific about file paths and locations when possible
- If line number cannot be determined, set line to null
- NO MARKDOWN OR EMOJIS: Write in plain text only - no **, ``, code blocks, emojis, or formatting
- Use double quotes "" to highlight code/variables instead of backticks
- Keep comments brief (1-3 sentences) and code-specific with actual code suggestions
- Reference actual code from the diff (function names, variables, patterns) and suggest improvements
- Provide code suggestions: show what to change, not just what's wrong
- Generate 5-15 comments maximum, prioritizing the most important issues
"""

    try:
        response = llm_service.client.messages.create(
            model=llm_service.model,
            max_tokens=4000,
            system="You are a senior code reviewer generating GitHub PR review comments. You create brief, code-specific, actionable comments in plain text (no markdown, no emojis). You provide actual code suggestions and improvements. You reference actual code elements from the diff using double quotes for highlighting (e.g., \"functionName\"). You keep comments short (1-3 sentences) and focus on real issues with specific code suggestions. Never use **, ``, code blocks, or emojis.",
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        if response.content and len(response.content) > 0:
            content = response.content[0].text.strip()
            
                                             
            try:
                                                                   
                json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if json_match:
                    content = json_match.group(1)
                
                import json
                result = json.loads(content)
                
                review_comments = result.get("reviewComments", [])
                
                                             
                validated_comments = []
                for comment in review_comments:
                    if comment.get("body") and comment.get("path"):
                                                                                
                        body = comment.get("body", "")
                                                               
                        body = re.sub(r'[⚠️✅❌🔍💡🚨📝⚡️🔥💯⭐️🎯]', '', body)
                        body = re.sub(r'[\U0001F300-\U0001F9FF]', '', body)                               
                                                     
                        body = re.sub(r'\*\*([^*]+)\*\*', r'\1', body)                   
                        body = re.sub(r'\*([^*]+)\*', r'\1', body)                   
                                                                                    
                        body = re.sub(r'`([^`]+)`', r'"\1"', body)                              
                        body = re.sub(r'```[\s\S]*?```', '', body)                      
                        body = re.sub(r'#+\s*', '', body)                           
                        body = body.strip()
                        
                                                               
                        code_snippet = ""
                        comment_path = comment.get("path")
                        comment_line = comment.get("line")
                        if comment_path and comment_line is not None:
                            code_snippet = extract_code_snippet(comment_path, comment_line, changed_files)
                        
                        validated_comments.append({
                            "path": comment_path,
                            "line": comment_line,               
                            "side": comment.get("side", "RIGHT"),                        
                            "body": body,
                            "severity": comment.get("severity", "medium"),
                            "issueType": comment.get("issueType", "other"),
                            "codeSnippet": code_snippet                          
                        })
                
                return validated_comments
            except json.JSONDecodeError:
                print(f"⚠ Failed to parse review comments JSON: {content[:200]}")
                return []
    except Exception as e:
        print(f"⚠ Review comments generation error: {e}")
        return []
    
    return []


def calculate_risk_assessment(changed_files: List[Dict], pr_data: Dict, issues: List[Dict] = None) -> Dict:
    
    if issues is None:
        issues = []
    
    total_files = len(changed_files)
    total_additions = sum(f.get('additions', 0) for f in changed_files)
    total_deletions = sum(f.get('deletions', 0) for f in changed_files)
    total_changes = total_additions + total_deletions
    
    factors = []
    risk_score = 0
    
                                                     
    if total_files > 20:
        factors.append(f"Very large number of files changed ({total_files})")
        risk_score += 25
    elif total_files > 10:
        factors.append(f"Large number of files changed ({total_files})")
        risk_score += 15
    elif total_files > 5:
        factors.append(f"Multiple files changed ({total_files})")
        risk_score += 8
    
                                           
    if total_changes > 2000:
        factors.append(f"Very large changes ({total_changes} lines)")
        risk_score += 25
    elif total_changes > 1000:
        factors.append(f"Large changes ({total_changes} lines)")
        risk_score += 15
    elif total_changes > 500:
        factors.append(f"Moderate changes ({total_changes} lines)")
        risk_score += 8
    
                                                              
                                                                         
    truly_critical_patterns = ['auth', 'security', 'database', 'core', 'main']
    critical_files = [
        f for f in changed_files
        if any(pattern in f['filePath'].lower() for pattern in truly_critical_patterns)
        and 'schema' not in f['filePath'].lower()                        
        and 'config' not in f['filePath'].lower()                                              
    ]
    if critical_files:
        factors.append(f"Critical infrastructure files modified ({len(critical_files)})")
        risk_score += 20
    
                                                                                
    if total_deletions > 500:
        factors.append(f"Very significant deletions ({total_deletions} lines)")
        risk_score += 20
    elif total_deletions > 200:
        factors.append(f"Significant deletions ({total_deletions} lines)")
        risk_score += 10
    
                                                                                             
    if issues:
                                                                                   
                                                                                            
        filtered_issues = []
        for i in issues:
            issue_file = i.get("file", "").lower()
            issue_type = i.get("type", "").lower()
            issue_desc = i.get("description", "").lower()
            issue_expl = i.get("explanation", "").lower()
            
                                                                                   
            if any(keyword in issue_file for keyword in ["schema", "config", "prompt", "template"]):
                                                               
                if "will break" in issue_expl or "break" in issue_desc or "crash" in issue_expl or "fail" in issue_expl:
                    filtered_issues.append(i)
                                                      
                elif i.get("severity") in ["critical", "high"]:
                                                                                      
                    if "migration" in issue_expl or "backwards compatibility" in issue_expl or "validation" in issue_expl:
                                                                         
                        continue                                               
                else:
                    filtered_issues.append(i)
            else:
                filtered_issues.append(i)
        
                                                                          
        actual_critical_issues = [
            i for i in filtered_issues 
            if i.get("severity") == "critical" 
            and i.get("type") in ["security", "breaking_change", "bug"]
        ]
        high_breaking_issues = [
            i for i in filtered_issues 
            if i.get("severity") == "high" 
            and i.get("type") in ["security", "breaking_change", "bug"]
        ]
        other_high_issues = [
            i for i in filtered_issues 
            if i.get("severity") == "high" 
            and i.get("type") not in ["security", "breaking_change", "bug"]
        ]
        medium_issues = [i for i in filtered_issues if i.get("severity") == "medium"]
        
                                                                                      
        if actual_critical_issues:
            factors.append(f"{len(actual_critical_issues)} critical breaking issue(s) detected")
            risk_score += 30                   
        if high_breaking_issues:
            factors.append(f"{len(high_breaking_issues)} high-severity breaking issue(s) detected")
            risk_score += 15                   
        if other_high_issues:
            factors.append(f"{len(other_high_issues)} high-severity issue(s) detected")
            risk_score += 8                   
        if medium_issues:
            factors.append(f"{len(medium_issues)} medium-severity issue(s) detected")
            risk_score += 3                  
        if len(filtered_issues) > 15:                       
            factors.append(f"Many issues detected ({len(filtered_issues)} total)")
            risk_score += 3                  
    
                                                                
                                                           
    if risk_score >= 70:
        level = "critical"
    elif risk_score >= 50:
        level = "very high"
    elif risk_score >= 30:
        level = "high"
    elif risk_score >= 15:
        level = "medium"
    else:
        level = "low"
    
                                                                   
    if level == "critical":
        explanation = "This PR contains changes that may break the codebase. "
    elif level == "very high":
        explanation = "This PR has significant changes that require careful review. "
    elif level == "high":
        explanation = "This PR has notable changes that should be reviewed. "
    elif level == "medium":
        explanation = "This PR has moderate changes. "
    else:
        explanation = "This PR appears to be low risk. "
    
    if factors:
        explanation += "Consider: " + "; ".join(factors[:2])                           
    else:
        if level in ["low", "medium"]:
            explanation += "Changes appear safe to merge."
        else:
            explanation += "Review recommended before merging."
    
    return {
        "level": level,
        "score": min(risk_score, 100),
        "factors": factors,
        "breakingChanges": [],                                 
        "explanation": explanation
    }

