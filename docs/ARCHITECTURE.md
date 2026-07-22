# SecPloit architecture

## Control plane

The FastAPI control plane owns engagement metadata and the autonomous research loop. It does not
receive the Docker socket. It communicates with the runner through a token-authenticated internal
network.

The LLM workflow has four distinct passes:

1. **Planner** — converts the objective into hypotheses and completion criteria.
2. **Operator** — chooses one concrete shell action at a time.
3. **Reviewer** — evaluates evidence, records findings, and selects the next focus.
4. **Reporter** — produces the final evidence-based report.

This separation is intentional. An operator optimized for forward progress is not trusted to grade
its own evidence.

## Runner

The runner is the only service with Docker Engine access. For each job it creates:

- a dedicated container;
- a dedicated named volume mounted at `/workspace`;
- no host path mounts;
- no Linux capabilities;
- `no-new-privileges`;
- a read-only root filesystem;
- tmpfs-backed `/tmp` and `/run`;
- CPU, memory, PID, command-time, and output limits;
- connection only to the internal `secploit-range` network.

The workspace is persistent for the engagement, so the agent can create scripts, compile code, retain
scanner output, and compare observations across steps.

## Network topology

The control plane requires public egress for its model API. Workspace containers do not. They are
created only on the internal range network, which contains the authorized target services.

For production deployment, place the runner on a separate rootless-Docker host. The Docker backend
can later be replaced by Kubernetes Jobs, Firecracker microVMs, Kata Containers, or another sandbox
without changing the orchestrator contract.

## Data model

SQLite stores jobs, immutable events, reviewer-approved findings, and final reports. Artifacts remain
in the per-job Docker volume and are indexed through the runner API.
