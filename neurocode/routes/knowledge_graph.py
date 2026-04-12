import hashlib
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from neurocode.services.analysis.parser import TreeSitterParser
from neurocode.services.neo4j_service import Neo4jService

router = APIRouter(tags=["knowledge-graph"])


                                                                                 

@router.get("/api/knowledge-graph/{repo_id}")
async def get_knowledge_graph(repo_id: str):
    
    try:
        neo4j = Neo4jService()
        try:
            graph = await neo4j.read_graph(repo_id)
        finally:
            await neo4j.close()

        if graph is None:
            return {"status": "not_built"}

        return {"status": "ready", **graph}
    except ValueError as e:
                              
        raise HTTPException(status_code=503, detail=f"Neo4j not configured: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


                                                                                

class FileInput(BaseModel):
    path: str
    content: str
    language: Optional[str] = None


class KnowledgeGraphRequest(BaseModel):
    files: List[FileInput]


                                                                                

def _id(*parts: str) -> str:
    
    return hashlib.sha1(":".join(parts).encode()).hexdigest()[:16]


                                                                                

@router.post("/api/knowledge-graph")
async def build_knowledge_graph(request: KnowledgeGraphRequest):
    
    raw_files = [
        {"path": f.path, "content": f.content, "language": f.language}
        for f in request.files
    ]

    parser = TreeSitterParser()
    result = await parser.parse_files(raw_files)
    structure = result.structure

    nodes: list = []
    edges: list = []
    node_ids: set = set()

    def add_node(node_id: str, label: str, props: dict) -> None:
        if node_id not in node_ids:
            node_ids.add(node_id)
            nodes.append({"id": node_id, "label": label, "properties": props})

    def add_edge(edge_id: str, edge_type: str, src: str, tgt: str) -> None:
        if src in node_ids and tgt in node_ids:
            edges.append({"id": edge_id, "type": edge_type, "sourceId": src, "targetId": tgt})

                                                                                 
    for parsed_file in structure.files:
        parts = [p for p in parsed_file.path.split("/") if p]
        parent_id: Optional[str] = None
        current_path = ""

        for i, part in enumerate(parts):
            current_path = f"{current_path}/{part}" if current_path else part
            is_file = i == len(parts) - 1
            label = "File" if is_file else "Folder"
            node_id = _id(label, current_path)

            props: dict = {"name": part, "filePath": current_path}
            if is_file:
                props["language"] = parsed_file.language

            add_node(node_id, label, props)

            if parent_id:
                add_edge(_id("CONTAINS", parent_id, node_id), "CONTAINS", parent_id, node_id)

            parent_id = node_id

        file_id = _id("File", parsed_file.path)

                                                                                 
        for func in parsed_file.functions:
            func_id = _id("Function", parsed_file.path, func.name, str(func.startLine))
            add_node(func_id, "Function", {
                "name": func.name,
                "filePath": parsed_file.path,
                "startLine": func.startLine,
                "endLine": func.endLine,
                "language": parsed_file.language,
                "isAsync": func.isAsync,
                "isExported": func.isExported,
            })
            add_edge(_id("CONTAINS", file_id, func_id), "CONTAINS", file_id, func_id)

                                                                                 
        for cls in parsed_file.classes:
            cls_id = _id("Class", parsed_file.path, cls.name, str(cls.startLine))
            add_node(cls_id, "Class", {
                "name": cls.name,
                "filePath": parsed_file.path,
                "startLine": cls.startLine,
                "endLine": cls.endLine,
                "language": parsed_file.language,
                "isExported": cls.isExported,
                "extends": cls.extends,
            })
            add_edge(_id("CONTAINS", file_id, cls_id), "CONTAINS", file_id, cls_id)

            for method in cls.methods:
                method_id = _id("Method", parsed_file.path, cls.name, method.name, str(method.startLine))
                add_node(method_id, "Method", {
                    "name": method.name,
                    "filePath": parsed_file.path,
                    "startLine": method.startLine,
                    "endLine": method.endLine,
                    "language": parsed_file.language,
                    "isAsync": method.isAsync,
                    "isStatic": method.isStatic,
                })
                add_edge(_id("HAS_METHOD", cls_id, method_id), "HAS_METHOD", cls_id, method_id)

                                                                                 
    TYPE_MAP = {
        "import": "IMPORTS",
        "call": "CALLS",
        "extends": "INHERITS",
        "implements": "IMPLEMENTS",
    }

    for dep in structure.dependencies:
        edge_type = TYPE_MAP.get(dep.type)
        if not edge_type:
            continue

        src = _id("File", dep.from_path)
        tgt = _id("File", dep.to_path)
        edge_id = _id(edge_type, dep.from_path, dep.to_path, dep.relationship)
        add_edge(edge_id, edge_type, src, tgt)

    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            **result.metadata,
            "totalNodes": len(nodes),
            "totalEdges": len(edges),
        },
    }
