# Provisional MInAS triad lookup deployment

This `OntIntegration` branch contains the DataHarmonizer editor, the standalone
lookup API, six pinned registry inputs representing ENVO, UBERON, PO, BTO, OBI,
DOID, and MONDO, tests, and deployment scripts. Suggestions are search results
from source ontologies. They are not approved mappings or hard triad validation.
The term shown in a cell is `Label [CURIE]`; selected terms can be composed
before `:::user jewel`. Jewel text is never searched.

## Artifact boundary and current release

The current artifact release is `mvp-cec56296b6466737`: 75,876 searchable
terms and a SciBERT/Qdrant collection named
`minas_triad_mvp_mvp_cec56296b6466737_9e3badfd4173644e`.
The catalog database SHA-256 is
`c73d0469dea6e9bbb1e33689fa3213f7a735f386d4349060251ca5e7473cf4a6`;
the embedding manifest SHA-256 is
`9e3badfd4173644e96cdf0117b6bfdd33824b7d3f3081bfe2b2363bc46c74308`.
SciBERT is `allenai/scibert_scivocab_uncased` at commit
`24f92d32b1bfb0bcaf9ab193ff3ad01e87732fc1`. The Qdrant server used for
this release is 1.19.0. Keep the entire artifact release directory together:
`catalog.sqlite3`, `manifest.json`, `embedding-manifest.json`, `EMBED_SUCCESS`,
`semantic-manifest.json`, and the `embeddings-scibert-*` shard directory.

The release is about 338 MiB on the current filesystem. Its database, vectors,
Qdrant storage, and model weights are **outside Git**. Registry JSONL inputs
are in `ontology/registries/`; each file is below 100 MB. No literature corpus,
source OWL files, local Mamba environments, or Qdrant storage is needed in Git.
The source registries and existing release manifests retain historical absolute
source paths in provenance. These paths do not direct serving. A newly built
catalog will have a new identity and needs new embeddings.

## Prepare a transfer bundle

On the source machine, from this repository root, use the already completed
artifact directory as the first argument and a **new** destination directory
as the second:

```bash
TRIAD_LOOKUP_ENV=MInAS_DH_lookup bash deployment/scripts/package-artifacts.sh \
  /path/to/completed/triad-mvp /path/to/transfer/mvp-cec56296b6466737
```

The script copies the release, writes `SHA256SUMS`, checks all files, and
verifies the catalog and linked manifests against the Git registry inputs.
Transfer this directory with the site's approved file transfer mechanism.
Keep its release name, contents, and checksums intact. A Qdrant snapshot may
be offered later, after a restore has been tested; the verified shard loader
is the supported migration route now.

## Install on the hosting server

1. Clone this branch. Install Mamba environments from
   `deployment/environments/node.yml` and `lookup.yml` on the hosting CPU node.
   These contain Node/Yarn and the lookup API/query model dependencies.
2. Install the locked JavaScript dependencies and build the static site:

   ```bash
   mamba run -n MInAS_DH_node yarn install --frozen-lockfile --ignore-scripts
   mamba run -n MInAS_DH_node yarn build:web
   ```

3. Put the transferred release under a permanent path outside Git. Copy
   `deployment/triad.env.example` to `.env.triad` and set
   `MINAS_MVP_CATALOG` to that absolute directory. Keep `.env.triad` private.
   Set `HF_HOME` to a persistent directory outside Git.
4. Cache the pinned SciBERT model once while network access is available:

   ```bash
   bash deployment/scripts/triad.sh model-cache
   ```

   Normal API runs are offline. The **CPU** encodes each user query using this
   cached model. The precomputed term vectors in Qdrant are reused by every
   user; there is no per-user GPU job.
5. Start Qdrant 1.19.0. `deployment/compose.qdrant.yml` is one loopback-only
   example; an existing managed Qdrant server is also suitable. Set
   `QDRANT_URL` and, if required, `QDRANT_API_KEY` in the service environment.
   Load the transferred vectors once, then verify the exact linked count:

   ```bash
   bash deployment/scripts/verify-artifacts.sh
   bash deployment/scripts/triad.sh load
   bash deployment/scripts/verify-artifacts.sh --qdrant
   ```

6. Run the API under the hosting service manager using
   `bash deployment/scripts/triad.sh api`. It binds to loopback by default.
   Serve `web/dist` through the HTTPS web server. Adapt
   `deployment/nginx-triad.conf.example` in that server so browser requests
   to `/api/v1/mvp/triad/` reach the local API at `/v1/mvp/triad/`.

Do not use the webpack development proxy as the production API route. Keep
Qdrant and the API on a private interface; the browser only needs the same
origin `/api/v1/mvp/triad/` route.

## Verification checklist

- [ ] The Git checkout is `OntIntegration` (or its reviewed merge commit) and
      the transferred bundle passes `verify-artifacts.sh`.
- [ ] The catalog and embedding manifest hashes above match; all six registry
      input hashes match `manifest.json`.
- [ ] Qdrant reports 75,876 total points and 75,876 points linked to this
      catalog and embedding manifest.
- [ ] The SciBERT model loads from `HF_HOME` with offline mode enabled; the
      API health and a semantic query both succeed.
- [ ] The production `/api/v1/mvp/triad/health` route succeeds through HTTPS.
- [ ] Exact label, synonym, typo, and semantic queries return source-owned
      terms. Search never sends text after `:::`.
- [ ] A browser spot check confirms selection, two-term composition, jewel
      editing, `env_medium` pipes, and CSV/XLSX round trip.
- [ ] No database, embeddings, Qdrant state, model weights, downloaded corpus,
      environment, credential, or file at or above 100 MB is staged in Git.

## Rebuilding a future release

The registry inputs and catalog builder are in this repository. Point
`MINAS_MVP_CATALOG` to a **new** output directory and run
`bash deployment/scripts/triad.sh catalog`. A new catalog identity requires
new term embeddings. This optional build step uses the included
`embed-gpu.yml` environment inside a Slurm GPU `srun` allocation via
`bash deployment/scripts/triad.sh embed`. Loading the vectors into Qdrant
is CPU work. The hosting server does not need a GPU for normal use.
