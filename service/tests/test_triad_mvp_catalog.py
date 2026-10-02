"""Behavioral checks for provisional seven-source catalog and API."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from lookup import triad_mvp_semantic as semantic_module
from lookup.triad_mvp_api import _catalog, app
from lookup.triad_mvp_catalog import Catalog, build, source_paths


def write_registries(root: Path) -> None:
    """Write seven small registries with owner and imported assertions."""
    paths = source_paths(root)
    rows = {
        "ENVO": [
            {
                "curie": "ENVO:0000001",
                "label": "cave sediment",
                "synonyms": ["cave dirt"],
                "ancestors": ["ENVO:00010483"],
                "definition": "Sediment within a cave.",
            },
            {"curie": "ENVO:0000002", "label": "cave system", "ancestors": ["ENVO:01000253"]},
            {"curie": "ENVO:0000003", "label": "cave entrance", "ancestors": ["ENVO:00002297"]},
            {"curie": "ENVO:0000004", "label": "obsolete cave", "obsolete": True},
            {"curie": "ENVO:0000005", "label": "  "},
            {"curie": "BFO:0000001", "label": "imported entity"},
            {
                "curie": "UBERON:0001474",
                "label": "imported bone",
                "definition": "Imported ENVO assertion for bone",
            },
        ],
        "UBERON": [{"curie": "UBERON:0001474", "label": "bone"}],
        "PO": [
            {"curie": "PO:0000001", "label": "plant structure"},
            {"curie": "BFO:0000001", "label": "imported entity"},
        ],
        "BTO": [{"curie": "BTO:0000001", "label": "animal tissue"}],
        "OBI": [{"curie": "OBI:0000001", "label": "assay"}],
        "DOID": [{"curie": "DOID:0000001", "label": "disease"}],
        "MONDO": [{"curie": "MONDO:0000001", "label": "disease or disorder"}],
    }
    for source, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in rows[source]:
                row = {
                    "source": source,
                    "ontology_version": f"{source}-test-release",
                    "source_iri": f"http://example.org/{source}",
                    "extraction_provenance": {"source_ontology": source},
                    **row,
                }
                handle.write(json.dumps(row) + "\n")


@pytest.fixture
def catalog(tmp_path: Path) -> Catalog:
    """Build a checksum-verified fixture catalog."""
    write_registries(tmp_path)
    build(tmp_path / "catalog", tmp_path)
    return Catalog(tmp_path / "catalog")


def test_build_owner_dedup_provenance_and_checksums(catalog: Catalog) -> None:
    """Keep owner CURIEs and imports while excluding foreign-only terms."""
    manifest = catalog.manifest
    assert manifest["status"] == "provisional"
    assert set(manifest["counts_by_source"]) == {
        "ENVO",
        "UBERON",
        "PO",
        "BTO",
        "OBI",
        "DOID",
        "MONDO",
    }
    assert manifest["total_terms"] == 9
    assert manifest["excluded_rows"]["foreign_curie"] == 11
    assert manifest["excluded_rows"]["obsolete"] == 1
    assert manifest["excluded_rows"]["unlabeled"] == 1
    assert manifest["source_rows_by_source"]["ENVO"] == 7
    assert manifest["unique_searchable_terms"] == 9
    assert manifest["import_assertions_retained"] == 1
    assert catalog.resolve("BFO:0000001") is None
    assert catalog.resolve("ENVO:0000004") is None
    assert catalog.resolve("ENVO:0000001")["iri"] == "http://purl.obolibrary.org/obo/ENVO_0000001"
    with catalog._readonly() as db:
        row = db.execute(
            "SELECT provenance_json, ontology_version FROM terms WHERE curie=?", ("PO:0000001",)
        ).fetchone()
        imported = db.execute(
            "SELECT asserted_in, label, provenance_json FROM source_assertions WHERE curie=?",
            ("UBERON:0001474",),
        ).fetchall()
    assert json.loads(row["provenance_json"])["source_ontology"] == "PO"
    assert row["ontology_version"] == "PO-test-release"
    assert catalog.resolve("UBERON:0001474")["source_ontology"] == "UBERON"
    assert len(imported) == 1
    assert imported[0]["asserted_in"] == "ENVO"
    assert imported[0]["label"] == "imported bone"
    with pytest.raises(FileExistsError):
        build(catalog.directory, catalog.directory.parent)
    catalog.database.write_bytes(catalog.database.read_bytes() + b"x")
    with pytest.raises(ValueError, match="checksum"):
        Catalog(catalog.directory)


def test_lexical_exact_prefix_synonym_typo_and_soft_fields(catalog: Catalog) -> None:
    """Exercise every lexical match tier and soft field behavior."""
    assert catalog.lexical("cave sediment")[0]["match_method"] == "exact_label"
    assert catalog.lexical("cave dirt")[0]["match_method"] == "exact_synonym"
    assert catalog.lexical("cave sed")[0]["match_method"] == "prefix_label"
    typo = catalog.lexical("cave sedimant")
    assert typo[0]["curie"] == "ENVO:0000001"
    assert typo[0]["match_method"] == "typo"
    assert catalog.lexical("cave system")[0]["field_hint"] == "env_broad_scale"
    assert catalog.lexical("cave entrance")[0]["field_hint"] is None
    medium = catalog.lexical("cave sediment", field="env_broad_scale")
    assert medium[0]["curie"] == "ENVO:0000001"  # hint does not filter
    assert medium[0]["field_hint"] == "env_medium"


def test_strong_lexical_matches_skip_typo_fallback(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exact, synonym, and prefix queries avoid the expensive typo branch."""
    import lookup.triad_mvp_catalog as catalog_module

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Typo fallback must not run after a strong lexical hit")

    monkeypatch.setattr(catalog_module, "SequenceMatcher", fail_if_called)
    assert catalog.lexical("cave sediment", limit=8)[0]["match_method"] == "exact_label"
    assert catalog.lexical("cave dirt", limit=8)[0]["match_method"] == "exact_synonym"
    assert catalog.lexical("cave sed", limit=8)[0]["match_method"] == "prefix_label"


