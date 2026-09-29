"""Verify the portable triad artifact bundle and, optionally, its Qdrant index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lookup.triad_mvp_catalog import Catalog, sha256, source_paths
from lookup.triad_mvp_semantic import SCIBERT_COMMIT, _client, collection_name


def verify(directory: Path, repository: Path, check_qdrant: bool = False) -> dict:
    """Verify linked release identities, local registries, and optional Qdrant state."""
    catalog = Catalog(directory)
    sources = source_paths(repository)
    for source, path in sources.items():
        if not path.is_file() or sha256(path) != catalog.manifest["sources"][source]["sha256"]:
            raise ValueError(f"Pinned registry missing or changed: {source}: {path}")

    embedding_path = directory / "embedding-manifest.json"
    embedding_hash = sha256(embedding_path)
    if (directory / "EMBED_SUCCESS").read_text(encoding="utf-8").strip() != embedding_hash:
        raise ValueError("Embedding success marker does not match its manifest")
    embeddings = json.loads(embedding_path.read_text(encoding="utf-8"))
    semantic = json.loads((directory / "semantic-manifest.json").read_text(encoding="utf-8"))
    expected = catalog.manifest["total_terms"]
    if (
        embeddings.get("status") != "provisional"
        or embeddings.get("catalog_version") != catalog.version
        or embeddings.get("catalog_sha256") != catalog.manifest["database_sha256"]
        or embeddings.get("resolved_revision") != SCIBERT_COMMIT
        or sum(shard["count"] for shard in embeddings["shards"]) != expected
        or semantic.get("status") != "provisional"
        or semantic.get("catalog_version") != catalog.version
        or semantic.get("catalog_sha256") != catalog.manifest["database_sha256"]
        or semantic.get("embedding_manifest_sha256") != embedding_hash
        or semantic.get("resolved_revision") != SCIBERT_COMMIT
        or semantic.get("collection") != collection_name(catalog.version, embedding_hash)
        or semantic.get("terms") != expected
        or semantic.get("qdrant_exact_count") != expected
    ):
        raise ValueError("Catalog, embedding, and semantic manifests disagree")

    result = {
        "status": "verified",
        "catalog_version": catalog.version,
        "catalog_sha256": catalog.manifest["database_sha256"],
        "embedding_manifest_sha256": embedding_hash,
        "collection": semantic["collection"],
        "expected_terms": expected,
        "model_revision": SCIBERT_COMMIT,
    }
    if check_qdrant:
        from qdrant_client import models

        client = _client()
        name = semantic["collection"]
        actual = client.count(collection_name=name, exact=True).count
        matching = client.count(
            collection_name=name,
            exact=True,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="catalog_version", match=models.MatchValue(value=catalog.version)
                    ),
                    models.FieldCondition(
                        key="embedding_manifest_sha256",
                        match=models.MatchValue(value=embedding_hash),
                    ),
                    models.FieldCondition(
                        key="status", match=models.MatchValue(value="provisional")
                    ),
                ]
            ),
        ).count
        if actual != expected or matching != expected:
            raise ValueError(
                f"Qdrant count mismatch: total={actual}, linked={matching}, expected={expected}"
            )
        result["qdrant_exact_count"] = actual
    return result


def main() -> None:
    """Parse CLI options and emit a compact release verification record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--qdrant", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.catalog, args.repository, args.qdrant), sort_keys=True))


if __name__ == "__main__":
    main()
