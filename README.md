# SecPloit

**SecPloit is an autonomous, evidence-driven security research platform for private cyber ranges.**

It is not a linear wrapper around Nmap. The control plane uses separate planning, operating,
review, and reporting passes. Every engagement receives a persistent disposable workspace where the
agent can write scripts, compile test cases, run security tools, inspect results, revise hypotheses,
and continue until it has enough evidence.

## Implemented

- Multi-pass LLM workflow: planner, operator, reviewer, final reporter
- Persistent engagement state, command transcript, findings, and artifacts
- A general shell inside a per-engagement Kali workspace
- Docker-isolated workspaces with no host mounts and no public network by default
- Private range containing OWASP Juice Shop and DVWA
- Nmap, Nikto, ffuf, Gobuster, SQLMap, Semgrep, GDB, Radare2, Binwalk, Checksec, curl,
  OpenSSL, DNS utilities, Python, GCC, Git, jq, and netcat
- Command budgets, output limits, cancellation, workspace lifecycle, and immutable event history
- Browser dashboard, JSON API, unit tests, and CI

## Architecture

```text
Browser / API
     |
     v
SecPloit control plane ----> OpenAI Responses API
     |
     v
Runner API (Docker SDK)
     |
     v
Per-job Kali workspace ----> internal secploit-range network
                                |-- juice-shop
                                `-- dvwa
```

The workspace has broad command-line autonomy. The hard boundary is infrastructure: it is attached
only to the internal cyber-range network, receives no host filesystem mounts, runs without Linux
capabilities, and has CPU, memory, PID, time, and output limits.

## Quick start

Requirements:

- Docker Engine with Compose
- An OpenAI API key
- Linux is recommended; rootless Docker or a dedicated lab host is strongly preferred

```bash
git clone https://github.com/ChathurangaBW/SecPloit.git
cd SecPloit
cp .env.example .env
```

Set `OPENAI_API_KEY` and choose a model available to your API account. Then:

```bash
docker compose --profile range up --build
```

Open `http://localhost:8000`.

Bundled targets:

- `http://juice-shop:3000`
- `http://dvwa`

The runner image is also the workspace image, so the Compose build creates everything needed for
per-job workspaces.

## CLI

```bash
secploit   --target http://juice-shop:3000   --objective "Map the attack surface and validate high-confidence web findings"   --steps 20
```

## API

```bash
curl -sS http://localhost:8000/api/jobs   -H 'content-type: application/json'   -d '{
    "target": "http://juice-shop:3000",
    "objective": "Assess authentication and input-handling weaknesses",
    "max_steps": 20
  }'
```

Important endpoints:

- `POST /api/jobs`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`
- `GET /api/jobs/{job_id}/artifacts`
- `GET /health`

## Operational boundary

SecPloit is built for systems you own or are explicitly authorized to test. The default Compose
topology has no public egress from workspaces. To attach additional lab targets, connect them to the
`secploit-range` Docker network and add their exact hostnames to `SECPLOIT_TARGET_ALLOWLIST`.

Do not expose the runner API or Docker socket to an untrusted network. For serious use, deploy the
runner on a separate rootless-Docker host or replace the Docker backend with Firecracker,
Kubernetes Jobs, or another hardened sandbox.

See [Architecture](docs/ARCHITECTURE.md) and [Threat Model](docs/THREAT_MODEL.md).
