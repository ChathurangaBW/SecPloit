# Threat model

SecPloit deliberately gives an LLM a general shell. The security boundary must therefore be enforced
outside the model.

## Protected assets

- Docker host
- control-plane API key
- other engagements
- non-range networks
- operator workstation
- target data not required for the authorized assessment

## Primary threats

### Prompt injection from target content

All target responses are treated as untrusted evidence. They are never promoted to system
instructions. The reviewer receives the command and result as data.

### Workspace escape

Workspaces have no Docker socket, no host path mounts, no capabilities, `no-new-privileges`, a
read-only root filesystem, resource limits, and an internal-only network. A dedicated runner host is
still recommended because container isolation is not equivalent to a microVM boundary.

### Runner compromise

The runner has Docker Engine authority and must not be internet-exposed. It is reachable only through
an internal Compose network and requires a shared token. Replace the mounted socket with rootless
Docker, a socket proxy, or a remote sandbox service for stronger deployments.

### Cross-job contamination

Each job receives a unique container and named volume. Job identifiers and workspace identifiers are
strictly validated. Containers do not share volumes.

### Unbounded autonomous execution

The control plane enforces maximum steps, wall time, command time, output size, memory, CPU, and PID
budgets. Jobs can be cancelled from the API or dashboard.

### Public-target misuse

The bundled topology has no public egress from workspaces. Targets must be attached to the private
range network and their exact hostname must be present in the allowlist. Public IP literals are
rejected.

## Explicit non-goals

The default build does not provide persistence, phishing, credential reuse outside the range,
destructive actions, denial of service, host escape, or arbitrary public-internet operation.
