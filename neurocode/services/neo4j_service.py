import json
import logging
import os
from typing import Any, Dict, List, Optional

from neo4j import AsyncGraphDatabase

                                                                            
                                                                                      
logging.getLogger("neo4j").setLevel(logging.ERROR)

                                                    
RELATIONSHIP_TYPES = {
    "CALLS",
    "IMPORTS",
    "CONTAINS",
    "INHERITS",
    "IMPLEMENTS",
    "HAS_METHOD",
    "MEMBER_OF",
    "PROCESS_STEP",
}

_BATCH = 500


class Neo4jService:
    def __init__(self) -> None:
        uri = os.getenv("NEO4J_URI", "")
        username = os.getenv("NEO4J_USERNAME", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "")
        if not uri or not password:
            raise ValueError("NEO4J_URI and NEO4J_PASSWORD must be set in environment")
        self._driver = AsyncGraphDatabase.driver(uri, auth=(username, password))

    async def close(self) -> None:
        await self._driver.close()

                                                                                 

    async def graph_exists(self, repo_id: str) -> bool:
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n:CodeNode {repoId: $repoId}) RETURN count(n) AS cnt LIMIT 1",
                repoId=repo_id,
            )
            record = await result.single()
            return int(record["cnt"] if record else 0) > 0

    async def write_graph(
        self,
        repo_id: str,
        nodes: List[Dict[str, Any]],
        relationships: List[Dict[str, Any]],
    ) -> None:
        async with self._driver.session() as session:
                                                 
            await session.run(
                "MATCH (n:CodeNode {repoId: $repoId}) DETACH DELETE n",
                repoId=repo_id,
            )

                                          
            try:
                await session.run(
                    "CREATE INDEX code_node_repo IF NOT EXISTS "
                    "FOR (n:CodeNode) ON (n.repoId, n.nodeId)"
                )
            except Exception:
                pass

                                    
            for i in range(0, len(nodes), _BATCH):
                batch = [
                    {
                        "id": n["id"],
                        "label": n["label"],
                        "data": json.dumps(n["properties"], default=str),
                    }
                    for n in nodes[i : i + _BATCH]
                ]
                await session.run(
                    """
                    UNWIND $batch AS node
                    CREATE (n:CodeNode {
                        repoId:    $repoId,
                        nodeId:    node.id,
                        nodeLabel: node.label,
                        data:      node.data
                    })
                    """,
                    batch=batch,
                    repoId=repo_id,
                )

                                                                                         
            rels_by_type: Dict[str, List] = {}
            for rel in relationships:
                t = rel.get("type", "")
                if t in RELATIONSHIP_TYPES:
                    rels_by_type.setdefault(t, []).append(rel)

            for rel_type, rels in rels_by_type.items():
                for i in range(0, len(rels), _BATCH):
                    batch = [
                        {
                            "srcId": r["sourceId"],
                            "tgtId": r["targetId"],
                            "relId": r.get("id", ""),
                        }
                        for r in rels[i : i + _BATCH]
                    ]
                    await session.run(
                        f"""
                        UNWIND $batch AS rel
                        MATCH (src:CodeNode {{repoId: $repoId, nodeId: rel.srcId}})
                        MATCH (tgt:CodeNode {{repoId: $repoId, nodeId: rel.tgtId}})
                        CREATE (src)-[:{rel_type} {{relId: rel.relId, repoId: $repoId}}]->(tgt)
                        """,
                        batch=batch,
                        repoId=repo_id,
                    )

    async def read_graph(self, repo_id: str) -> Optional[Dict[str, Any]]:
        async with self._driver.session() as session:
            if not await self.graph_exists(repo_id):
                return None

            nodes_result = await session.run(
                "MATCH (n:CodeNode {repoId: $repoId}) "
                "RETURN n.nodeId AS id, n.nodeLabel AS label, n.data AS data",
                repoId=repo_id,
            )
            nodes: List[Dict] = []
            async for record in nodes_result:
                nodes.append(
                    {
                        "id": record["id"],
                        "label": record["label"],
                        "properties": json.loads(record["data"] or "{}"),
                    }
                )

            rels_result = await session.run(
                """
                MATCH (src:CodeNode {repoId: $repoId})-[r]->(tgt:CodeNode {repoId: $repoId})
                RETURN r.relId AS id,
                       type(r)   AS relType,
                       src.nodeId AS sourceId,
                       tgt.nodeId AS targetId
                """,
                repoId=repo_id,
            )
            relationships: List[Dict] = []
            async for record in rels_result:
                relationships.append(
                    {
                        "id": record["id"] or "",
                        "type": record["relType"],
                        "sourceId": record["sourceId"],
                        "targetId": record["targetId"],
                    }
                )

            return {
                "nodes": nodes,
                "relationships": relationships,
                "metadata": {
                    "nodeCount": len(nodes),
                    "edgeCount": len(relationships),
                },
            }

    async def delete_graph(self, repo_id: str) -> None:
        async with self._driver.session() as session:
            await session.run(
                "MATCH (n:CodeNode {repoId: $repoId}) DETACH DELETE n",
                repoId=repo_id,
            )
