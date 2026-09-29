#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ -f "$root/.env.triad" ]]; then
  set -a
  source "$root/.env.triad"
  set +a
fi
directory=${MINAS_MVP_CATALOG:-}
[[ -n "$directory" && -f "$directory/SHA256SUMS" ]] || {
  echo "Set MINAS_MVP_CATALOG to a transferred artifact bundle with SHA256SUMS" >&2
  exit 2
}
(
  cd "$directory"
  sha256sum --check --status SHA256SUMS
)
lookup_env=${TRIAD_LOOKUP_ENV:-MInAS_DH_lookup}
mamba run -n "$lookup_env" env PYTHONPATH="$root/service" \
  python -m lookup.release --catalog "$directory" --repository "$root" "${@}"
