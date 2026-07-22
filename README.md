# SecPloit

[![CI](https://github.com/ChathurangaBW/SecPloit/actions/workflows/ci.yml/badge.svg)](https://github.com/ChathurangaBW/SecPloit/actions/workflows/ci.yml)
[![QA](https://github.com/ChathurangaBW/SecPloit/actions/workflows/qa.yml/badge.svg)](https://github.com/ChathurangaBW/SecPloit/actions/workflows/qa.yml)
[![Release](https://github.com/ChathurangaBW/SecPloit/actions/workflows/release.yml/badge.svg)](https://github.com/ChathurangaBW/SecPloit/actions/workflows/release.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Long-horizon, evidence-driven security research for isolated and explicitly authorized cyber ranges.**

SecPloit combines autonomous assessment agents with a durable campaign engine. It can plan, execute, review, checkpoint, resume, and score research experiments while keeping the execution boundary outside the model.

> SecPloit is not a universal vulnerability oracle. Findings require reproducible evidence and human review. The default deployment is intentionally restricted to private-range targets.

## Core capabilities

- GPT-5.6 reasoning profiles through `max`, with optional `pro` mode
- Parallel web, network, code/binary, authentication, strategy, and skeptical-review specialists
- Lead planner, hands-on operator, per-step critic, final evidence auditor, and report writer
- Persistent Kali workspaces with browser, network, source, compilation, and binary-analysis tooling
- Durable campaign and experiment dependency graph stored in SQLite
- Capability-routed distributed worker leases
- Checkpoint heartbeats, retries, attempt budgets, and lease-expiry recovery
- Bounded campaign parallelism and deterministic terminal states
- Ground-truth precision, recall, and F1 evaluation
- Bundled OWASP Juice Shop and DVWA private-range targets
- FastAPI control plane, browser dashboard, CLI, tests, Docker QA, releases, and GHCR images

## Architecture

```text
                         specialist committee
               +-------------------------------------+
               | web | network | code | auth | critic|
               +------------------+------------------+
                                  |
                                  v
Browser / API ---> lead planner ---> operator ---> Kali workspace
                                       |                 |
                                       |                 v
                                       |          private range targets
                                       v
                                 step reviewer
                                       |
                                       v
                               final evidence audit
                                       |
                                       v
                                professional report

Long-horizon campaign control plane
               |
               v
      dependency experiment graph
       /          |             \
 browser worker  fuzz worker   binary worker
       \          |             /
         checkpoints + results
```

The single-engagement workflow is optimized for one autonomous assessment. The campaign engine is optimized for resumable research with competing hypotheses, independent experiments, capability-specific worker pools, and explicit evidence dependencies.

## Quick start

Requirements:

- Docker Engine and Docker Compose
- An OpenAI API key
- Linux recommended; rootless Docker or a dedicated lab host preferred

```bash
git clone https://github.com/ChathurangaBW/SecPloit.git
cd SecPloit
cp .env.example .env
```

Set at least:

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5.6
OPENAI_REASONING_MODE=pro
OPENAI_REASONING_EFFORT=max
OPENAI_OPERATOR_REASONING_EFFORT=max
OPENAI_CRITIC_REASONING_EFFORT=max
OPENAI_MAX_OUTPUT_TOKENS=64000
```

Start the control plane, runner, and bundled range:

```bash
docker compose --profile range up --build
```

Open `http://localhost:8000`.

Bundled targets:

- `http://juice-shop:3000`
- `http://dvwa`

Inspect the effective configuration:

```bash
curl -sS http://localhost:8000/api/capabilities | jq
```

## Autonomous engagement

```bash
curl -sS http://localhost:8000/api/jobs \
  -H 'content-type: application/json' \
  -d '{
    "target": "http://juice-shop:3000",
    "objective": "Assess authentication and input-handling weaknesses",
    "max_steps": 30
  }' | jq
```

## Long-horizon campaign

Create a campaign:

```bash
CAMPAIGN_ID=$(
  curl -sS http://localhost:8000/api/campaigns \
    -H 'content-type: application/json' \
    -d '{
      "name": "Juice Shop research campaign",
      "target": "http://juice-shop:3000",
      "objective": "Run a resumable evidence-driven research campaign.",
      "max_parallel": 4,
      "max_experiments": 500
    }' | jq -r '.campaign.id'
)
```

Create a root experiment:

```bash
ROOT_ID=$(
  curl -sS "http://localhost:8000/api/campaigns/${CAMPAIGN_ID}/experiments" \
    -H 'content-type: application/json' \
    -d '{
      "title": "Map application state and routes",
      "kind": "browser",
      "objective": "Collect DOM, route, form, script, and network evidence.",
      "required_capabilities": ["browser", "http"],
      "priority": 100
    }' | jq -r '.experiment.id'
)
```

Create a dependent experiment and activate the campaign:

```bash
curl -sS "http://localhost:8000/api/campaigns/${CAMPAIGN_ID}/experiments" \
  -H 'content-type: application/json' \
  -d "{
    \"title\": \"Validate authorization hypotheses\",
    \"kind\": \"validation\",
    \"objective\": \"Test evidence-backed authorization hypotheses.\",
    \"parent_ids\": [\"${ROOT_ID}\"],
    \"required_capabilities\": [\"browser\", \"http\"],
    \"priority\": 90
  }" | jq

curl -sS -X POST \
  "http://localhost:8000/api/campaigns/${CAMPAIGN_ID}/activate" | jq
```

Lease work to a matching worker:

```bash
curl -sS "http://localhost:8000/api/campaigns/${CAMPAIGN_ID}/lease" \
  -H 'content-type: application/json' \
  -d '{
    "worker_id": "browser-worker-01",
    "capabilities": ["browser", "http"],
    "lease_seconds": 600
  }' | jq
```

See [Long-Horizon Research](docs/LONG_HORIZON_RESEARCH.md) for heartbeat, completion, failure, dependency, recovery, and evaluation examples.

## Browser evidence

```bash
secploit-browser snapshot http://juice-shop:3000 \
  --out /workspace/browser/juice-shop

secploit-browser crawl http://juice-shop:3000 \
  --max-pages 20 \
  --max-depth 2 \
  --screenshots \
  --out /workspace/browser/crawl
```

The helper records DOM, links, forms, scripts, response headers, network metadata, screenshots, and crawl indexes in the engagement workspace.

## Evaluation

Operational completion is not proof of vulnerability-discovery quality. Use targets with known ground truth and score observed findings:

```bash
curl -sS http://localhost:8000/api/evaluations/ground-truth \
  -H 'content-type: application/json' \
  --data @benchmarks/ground_truth_example.json | jq
```

The evaluator reports true positives, false positives, false negatives, precision, recall, F1, matches, misses, and unmatched observations.

Run the bundled operational benchmark:

```bash
python benchmarks/run_benchmark.py \
  --base-url http://localhost:8000 \
  --output benchmark-results.json
```

## QA

Local quality checks:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
ruff check .
pytest --cov=app --cov=runner --cov-report=term-missing
python -m compileall -q app runner scripts scanner.py
```

Full Docker QA:

```bash
cp .env.example .env
docker compose build --pull control runner
docker compose --profile range up -d --no-build
python scripts/qa_smoke.py --base-url http://127.0.0.1:8000
docker compose --profile range down --volumes --remove-orphans
```

The GitHub QA workflow additionally tests Python 3.11 and 3.12, validates source and wheel distributions, checks CLI entry points, validates Compose, builds both Docker images, starts the complete private range, and exercises campaign lifecycle, leases, checkpoints, dependencies, graph APIs, and ground-truth scoring.

## Releases and packages

- [GitHub releases](https://github.com/ChathurangaBW/SecPloit/releases)
- [Control-plane container](https://github.com/ChathurangaBW/SecPloit/pkgs/container/secploit-control)
- [Runner container](https://github.com/ChathurangaBW/SecPloit/pkgs/container/secploit-runner)

Versioned images:

```text
ghcr.io/chathurangabw/secploit-control:4.0.0
ghcr.io/chathurangabw/secploit-runner:4.0.0
```

The release contains a Python wheel and source distribution. GHCR packages are built from the tagged source and also receive `latest` tags.

## Main API endpoints

- `GET /health`
- `GET /api/capabilities`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`
- `POST /api/campaigns`
- `GET /api/campaigns/{campaign_id}`
- `GET /api/campaigns/{campaign_id}/graph`
- `POST /api/campaigns/{campaign_id}/experiments`
- `POST /api/campaigns/{campaign_id}/activate`
- `POST /api/campaigns/{campaign_id}/pause`
- `POST /api/campaigns/{campaign_id}/cancel`
- `POST /api/campaigns/{campaign_id}/lease`
- `POST /api/experiments/{experiment_id}/heartbeat`
- `POST /api/experiments/{experiment_id}/complete`
- `POST /api/experiments/{experiment_id}/fail`
- `POST /api/evaluations/ground-truth`

## Project resources

- [Architecture](docs/ARCHITECTURE.md)
- [Long-horizon research](docs/LONG_HORIZON_RESEARCH.md)
- [Threat model](docs/THREAT_MODEL.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Release notes](RELEASE.md)

## Security boundary

SecPloit is for systems you own or are explicitly authorized to test. The default range topology has no public egress from research workspaces, no host path mounts, non-root execution, dropped Linux capabilities, bounded resources, and separate evidence review.

Do not expose the runner API or Docker socket to an untrusted network. Do not commit API keys, runner tokens, target credentials, private findings, or proprietary artifacts.
