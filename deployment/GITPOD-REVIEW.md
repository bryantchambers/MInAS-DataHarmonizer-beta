# Deployment review — 2026-10-02

Independent reviewer: GPT-6.1 sol, medium effort, read-only review. Reviewed
the standalone service, artifacts, devcontainer and current official Ona docs.
The final startup driver was validated by the main implementer separately.

Assessment: feasible for a researcher beta, subject to a real hosted acceptance
run. Current Gitpod is Ona; Classic ended in 2025. Use the canonical
`.ona/config.yaml` with `.devcontainer/devcontainer.json`. The host-network
runtime option, `0.0.0.0` web bind, foreground service, resume trigger and
actual search readiness test have been incorporated in the implementation.

The reviewer identified these requirements, all reflected in the beta:

- Explicit LFS hydration after the tool is available, with checksums before
  index loading. Preserve the pinned Hugging Face cache layout and revision.
- One browser origin: mount lookup at `/api` ahead of the static editor.
- Keep Qdrant loopback-only; ensure Docker-in-Docker's listener is reachable.
- Use `postEnvironmentStart` for resumed environments and a generous first
  startup readiness timeout. Services do not support task `dependsOn`; setup
  coordination belongs in the driver. Keep the start command running.
- `forwardPorts` is editor forwarding, not a shareable Ona URL. Open port
  8088 with an explicit admission level in Ona; organization policy controls
  whether researchers can access it without an account.

Four CPUs, 8 GiB memory, 30 GiB disk is a reasonable initial small-beta target,
not a measured hosted minimum. Prefer 16 GiB for simultaneous users and first
builds. No cloud GPU is required. Benchmark concurrent query latency before
making a throughput commitment.

Outstanding hosted gates: clean cloud clone/LFS hydration, successful
devcontainer build, startup and exact linked point count, real offline model
query, HTTPS preview access, user browser editing and jewel/export round trips,
stop/resume, storage persistence and environment auto-stop behavior. Do not
infer these from local tests or treat browser activity as a keep-alive guarantee.

References: [Ona config schema](https://ona.com/docs/ona/reference/ona-config-schema),
[Port sharing](https://ona.com/docs/ona/integrations/ports),
[Classic retirement](https://ona.com/stories/migrating-from-classic-to-ona).
