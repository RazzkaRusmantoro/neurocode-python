import re
from collections import Counter, defaultdict
from typing import Any, Dict, List

SYMBOL_LABELS = {"Function", "Class", "Method", "Interface"}


def _heuristic_cluster_label(node_names: List[str]) -> str:
    
    words: List[str] = []
    for name in node_names:
        parts = re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+', name)
        words.extend([p.lower() for p in parts if len(p) > 2])
    stop = {
        "the", "and", "for", "with", "from", "this", "that",
        "get", "set", "has", "use", "can", "will", "not",
        "handle", "create", "update", "delete", "make", "build",
        "run", "init", "load", "check", "add", "remove", "fetch",
        "return", "async", "await",
    }
    words = [w for w in words if w not in stop]
    if not words:
        return "General"
    most_common = Counter(words).most_common(2)
    return " & ".join(w.title() for w, _ in most_common) or "General"


def run_semantic_clustering(
    nodes: List[Dict[str, Any]],
    file_contents: Dict[str, str],                                 
    embed_model=None,                                                         
) -> List[Dict[str, Any]]:
    
    try:
        import numpy as np
        import umap as umap_lib
        import hdbscan as hdbscan_lib
    except ImportError as e:
        print(f"[semantic_clustering] Missing dependency ({e}) — skipping.", flush=True)
        return nodes

                                                                               
    symbol_nodes: List[Dict] = []
    snippets: List[str] = []

    for n in nodes:
        if n["label"] not in SYMBOL_LABELS:
            continue
        props = n["properties"]
        path = props.get("filePath", "")
        start = props.get("startLine") or 0
        end = props.get("endLine") or 0
        content = file_contents.get(path, "")
        if not content:
            continue
        lines = content.splitlines()
        snippet = "\n".join(lines[max(0, start - 1): min(len(lines), end)]).strip()
        if not snippet or len(snippet) < 10:
            continue
        symbol_nodes.append(n)
        snippets.append(snippet[:1500])                                

    if len(snippets) < 4:
        print(
            f"[semantic_clustering] Only {len(snippets)} embeddable nodes — skipping.",
            flush=True,
        )
        return nodes

                                                                                
    print(f"[semantic_clustering] Embedding {len(snippets)} symbol nodes...", flush=True)
    try:
        if embed_model is None:
            from sentence_transformers import SentenceTransformer
            import os
            model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
            embed_model = SentenceTransformer(model_name)
        embeddings = embed_model.encode(snippets, show_progress_bar=False, batch_size=32)
        import numpy as np
        embeddings = np.array(embeddings, dtype=np.float32)
    except Exception as e:
        print(f"[semantic_clustering] Embedding failed: {e}", flush=True)
        return nodes

                                                                               
    print("[semantic_clustering] Running UMAP...", flush=True)
    n_neighbors = min(15, max(2, len(snippets) // 5))
    try:
        reducer = umap_lib.UMAP(
            n_components=2,
            n_neighbors=n_neighbors,
            min_dist=0.1,
            random_state=42,
            verbose=False,
        )
        coords_2d = reducer.fit_transform(embeddings)
    except Exception as e:
        print(f"[semantic_clustering] UMAP failed: {e}", flush=True)
        return nodes

                          
    import numpy as np
    for dim in range(2):
        col = coords_2d[:, dim]
        cmin, cmax = float(col.min()), float(col.max())
        rng = max(cmax - cmin, 1e-6)
        coords_2d[:, dim] = (col - cmin) / rng * 2.0 - 1.0

                                                                                
    print("[semantic_clustering] Running HDBSCAN...", flush=True)
    min_cluster_size = max(2, len(snippets) // 40)
    try:
        clusterer = hdbscan_lib.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=1,
            cluster_selection_method="leaf",
        )
        labels = clusterer.fit_predict(embeddings)
    except Exception as e:
        print(f"[semantic_clustering] HDBSCAN failed: {e}", flush=True)
        return nodes

                                                                                
    cluster_names: Dict[int, List[str]] = defaultdict(list)
    for i, n in enumerate(symbol_nodes):
        cid = int(labels[i])
        if cid >= 0:
            cluster_names[cid].append(n["properties"].get("name", ""))

    cluster_label_map: Dict[int, str] = {
        cid: _heuristic_cluster_label(names)
        for cid, names in cluster_names.items()
    }

    n_clusters = len([c for c in set(labels) if c >= 0])
    n_noise = int(sum(1 for lb in labels if lb == -1))
    print(
        f"[semantic_clustering] ✓ {n_clusters} semantic clusters, {n_noise} noise nodes",
        flush=True,
    )

                                                                                
    node_to_idx = {n["id"]: i for i, n in enumerate(symbol_nodes)}
    for n in nodes:
        idx = node_to_idx.get(n["id"])
        if idx is None:
            continue
        cid = int(labels[idx])
        x, y = float(coords_2d[idx, 0]), float(coords_2d[idx, 1])
        n["properties"]["semanticClusterId"] = cid
        n["properties"]["semanticClusterLabel"] = cluster_label_map.get(cid, "Unclustered")
        n["properties"]["umapX"] = round(x, 4)
        n["properties"]["umapY"] = round(y, 4)

    return nodes
