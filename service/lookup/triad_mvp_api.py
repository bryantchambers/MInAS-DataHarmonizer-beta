"""Standalone provisional triad lookup API; canonical endpoints are untouched."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from lookup.fields import TriadField
from lookup.triad_mvp_catalog import Catalog
from lookup.triad_mvp_semantic import semantic_search


class Result(BaseModel):
    """One source-owned provisional term and its search evidence."""

    curie: str
    label: str
    iri: str
    source_ontology: str
    definition: str | None
    match_method: str
    score: float
    field_hint: str | None
    field_hint_basis: str | None


class SearchResponse(BaseModel):
    """Versioned results from one provisional catalog snapshot."""

    catalog_version: str
    results: list[Result]


@lru_cache(maxsize=4)
def _catalog(directory: str) -> Catalog:
    return Catalog(Path(directory))


def current_catalog() -> Catalog:
    """Return the configured catalog or a service-unavailable response."""
    directory = os.getenv("MINAS_MVP_CATALOG")
    if not directory:
        raise HTTPException(status_code=503, detail="MINAS_MVP_CATALOG is not configured")
    try:
        return _catalog(directory)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=503, detail=f"Provisional catalog unavailable: {exc}"
        ) from exc


app = FastAPI(title="MInAS provisional triad MVP", version="0.1.0")


@app.get("/v1/mvp/triad/health")
def health() -> dict[str, str | int | bool]:
    """Report catalog identity and whether semantic loading has been recorded."""
    catalog = current_catalog()
    semantic_manifest = catalog.directory / "semantic-manifest.json"
    return {
        "status": "provisional",
        "catalog_version": catalog.version,
        "total_terms": catalog.manifest["total_terms"],
        "semantic_index_present": semantic_manifest.is_file(),
    }


@app.get("/v1/mvp/triad/lexical", response_model=SearchResponse)
def lexical(
    q: str = Query(min_length=1, max_length=500),
    field: TriadField | None = None,
    limit: int = Query(default=10, ge=1, le=25),
) -> SearchResponse:
    """Search labels and synonyms with exact, prefix, and typo matching."""
    catalog = current_catalog()
    return SearchResponse(
        catalog_version=catalog.version,
        results=catalog.lexical(q, limit, field.value if field else None),
    )


@app.get("/v1/mvp/triad/semantic", response_model=SearchResponse)
def semantic(
    q: str = Query(min_length=1, max_length=500),
    field: TriadField | None = None,
    limit: int = Query(default=10, ge=1, le=25),
) -> SearchResponse:
    """Search the isolated provisional vector collection."""
    catalog = current_catalog()
    if not (catalog.directory / "semantic-manifest.json").is_file():
        raise HTTPException(status_code=503, detail="Provisional semantic index has not been built")
    try:
        results = semantic_search(catalog, q, limit, field.value if field else None)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        raise HTTPException(
            status_code=503, detail=f"Provisional semantic index unavailable: {exc}"
        ) from exc
    return SearchResponse(catalog_version=catalog.version, results=results)


@app.get("/v1/mvp/triad/resolve", response_model=SearchResponse)
def resolve(curie: str = Query(min_length=3, max_length=100)) -> SearchResponse:
    """Resolve a source-owned CURIE in the provisional catalog."""
    catalog = current_catalog()
    result = catalog.resolve(curie)
    if result is None:
        raise HTTPException(status_code=404, detail="CURIE not in provisional catalog")
    return SearchResponse(catalog_version=catalog.version, results=[result])
