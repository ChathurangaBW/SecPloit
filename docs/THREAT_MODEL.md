# Threat model

SecPloit deliberately gives an LLM a general shell and a headless browser. The security boundary must
therefore be enforced outside the model.

## Protected assets

- Docker host
- control-plane API key
- other engagements
- non-range networks
- operator workstation
- target data not required for the authorized assessment
- model transcripts and generated reports

## Primary threats

### Prompt injection from target content

All target responses, DOM content, scripts, screenshots, command output, and scanner output are treated
as untrusted evidence. They are never promoted to system instructions. Specialist assessments are
also treated as hypotheses rather than facts. The step reviewer receives commands and results as data,
and the final auditor re-evaluates candidate findings against the full evidence set.

### Workspace escape

Workspaces have no Docker socket, no host path mounts, no capabilities, `no-new-privileges`, a
read-only root filesystem, resource limits, and an internal-only network. A dedicated runner host is
still recommended because container isolation is not equivalent to a microVM boundary.

### Browser exploitation

Chromium processes untrusted range content. The browser runs as the non-root workspace user inside the
same disposable container, has no public egress, receives no host mounts, and is subject to the same
CPU, memory, PID, wall-time, and command-time limits. The helper blocks credential-bearing URLs,
performs bounded same-origin crawling, and does not submit forms. A hardened deployment should place
the runner in a microVM or dedicated sandbox host.

### Runner compromise

The runner has Docker Engine authority and must not be internet-exposed. It is reachable only through
an internal Compose network and requires a shared token. Replace the mounted socket with rootless
Docker, a socket proxy, a remote sandbox service, or a microVM backend for stronger deployments.

### Cross-job contamination

Each job receives a unique container and named volume. Job identifiers and workspace identifiers are
strictly validated. Containers do not share volumes. Specialist model calls share only the explicit
planning payload and do not share workspace credentials or hidden state.

### Unbounded autonomous execution

The control plane enforces maximum specialists, steps, wall time, command time, output size, model
output tokens, memory, CPU, and PID budgets. Browser crawling additionally enforces page, depth, and
navigation-time limits. Jobs can be cancelled from the API or dashboard.

### Hallucinated or duplicated findings

A separate reviewer evaluates every command result. Candidate findings require a concrete component
and reproducible evidence. Duplicate title/claim pairs are suppressed. A final evidence auditor can
reject or qualify findings before the report is generated. Human review remains required for external
use of the report.

### Public-target misuse

The bundled topology has no public egress from workspaces. Targets must be attached to the private
range network and their exact hostname must be present in the allowlist. Public IP literals are
rejected.

### Sensitive API retention

`OPENAI_STORE_RESPONSES` defaults to `false`. Engagement prompts should still be treated as data sent
to the configured model provider. Do not place unnecessary production secrets, unrelated personal
data, or third-party credentials into objectives or artifacts.

## Explicit non-goals

The default build does not provide persistence, phishing, credential reuse outside the range,
destructive actions, denial of service, host escape, or arbitrary public-internet operation. It is not
a replica of any private internal evaluation harness and does not include undisclosed vulnerabilities.
