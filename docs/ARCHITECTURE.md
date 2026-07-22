# SecPloit architecture

## Control plane

The FastAPI control plane owns engagement metadata and the autonomous research loop. It does not
receive the Docker socket. It communicates with the runner through a token-authenticated internal
network.

The V3 LLM workflow has six stages:

1. **Parallel specialist committee** — web, network, code/binary, authentication, strategy, and
   skeptical-review roles produce independent assessments.
2. **Lead planner** — synthesizes the specialist assessments into hypotheses, discriminating tests,
   and completion criteria.
3. **Operator** — chooses one concrete shell or bounded-browser action at a time.
4. **Step reviewer** — grades each action and result, suppresses unsupported conclusions, and records
   evidence-backed candidate findings.
5. **Final evidence auditor** — accepts, rejects, or qualifies candidate findings after reviewing the
   complete transcript and artifacts.
6. **Reporter** — writes the final report while respecting the evidence audit.

The specialist committee runs concurrently. Its output is advisory and is never treated as evidence.
The operator is optimized for information gain and progress; separate reviewers grade the evidence.
All roles can use independently configured reasoning effort, set to `high` by default.

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
scanner and browser output, compare observations across steps, and preserve evidence artifacts.

## Browser evidence subsystem

`secploit-browser` uses headless Chromium through Playwright inside the workspace. It provides:

- single-page evidence snapshots;
- full-page screenshots;
- DOM and response-header capture;
- link, form, script, and network-response inventories;
- bounded same-origin crawling;
- HTML and JSON artifact generation.

The crawler does not submit forms. It obeys page, depth, navigation-time, wall-time, and workspace
resource limits. Public egress remains unavailable at the network layer.

## Network topology

The control plane requires public egress for its model API. Workspace containers do not. They are
created only on the internal range network, which contains the authorized target services.

For production deployment, place the runner on a separate rootless-Docker host. The Docker backend
can later be replaced by Kubernetes Jobs, Firecracker microVMs, Kata Containers, or another sandbox
without changing the orchestrator contract.

## Data model

SQLite stores jobs, immutable events, specialist assessments, plans, command results, step reviews,
reviewer-approved candidate findings, evidence audits, and final reports. Artifacts remain in the
per-job Docker volume and are indexed through the runner API.

## Benchmarking

The bundled benchmark runner creates real engagements against Juice Shop and DVWA and records
completion, commands, specialist passes, reviews, findings, report presence, duration, and errors.
This tests operational behavior and regression stability; it is not a substitute for human validation
of vulnerability accuracy.
