#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ -f "$root/.env.triad" ]]; then
  set -a
  # Local operator configuration; keep this file private and out of Git.
  source "$root/.env.triad"
  set +a
fi
lookup_env=${TRIAD_LOOKUP_ENV:-MInAS_DH_lookup}
node_env=${TRIAD_NODE_ENV:-MInAS_DH_node}
gpu_env=${TRIAD_GPU_ENV:-MInAS_DH_embed_gpu}
action=${1:-help}

require_catalog() {
  [[ -n "${MINAS_MVP_CATALOG:-}" ]] || {
    echo "Set MINAS_MVP_CATALOG to an absolute artifact release directory" >&2
    exit 2
  }
  [[ "$MINAS_MVP_CATALOG" = /* ]] || {
    echo "MINAS_MVP_CATALOG must be absolute" >&2
    exit 2
  }
}

case "$action" in
  catalog)
    require_catalog
    mamba run -n "$lookup_env" env PYTHONPATH="$root/service" \
      python -m lookup.triad_mvp_catalog build --root "$root" --output "$MINAS_MVP_CATALOG"
    ;;
  embed)
    require_catalog
    command -v srun >/dev/null || { echo "A Slurm GPU srun is required for embedding" >&2; exit 2; }
    srun --partition="${TRIAD_SLURM_PARTITION:-compregular}" \
      --gres="${TRIAD_SLURM_GPU:-gpu:a100:1}" --cpus-per-task=4 \
      --mem=24G --time=01:00:00 --chdir="$root" \
      mamba run -n "$gpu_env" env PYTHONPATH="$root/service" \
      python -m lookup.triad_mvp_semantic embed \
      --catalog "$MINAS_MVP_CATALOG" --config "$root/deployment/embedding.yaml"
    ;;
  load)
    require_catalog
    mamba run -n "$lookup_env" env PYTHONPATH="$root/service" \
      python -m lookup.triad_mvp_semantic load --catalog "$MINAS_MVP_CATALOG"
    ;;
  verify)
    require_catalog
    shift
    mamba run -n "$lookup_env" env PYTHONPATH="$root/service" \
      python -m lookup.release --catalog "$MINAS_MVP_CATALOG" --repository "$root" "$@"
    ;;
  api)
    require_catalog
    export HF_HUB_OFFLINE=${HF_HUB_OFFLINE:-1}
    export TRANSFORMERS_OFFLINE=${TRANSFORMERS_OFFLINE:-1}
    export TOKENIZERS_PARALLELISM=${TOKENIZERS_PARALLELISM:-false}
    exec mamba run -n "$lookup_env" env PYTHONPATH="$root/service" \
      uvicorn lookup.triad_mvp_api:app \
      --host "${TRIAD_API_HOST:-127.0.0.1}" --port "${TRIAD_API_PORT:-8766}"
    ;;
  dev-web)
    cd "$root"
    exec mamba run -n "$node_env" yarn dev
    ;;
  model-cache)
    mamba run -n "$lookup_env" env HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 \
      python -c 'from huggingface_hub import snapshot_download; snapshot_download(repo_id="allenai/scibert_scivocab_uncased", revision="24f92d32b1bfb0bcaf9ab193ff3ad01e87732fc1")'
    ;;
  *)
    echo "usage: $0 {catalog|embed|load|verify [--qdrant]|api|dev-web|model-cache}" >&2
    exit 2
    ;;
esac
