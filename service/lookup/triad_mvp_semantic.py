"""Checkpointed GPU SciBERT embedding and separate CPU Qdrant loading.

``embed`` runs inside a GPU Slurm allocation and writes artifact shards.
``load`` runs on the CPU node that owns Qdrant's configured endpoint. No Qdrant
connection is made by ``embed``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import socket
import sqlite3
import tempfile
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Any

from lookup.triad_mvp_catalog import Catalog, sha256

SCIBERT_MODEL = "allenai/scibert_scivocab_uncased"
SCIBERT_COMMIT = "24f92d32b1bfb0bcaf9ab193ff3ad01e87732fc1"


def _atomic_new(path: Path, data: bytes) -> None:
    """Publish a new small artifact atomically; never replace success output."""
    if path.exists():
        raise FileExistsError(path)
    temporary = tempfile.NamedTemporaryFile(prefix=".pending-", dir=path.parent, delete=False)
    temp_path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(data)
        if path.exists():
            raise FileExistsError(path)
        os.link(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _json_new(path: Path, value: dict[str, Any]) -> None:
    _atomic_new(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def _embedding_version(catalog: Catalog, max_tokens: int, batch_size: int, shard_size: int) -> str:
    key = {
        "catalog_version": catalog.version,
        "model": SCIBERT_MODEL,
        "revision": SCIBERT_COMMIT,
        "max_tokens": max_tokens,
        "batch_size": batch_size,
        "shard_size": shard_size,
        "builder_sha256": sha256(Path(__file__)),
    }
    return "scibert-" + hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]


def _check_shard(
    directory: Path, record: dict[str, Any], expected_curies: list[str] | None = None
) -> None:
    import numpy as np

    vectors_path = directory / record["vectors"]
    curies_path = directory / record["curies"]
    if sha256(vectors_path) != record["vectors_sha256"]:
        raise ValueError(f"Vector checksum mismatch: {vectors_path}")
    if sha256(curies_path) != record["curies_sha256"]:
        raise ValueError(f"CURIE checksum mismatch: {curies_path}")
    curies = curies_path.read_text(encoding="utf-8").splitlines()
    if expected_curies is not None and curies != expected_curies:
        raise ValueError(f"CURIE order mismatch: {curies_path}")
    vectors = np.load(vectors_path, mmap_mode="r", allow_pickle=False)
    if vectors.dtype != np.float32 or vectors.shape != (len(curies), record["dimension"]):
        raise ValueError(f"Invalid vector dtype/shape: {vectors_path}")
    if len(curies) != record["count"]:
        raise ValueError(f"Shard count mismatch: {curies_path}")


def _shard_record(
    directory: Path, relative_base: str, expected_curies: list[str]
) -> dict[str, Any]:
    import numpy as np

    vectors_name = f"{relative_base}.npy"
    curies_name = f"{relative_base}.curies.txt"
    vectors_path = directory / vectors_name
    curies_path = directory / curies_name
    if not vectors_path.is_file() or not curies_path.is_file():
        raise FileNotFoundError(f"Incomplete shard {relative_base}; inspect before retrying")
    vectors = np.load(vectors_path, mmap_mode="r", allow_pickle=False)
    if vectors.ndim != 2 or vectors.dtype != np.float32:
        raise ValueError(f"Invalid float32 shard: {vectors_path}")
    record = {
        "vectors": vectors_name,
        "vectors_sha256": sha256(vectors_path),
        "curies": curies_name,
        "curies_sha256": sha256(curies_path),
        "count": len(expected_curies),
        "dimension": int(vectors.shape[1]),
    }
    _check_shard(directory, record, expected_curies)
    return record


def _write_shard(
    directory: Path, relative_base: str, vectors: Any, curies: list[str]
) -> dict[str, Any]:
    import numpy as np

    base = directory / relative_base
    base.parent.mkdir(parents=True, exist_ok=True)
    target_vectors = Path(str(base) + ".npy")
    target_curies = Path(str(base) + ".curies.txt")
    if target_vectors.exists() or target_curies.exists():
        raise FileExistsError(f"Existing shard needs validation: {base}")
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[0] != len(curies):
        raise ValueError("Embedding row count does not match CURIE count")
    temporary = tempfile.NamedTemporaryFile(
        prefix=".pending-", suffix=".npy", dir=base.parent, delete=False
    )
    temp_path = Path(temporary.name)
    try:
        with temporary:
            np.save(temporary, matrix, allow_pickle=False)
        os.link(temp_path, target_vectors)
    finally:
        temp_path.unlink(missing_ok=True)
    _atomic_new(target_curies, ("\n".join(curies) + "\n").encode())
    return _shard_record(directory, relative_base, curies)


@lru_cache(maxsize=4)
def _verified_manifest(
    directory_name: str,
    manifest_hash: str,
    catalog_version: str,
    catalog_sha: str,
    expected_terms: int,
) -> dict[str, Any]:
    """Verify shard hashes once per immutable success manifest per process."""
    directory = Path(directory_name)
    manifest = json.loads((directory / "embedding-manifest.json").read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "provisional"
        or manifest.get("catalog_version") != catalog_version
        or manifest.get("catalog_sha256") != catalog_sha
        or manifest.get("resolved_revision") != SCIBERT_COMMIT
    ):
        raise ValueError("Embedding manifest does not match catalog/model")
    total = 0
    dimensions = set()
    uri = f"file:{(directory / 'catalog.sqlite3').resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        cursor = db.execute("SELECT curie FROM terms ORDER BY curie")
        for record in manifest["shards"]:
            expected_curies = [row[0] for row in cursor.fetchmany(record["count"])]
            _check_shard(directory, record, expected_curies)
            total += record["count"]
            dimensions.add(record["dimension"])
        if cursor.fetchone() is not None:
            raise ValueError("Embedding shards omit catalog CURIEs")
    if total != expected_terms or len(dimensions) != 1:
        raise ValueError("Embedding count or dimensions mismatch")
    return manifest


def _embedding_manifest(catalog: Catalog) -> dict[str, Any]:
    """Require a matching atomic success marker before serving/loading."""
    manifest_path = catalog.directory / "embedding-manifest.json"
    manifest_hash = (catalog.directory / "EMBED_SUCCESS").read_text(encoding="utf-8").strip()
    if manifest_hash != sha256(manifest_path):
        raise ValueError("Embedding success marker does not match manifest")
    return _verified_manifest(
        str(catalog.directory.resolve()),
        manifest_hash,
        catalog.version,
        catalog.manifest["database_sha256"],
        catalog.manifest["total_terms"],
    )


def _embedding_manifest_for_query(catalog: Catalog) -> dict[str, Any]:
    """Verify the immutable manifest for serving without rehashing 230 MB of shards.

    The CPU loader validates every shard before loading points and publishes the
    final Qdrant manifest only after exact count checks. Query serving consumes
    Qdrant vectors, so it needs to verify the small embedding manifest and its
    success marker, not reread the embedding payload files on every API restart.
    """
    path = catalog.directory / "embedding-manifest.json"
    marker = (catalog.directory / "EMBED_SUCCESS").read_text(encoding="utf-8").strip()
    if marker != sha256(path):
        raise ValueError("Embedding success marker does not match manifest")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "provisional"
        or manifest.get("catalog_version") != catalog.version
        or manifest.get("catalog_sha256") != catalog.manifest["database_sha256"]
        or manifest.get("resolved_revision") != SCIBERT_COMMIT
    ):
        raise ValueError("Embedding manifest does not match catalog/model")
    return manifest


def embed(
    directory: Path, config_path: Path, batch_size: int = 32, shard_size: int = 1024
) -> dict[str, Any]:
    """Resume verified shards or build missing shards on a CUDA node."""
    if batch_size < 1 or shard_size < batch_size or shard_size % batch_size:
        raise ValueError("shard_size must be a positive multiple of batch_size")
    import numpy as np
    import torch
    import yaml

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    from lookup.embed import LookupEmbedder

    if not torch.cuda.is_available():
        raise RuntimeError("GPU embedding requires CUDA inside a Slurm srun allocation")
    if not os.getenv("SLURM_JOB_ID") or not os.getenv("SLURM_STEP_ID"):
        raise RuntimeError("GPU embedding must run inside a Slurm srun step")
    run_started = perf_counter()
    catalog = Catalog(directory)
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict) or not isinstance(config.get("models"), dict):
        raise ValueError("Embedding configuration must contain a models section")
    model = config["models"]
    if str(model["embedding_model"]) != SCIBERT_MODEL:
        raise ValueError(f"Expected {SCIBERT_MODEL}")
    max_tokens = int(model["max_tokens"])
    version = _embedding_version(catalog, max_tokens, batch_size, shard_size)
    marker = directory / "EMBED_SUCCESS"
    manifest_path = directory / "embedding-manifest.json"
    if marker.exists():
        manifest = _embedding_manifest(catalog)
        if manifest["embedding_version"] != version:
            raise ValueError("Existing embeddings use different build parameters/code")
        return manifest
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("embedding_version") != version:
            raise ValueError("Existing embedding manifest uses different parameters/code")
        manifest_sha = sha256(manifest_path)
        _verified_manifest(
            str(directory.resolve()),
            manifest_sha,
            catalog.version,
            catalog.manifest["database_sha256"],
            catalog.manifest["total_terms"],
        )
        _atomic_new(marker, (manifest_sha + "\n").encode())
        return _embedding_manifest(catalog)
    shard_records: list[dict[str, Any]] = []
    encoder = None
    new_terms = 0
    resumed_shards = 0
    device_name = torch.cuda.get_device_name(0)
    with catalog._readonly() as db:
        cursor = db.execute(
            "SELECT curie, label, definition, synonyms_json FROM terms ORDER BY curie"
        )
        shard_number = 0
        while rows := cursor.fetchmany(shard_size):
            curies = [row["curie"] for row in rows]
            relative_base = f"embeddings-{version}/part-{shard_number:06d}"
            shard_marker = directory / f"{relative_base}.json"
            if shard_marker.exists():
                record = json.loads(shard_marker.read_text(encoding="utf-8"))
                _check_shard(directory, record, curies)
                resumed_shards += 1
            elif (directory / f"{relative_base}.npy").exists() or (
                directory / f"{relative_base}.curies.txt"
            ).exists():
                record = _shard_record(directory, relative_base, curies)
                _json_new(shard_marker, record)
                resumed_shards += 1
            else:
                shard_started = perf_counter()
                if encoder is None:
                    encoder = LookupEmbedder(
                        SCIBERT_MODEL, SCIBERT_COMMIT, max_tokens, device="cuda", require_cuda=True
                    )
                    loaded_commit = getattr(encoder.model.config, "_commit_hash", None)
                    if loaded_commit and loaded_commit != SCIBERT_COMMIT:
                        raise RuntimeError("Loaded SciBERT commit differs from requested commit")
                vectors = []
                for start in range(0, len(rows), batch_size):
                    texts = [
                        " ".join(
                            filter(
                                None,
                                [
                                    row["label"],
                                    row["definition"],
                                    *json.loads(row["synonyms_json"]),
                                ],
                            )
                        )
                        for row in rows[start : start + batch_size]
                    ]
                    vectors.extend(encoder.encode(texts))
                record = _write_shard(
                    directory, relative_base, np.asarray(vectors, dtype=np.float32), curies
                )
                record.update(
                    {
                        "elapsed_seconds": round(perf_counter() - shard_started, 3),
                        "slurm_job_id": os.environ["SLURM_JOB_ID"],
                        "slurm_step_id": os.environ["SLURM_STEP_ID"],
                        "node": socket.gethostname(),
                        "cuda_device": device_name,
                        "peak_cuda_memory_bytes": torch.cuda.max_memory_allocated(0),
                        "batch_size": batch_size,
                    }
                )
                _json_new(shard_marker, record)
                new_terms += len(curies)
            shard_records.append(record)
            shard_number += 1
    manifest = {
        "status": "provisional",
        "catalog_version": catalog.version,
        "catalog_sha256": catalog.manifest["database_sha256"],
        "embedding_version": version,
        "embedding_model": SCIBERT_MODEL,
        "resolved_revision": SCIBERT_COMMIT,
        "max_tokens": max_tokens,
        "batch_size": batch_size,
        "shard_size": shard_size,
        "device": "cuda",
        "cuda_device": device_name,
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "slurm_step_id": os.environ["SLURM_STEP_ID"],
        "node": socket.gethostname(),
        "slurm_partition": os.getenv("SLURM_JOB_PARTITION"),
        "slurm_cpus_per_task": os.getenv("SLURM_CPUS_PER_TASK"),
        "slurm_mem_per_node": os.getenv("SLURM_MEM_PER_NODE"),
        "cuda_visible_devices": os.getenv("CUDA_VISIBLE_DEVICES"),
        "cuda_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "peak_cuda_memory_bytes": torch.cuda.max_memory_allocated(0),
        "run_elapsed_seconds": round(perf_counter() - run_started, 3),
        "run_terms_embedded": new_terms,
        "run_throughput_terms_per_second": round(
            new_terms / max(perf_counter() - run_started, 1e-9), 3
        ),
        "resumed_shards": resumed_shards,
        "shard_elapsed_complete": all("elapsed_seconds" in item for item in shard_records),
        "total_shard_elapsed_seconds": round(
            sum(item.get("elapsed_seconds", 0) for item in shard_records), 3
        ),
        "torch_version": torch.__version__,
        "transformers_version": importlib.metadata.version("transformers"),
        "huggingface_hub_version": importlib.metadata.version("huggingface-hub"),
        "numpy_version": np.__version__,
        "shards": shard_records,
        "total_terms": sum(record["count"] for record in shard_records),
    }
    if manifest["total_terms"] != catalog.manifest["total_terms"]:
        raise ValueError("Embedding count does not match catalog")
    _json_new(manifest_path, manifest)
    _atomic_new(marker, (sha256(manifest_path) + "\n").encode())
    return _embedding_manifest(catalog)


def collection_name(catalog_version: str, embedding_manifest_sha: str) -> str:
    """Isolate MVP vectors from canonical collections and other builds."""
    return (
        "minas_triad_mvp_" + catalog_version.replace("-", "_") + "_" + embedding_manifest_sha[:16]
    )


def _client():
    from qdrant_client import QdrantClient

    return QdrantClient(
        url=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"),
        api_key=os.getenv("QDRANT_API_KEY"),
        timeout=30,
    )


def load(directory: Path, upsert_batch: int = 256) -> dict[str, Any]:
    """Stream verified vectors into local Qdrant and publish only after count gates."""
    if upsert_batch < 1 or upsert_batch > 2048:
        raise ValueError("upsert_batch must be between 1 and 2048")
    import numpy as np
    from qdrant_client import models

    catalog = Catalog(directory)
    embeddings = _embedding_manifest_for_query(catalog)
    embedding_manifest_sha = sha256(directory / "embedding-manifest.json")
    target = directory / "semantic-manifest.json"
    existing = None
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if (
            existing.get("embedding_manifest_sha256") != embedding_manifest_sha
            or existing.get("catalog_version") != catalog.version
            or existing.get("status") != "provisional"
        ):
            raise ValueError("Existing semantic manifest points to different embeddings")
    name = collection_name(catalog.version, embedding_manifest_sha)
    client = _client()
    dimensions = embeddings["shards"][0]["dimension"]
    if not client.collection_exists(name):
        client.create_collection(
            name,
            vectors_config=models.VectorParams(size=dimensions, distance=models.Distance.COSINE),
        )
    offset = 0
    for shard in embeddings["shards"]:
        vectors = np.load(directory / shard["vectors"], mmap_mode="r", allow_pickle=False)
        curies = (directory / shard["curies"]).read_text(encoding="utf-8").splitlines()
        for start in range(0, len(curies), upsert_batch):
            points = [
                models.PointStruct(
                    id=offset + i,
                    vector=vectors[i].tolist(),
                    payload={
                        "curie": curies[i],
                        "catalog_version": catalog.version,
                        "embedding_manifest_sha256": embedding_manifest_sha,
                        "status": "provisional",
                    },
                )
                for i in range(start, min(start + upsert_batch, len(curies)))
            ]
            client.upsert(collection_name=name, points=points, wait=True)
        offset += len(curies)
    expected = catalog.manifest["total_terms"]
    actual = client.count(collection_name=name, exact=True).count
    matched = client.count(
        collection_name=name,
        exact=True,
        count_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="catalog_version", match=models.MatchValue(value=catalog.version)
                ),
                models.FieldCondition(
                    key="embedding_manifest_sha256",
                    match=models.MatchValue(value=embedding_manifest_sha),
                ),
                models.FieldCondition(key="status", match=models.MatchValue(value="provisional")),
            ]
        ),
    ).count
    if actual != expected or matched != expected or offset != expected:
        raise RuntimeError(
            f"Qdrant count gate failed: total={actual}, matching={matched}, expected={expected}"
        )
    manifest = {
        "status": "provisional",
        "catalog_version": catalog.version,
        "catalog_sha256": catalog.manifest["database_sha256"],
        "embedding_manifest_sha256": embedding_manifest_sha,
        "resolved_revision": SCIBERT_COMMIT,
        "collection": name,
        "terms": expected,
        "qdrant_exact_count": actual,
        "qdrant_client_version": importlib.metadata.version("qdrant-client"),
    }
    if existing is not None:
        if existing != manifest:
            raise ValueError("Existing semantic manifest differs from verified Qdrant state")
        return existing
    _json_new(target, manifest)
    return manifest


@lru_cache(maxsize=1)
def _embedder(model_name: str, revision: str, max_tokens: int):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    from lookup.embed import LookupEmbedder

    return LookupEmbedder(model_name, revision, max_tokens, device="cpu")


def semantic_search(
    catalog: Catalog, query: str, limit: int = 10, field: str | None = None
) -> list[dict[str, Any]]:
    """Query a loaded provisional snapshot; field hints only boost ranking."""
    manifest = json.loads(
        (catalog.directory / "semantic-manifest.json").read_text(encoding="utf-8")
    )
    if (
        manifest.get("catalog_version") != catalog.version
        or manifest.get("catalog_sha256") != catalog.manifest["database_sha256"]
        or manifest.get("embedding_manifest_sha256")
        != sha256(catalog.directory / "embedding-manifest.json")
        or manifest.get("status") != "provisional"
        or manifest.get("resolved_revision") != SCIBERT_COMMIT
    ):
        raise ValueError("Semantic index does not match the provisional catalog")
    embeddings = _embedding_manifest(catalog)
    encoder = _embedder(embeddings["embedding_model"], SCIBERT_COMMIT, embeddings["max_tokens"])
    response = _client().query_points(
        collection_name=manifest["collection"],
        query=encoder.encode_query(query),
        limit=min(limit * 4, 100),
        with_payload=True,
    )
    found = []
    for point in response.points:
        payload = point.payload or {}
        if (
            payload.get("catalog_version") != catalog.version
            or payload.get("embedding_manifest_sha256") != manifest["embedding_manifest_sha256"]
            or payload.get("status") != "provisional"
        ):
            continue
        row = catalog.resolve(str(payload.get("curie", "")))
        if row is None:
            continue
        row["match_method"] = "semantic"
        row["score"] = round(
            min(1.0, float(point.score) + (0.02 if field and row["field_hint"] == field else 0)), 4
        )
        found.append(row)
    return sorted(found, key=lambda row: (-row["score"], row["curie"]))[:limit]


def main() -> None:
    """Dispatch GPU embedding or local CPU loading."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gpu = sub.add_parser("embed", help="Run inside GPU srun allocation")
    gpu.add_argument("--catalog", type=Path, required=True)
    gpu.add_argument("--config", type=Path, default=Path("deployment/embedding.yaml"))
    gpu.add_argument("--batch-size", type=int, default=32)
    gpu.add_argument("--shard-size", type=int, default=1024)
    cpu = sub.add_parser("load", help="Run on CPU node with local Qdrant")
    cpu.add_argument("--catalog", type=Path, required=True)
    cpu.add_argument("--upsert-batch", type=int, default=256)
    args = parser.parse_args()
    result = (
        embed(args.catalog, args.config, args.batch_size, args.shard_size)
        if args.command == "embed"
        else load(args.catalog, args.upsert_batch)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
