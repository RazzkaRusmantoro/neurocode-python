#!/usr/bin/env python3

import os
import sys
from pathlib import Path

                                            
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    load_dotenv(env_path)
except ImportError:
    pass

from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct

OLD_COLLECTION = os.getenv("OLD_COLLECTION", "rko_community_2sc8s_neurocode_python_main")
NEW_COLLECTION = os.getenv("NEW_COLLECTION", "neurocode_team_2sc8s_neurocode_python_main")
BATCH_SIZE = 100

def main():
    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    if not qdrant_url:
        print("Error: QDRANT_URL not set. Set it in .env or environment.")
        sys.exit(1)

    print(f"Connecting to Qdrant at {qdrant_url}...")
    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key or None)

    collections = [c.name for c in client.get_collections().collections]
    if OLD_COLLECTION not in collections:
        print(f"Error: Source collection '{OLD_COLLECTION}' does not exist.")
        print(f"Existing collections: {collections}")
        sys.exit(1)
    if NEW_COLLECTION in collections:
        print(f"Error: Target collection '{NEW_COLLECTION}' already exists. Delete it first or choose another name.")
        sys.exit(1)

    info = client.get_collection(OLD_COLLECTION)
    vector_config = info.config.params.vectors
    if hasattr(vector_config, "size"):
        size = int(vector_config.size)
    elif isinstance(vector_config, dict):
        first = next(iter(vector_config.values()))
        size = int(first.size) if hasattr(first, "size") else 768
    else:
        size = 768
    print(f"Source collection: {OLD_COLLECTION}, points: {info.points_count}, vector size: {size}")

    print(f"Creating collection '{NEW_COLLECTION}' with same config...")
    client.create_collection(
        collection_name=NEW_COLLECTION,
        vectors_config=VectorParams(size=size, distance=Distance.COSINE),
        on_disk_payload=True,
    )

    offset = None
    total = 0
    print("Copying points...")
    while True:
        records, offset = client.scroll(
            collection_name=OLD_COLLECTION,
            limit=BATCH_SIZE,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not records:
            break
        points = [
            PointStruct(id=r.id, vector=r.vector, payload=r.payload or {})
            for r in records
        ]
        client.upsert(collection_name=NEW_COLLECTION, points=points)
        total += len(points)
        print(f"  Copied {total} points...")
        if offset is None:
            break

    print(f"Copied {total} points to '{NEW_COLLECTION}'.")
    confirm = input("Delete old collection '%s'? [y/N] " % OLD_COLLECTION).strip().lower()
    if confirm == "y" or confirm == "yes":
        client.delete_collection(OLD_COLLECTION)
        print(f"Deleted '{OLD_COLLECTION}'.")
    else:
        print("Left old collection in place. You can delete it manually later.")

    print("Done.")


if __name__ == "__main__":
    main()
