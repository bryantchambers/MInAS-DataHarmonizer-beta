#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
source_dir=${1:-}
destination=${2:-}
[[ -n "$source_dir" && -n "$destination" && -d "$source_dir" ]] || {
  echo "usage: $0 SOURCE_ARTIFACT_DIRECTORY NEW_DESTINATION_DIRECTORY" >&2
  exit 2
}
[[ ! -e "$destination" ]] || { echo "Destination already exists: $destination" >&2; exit 2; }
[[ -f "$source_dir/catalog.sqlite3" && -f "$source_dir/semantic-manifest.json" ]] || {
  echo "Source is missing the completed catalog or semantic manifest" >&2
  exit 2
}
mkdir -p "$destination"
cp -a "$source_dir/." "$destination/"
(
  cd "$destination"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 -r sha256sum > SHA256SUMS
  sha256sum --check --status SHA256SUMS
)
lookup_env=${TRIAD_LOOKUP_ENV:-MInAS_DH_lookup}
mamba run -n "$lookup_env" env PYTHONPATH="$root/service" \
  python -m lookup.release --catalog "$destination" --repository "$root"
echo "Artifact bundle ready: $destination"
