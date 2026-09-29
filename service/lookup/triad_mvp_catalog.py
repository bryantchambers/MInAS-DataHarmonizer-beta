"""Build and query an explicitly provisional, seven-source triad term catalog.

Run ``python -m lookup.triad_mvp_catalog build --output DIR`` in the
DataHarmonizer lookup environment. The inputs are pinned term registries; no ontology
alignment or publication decision is inferred from them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterator

SOURCES = ("ENVO", "UBERON", "PO", "BTO", "OBI", "DOID", "MONDO")
SCHEMA_VERSION = 2
OBO = "http://purl.obolibrary.org/obo/"


def source_paths(root: Path) -> dict[str, Path]:
    """Return the pinned registry paths under the DataHarmonizer repository."""
    core = root / "ontology/registries/term-registry.jsonl"
    return {
        source: core
        if source in {"ENVO", "UBERON"}
        else root / f"ontology/registries/isolated/term-registry-{source.lower()}.jsonl"
        for source in SOURCES
    }


def sha256(path: Path) -> str:
    """Hash a file without loading it into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(value: str) -> str:
    """Normalize a lexical surface for case-insensitive lookup."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def fts_literal(value: str) -> str:
    """Quote a literal safely for an FTS5 MATCH expression."""
    return '"' + value.replace('"', '""') + '"'


def term_iri(curie: str) -> str:
    """Construct the OBO PURL for one validated source-owned CURIE."""
    prefix, identifier = curie.split(":", 1)
    return f"{OBO}{prefix}_{identifier}"


def field_hint(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """Suggest a field only where the source ancestry supports a modest hint."""
    source = row["source"]
    ancestry = set(row.get("ancestors") or ()) | {row["curie"]}
    if source == "ENVO":
        for field, roots, basis in (
            ("env_broad_scale", {"ENVO:01000253", "ENVO:00000428"}, "ENVO system/biome ancestry"),
            ("env_medium", {"ENVO:00010483"}, "ENVO environmental-material ancestry"),
        ):
            if ancestry & roots:
                return field, basis + "; provisional search hint"
    if source == "UBERON":
        return None, "UBERON anatomy: host-associated field placement needs class-specific review"
    return None, "Unreviewed for environmental-triad field placement"


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON in {path}:{number}") from exc
                if not isinstance(row, dict):
                    raise ValueError(f"Expected object in {path}:{number}")
                yield row


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _create_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
        CREATE TABLE terms (
            curie TEXT PRIMARY KEY, label TEXT NOT NULL, iri TEXT NOT NULL,
            source_ontology TEXT NOT NULL, definition TEXT,
            synonyms_json TEXT NOT NULL, ancestors_json TEXT NOT NULL,
            ontology_version TEXT, source_iri TEXT, provenance_json TEXT NOT NULL,
            field_hint TEXT, field_hint_basis TEXT
        );
        CREATE TABLE source_assertions (
            id INTEGER PRIMARY KEY, curie TEXT NOT NULL REFERENCES terms(curie),
            asserted_in TEXT NOT NULL, registry_path TEXT NOT NULL,
            label TEXT, definition TEXT, synonyms_json TEXT NOT NULL,
            ontology_version TEXT, source_iri TEXT, provenance_json TEXT NOT NULL,
            obsolete INTEGER NOT NULL
        );
        CREATE INDEX source_assertions_curie ON source_assertions(curie);
        CREATE TABLE surfaces (
            curie TEXT NOT NULL REFERENCES terms(curie),
            surface TEXT NOT NULL, normalized TEXT NOT NULL,
            kind TEXT NOT NULL, PRIMARY KEY(curie, normalized, kind)
        );
        CREATE INDEX surfaces_exact ON surfaces(normalized);
        CREATE VIRTUAL TABLE surface_fts USING fts5(curie UNINDEXED, normalized);
        CREATE VIRTUAL TABLE surface_grams USING fts5(
            curie UNINDEXED, normalized, tokenize='trigram'
        );
    """)


