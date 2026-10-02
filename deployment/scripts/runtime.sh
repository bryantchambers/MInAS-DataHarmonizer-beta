#!/usr/bin/env bash
# Shared repository-relative defaults. Source this file from deployment scripts.
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ -f "$root/.env.triad" ]]; then
  set -a
  source "$root/.env.triad"
  set +a
fi
repo_path() {
  case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s/%s\n' "$root" "$1" ;; esac
}
export MINAS_MVP_CATALOG=$(repo_path "${MINAS_MVP_CATALOG:-artifacts/triad-mvp/mvp-cec56296b6466737}")
export HF_HOME=$(repo_path "${HF_HOME:-artifacts/model-cache}")
export QDRANT_URL=${QDRANT_URL:-http://127.0.0.1:6333}
export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
export TRANSFORMERS_OFFLINE=${TRANSFORMERS_OFFLINE:-1}
export TOKENIZERS_PARALLELISM=${TOKENIZERS_PARALLELISM:-false}
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-2}
export MKL_NUM_THREADS=${MKL_NUM_THREADS:-2}
lookup_env=${TRIAD_LOOKUP_ENV:-MInAS_DH_lookup}
node_env=${TRIAD_NODE_ENV:-MInAS_DH_node}
tools_env=${TRIAD_TOOLS_ENV:-MInAS_DH_tools}
