import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from tree_sitter import Parser
from neurocode.services.analysis.parser.language_support import (
    detect_language,
    get_language_grammar,
    EXTENSION_TO_LANGUAGE,
)


@dataclass
class TreeNode:
    name: str
    type: str
    path: str
    description: str = ""
    details: str = ""
    children: List["TreeNode"] = field(default_factory=list)
    language: Optional[str] = None
    usages: List[str] = field(default_factory=list)
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    purpose: str = ""
    logic_flow: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    api_calls: List[str] = field(default_factory=list)
    code_sample: str = ""
    explanation: str = ""

    def to_dict(self) -> Dict:
        def _cap(s: str, limit: int = 600) -> str:
            return s if len(s) <= limit else s[:limit] + "..."

        d: Dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "path": self.path,
            "description": _cap(self.description, 400),
            "details": _cap(self.details, 400),
            "language": self.language,
            "children": [c.to_dict() for c in self.children],
        }
        if self.usages:
            d["usages"] = self.usages[:10]
        if self.line_start is not None:
            d["line_start"] = self.line_start
        if self.line_end is not None:
            d["line_end"] = self.line_end
        d["purpose"] = _cap(self.purpose, 400) if self.purpose else self.description
        d["explanation"] = _cap(self.explanation, 600) if self.explanation else ""
        if self.logic_flow:
            d["logic_flow"] = [_cap(s, 200) for s in self.logic_flow[:10]]
        if self.dependencies:
            d["dependencies"] = self.dependencies[:15]
        if self.api_calls:
            d["api_calls"] = self.api_calls[:10]
        if self.code_sample:
            cs = self.code_sample
            if len(cs) > 1500:
                cs = cs[:1500] + "\n// ... (truncated)"
            d["code_sample"] = cs
        return d


                                                                
_LANG_TO_TS = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "tsx": "tsx",
    "java": "java",
    "go": "go",
    "rust": "rust",
    "c++": "cpp",
    "c": "c",
    "cpp": "cpp",
}

IMPORT_TYPES = {
    "import_statement", "import_from_statement", "import_declaration",
    "preproc_include", "include_statement",
}
FUNC_TYPES = {
    "function_definition", "method_definition", "function_declaration",
    "arrow_function", "lexical_declaration",
}
CLASS_TYPES = {"class_definition", "class_declaration"}


def _parse_llm_json(raw: str) -> Any:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty content")
    fb = raw.find("{")
    fb2 = raw.find("[")
    cands = [x for x in (fb, fb2) if x != -1]
    start = min(cands) if cands else 0
    txt = raw[start:]
    txt = "".join(ch for ch in txt if ch >= " " or ch in "\n\r\t")
    lb = txt.rfind("}")
    lb2 = txt.rfind("]")
    end = max(lb, lb2)
    if end != -1:
        txt = txt[:end + 1]

    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        pass

    fixed = re.sub(r',\s*([}\]])', r'\1', txt)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    def _fix_strings(s: str) -> str:
        out, i = [], 0
        while i < len(s):
            if s[i] == '"':
                out.append('"')
                i += 1
                while i < len(s):
                    ch = s[i]
                    if ch == '\\' and i + 1 < len(s):
                        out.append(ch)
                        out.append(s[i + 1])
                        i += 2
                        continue
                    if ch == '"':
                        rest = s[i + 1:].lstrip()
                        if not rest or rest[0] in ':,}]':
                            out.append('"')
                            i += 1
                            break
                        else:
                            out.append('\\"')
                            i += 1
                            continue
                    if ch == '\n':
                        out.append('\\n')
                        i += 1
                        continue
                    out.append(ch)
                    i += 1
            else:
                out.append(s[i])
                i += 1
        return "".join(out)

    fixed2 = _fix_strings(fixed)
    try:
        return json.loads(fixed2)
    except json.JSONDecodeError:
        pass

    for trim_end in range(len(txt), 0, -1):
        candidate = txt[:trim_end]
        if candidate.rstrip()[-1:] in ('}', ']'):
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not parse LLM JSON (len={len(txt)}): {txt[:200]!r}...")