def build(output: Path, root: Path) -> dict[str, Any]:
    """Stream owner-CURIE terms into an immutable SQLite FTS5 snapshot."""
    paths = source_paths(root)
    missing = sorted({str(path) for path in paths.values() if not path.is_file()})
    if missing:
        raise FileNotFoundError("Missing source registries: " + ", ".join(missing))
    output.mkdir(parents=True, exist_ok=True)
    database = output / "catalog.sqlite3"
    manifest_path = output / "manifest.json"
    if database.exists() or manifest_path.exists():
        raise FileExistsError(f"Catalog already exists in {output}; choose a new output directory")
    input_hashes = {source: sha256(path) for source, path in paths.items()}
    builder_hash = sha256(Path(__file__))
    version_key = json.dumps(
        {"schema": SCHEMA_VERSION, "inputs": input_hashes, "builder_sha256": builder_hash},
        sort_keys=True,
    )
    version = "mvp-" + hashlib.sha256(version_key.encode()).hexdigest()[:16]
    counts = {source: 0 for source in SOURCES}
    source_rows = {source: 0 for source in SOURCES}
    excluded = {"foreign_curie": 0, "obsolete": 0, "unlabeled": 0}
    metadata: dict[str, dict[str, str | None]] = {}
    temporary = tempfile.NamedTemporaryFile(
        prefix="catalog-", suffix=".sqlite3", dir=output, delete=False
    )
    temp_path = Path(temporary.name)
    temporary.close()
    try:
        with _connect(temp_path) as db:
            _create_schema(db)
            for source, path in paths.items():
                versions: set[str | None] = set()
                source_iris: set[str | None] = set()
                for row in _rows(path):
                    curie = str(row.get("curie") or "")
                    if row.get("source") == source:
                        source_rows[source] += 1
                    if not curie.startswith(source + ":") or row.get("source") != source:
                        excluded["foreign_curie"] += 1
                        continue
                    if row.get("obsolete"):
                        excluded["obsolete"] += 1
                        continue
                    label = str(row.get("label") or "").strip()
                    if not label:
                        excluded["unlabeled"] += 1
                        continue
                    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*:[A-Za-z0-9_]+", curie):
                        raise ValueError(f"Unexpected CURIE: {curie}")
                    hint, basis = field_hint(row)
                    synonyms = sorted(
                        {str(s).strip() for s in (row.get("synonyms") or []) if str(s).strip()}
                    )
                    provenance = row.get("extraction_provenance") or {}
                    db.execute(
                        "INSERT INTO terms VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            curie,
                            label,
                            term_iri(curie),
                            source,
                            row.get("definition"),
                            json.dumps(synonyms, ensure_ascii=False),
                            json.dumps(row.get("ancestors") or []),
                            row.get("ontology_version"),
                            row.get("source_iri"),
                            json.dumps(provenance, sort_keys=True),
                            hint,
                            basis,
                        ),
                    )
                    for surface, kind in [(label, "label"), *((s, "synonym") for s in synonyms)]:
                        normalized = normalize(surface)
                        if not normalized:
                            continue
                        inserted = db.execute(
                            "INSERT OR IGNORE INTO surfaces VALUES (?,?,?,?)",
                            (curie, surface, normalized, kind),
                        ).rowcount
                        if inserted:
                            db.execute("INSERT INTO surface_fts VALUES (?,?)", (curie, normalized))
                            if len(normalized) >= 3:
                                db.execute(
                                    "INSERT INTO surface_grams VALUES (?,?)", (curie, normalized)
                                )
                    versions.add(row.get("ontology_version"))
                    source_iris.add(row.get("source_iri"))
                    counts[source] += 1
                if len(versions) > 1 or len(source_iris) > 1:
                    raise ValueError(f"Mixed ontology releases in {path}")
                metadata[source] = {
                    "ontology_version": next(iter(versions), None),
                    "source_iri": next(iter(source_iris), None),
                }
            if any(count == 0 for count in counts.values()):
                raise ValueError("Each of the seven owner sources must contain terms")
            imported_assertions = 0
            for path in dict.fromkeys(paths.values()):
                for row in _rows(path):
                    curie = str(row.get("curie") or "")
                    owner = curie.split(":", 1)[0]
                    if owner not in SOURCES or row.get("source") == owner:
                        continue
                    if not db.execute("SELECT 1 FROM terms WHERE curie=?", (curie,)).fetchone():
                        continue
                    db.execute(
                        "INSERT INTO source_assertions "
                        "(curie,asserted_in,registry_path,label,definition,synonyms_json,"
                        "ontology_version,source_iri,provenance_json,obsolete) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            curie,
                            str(row.get("source") or ""),
                            str(path.resolve()),
                            row.get("label"),
                            row.get("definition"),
                            json.dumps(row.get("synonyms") or [], ensure_ascii=False),
                            row.get("ontology_version"),
                            row.get("source_iri"),
                            json.dumps(row.get("extraction_provenance") or {}, sort_keys=True),
                            int(bool(row.get("obsolete"))),
                        ),
                    )
                    imported_assertions += 1
            db.execute("PRAGMA optimize")
        temp_path.replace(database)
        manifest = {
            "catalog_version": version,
            "status": "provisional",
            "schema_version": SCHEMA_VERSION,
            "builder_sha256": builder_hash,
            "database_sha256": sha256(database),
            "total_terms": sum(counts.values()),
            "unique_searchable_terms": sum(counts.values()),
            "source_rows_by_source": source_rows,
            "counts_by_source": counts,
            "import_assertions_retained": imported_assertions,
            "excluded_rows": excluded,
            "sources": {
                source: {
                    "path": str(paths[source].resolve()),
                    "sha256": input_hashes[source],
                    **metadata[source],
                }
                for source in SOURCES
            },
            "curie_policy": (
                "Only source-owned CURIEs are searchable; imported assertions are provenance only"
            ),
            "field_hint_policy": (
                "Broad and material ancestry hints only; no local or blanket UBERON eligibility"
            ),
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return manifest
    finally:
        temp_path.unlink(missing_ok=True)


class Catalog:
    """Read-only access to a checksum-verified snapshot."""

    def __init__(self, directory: Path):
        """Verify and open a completed catalog directory."""
        self.directory = directory
        self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if (
            self.manifest.get("status") != "provisional"
            or self.manifest.get("schema_version") != SCHEMA_VERSION
        ):
            raise ValueError("Unsupported catalog manifest")
        self.database = directory / "catalog.sqlite3"
        if sha256(self.database) != self.manifest.get("database_sha256"):
            raise ValueError("Catalog checksum mismatch")
        self.version = self.manifest["catalog_version"]

    def _readonly(self) -> sqlite3.Connection:
        db = sqlite3.connect(f"file:{self.database.resolve()}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def result(row: sqlite3.Row, method: str, score: float) -> dict[str, Any]:
        """Convert one SQLite term row to the public result shape."""
        return {
            "curie": row["curie"],
            "label": row["label"],
            "iri": row["iri"],
            "source_ontology": row["source_ontology"],
            "definition": row["definition"],
            "match_method": method,
            "score": round(score, 4),
            "field_hint": row["field_hint"],
            "field_hint_basis": row["field_hint_basis"],
        }

    def resolve(self, curie: str) -> dict[str, Any] | None:
        """Resolve a source-owned CURIE exactly."""
        with self._readonly() as db:
            row = db.execute("SELECT * FROM terms WHERE curie=?", (curie,)).fetchone()
        return self.result(row, "resolve", 1.0) if row else None

    def lexical(
        self, query: str, limit: int = 10, field: str | None = None
    ) -> list[dict[str, Any]]:
        """Rank exact, synonym, prefix, and typo candidates with soft hints."""
        normalized = normalize(query)
        if not normalized:
            return []
        found: dict[str, tuple[str, float]] = {}

        def add(curie: str, method: str, score: float) -> None:
            previous = found.get(curie)
            if previous is None or score > previous[1]:
                found[curie] = (method, score)

        with self._readonly() as db:
            for row in db.execute(
                "SELECT curie, kind FROM surfaces WHERE normalized=? LIMIT 1000", (normalized,)
            ):
                add(
                    row["curie"],
                    "exact_label" if row["kind"] == "label" else "exact_synonym",
                    1.0 if row["kind"] == "label" else 0.96,
                )
            tokens = re.findall(r"\w+", normalized, re.UNICODE)
            if tokens:
                expression = fts_literal(" ".join(tokens)) + "*"
                for row in db.execute(
                    "SELECT s.curie, s.kind FROM surface_fts f JOIN surfaces s "
                    "ON s.curie=f.curie AND s.normalized=f.normalized "
                    "WHERE surface_fts MATCH ? LIMIT 1500",
                    (expression,),
                ):
                    add(
                        row["curie"],
                        "prefix_label" if row["kind"] == "label" else "prefix_synonym",
                        0.86 if row["kind"] == "label" else 0.82,
                    )
            # Typo retrieval is a fallback. Exact/synonym/prefix hits already
            # give the dropdown useful choices; trigram ranking is expensive
            # on the shared NFS catalog even when only one strong hit exists.
            if len(normalized) >= 5 and not found:
                if len(normalized) >= 7:
                    middle = (len(normalized) - 3) // 2
                    anchors = list(
                        dict.fromkeys(
                            (normalized[:3], normalized[middle : middle + 3], normalized[-3:])
                        )
                    )
                    pairs = [
                        (left, right)
                        for i, left in enumerate(anchors)
                        for right in anchors[i + 1 :]
                    ]
                    expression = " OR ".join(
                        f"({fts_literal(left)} AND {fts_literal(right)})"
                        for left, right in pairs
                    ) or fts_literal(anchors[0])
                else:
                    grams = sorted({normalized[i : i + 3] for i in range(len(normalized) - 2)})
                    expression = " OR ".join(fts_literal(gram) for gram in grams)
                for row in db.execute(
                    "SELECT curie, normalized FROM surface_grams "
                    "WHERE surface_grams MATCH ? ORDER BY bm25(surface_grams) LIMIT 400",
                    (expression,),
                ):
                    if row["curie"] in found or abs(len(row["normalized"]) - len(normalized)) > 2:
                        continue
                    ratio = SequenceMatcher(None, normalized, row["normalized"]).ratio()
                    if ratio >= 0.78:
                        add(row["curie"], "typo", 0.4 + ratio * 0.2)
            ranked = sorted(found.items(), key=lambda item: (-item[1][1], item[0]))[
                : max(limit * 3, limit)
            ]
            if not ranked:
                return []
            placeholders = ",".join("?" for _ in ranked)
            terms = {
                row["curie"]: row
                for row in db.execute(
                    f"SELECT * FROM terms WHERE curie IN ({placeholders})",
                    [curie for curie, _ in ranked],
                )
            }
        results = []
        for curie, (method, score) in ranked:
            row = terms[curie]
            bonus = 0.02 if field and row["field_hint"] == field else 0.0
            results.append(self.result(row, method, min(score + bonus, 1.0)))
        return sorted(results, key=lambda item: (-item["score"], item["curie"]))[:limit]


def main() -> None:
    """Parse and run the catalog build command."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("build")
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.root), indent=2))


if __name__ == "__main__":
    main()
