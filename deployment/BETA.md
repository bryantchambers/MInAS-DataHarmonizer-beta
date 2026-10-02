# Self-contained MInAS DataHarmonizer beta — 2026-10-02

The beta includes all project data needed for lexical and semantic triad
lookup. Git LFS distributes the SQLite catalog, 75 precomputed vector shards,
SciBERT query weights, and the large MONDO registry. The six registry files
represent ENVO, UBERON, PO, BTO, OBI, DOID, and MONDO. Metadata, evidence,
checksums, licenses, scripts, and configuration remain ordinary Git files.
Installing software still requires access to package registries and the
Qdrant container registry; no TermLimit checkout or separate data transfer
is required. Query serving is CPU-only; existing vectors are reused and no
GPU embedding job runs on boot or for users.

## Local installation

Use Linux x86-64 with Mamba/Miniforge, Docker Engine and Docker Compose v2.
The development container supplies those tools automatically. A conservative
starting size is 4 CPUs, 8 GiB RAM and 30 GiB disk. This is a configuration
target, not a measured cloud capacity guarantee.

```bash
git clone --branch OntIntegration https://github.com/bryantchambers/MInAS-DataHarmonizer.git
cd MInAS-DataHarmonizer
bash deployment/scripts/beta.sh setup
bash deployment/scripts/beta.sh run
```

`setup` installs the three named CPU Mamba environments, pulls Git LFS assets,
verifies the catalog/vector and model hashes, and builds the editor. If Git LFS
is absent during the initial clone, Git may leave pointers or fail checkout;
install Git LFS first or clone with `GIT_LFS_SKIP_SMUDGE=1`, then run `setup`.
All paths default to the cloned repository. No `.env.triad` is necessary.
Optional overrides are illustrated in `deployment/triad.env.example`.

`run` starts Qdrant on private loopback port 6333, waits for readiness, loads
the existing vectors if needed, verifies all 75,876 linked points, warms
SciBERT offline, and serves the production editor and API on port 8088.
Open `http://127.0.0.1:8088/`. Only this port needs forwarding or sharing.
The browser API path is `/api/v1/mvp/triad/`; it uses the same origin as the
editor. No development proxy or second public API port is required.

In another terminal run:

```bash
bash deployment/scripts/beta.sh check
```

This checks the editor HTML, exact release term count, `snoil` → soil typo
lookup, and a real semantic `desert environment` request. Then select an
appropriate MInAS template in the browser, edit each environmental triad
column, choose suggestions, compose two terms, append `:::your jewel`, and
check CSV/XLSX export and reimport. Text after `:::` is a user annotation and
must not trigger lookup. Automated editor tests cover this; browser spot
checking remains part of acceptance.

Stop the web process with Ctrl-C; Qdrant persists until
`docker compose -f deployment/compose.qdrant.yml stop`. Its mutable state is
ignored under `.state/`. Restarting reuses a verified collection. A partial
load can be resumed through deterministic upserts; no collection is deleted.
An existing managed Qdrant can be used by setting `QDRANT_URL` and
`TRIAD_MANAGE_QDRANT=0`. Credentials belong outside Git.

## Gitpod / Ona

Gitpod Classic was retired; the current service is Ona. The supported
configuration is `.devcontainer/devcontainer.json` plus
`.ona/config.yaml`, rather than a legacy `.gitpod.yml`. The older
`.ona/automations.yaml` name is supported, but the current canonical path is
used here. Do not configure a conflicting explicit task/service path in Ona.

1. Sign in to Ona and connect the GitHub account authorized to read this repo.
2. Create a project from the fork above and select `OntIntegration`. Choose
   an x86-64 Linux environment with at least the resources above. Ensure its
   runner supports the Docker-in-Docker development-container feature.
3. Start the environment. The development container installs pinned
   Miniforge. The beta service hydrates LFS, installs the CPU environments,
   builds the editor and starts Qdrant plus the one-port web/API application.
   Initial boot includes data download, package installation and index load;
   it is not instantaneous. Inspect the `triad-beta` service output.
4. Wait until `triad-beta` is ready, open preview port **8088**, and run
   `bash deployment/scripts/beta.sh check` inside that environment.
5. Choose the port admission level permitted by your Ona organization for
   researchers to access that preview URL. Share the web preview, not the IDE
   or Qdrant port. Editor `forwardPorts` does not create a shared Ona URL.
   Use `ona environment port open 8088 --name minas-beta --admission creator_only`
   for a private preview, or explicitly use `--admission everyone` to share
   with researchers without Ona authentication when organization policy
   permits. Private previews require a permitted account. A shared
   preview depends on the environment staying running; it is a test session,
   not an always-on hosting service.

The devcontainer uses host networking for Ona gateway access and exposes only
the web preview. Local starts bind loopback;
inside the devcontainer the preview binds `0.0.0.0` so its gateway can reach
it. Runtime preparation is serialized, errors fail startup, and the service
is advertised ready only after preparation and an actual lexical/semantic
acceptance check. `postEnvironmentStart` restarts it on environment resume.
The 30-minute readiness timeout allows the first package/data bootstrap.
No custom stop command is configured; Ona applies its default graceful
termination to the foreground service. A hosted stop/resume check remains
required. Consider 16 GiB RAM for first builds and concurrent users.

## Data and provenance

`artifacts/triad-mvp/mvp-cec56296b6466737/SHA256SUMS` covers the immutable
release. Catalog SHA-256:
`c73d0469dea6e9bbb1e33689fa3213f7a735f386d4349060251ca5e7473cf4a6`.
The embedding manifest SHA-256 is
`9e3badfd4173644e96cdf0117b6bfdd33824b7d3f3081bfe2b2363bc46c74308`.
The model is `allenai/scibert_scivocab_uncased`, revision
`24f92d32b1bfb0bcaf9ab193ff3ad01e87732fc1`.
`artifacts/model-cache/model-manifest.json` records query-file checksums;
`SCIBERT-LICENSE.txt` preserves its Apache 2.0 license. Historical absolute
paths in the release manifests remain provenance and do not control serving.

LFS stores data outside normal Git blobs and restores it through GitHub on
clone/pull. Downloads consume the repository owner's LFS bandwidth quota;
each new researcher environment downloads approximately one GiB of LFS data.
Check the owning GitHub account's allowance before a large invitation round.
No history rewrite was used: the earlier MONDO Git blob remains in historical
commits, while the current tree carries its LFS pointer.

Suggestions are provisional source-ontology terms. Rankings and field hints
do not establish equivalent concepts, expert-approved mappings, or canonical
triad validity. This beta does not replace the ontology repair/review pipeline.

## Verification and remaining gate

Local validation uses the actual committed CPU environment specifications,
Qdrant 1.19.0 with fresh storage, offline packaged SciBERT, and production
frontend assets. The exact point-count and lexical/semantic checks must also
pass from a clean GitHub clone. Record that result with the release commit.

A real Ona environment launch and researcher-facing browser interaction are
separate acceptance gates. Repository configuration or local tests alone
cannot establish that the user's Ona account, runner, GitHub integration,
port admission policy and available capacity are correctly configured.

Official references: [Git LFS](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-git-large-file-storage),
[LFS billing](https://docs.github.com/en/billing/concepts/product-billing/git-lfs),
[Classic migration](https://ona.com/stories/migrating-from-classic-to-ona),
[Ona configuration schema](https://ona.com/docs/ona/reference/ona-config-schema),
[Ona port sharing](https://ona.com/docs/ona/integrations/ports),
[Ona documentation](https://ona.com/docs).