class TreeBuilder:
    

    def __init__(self, llm_client=None, model: str = "", model_fast: str = ""):
        self.client = llm_client
        self.model = model
        self.model_fast = model_fast

    def _safe_llm_call(self, prompt: str, max_tokens: int = 4000, retries: int = 3) -> str:
        if not self.client:
            return ""
        for attempt in range(1, retries + 1):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip() if response.content else ""
                if text:
                    return text
                raise ValueError("Empty response from model")
            except Exception as e:
                msg = str(e)
                if attempt < retries and any(k in msg.lower() for k in ("rate limit", "retry", "overloaded")):
                    wait = 10.0
                    m = re.search(r"retry in ([0-9.]+)s", msg)
                    if m:
                        try:
                            wait = float(m.group(1))
                        except ValueError:
                            pass
                    print(f"[TreeBuilder] Rate limit; sleeping {wait:.1f}s (attempt {attempt}/{retries})")
                    time.sleep(wait)
                    continue
                if attempt == retries:
                    raise
        return ""

    def _safe_llm_call_fast(self, prompt: str, max_tokens: int = 3000, retries: int = 2) -> str:
        if not self.client:
            return ""
        for attempt in range(1, retries + 1):
            try:
                response = self.client.messages.create(
                    model=self.model_fast,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text.strip() if response.content else ""
                if text:
                    return text
                raise ValueError("Empty response from model")
            except Exception as e:
                msg = str(e)
                if attempt < retries and any(k in msg.lower() for k in ("rate limit", "retry", "overloaded")):
                    time.sleep(10.0)
                    continue
                if attempt == retries:
                    raise
        return ""

                                                                        
                                                  
                                                                        

    def _parse_content(self, content: str, language_id: str, rel_path: str):
        
        grammar = get_language_grammar(language_id)
        if not grammar:
            return [], [], content

        try:
            parser = Parser(grammar)
        except Exception:
            try:
                parser = Parser()
                parser.language = grammar
            except Exception:
                return [], [], content

        source_bytes = content.encode("utf-8", errors="ignore")
        try:
            tree = parser.parse(source_bytes)
        except Exception:
            return [], [], content

        root = tree.root_node
        symbols: List[TreeNode] = []
        imports: List[str] = []

        def _ident(node):
            for ch in node.children:
                if ch.type in ("identifier", "type_identifier", "function_declarator",
                               "name", "property_identifier"):
                    return source_bytes[ch.start_byte:ch.end_byte].decode("utf-8", "ignore")
            return ""

        def _snippet(node, max_lines=12, max_chars=1500):
            start = node.start_point[0]
            end = node.end_point[0]
            lines = content.splitlines()[start:end + 1]
            if len(lines) > max_lines:
                lines = lines[:max_lines] + ["  // ... (truncated)"]
            result = "\n".join(lines)
            return result[:max_chars] if len(result) > max_chars else result

        for child in root.children:
            t = child.type
            if t in IMPORT_TYPES:
                imp_text = source_bytes[child.start_byte:child.end_byte].decode("utf-8", "ignore").strip()
                imports.append(imp_text)
            elif t in FUNC_TYPES:
                name = _ident(child) or "(anonymous)"
                symbols.append(TreeNode(
                    name=name, type="function", path=rel_path, language=language_id,
                    line_start=child.start_point[0] + 1,
                    line_end=child.end_point[0] + 1,
                    code_sample=_snippet(child),
                ))
            elif t in CLASS_TYPES:
                name = _ident(child) or "(class)"
                symbols.append(TreeNode(
                    name=name, type="class", path=rel_path, language=language_id,
                    line_start=child.start_point[0] + 1,
                    line_end=child.end_point[0] + 1,
                    code_sample=_snippet(child),
                ))
            elif t == "export_statement":
                for sub in child.children:
                    st = sub.type
                    if st in FUNC_TYPES:
                        name = _ident(sub) or "(anonymous)"
                        symbols.append(TreeNode(
                            name=name, type="function", path=rel_path, language=language_id,
                            line_start=sub.start_point[0] + 1,
                            line_end=sub.end_point[0] + 1,
                            code_sample=_snippet(sub),
                        ))
                    elif st in CLASS_TYPES:
                        name = _ident(sub) or "(class)"
                        symbols.append(TreeNode(
                            name=name, type="class", path=rel_path, language=language_id,
                            line_start=sub.start_point[0] + 1,
                            line_end=sub.end_point[0] + 1,
                            code_sample=_snippet(sub),
                        ))

        return symbols, imports, content

                                                                        
                                                   
                                                                        

    def _build_code_tree(self, files: List[Dict[str, Any]], repo_name: str):
        root_node = TreeNode(name=repo_name, type="folder", path=".")
        folder_nodes: Dict[str, TreeNode] = {".": root_node}
        file_sources: Dict[str, str] = {}
        all_file_info: Dict[str, Dict] = {}

        for f in files:
            rel_path: str = f.get("path", "")
            content: str = f.get("content", "")
            gh_lang: str = f.get("language", "")

            if not rel_path or not content:
                continue

            parts = rel_path.split("/")
            parent_path = "."
            parent_node = root_node
            for part in parts[:-1]:
                child_path = f"{parent_path}/{part}" if parent_path != "." else part
                if child_path not in folder_nodes:
                    node = TreeNode(name=part, type="folder", path=child_path)
                    folder_nodes[child_path] = node
                    parent_node.children.append(node)
                parent_node = folder_nodes[child_path]
                parent_path = child_path

            ext = "." + rel_path.rsplit(".", 1)[-1] if "." in rel_path else ""
            ts_lang = EXTENSION_TO_LANGUAGE.get(ext.lower())
            if not ts_lang:
                ts_lang = _LANG_TO_TS.get(gh_lang.lower(), "")

            file_node = TreeNode(name=parts[-1], type="file", path=rel_path, language=ts_lang or None)
            parent_node.children.append(file_node)

            if ts_lang:
                try:
                    symbols, imports, source_text = self._parse_content(content, ts_lang, rel_path)
                    file_node.children.extend(symbols)
                    file_node.dependencies = imports
                except Exception as e:
                    print(f"[TreeBuilder] Parse error for {rel_path}: {e}")

            file_sources[rel_path] = content
            all_file_info[rel_path] = {
                "symbols": [s.name for s in file_node.children if s.type in ("function", "class")],
                "imports": file_node.dependencies[:10],
            }

                                    
        all_nodes: List[TreeNode] = []
        def _collect(n):
            all_nodes.append(n)
            for c in n.children:
                _collect(c)
        _collect(root_node)

        symbol_nodes = [n for n in all_nodes if n.type in ("function", "class") and n.name]
        for sym in symbol_nodes:
            for rp, src in file_sources.items():
                if rp == sym.path:
                    continue
                if sym.name in src:
                    sym.usages.append(rp)
                    if len(sym.usages) >= 10:
                        break

        return root_node, file_sources, all_file_info

                                                                        
                                                          
                                                                        

    @staticmethod
    def _extract_config_content(files: List[Dict[str, Any]]) -> Dict[str, str]:
        
        targets = {
            "package.json", "pyproject.toml", "setup.py", "setup.cfg",
            "Cargo.toml", "go.mod", "composer.json", "Gemfile",
        }
        out: Dict[str, str] = {}
        for f in files:
            name = (f.get("path") or "").rsplit("/", 1)[-1]
            if name in targets:
                content = (f.get("content") or "")[:5000]
                if content:
                    out[name] = content
        return out

    @staticmethod
    def _measure_min_depth(tree_list: list) -> int:
        
        def _depth(node: dict) -> int:
            if node.get("type") in ("file", "function", "class"):
                return 0
            children = node.get("children") or []
            if not children:
                return 0
            return 1 + min(_depth(c) for c in children if isinstance(c, dict)) if children else 0
        if not tree_list:
            return 0
        return min(_depth(t) for t in tree_list if isinstance(t, dict))

    def _generate_feature_tree(self, repo_name: str, all_rel_files: List[str],
                                file_info: Dict[str, Dict],
                                readme_content: str = "",
                                config_content: Optional[Dict[str, str]] = None) -> Optional[dict]:
        top_folders = sorted({p.split("/", 1)[0] for p in all_rel_files if "/" in p})[:80]
        root_files = sorted([p for p in all_rel_files if "/" not in p])[:60]

        compact_info: List[dict] = []
        for rp in all_rel_files[:500]:
            entry: dict = {"path": rp}
            info = file_info.get(rp)
            if info:
                if info.get("symbols"):
                    entry["symbols"] = info["symbols"][:20]
                if info.get("imports"):
                    entry["imports"] = [imp[:80] for imp in info["imports"][:10]]
            compact_info.append(entry)

        config_section = ""
        if config_content:
            for fname, content in config_content.items():
                config_section += f"\n{fname}:\n{content}\n"

                                                                         

        pass1_prompt = f"""You are an expert software architect creating a CONCEPTUAL MAP of a repository.
Your job is to analyze the codebase and produce a DEEP, multi-level hierarchy that explains what this software does in plain English.

IMPORTANT: You are NOT listing files or code yet. You are creating a BUSINESS/FEATURE taxonomy — like a table of contents for a developer onboarding guide.

You MUST produce EXACTLY this structure:

LEVEL 1 — Business Domains (type: "domain")
  The broadest categories of what the software does. Think "chapters" of a book.
  Example: "User Management & Authentication", "Data Processing Pipeline", "API Gateway"
  MUST have 3-8 domains. Each domain MUST have a 2-3 sentence description explaining what it covers and why it exists.

LEVEL 2 — Services (type: "service")
  Major functional areas within each domain. Think "sections" of a chapter.
  Example: "OAuth Integration", "Session Management", "Password Security"
  Each domain MUST have 2-6 services. Each service MUST have a description.

LEVEL 3 — Components (type: "component")
  Specific functional components within each service. Think "subsections".
  Example: "Token Refresh Logic", "Login Form Handling", "Rate Limiting"
  Each service MUST have 2-5 components. Each component MUST have a description.

LEVEL 4 — Features (type: "feature")
  Individual features, workflows, or capabilities within each component.
  Example: "Email Verification Flow", "JWT Token Generation", "Brute Force Detection"
  Each component SHOULD have 1-4 features. Each feature MUST have a description and a "relevant_paths" array listing the repo-relative file paths that implement it.

CRITICAL RULES:
- Base EVERYTHING on the actual file paths, README, and project config below. Do NOT invent features that don't exist.
- The hierarchy must be at least 4 levels deep before mentioning any files.
- "relevant_paths" in Level 4 features must contain REAL file paths from the list below.
- A single file CAN appear under multiple features if it serves multiple purposes.
- Names must be short, human-readable labels (not file paths or code names).
- Descriptions must be helpful, specific, and written for a junior developer.

Return STRICT, VALID JSON ONLY. No markdown fences, no comments, no trailing commas.

Return this exact shape:
{{
  "repo_description": "2-3 sentence overview of the entire repository",
  "repo_details": "What makes this project unique and how it's organized",
  "domains": [
    {{
      "name": string,
      "description": string,
      "details": string,
      "services": [
        {{
          "name": string,
          "description": string,
          "details": string,
          "components": [
            {{
              "name": string,
              "description": string,
              "details": string,
              "features": [
                {{
                  "name": string,
                  "description": string,
                  "details": string,
                  "relevant_paths": ["path/to/file.ts", ...]
                }}
              ]
            }}
          ]
        }}
      ]
    }}
  ]
}}

=== REPO INFO ===
Repo name: {repo_name}
Top-level folders: {json.dumps(top_folders)}
Root files: {json.dumps(root_files)}

README:
{readme_content[:8000] if readme_content else "(not available)"}
{config_section}
All file paths with symbols:
{json.dumps(compact_info, ensure_ascii=False)}""".strip()

        print(f"[TreeBuilder] Pass 1: Generating conceptual hierarchy...")
        raw1 = self._safe_llm_call(pass1_prompt, max_tokens=16000)
        try:
            hierarchy = _parse_llm_json(raw1)
        except Exception as e:
            print(f"[TreeBuilder] Pass 1 JSON parse failed: {e!r}, falling back to single-pass")
            return self._generate_feature_tree_fallback(
                repo_name, all_rel_files, file_info, readme_content, config_section, compact_info, top_folders, root_files)

        if not isinstance(hierarchy, dict) or not isinstance(hierarchy.get("domains"), list):
            print(f"[TreeBuilder] Pass 1 returned unexpected shape, falling back")
            return self._generate_feature_tree_fallback(
                repo_name, all_rel_files, file_info, readme_content, config_section, compact_info, top_folders, root_files)

                                                                     
        tree_nodes: List[dict] = []
        for domain in hierarchy["domains"]:
            if not isinstance(domain, dict):
                continue
            domain_node = {
                "name": domain.get("name", ""),
                "type": "domain",
                "description": domain.get("description", ""),
                "details": domain.get("details", ""),
                "path": "",
                "purpose": domain.get("description", ""),
                "children": [],
            }
            for service in (domain.get("services") or []):
                if not isinstance(service, dict):
                    continue
                service_node = {
                    "name": service.get("name", ""),
                    "type": "service",
                    "description": service.get("description", ""),
                    "details": service.get("details", ""),
                    "path": "",
                    "purpose": service.get("description", ""),
                    "children": [],
                }
                for comp in (service.get("components") or []):
                    if not isinstance(comp, dict):
                        continue
                    comp_node = {
                        "name": comp.get("name", ""),
                        "type": "component",
                        "description": comp.get("description", ""),
                        "details": comp.get("details", ""),
                        "path": "",
                        "purpose": comp.get("description", ""),
                        "children": [],
                    }
                    for feat in (comp.get("features") or []):
                        if not isinstance(feat, dict):
                            continue
                        feat_node = {
                            "name": feat.get("name", ""),
                            "type": "feature",
                            "description": feat.get("description", ""),
                            "details": feat.get("details", ""),
                            "path": "",
                            "purpose": feat.get("description", ""),
                            "children": [],
                        }
                        for fp in (feat.get("relevant_paths") or []):
                            if isinstance(fp, str) and fp.strip():
                                feat_node["children"].append({
                                    "name": fp.rsplit("/", 1)[-1],
                                    "type": "file",
                                    "path": fp.strip(),
                                    "description": "",
                                    "details": "",
                                    "purpose": "",
                                    "children": [],
                                })
                        comp_node["children"].append(feat_node)
                    service_node["children"].append(comp_node)
                domain_node["children"].append(service_node)
            tree_nodes.append(domain_node)

        min_depth = self._measure_min_depth(tree_nodes)
        print(f"[TreeBuilder] Pass 1 complete — {len(tree_nodes)} domains, min depth to files: {min_depth}")

        if min_depth < 3:
            print(f"[TreeBuilder] Hierarchy too shallow (depth {min_depth}), retrying with fallback")
            return self._generate_feature_tree_fallback(
                repo_name, all_rel_files, file_info, readme_content, config_section, compact_info, top_folders, root_files)

        return {
            "repo_description": (hierarchy.get("repo_description") or "").strip(),
            "repo_details": (hierarchy.get("repo_details") or "").strip(),
            "tree": tree_nodes,
        }

    def _generate_feature_tree_fallback(self, repo_name: str,
                                         all_rel_files: List[str],
                                         file_info: Dict[str, Dict],
                                         readme_content: str,
                                         config_section: str,
                                         compact_info: list,
                                         top_folders: list,
                                         root_files: list) -> Optional[dict]:
        
        prompt = f"""You are generating a DEEP, multi-level, feature-first repository map.

The tree MUST have AT LEAST 4 LEVELS of plain-English categories BEFORE reaching any code files.
Do NOT skip levels. Do NOT put files directly under Level 1 or Level 2.

Here is a CONCRETE EXAMPLE of the expected depth (for a hypothetical e-commerce app):

Level 1 (domain): "Order Processing"
  Level 2 (service): "Payment Gateway Integration"
    Level 3 (component): "Stripe Checkout Flow"
      Level 4 (feature): "Payment Intent Creation"
        Level 5 (file): "services/stripe/create-intent.ts"

You MUST follow this exact pattern. Every domain must have services, every service must have components, every component must have features, and features contain the actual file paths.

LEVEL TYPES:
- "domain" — Business area (3-8 per repo)
- "service" — Functional area within domain (2-6 per domain)
- "component" — Specific capability within service (2-5 per service)
- "feature" — Individual workflow/feature (1-4 per component)
- "file" — Actual source file (real paths from list below)

RULES:
- Base everything on REAL file paths and symbols below
- Every file node "path" MUST match an actual repo-relative path
- Names must be short, human-readable, plain English
- Every node MUST have a helpful "description" (2-3 sentences)
- Every node MUST have "purpose" explaining why it exists

Return STRICT, VALID JSON ONLY.

Return this exact shape:
{{
  "repo_description": string,
  "repo_details": string,
  "tree": [
    {{
      "name": string,
      "type": "domain"|"service"|"component"|"feature"|"file"|"function"|"class",
      "description": string,
      "details": string,
      "path": string,
      "purpose": string,
      "children": [ ... same shape recursively ... ],
      "line_start": null,
      "line_end": null,
      "logic_flow": [],
      "api_calls": [],
      "dependencies": []
    }}
  ]
}}

=== REPO INFO ===
Repo name: {repo_name}
Top-level folders: {json.dumps(top_folders)}
Root files: {json.dumps(root_files)}

README:
{readme_content[:8000] if readme_content else "(not available)"}
{config_section}
Files with symbols:
{json.dumps(compact_info, ensure_ascii=False)}""".strip()

        print(f"[TreeBuilder] Fallback: Generating feature tree (single-pass)...")
        raw = self._safe_llm_call(prompt, max_tokens=16000)
        data = _parse_llm_json(raw)
        if isinstance(data, dict) and isinstance(data.get("tree"), list):
            return data
        return None

                                                                        
                                 
                                                                        

    def _build_enrich_prompt(self, file_data: list) -> str:
        return f"""Analyze these source files and return enriched metadata.
Write every description in simple, clear English that a newcomer to this codebase could understand.

For EACH file, return:
- file_purpose: 2-3 sentences — what this file does and its role in the system.
- file_explanation: 3-5 sentences — HOW it works: patterns used, data flow, how it connects to the rest. Write like friendly developer docs.
- For each function/class:
  - purpose: 1-2 sentences — what it does and why it exists.
  - explanation: 3-6 sentences — HOW it works internally: what it checks, transforms, edge cases, return values. Write like short developer onboarding docs.
  - logic_flow: array of step-by-step descriptions of the internal logic (plain English, like "1. Validates the input parameters", "2. Queries the database for matching records")
  - api_calls: external function/endpoint names called
  - dependencies: key imports/libraries used

Return STRICT VALID JSON only. Escape all special characters. No markdown, no comments, no trailing commas. Keep each string under 300 characters.

Return exactly:
{{
  "files": [
    {{
      "path": string,
      "file_purpose": string,
      "file_explanation": string,
      "symbols": [
        {{
          "name": string,
          "purpose": string,
          "explanation": string,
          "logic_flow": [string],
          "api_calls": [string],
          "dependencies": [string]
        }}
      ]
    }}
  ]
}}

Files:
{json.dumps(file_data, ensure_ascii=False)}""".strip()

    def _apply_enrichment(self, file_node: TreeNode, fdata: dict):
        fp = (fdata.get("file_purpose") or "").strip()
        fe = (fdata.get("file_explanation") or "").strip()
        if fp:
            file_node.purpose = fp
            if not file_node.description:
                file_node.description = fp
        if fe:
            file_node.explanation = fe

        sym_map = {}
        for s in (fdata.get("symbols") or []):
            if isinstance(s, dict) and s.get("name"):
                sym_map[s["name"]] = s

        for child in file_node.children:
            if child.type not in ("function", "class"):
                continue
            sdata = sym_map.get(child.name)
            if not sdata:
                continue
            p = (sdata.get("purpose") or "").strip()
            if p:
                child.purpose = p
                if not child.description:
                    child.description = p
            e = (sdata.get("explanation") or "").strip()
            if e:
                child.explanation = e
            child.logic_flow = [str(x) for x in (sdata.get("logic_flow") or []) if x]
            child.api_calls = [str(x) for x in (sdata.get("api_calls") or []) if x]
            child.dependencies = [str(x) for x in (sdata.get("dependencies") or []) if x]

    def _prepare_file_data(self, fn: TreeNode, file_sources: Dict[str, str]) -> dict:
        src = file_sources.get(fn.path, "")
        if len(src) > 3000:
            src = src[:3000] + "\n// ... (truncated)"
        syms = [{"name": c.name, "type": c.type,
                 "line_start": c.line_start, "line_end": c.line_end}
                for c in fn.children if c.type in ("function", "class")]
        return {"path": fn.path, "language": fn.language or "", "source": src, "symbols": syms}

    def _enrich_files(self, code_root: TreeNode, file_sources: Dict[str, str],
                      max_files: int = 999):
        file_nodes: List[TreeNode] = []
        def _collect_files(n: TreeNode):
            if n.type == "file" and n.path and n.path in file_sources:
                file_nodes.append(n)
            for c in n.children:
                _collect_files(c)
        _collect_files(code_root)

        file_nodes.sort(key=lambda n: len(n.children), reverse=True)
        batch = file_nodes[:max_files]
        if not batch:
            return

        print(f"[TreeBuilder] Enriching {len(batch)} files with AI analysis...")
        BATCH_SIZE = 3
        failed: List[TreeNode] = []

        for i in range(0, len(batch), BATCH_SIZE):
            chunk = batch[i:i + BATCH_SIZE]
            file_data = [self._prepare_file_data(fn, file_sources) for fn in chunk]
            prompt = self._build_enrich_prompt(file_data)
            try:
                raw = self._safe_llm_call_fast(prompt, max_tokens=6000)
                data = _parse_llm_json(raw)
                if not isinstance(data, dict) or "files" not in data:
                    failed.extend(chunk)
                    continue
                by_path = {f["path"]: f for f in data["files"] if isinstance(f, dict) and "path" in f}
                for fn in chunk:
                    fdata = by_path.get(fn.path)
                    if fdata:
                        self._apply_enrichment(fn, fdata)
                    else:
                        failed.append(fn)
            except Exception as e:
                print(f"[TreeBuilder] Batch enrichment failed: {e!r}")
                failed.extend(chunk)

        if failed:
            print(f"[TreeBuilder] Retrying {len(failed)} files individually...")
            for fn in failed:
                file_data = [self._prepare_file_data(fn, file_sources)]
                prompt = self._build_enrich_prompt(file_data)
                try:
                    raw = self._safe_llm_call_fast(prompt, max_tokens=3000)
                    data = _parse_llm_json(raw)
                    if isinstance(data, dict) and "files" in data:
                        for fdata in data["files"]:
                            if isinstance(fdata, dict):
                                self._apply_enrichment(fn, fdata)
                                break
                except Exception as e:
                    print(f"[TreeBuilder] Single file enrichment failed for {fn.path}: {e!r}")

                                                                        
                                                
                                                                        

    @staticmethod
    def _spec_to_tree_node(spec: dict) -> TreeNode:
        name = (spec.get("name") or "").strip() or "(unnamed)"
        ntype = (spec.get("type") or "feature").strip()
        desc = (spec.get("description") or "").strip()
        details = (spec.get("details") or "").strip()
        path = (spec.get("path") or "").strip()
        purpose = (spec.get("purpose") or "").strip()
        line_start = spec.get("line_start")
        line_end = spec.get("line_end")
        logic_flow = [str(x) for x in (spec.get("logic_flow") or []) if x]
        api_calls = [str(x) for x in (spec.get("api_calls") or []) if x]
        deps = [str(x) for x in (spec.get("dependencies") or []) if x]

        node = TreeNode(
            name=name, type=ntype, path=path, description=desc, details=details,
            purpose=purpose,
            line_start=int(line_start) if isinstance(line_start, (int, float)) else None,
            line_end=int(line_end) if isinstance(line_end, (int, float)) else None,
            logic_flow=logic_flow, api_calls=api_calls, dependencies=deps,
        )
        for ch in (spec.get("children") or []):
            if isinstance(ch, dict):
                node.children.append(TreeBuilder._spec_to_tree_node(ch))
        return node

    @staticmethod
    def _clone_subtree(node: TreeNode) -> TreeNode:
        c = TreeNode(
            name=node.name, type=node.type, path=node.path,
            description=node.description, details=node.details,
            language=node.language, usages=list(node.usages or []),
            line_start=node.line_start, line_end=node.line_end,
            purpose=node.purpose, explanation=node.explanation,
            logic_flow=list(node.logic_flow or []),
            dependencies=list(node.dependencies or []),
            api_calls=list(node.api_calls or []),
            code_sample=node.code_sample,
        )
        c.children = [TreeBuilder._clone_subtree(ch) for ch in (node.children or [])]
        return c

    @staticmethod
    def _index_file_nodes(root: TreeNode) -> Dict[str, TreeNode]:
        out: Dict[str, TreeNode] = {}
        def dfs(n):
            if n.type == "file" and n.path:
                out[n.path] = n
            for c in n.children:
                dfs(c)
        dfs(root)
        return out

    @staticmethod
    def _graft_real_code(ai_node: TreeNode, file_lookup: Dict[str, TreeNode]):
        if ai_node.type == "file" and ai_node.path and ai_node.path in file_lookup:
            real = file_lookup[ai_node.path]
            cloned = TreeBuilder._clone_subtree(real)
            if ai_node.description and not cloned.description:
                cloned.description = ai_node.description
            if ai_node.details and not cloned.details:
                cloned.details = ai_node.details
            if ai_node.purpose and not cloned.purpose:
                cloned.purpose = ai_node.purpose
            ai_node.children = cloned.children
            ai_node.language = cloned.language or ai_node.language
            ai_node.dependencies = cloned.dependencies or ai_node.dependencies
            ai_node.line_start = cloned.line_start or ai_node.line_start
            ai_node.line_end = cloned.line_end or ai_node.line_end
            return
        for child in ai_node.children:
            TreeBuilder._graft_real_code(child, file_lookup)

                                                                        
                           
                                                                        

    @staticmethod
    def ensure_fallback_descriptions(root: TreeNode):
        stack = [root]
        while stack:
            n = stack.pop()
            TreeBuilder._ensure_node_content(n)
            stack.extend(n.children or [])

    @staticmethod
    def _ensure_node_content(n: TreeNode):
        base = n.name or "(unnamed)"
        t = n.type
        child_names = [c.name for c in (n.children or []) if c.name]

        if not (n.description or "").strip():
            n.description = TreeBuilder._gen_description(n, base, t, child_names)
        if not (n.purpose or "").strip():
            n.purpose = n.description
        if not (n.explanation or "").strip():
            n.explanation = TreeBuilder._gen_explanation(n, base, t, child_names)
        if not (n.details or "").strip():
            n.details = n.description

    @staticmethod
    def _gen_description(n: TreeNode, base: str, t: str, child_names: List[str]) -> str:
        if t == "repo":
            return f"Repository: {base}. Contains {len(n.children or [])} top-level sections."
        if t in ("features", "feature", "domain", "service", "component", "capability"):
            if child_names:
                return f"{base} — includes {', '.join(child_names[:5])}{'...' if len(child_names) > 5 else ''}."
            return base
        if t == "folder":
            file_count = sum(1 for c in (n.children or []) if c.type == "file")
            dir_count = sum(1 for c in (n.children or []) if c.type == "folder")
            parts = []
            if file_count:
                parts.append(f"{file_count} file{'s' if file_count != 1 else ''}")
            if dir_count:
                parts.append(f"{dir_count} subfolder{'s' if dir_count != 1 else ''}")
            contents = f" containing {' and '.join(parts)}" if parts else ""
            return f"Directory '{base}'{contents}."
        if t == "code":
            return "Complete file tree with all source code, folders, and parsed symbols."
        if t == "file":
            lang = (n.language or "source").capitalize()
            funcs = [c.name for c in (n.children or []) if c.type == "function"]
            classes = [c.name for c in (n.children or []) if c.type == "class"]
            parts = []
            if classes:
                parts.append(f"classes: {', '.join(classes[:4])}")
            if funcs:
                parts.append(f"functions: {', '.join(funcs[:6])}")
            detail = f" Defines {'; '.join(parts)}." if parts else ""
            return f"{lang} file '{base}'.{detail}"
        if t == "function":
            loc = f" at lines {n.line_start}-{n.line_end}" if n.line_start and n.line_end else ""
            return f"Function '{base}'{loc} in {n.path or 'unknown'}."
        if t == "class":
            methods = [c.name for c in (n.children or []) if c.type == "function"]
            method_str = f" Methods: {', '.join(methods[:6])}." if methods else ""
            return f"Class '{base}'.{method_str}"
        return base

    @staticmethod
    def _gen_explanation(n: TreeNode, base: str, t: str, child_names: List[str]) -> str:
        if t == "repo":
            return f"This repository contains the full source for '{base}'. Browse Features & Architecture for a high-level overview, or Code for the raw file tree."
        if t in ("features", "feature", "domain", "service", "component", "capability"):
            if child_names:
                return f"This section groups related functionality under '{base}'. It contains: {', '.join(child_names[:8])}. Expand each to drill down into implementation details."
            return f"This section represents the '{base}' area of the codebase."
        if t == "folder":
            if child_names:
                return f"The '{base}' directory organizes code into: {', '.join(child_names[:8])}."
            return f"Directory '{base}' in the project structure."
        if t == "code":
            return "Raw file-system view of the repository. Every folder, file, function, and class is listed here."
        if t == "file":
            lang = (n.language or "source").capitalize()
            funcs = [c for c in (n.children or []) if c.type == "function"]
            classes = [c for c in (n.children or []) if c.type == "class"]
            parts = []
            if n.path:
                parts.append(f"Located at '{n.path}'.")
            if classes:
                parts.append(f"Defines {len(classes)} class(es): {', '.join(c.name for c in classes[:4])}.")
            if funcs:
                parts.append(f"Contains {len(funcs)} function(s): {', '.join(f.name for f in funcs[:6])}.")
            return f"{lang} source file. " + " ".join(parts) if parts else f"{lang} source file '{base}'."
        if t == "function":
            loc = f" (lines {n.line_start}-{n.line_end})" if n.line_start and n.line_end else ""
            deps = f" Uses: {', '.join(n.dependencies[:4])}." if n.dependencies else ""
            apis = f" Calls: {', '.join(n.api_calls[:4])}." if n.api_calls else ""
            return f"Function '{base}' defined{loc} in '{n.path or 'unknown'}'.{deps}{apis}"
        if t == "class":
            methods = [c.name for c in (n.children or []) if c.type == "function"]
            if methods:
                return f"Class '{base}' with methods: {', '.join(methods[:8])}. Expand to see implementation."
            return f"Class '{base}' defined in '{n.path or 'unknown'}'."
        return n.description or base

                                                                        
                      
                                                                        

    def build_tree(self, files: List[Dict[str, Any]], repo_name: str,
                   readme_content: str = "") -> dict:
        
        print(f"[TreeBuilder] Building tree for '{repo_name}' ({len(files)} files)")

        code_root, file_sources, file_info = self._build_code_tree(files, repo_name)
        file_lookup = self._index_file_nodes(code_root)
        all_rel_files = sorted(file_lookup.keys())

        config_content = self._extract_config_content(files)

        if self.client:
            self._enrich_files(code_root, file_sources, max_files=999)

        features_root = TreeNode(
            name="Features & Architecture", type="features", path="",
            description="High-level view: business domains, services, components, then code.",
            details="Navigate from business concepts down to individual functions.",
        )

        ai_data = None
        if self.client:
            try:
                ai_data = self._generate_feature_tree(
                    repo_name, all_rel_files, file_info, readme_content,
                    config_content=config_content)
            except Exception as e:
                print(f"[TreeBuilder] Feature tree generation failed: {e!r}")

        if ai_data and isinstance(ai_data.get("tree"), list) and ai_data["tree"]:
            for spec in ai_data["tree"]:
                if isinstance(spec, dict):
                    node = self._spec_to_tree_node(spec)
                    self._graft_real_code(node, file_lookup)
                    features_root.children.append(node)
            repo_desc = (ai_data.get("repo_description") or "").strip()
            repo_details = (ai_data.get("repo_details") or "").strip()
        else:
            groups: Dict[str, List[str]] = {}
            for p in all_rel_files:
                seg = p.split("/", 1)[0] if "/" in p else "(root files)"
                groups.setdefault(seg, []).append(p)
            for seg in sorted(groups.keys(), key=lambda s: (s == "(root files)", s.lower())):
                node = TreeNode(name=seg, type="component", path="",
                                description=f"Code area: {seg}")
                for fp in sorted(groups[seg])[:60]:
                    src = file_lookup.get(fp)
                    node.children.append(
                        self._clone_subtree(src) if src else TreeNode(name=fp.rsplit("/", 1)[-1], type="file", path=fp))
                features_root.children.append(node)
            repo_desc = "Feature-first repository map with code drill-down."
            repo_details = "Start from Features for high-level understanding, then drill into Code for implementation."

        code_root_clone = self._clone_subtree(code_root)
        code_root_clone.name = "Code (all files)"
        code_root_clone.type = "code"
        code_root_clone.description = "Full file-tree view: folders, files, functions, classes."

        root = TreeNode(
            name=repo_name, type="repo", path=".",
            description=repo_desc, details=repo_details,
            children=[features_root, code_root_clone],
        )
        self.ensure_fallback_descriptions(root)

        print(f"[TreeBuilder] Tree built successfully")
        return root.to_dict()
