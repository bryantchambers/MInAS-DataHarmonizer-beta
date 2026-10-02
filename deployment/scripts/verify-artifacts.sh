#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/runtime.sh"
directory=${MINAS_MVP_CATALOG:-}
[[ -n "$directory" && -f "$directory/SHA256SUMS" ]] || {
  echo "Catalog release with SHA256SUMS is missing; run beta.sh setup to fetch LFS assets" >&2
  exit 2
}
(
  cd "$directory"
  sha256sum --check --status SHA256SUMS
)
mamba run -n "$lookup_env" env PYTHONPATH="$root/service" \
  python -m lookup.release --catalog "$directory" --repository "$root" "${@}"
