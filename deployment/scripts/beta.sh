#!/usr/bin/env bash
# Self-contained CPU beta: hydrate, install, verify, load, and serve one port.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/runtime.sh"
cd "$root"
action=${1:-run}
py() { mamba run -n "$lookup_env" env PYTHONPATH="$root/service" python "$@"; }
ensure_env() {
  local name=$1 spec=$2
  if ! mamba env list | awk -v name="$name" '$1 == name { found=1 } END { exit !found }'; then
    mamba env create -y -n "$name" -f "$root/deployment/environments/$spec.yml"
  fi
}
wait_http() {
  local url=$1
  for ((attempt=0; attempt<120; attempt++)); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then return; fi
    sleep 1
  done
  echo "Timed out waiting for $url" >&2
  return 1
}
case "$action" in
  setup)
    command -v mamba >/dev/null || { echo "Install Mamba/Miniforge first" >&2; exit 2; }
    mkdir -p "$root/.state"
    exec 9>"$root/.state/beta-setup.lock"
    flock 9
    ensure_env "$tools_env" tools
    export PATH="$(mamba run -n "$tools_env" sh -c 'dirname "$(command -v git-lfs)"'):$PATH"
    git lfs install --local
    git lfs pull
    ensure_env "$lookup_env" lookup
    ensure_env "$node_env" node
    py -m lookup.beta_assets verify --directory "$HF_HOME"
    bash deployment/scripts/verify-artifacts.sh
    commit=$(git rev-parse HEAD)
    if [[ ! -f "$root/.state/beta-installed.commit" || ! -f "$root/web/dist/index.html" ||
          "$(<"$root/.state/beta-installed.commit")" != "$commit" ]]; then
      mamba run -n "$node_env" yarn install --frozen-lockfile --ignore-scripts
      mamba run -n "$node_env" yarn build:web
      printf '%s\n' "$commit" >"$root/.state/beta-installed.commit"
    fi
    ;;
  prepare)
    mkdir -p "$root/.state"
    exec 9>"$root/.state/beta-prepare.lock"
    flock 9
    py -m lookup.beta_assets verify --directory "$HF_HOME"
    bash deployment/scripts/verify-artifacts.sh
    if [[ "${TRIAD_MANAGE_QDRANT:-1}" == 1 ]]; then
      docker compose -f deployment/compose.qdrant.yml up -d
    fi
    wait_http "$QDRANT_URL/healthz"
    # A persisted, correctly linked collection can be reused after a restart.
    if ! bash deployment/scripts/triad.sh verify --qdrant >"$root/.state/qdrant-preflight.log" 2>&1; then
      echo "No verified Qdrant collection yet; loading the bundled vectors"
      bash deployment/scripts/triad.sh load
      bash deployment/scripts/triad.sh verify --qdrant
    fi
    # Warm and exercise the real CPU encoder before advertising the preview.
    py -c 'from lookup.triad_mvp_api import current_catalog; from lookup.triad_mvp_semantic import semantic_search; rows=semantic_search(current_catalog(), "desert environment", 3); assert rows; print({"semantic_warmup": "passed", "curies": [r["curie"] for r in rows]})'
    [[ -f "$root/web/dist/index.html" ]] || { echo "Run beta.sh setup to build the editor" >&2; exit 2; }
    ;;
  serve)
    exec mamba run -n "$lookup_env" env PYTHONPATH="$root/service" \
      uvicorn lookup.beta_app:app --host "${TRIAD_BETA_HOST:-127.0.0.1}" --port "${TRIAD_BETA_PORT:-8088}"
    ;;
  run)
    bash deployment/scripts/beta.sh prepare
    exec bash deployment/scripts/beta.sh serve
    ;;
  check)
    py -m lookup.beta_check --url "${TRIAD_BETA_URL:-http://127.0.0.1:${TRIAD_BETA_PORT:-8088}}"
    ;;
  *) echo "usage: $0 {setup|prepare|serve|run|check}" >&2; exit 2 ;;
esac
