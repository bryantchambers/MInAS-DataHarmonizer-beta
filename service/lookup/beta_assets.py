"""Package and verify the minimal pinned SciBERT cache for an offline beta."""

import argparse
import json
import shutil
from pathlib import Path

from lookup.triad_mvp_catalog import sha256
from lookup.triad_mvp_semantic import SCIBERT_COMMIT, SCIBERT_MODEL

FILES = ("config.json", "pytorch_model.bin", "vocab.txt")
SNAPSHOT = Path("hub/models--allenai--scibert_scivocab_uncased/snapshots") / SCIBERT_COMMIT


def package(source: Path, destination: Path, license_path: Path) -> None:
    """Copy cached weights without symlinks; do not redownload or regenerate vectors."""
    if source.name != SCIBERT_COMMIT:
        raise ValueError("Source snapshot must be the pinned SciBERT revision")
    if destination.exists():
        raise FileExistsError(destination)
    snapshot = destination / SNAPSHOT
    snapshot.mkdir(parents=True)
    for name in FILES:
        shutil.copyfile(source / name, snapshot / name)
    shutil.copyfile(license_path, destination / "SCIBERT-LICENSE.txt")
    paths = [snapshot / name for name in FILES] + [destination / "SCIBERT-LICENSE.txt"]
    manifest = {
        "model": SCIBERT_MODEL,
        "revision": SCIBERT_COMMIT,
        "license": "Apache-2.0",
        "license_source": "https://github.com/allenai/scibert/blob/master/LICENSE.txt",
        "files": {str(path.relative_to(destination)): sha256(path) for path in paths},
    }
    (destination / "model-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def verify(directory: Path) -> dict:
    """Reject LFS pointers, incomplete caches, altered weights, or wrong revisions."""
    manifest = json.loads((directory / "model-manifest.json").read_text())
    if manifest["model"] != SCIBERT_MODEL or manifest["revision"] != SCIBERT_COMMIT:
        raise ValueError("Model provenance does not match the embedding release")
    required = {str(SNAPSHOT / name) for name in FILES} | {"SCIBERT-LICENSE.txt"}
    if set(manifest["files"]) != required:
        raise ValueError("Incomplete pinned model manifest")
    for name, checksum in manifest["files"].items():
        if sha256(directory / name) != checksum:
            raise ValueError(f"Model checksum mismatch (fetch Git LFS): {name}")
    return {"status": "verified", "model": manifest["model"], "revision": manifest["revision"]}


def main() -> None:
    """Dispatch cache packaging or checksum verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["package", "verify"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--license", type=Path)
    args = parser.parse_args()
    if args.command == "package":
        if args.source is None or args.license is None:
            parser.error("package requires --source and --license")
        package(args.source, args.directory, args.license)
    print(json.dumps(verify(args.directory), sort_keys=True))


if __name__ == "__main__":
    main()
