import hashlib
from typing import Any, Dict, List, Optional

from neurocode.config import github_fetcher, vectorizer
from neurocode.services.analysis.parser import TreeSitterParser
from neurocode.services.graph_analytics import compute_risk_scores, detect_communities
from neurocode.services.neo4j_service import Neo4jService
from neurocode.services.semantic_clustering import run_semantic_clustering

                                                                                 

CODE_EXTENSIONS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".go", ".rs", ".java", ".cs",
    ".cpp", ".c", ".rb", ".php", ".swift", ".kt",
    ".vue", ".svelte",
}
SKIP_DIRS = {
    "node_modules", ".git", "dist", "build", ".next", "__pycache__",
    ".pytest_cache", "vendor", ".venv", "venv", "coverage",
    ".turbo", ".cache", "out", "target", "bin", "obj",
    ".idea", ".vscode",
}
MAX_FILE_BYTES = 200_000          


def _should_include(path: str, content: str) -> bool:
    parts = path.split("/")
    for part in parts[:-1]:
        if part in SKIP_DIRS or part.startswith("."):
            return False
    name = parts[-1]
    ext = ("." + name.rsplit(".", 1)[-1]) if "." in name else ""
    return ext.lower() in CODE_EXTENSIONS and len(content) < MAX_FILE_BYTES


                                                                                 

def _hid(*parts: str) -> str:
    return hashlib.sha1(":".join(parts).encode()).hexdigest()[:16]


def _build_nodes_and_edges(structure: Any) -> tuple:
    nodes: List[Dict] = []
    edges: List[Dict] = []
    node_ids: set = set()

    def add_node(node_id: str, label: str, props: dict) -> None:
        if node_id not in node_ids:
            node_ids.add(node_id)
            nodes.append({"id": node_id, "label": label, "properties": props})

    def add_edge(edge_id: str, edge_type: str, src: str, tgt: str) -> None:
        if src in node_ids and tgt in node_ids:
            edges.append(
                {"id": edge_id, "type": edge_type, "sourceId": src, "targetId": tgt}
            )

    TYPE_MAP = {
        "import": "IMPORTS",
        "call": "CALLS",
        "extends": "INHERITS",
        "implements": "IMPLEMENTS",
    }

    for parsed_file in structure.files:
        parts = [p for p in parsed_file.path.split("/") if p]
        parent_id: Optional[str] = None
        current_path = ""

        for i, part in enumerate(parts):
            current_path = f"{current_path}/{part}" if current_path else part
            is_file = i == len(parts) - 1
            label = "File" if is_file else "Folder"
            node_id = _hid(label, current_path)

            props: Dict = {"name": part, "filePath": current_path}
            if is_file:
                props["language"] = parsed_file.language

            add_node(node_id, label, props)
            if parent_id:
                add_edge(_hid("CONTAINS", parent_id, node_id), "CONTAINS", parent_id, node_id)
            parent_id = node_id

        file_id = _hid("File", parsed_file.path)

        for func in parsed_file.functions:
            func_id = _hid("Function", parsed_file.path, func.name, str(func.startLine))
            add_node(
                func_id,
                "Function",
                {
                    "name": func.name,
                    "filePath": parsed_file.path,
                    "startLine": func.startLine,
                    "endLine": func.endLine,
                    "language": parsed_file.language,
                    "isAsync": func.isAsync,
                    "isExported": func.isExported,
                },
            )
            add_edge(_hid("CONTAINS", file_id, func_id), "CONTAINS", file_id, func_id)

        for cls in parsed_file.classes:
            cls_id = _hid("Class", parsed_file.path, cls.name, str(cls.startLine))
            add_node(
                cls_id,
                "Class",
                {
                    "name": cls.name,
                    "filePath": parsed_file.path,
                    "startLine": cls.startLine,
                    "endLine": cls.endLine,
                    "language": parsed_file.language,
                    "isExported": cls.isExported,
                    "extends": cls.extends,
                },
            )
            add_edge(_hid("CONTAINS", file_id, cls_id), "CONTAINS", file_id, cls_id)

            for method in cls.methods:
                method_id = _hid(
                    "Method", parsed_file.path, cls.name, method.name, str(method.startLine)
                )
                add_node(
                    method_id,
                    "Method",
                    {
                        "name": method.name,
                        "filePath": parsed_file.path,
                        "startLine": method.startLine,
                        "endLine": method.endLine,
                        "language": parsed_file.language,
                        "isAsync": method.isAsync,
                        "isStatic": method.isStatic,
                    },
                )
                add_edge(_hid("HAS_METHOD", cls_id, method_id), "HAS_METHOD", cls_id, method_id)

    for dep in structure.dependencies:
        edge_type = TYPE_MAP.get(dep.type)
        if not edge_type:
            continue
        src = _hid("File", dep.from_path)
        tgt = _hid("File", dep.to_path)
        add_edge(_hid(edge_type, dep.from_path, dep.to_path, dep.relationship), edge_type, src, tgt)

    return nodes, edges


                                                                                 

async def build_kg_for_repo(
    *,
    repo_id: str,
    repo_full_name: str,
    github_token: str,
    branch: str = "main",
) -> Dict[str, Any]:
    
    print(f"[KG Pipeline] ▶ {repo_full_name} (repo_id={repo_id})", flush=True)

                    
    print("[KG Pipeline] Fetching files from GitHub...", flush=True)
    all_files = await github_fetcher.fetch_repository_files(
        repo_full_name=repo_full_name,
        access_token=github_token,
        branch=branch,
    )
    code_files = [
        f for f in all_files if _should_include(f["path"], f.get("content", ""))
    ]
    print(
        f"[KG Pipeline] {len(code_files)}/{len(all_files)} code files selected",
        flush=True,
    )

    if not code_files:
        return {"success": False, "error": "No code files found in repository"}

                               
    print("[KG Pipeline] Parsing with tree-sitter...", flush=True)
    parser = TreeSitterParser()
    result = await parser.parse_files(
        [
            {"path": f["path"], "content": f["content"], "language": f.get("language")}
            for f in code_files
        ]
    )
    nodes, edges = _build_nodes_and_edges(result.structure)
    print(
        f"[KG Pipeline] Parsed → {len(nodes)} nodes, {len(edges)} edges",
        flush=True,
    )

                                                   
    print("[KG Pipeline] Running community detection...", flush=True)
    nodes, edges = detect_communities(nodes, edges)
    print(
        f"[KG Pipeline] After communities → {len(nodes)} nodes, {len(edges)} edges",
        flush=True,
    )

                     
    print("[KG Pipeline] Computing risk scores...", flush=True)
    nodes = compute_risk_scores(nodes, edges)

                                                         
    print("[KG Pipeline] Running semantic clustering...", flush=True)
    file_contents = {f["path"]: f.get("content", "") for f in code_files}
    embed_model = getattr(getattr(vectorizer, "embedding_service", None), "model", None)
    nodes = run_semantic_clustering(nodes, file_contents, embed_model=embed_model)

                       
    print("[KG Pipeline] Writing to Neo4j...", flush=True)
    neo4j = Neo4jService()
    try:
        await neo4j.write_graph(repo_id, nodes, edges)
    finally:
        await neo4j.close()

    print(
        f"[KG Pipeline] ✓ Done — {len(nodes)} nodes, {len(edges)} edges stored",
        flush=True,
    )

    return {
        "success": True,
        "nodes": nodes,
        "relationships": edges,
        "metadata": {
            "nodeCount": len(nodes),
            "edgeCount": len(edges),
            "filesProcessed": len(code_files),
        },
    }