def test_api_contract_and_semantic_unbuilt(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose the specified response shape and unbuilt semantic state."""
    monkeypatch.setenv("MINAS_MVP_CATALOG", str(catalog.directory))
    _catalog.cache_clear()
    client = TestClient(app)
    health = client.get("/v1/mvp/triad/health")
    assert health.status_code == 200
    assert health.json()["status"] == "provisional"
    response = client.get("/v1/mvp/triad/lexical", params={"q": "cave dirt", "field": "env_medium"})
    assert response.status_code == 200
    data = response.json()
    assert data["catalog_version"] == catalog.version
    assert set(data["results"][0]) == {
        "curie",
        "label",
        "iri",
        "source_ontology",
        "definition",
        "match_method",
        "score",
        "field_hint",
        "field_hint_basis",
    }
    assert (
        client.get("/v1/mvp/triad/resolve", params={"curie": "UBERON:0001474"}).json()["results"][
            0
        ]["field_hint"]
        is None
    )
    assert client.get("/v1/mvp/triad/resolve", params={"curie": "BFO:0000001"}).status_code == 404
    assert client.get("/v1/mvp/triad/semantic", params={"q": "cave dirt"}).status_code == 503
    assert (
        client.get("/v1/mvp/triad/lexical", params={"q": "cave", "field": "bad"}).status_code == 422
    )


def test_beta_one_port_static_and_lookup(catalog: Catalog, monkeypatch, tmp_path) -> None:
    """The production preview serves schema assets and API at the browser's origin."""
    import importlib

    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>beta editor</html>")
    (web / "dist-schemas").mkdir()
    (web / "dist-schemas/schemas.js").write_text("var schemas = {};")
    monkeypatch.setenv("TRIAD_WEB_DIRECTORY", str(web))
    monkeypatch.setenv("MINAS_MVP_CATALOG", str(catalog.directory))
    _catalog.cache_clear()
    beta = importlib.import_module("lookup.beta_app")
    beta = importlib.reload(beta)
    client = TestClient(beta.app)
    assert "beta editor" in client.get("/").text
    assert client.get("/dist-schemas/schemas.js").status_code == 200
    assert client.get("/api/v1/mvp/triad/health").json()["total_terms"] == 9
    response = client.get("/api/v1/mvp/triad/lexical", params={"q": "cave dirt"})
    assert response.status_code == 200
    assert response.json()["results"][0]["label"] == "cave sediment"
    assert client.get("/api/v1/mvp/triad/semantic", params={"q": "cave"}).status_code == 503


def test_bundled_model_integrity_rejects_lfs_pointer(tmp_path) -> None:
    """An unhydrated LFS checkout must fail before advertising semantic search."""
    from lookup.beta_assets import FILES, SCIBERT_COMMIT, SNAPSHOT, package, verify

    source = tmp_path / SCIBERT_COMMIT
    source.mkdir()
    for name in FILES:
        (source / name).write_bytes(name.encode())
    license_path = tmp_path / "license.txt"
    license_path.write_text("fixture license")
    destination = tmp_path / "cache"
    package(source, destination, license_path)
    assert verify(destination)["status"] == "verified"
    (destination / SNAPSHOT / "pytorch_model.bin").write_text(
        "version https://git-lfs.github.com/spec/v1\n"
    )
    with pytest.raises(ValueError, match="checksum mismatch"):
        verify(destination)


def test_semantic_artifacts_resume_local_load_and_cpu_query(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise handoff with fake vectors and in-memory Qdrant, without inference."""
    import lookup.embed as lookup_embed
    import numpy as np
    import torch
    from qdrant_client import QdrantClient, models

    calls = []

    class FakeEmbedder:
        def __init__(self, model_name, revision, max_tokens, **kwargs):
            assert revision == semantic_module.SCIBERT_COMMIT
            assert kwargs["require_cuda"] is True
            self.model = SimpleNamespace(config=SimpleNamespace(_commit_hash=revision))

        def encode(self, texts):
            calls.extend(texts)
            return [[1.0, float(len(text) % 7), 0.5] for text in texts]

    monkeypatch.setattr(lookup_embed, "LookupEmbedder", FakeEmbedder)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda _: "mock A100")
    monkeypatch.setattr(
        torch.cuda, "get_device_properties", lambda _: SimpleNamespace(total_memory=24_000_000)
    )
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda _: 1_000_000)
    monkeypatch.setenv("SLURM_JOB_ID", "12345")
    monkeypatch.setenv("SLURM_STEP_ID", "0")
    manifest = semantic_module.embed(
        catalog.directory, Path("deployment/embedding.yaml"), batch_size=2, shard_size=4
    )
    assert manifest["total_terms"] == catalog.manifest["total_terms"]
    assert manifest["slurm_job_id"] == "12345"
    assert manifest["cuda_device"] == "mock A100"
    assert manifest["peak_cuda_memory_bytes"] == 1_000_000
    assert manifest["run_terms_embedded"] == 9
    assert manifest["run_throughput_terms_per_second"] > 0
    assert manifest["shard_elapsed_complete"] is True
    assert manifest["batch_size"] == 2
    assert manifest["shard_size"] == 4
    assert (catalog.directory / "EMBED_SUCCESS").is_file()
    assert np.load(catalog.directory / manifest["shards"][0]["vectors"]).dtype == np.float32
    first_calls = len(calls)
    assert (
        semantic_module.embed(catalog.directory, Path("deployment/embedding.yaml"), 2, 4)
        == manifest
    )
    assert len(calls) == first_calls

    client = QdrantClient(":memory:")
    monkeypatch.setattr(semantic_module, "_client", lambda: client)
    loaded = semantic_module.load(catalog.directory, upsert_batch=3)
    assert loaded["terms"] == 9
    assert client.count(loaded["collection"], exact=True).count == 9
    client.delete(loaded["collection"], models.PointIdsList(points=[0]), wait=True)
    assert client.count(loaded["collection"], exact=True).count == 8
    assert semantic_module.load(catalog.directory, upsert_batch=3) == loaded
    assert client.count(loaded["collection"], exact=True).count == 9

    class FakeQueryEmbedder:
        def encode_query(self, query):
            return [1.0, 1.0, 0.5]

    monkeypatch.setattr(semantic_module, "_embedder", lambda *args: FakeQueryEmbedder())
    results = semantic_module.semantic_search(catalog, "cave sediment", field="env_local_scale")
    assert results
    assert all(row["match_method"] == "semantic" for row in results)
    assert any(row["field_hint"] is None for row in results)
    monkeypatch.setenv("MINAS_MVP_CATALOG", str(catalog.directory))
    _catalog.cache_clear()
    response = TestClient(app).get("/v1/mvp/triad/semantic", params={"q": "cave sediment"})
    assert response.status_code == 200
    assert response.json()["results"][0]["match_method"] == "semantic"

    # A count failure must leave the final load manifest unpublished.
    (catalog.directory / "semantic-manifest.json").unlink()
    monkeypatch.setattr(client, "count", lambda *args, **kwargs: SimpleNamespace(count=0))
    with pytest.raises(RuntimeError, match="count gate failed"):
        semantic_module.load(catalog.directory, upsert_batch=3)
    assert not (catalog.directory / "semantic-manifest.json").exists()


def test_embed_resumes_only_verified_shards_after_interruption(
    catalog: Catalog, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed later batch leaves earlier checksummed shards reusable."""
    import lookup.embed as lookup_embed
    import torch

    calls = []
    fail_after = [2]

    class StubEncoder:
        def __init__(self, model_name, revision, max_tokens, **kwargs):
            self.model = SimpleNamespace(config=SimpleNamespace(_commit_hash=revision))

        def encode(self, texts):
            if len(calls) >= fail_after[0]:
                raise RuntimeError("synthetic interrupted batch")
            calls.append(len(texts))
            return [[1.0, 0.5, 0.25] for _ in texts]

    monkeypatch.setattr(lookup_embed, "LookupEmbedder", StubEncoder)
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda _: "mock A100")
    monkeypatch.setattr(
        torch.cuda, "get_device_properties", lambda _: SimpleNamespace(total_memory=24_000_000)
    )
    monkeypatch.setattr(torch.cuda, "max_memory_allocated", lambda _: 1_000_000)
    monkeypatch.setenv("SLURM_JOB_ID", "56789")
    monkeypatch.setenv("SLURM_STEP_ID", "0")
    with pytest.raises(RuntimeError, match="interrupted"):
        semantic_module.embed(catalog.directory, Path("deployment/embedding.yaml"), 2, 4)
    assert not (catalog.directory / "EMBED_SUCCESS").exists()
    shard_marker = next(catalog.directory.glob("embeddings-*/part-000000.json"))
    original_marker = shard_marker.read_bytes()
    fail_after[0] = 100
    manifest = semantic_module.embed(catalog.directory, Path("deployment/embedding.yaml"), 2, 4)
    assert shard_marker.read_bytes() == original_marker
    assert manifest["resumed_shards"] == 1
    assert manifest["run_terms_embedded"] == 5
    assert manifest["total_terms"] == 9
