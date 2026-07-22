# SecPloit 4.0.0

SecPloit 4 introduces a durable long-horizon research control plane for isolated, explicitly authorized cyber ranges.

## Highlights

- Autonomous engagements with parallel specialist planning, operation, review, audit, and reporting
- Durable campaign and experiment dependency graphs
- Capability-routed worker leasing
- Checkpoint heartbeats, retries, attempt budgets, and lease-expiry recovery
- Bounded campaign parallelism and deterministic terminal states
- Ground-truth precision, recall, and F1 evaluation
- Persistent Kali workspaces with browser, network, source, and binary tooling
- Bundled OWASP Juice Shop and DVWA range targets
- GPT-5.6 reasoning profiles through `max`, including optional `pro` mode

## QA and release verification

The release pipeline verifies:

- Ruff static analysis
- Python 3.11 and 3.12 test suites
- Coverage generation
- Python source compilation
- Wheel and source-distribution builds
- Twine package validation
- Installed CLI entry points
- Docker Compose configuration
- Control and runner image builds
- Live Docker startup of the control plane, runner, Juice Shop, and DVWA
- End-to-end campaign lifecycle, worker lease, checkpoint, dependency, graph, and evaluation API smoke tests

## Images

The release workflow publishes:

- `ghcr.io/chathurangabw/secploit-control:4.0.0`
- `ghcr.io/chathurangabw/secploit-runner:4.0.0`
- corresponding `latest` tags

## Boundary

SecPloit is intended only for systems you own or are explicitly authorized to assess. Default research workspaces are confined to an internal Docker range and are not configured for arbitrary public-target operation.
