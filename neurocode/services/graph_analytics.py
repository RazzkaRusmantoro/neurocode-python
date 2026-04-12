import hashlib
from collections import defaultdict
from typing import Any, Dict, List, Tuple

                                                                                 

SYMBOL_LABELS = {"Function", "Class", "Method", "Interface"}
COMMUNITY_EDGE_TYPES = {"CALLS", "INHERITS", "IMPLEMENTS"}
RISK_EDGE_TYPES = {"CALLS", "IMPORTS", "INHERITS", "IMPLEMENTS", "HAS_METHOD"}

RISK_WEIGHTS = {
    "in_degree": 0.40,
    "crossings": 0.30,
    "loc": 0.20,
    "out_degree": 0.10,
}
SCORED_LABELS = {"Function", "Class", "Method", "Interface", "File"}


def _id(*parts: str) -> str:
    return hashlib.sha1(":".join(parts).encode()).hexdigest()[:16]


                                                                                 

def detect_communities(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    
    try:
        import networkx as nx
        from networkx.algorithms.community import louvain_communities
    except ImportError:
        print("[graph_analytics] networkx not available — skipping community detection", flush=True)
        return nodes, edges

    symbol_ids = {n["id"] for n in nodes if n["label"] in SYMBOL_LABELS}

    G = nx.Graph()
    for nid in symbol_ids:
        G.add_node(nid)
    for e in edges:
        if (
            e["type"] in COMMUNITY_EDGE_TYPES
            and e["sourceId"] in symbol_ids
            and e["targetId"] in symbol_ids
        ):
            G.add_edge(e["sourceId"], e["targetId"])

    if G.number_of_nodes() == 0:
        return nodes, edges

    try:
        communities = louvain_communities(G, seed=42, resolution=1.0)
    except Exception as ex:
        print(f"[graph_analytics] Louvain failed: {ex}", flush=True)
        return nodes, edges

                         
    partition: Dict[str, int] = {}
    for idx, community_set in enumerate(communities):
        for nid in community_set:
            partition[nid] = idx

    node_map = {n["id"]: n for n in nodes}
    new_nodes: List[Dict] = list(nodes)
    new_edges: List[Dict] = list(edges)

    for comm_idx, community_set in enumerate(communities):
        if len(community_set) < 2:
            continue

        comm_id = f"comm_{comm_idx}"
        member_nodes = [node_map[nid] for nid in community_set if nid in node_map]

                                                           
        file_parts: List[str] = []
        for mn in member_nodes:
            fp: str = mn["properties"].get("filePath", "")
            parts = fp.split("/")
            if len(parts) > 1:
                file_parts.append(parts[0])

        heuristic_label = "Community"
        if file_parts:
            most_common = max(set(file_parts), key=file_parts.count)
            heuristic_label = (
                most_common.replace("_", " ").replace("-", " ").title() or "Community"
            )

                                                                       
        subgraph = G.subgraph(community_set)
        possible = len(community_set) * (len(community_set) - 1) / 2
        cohesion = round(subgraph.number_of_edges() / max(1.0, possible), 3)

        new_nodes.append(
            {
                "id": comm_id,
                "label": "Community",
                "properties": {
                    "name": heuristic_label,
                    "filePath": "",
                    "heuristicLabel": heuristic_label,
                    "symbolCount": len(community_set),
                    "cohesion": cohesion,
                    "communityIndex": comm_idx,
                },
            }
        )

        for nid in community_set:
            new_edges.append(
                {
                    "id": _id("MEMBER_OF", nid, comm_id),
                    "type": "MEMBER_OF",
                    "sourceId": nid,
                    "targetId": comm_id,
                }
            )

                                               
    for n in new_nodes:
        if n["id"] in partition:
            n["properties"]["communityIndex"] = partition[n["id"]]

    return new_nodes, new_edges


                                                                                 

def compute_risk_scores(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    
    scored_ids = {n["id"] for n in nodes if n["label"] in SCORED_LABELS}
    if not scored_ids:
        return nodes

                                                                               
    community_of: Dict[str, int] = {}
    for e in edges:
        if e["type"] == "MEMBER_OF" and e["sourceId"] in scored_ids:
            try:
                community_of[e["sourceId"]] = int(e["targetId"].replace("comm_", ""))
            except ValueError:
                pass

    in_deg: Dict[str, int] = defaultdict(int)
    out_deg: Dict[str, int] = defaultdict(int)
    crossings: Dict[str, int] = defaultdict(int)

    for e in edges:
        if e["type"] not in RISK_EDGE_TYPES:
            continue
        src, tgt = e["sourceId"], e["targetId"]
        if tgt in scored_ids:
            in_deg[tgt] += 1
        if src in scored_ids:
            out_deg[src] += 1
                                   
        sc, tc = community_of.get(src), community_of.get(tgt)
        if sc is not None and tc is not None and sc != tc:
            if src in scored_ids:
                crossings[src] += 1
            if tgt in scored_ids:
                crossings[tgt] += 1

    node_map = {n["id"]: n for n in nodes}

                                   
    locs: Dict[str, int] = {}
    for nid in scored_ids:
        n = node_map.get(nid)
        if not n:
            continue
        start = n["properties"].get("startLine") or 0
        end = n["properties"].get("endLine") or 0
        locs[nid] = max(0, end - start)

    def _norm(d: Dict[str, int]) -> Dict[str, float]:
        mx = max(d.values(), default=1) or 1
        return {k: v / mx for k, v in d.items()}

    n_in = _norm(dict(in_deg))
    n_out = _norm(dict(out_deg))
    n_cross = _norm(dict(crossings))
    n_loc = _norm(locs)

    def _level(score: float) -> str:
        if score < 0.25:
            return "low"
        if score < 0.50:
            return "medium"
        if score < 0.75:
            return "high"
        return "critical"

    for n in nodes:
        nid = n["id"]
        if nid not in scored_ids:
            continue
        ni = n_in.get(nid, 0.0)
        no = n_out.get(nid, 0.0)
        nc = n_cross.get(nid, 0.0)
        nl = n_loc.get(nid, 0.0)

        score = round(
            ni * RISK_WEIGHTS["in_degree"]
            + nc * RISK_WEIGHTS["crossings"]
            + nl * RISK_WEIGHTS["loc"]
            + no * RISK_WEIGHTS["out_degree"],
            4,
        )
        n["properties"]["riskScore"] = score
        n["properties"]["riskLevel"] = _level(score)
        n["properties"]["riskFactors"] = {
            "inDegree": in_deg.get(nid, 0),
            "outDegree": out_deg.get(nid, 0),
            "communityCrossings": crossings.get(nid, 0),
            "linesOfCode": locs.get(nid, 0),
            "normInDegree": round(ni, 4),
            "normOutDegree": round(no, 4),
            "normCrossings": round(nc, 4),
            "normLOC": round(nl, 4),
        }

    return nodes
