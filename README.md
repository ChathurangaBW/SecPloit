# SecPloit

**SecPloit is a long-horizon, evidence-driven security research platform for private cyber ranges.**

SecPloit v4 combines two execution modes:

1. **Autonomous engagements** — parallel specialist planning, a lead planner, an operator, per-step review, final evidence audit, and reporting.
2. **Research campaigns** — durable experiment graphs that can run for hours or days across multiple capability-specific workers with leases, checkpoints, retries, dependencies, and ground-truth scoring.

## SecPloit v4

- GPT-5.6 reasoning profiles through `max`, with optional `pro` mode
- Parallel web, network, code/binary, authentication, strategy, and skeptical-review specialists
- Persistent Kali workspaces with browser, network, source, and binary tooling
- Durable campaign and experiment graph stored in SQLite
- Dependency-aware experiment scheduling
- Distributed worker leasing with capability routing
- Per-campaign parallelism limits
- Checkpoint heartbeats and lease-expiry recovery
- Retry budgets and deterministic terminal states
- Ground-truth precision, recall, and F1 scoring
- Juice Shop and DVWA private-range benchmark scenarios
- FastAPI, dashboard, CLI, tests, and CI

## Architecture

```text
                         specialist committee
               +------------------------------------+
               | web | network | code | auth | critic|
               +-----------------+------------------+
                                 |
                                 v
Browser / API ---> lead planner ---> operator ---> Kali workspace
                                      |
                                      v
                                evidence reviewer
                                      |
                                      v
                                final report audit

Long-horizon campaign control plane
               |
               v
      dependency experiment graph
       /          |            \
 browser worker  fuzz worker   binary worker
       \          |            /
         checkpoints + results
```

The single-engagement workflow is optimized for one autonomous assessment. The campaign engine is optimized for resumable research with independent experiments, competing hypotheses, large worker pools, and explicit evidence dependencies.

## Quick start

```bash
git clone https://github.com/ChathurangaBW/SecPloit.git
cd SecPloit
cp .env.example .env
```

Set:

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5.6
OPENAI_REASONING_MODE=pro
OPENAI_REASONING_EFFORT=max
OPENAI_OPERATOR_REASONING_EFFORT=max
OPENAI_CRITIC_REASONING_EFFORT=max
OPENAI_MAX_OUTPUT_TOKENS=64000
```

Start:

```bash
docker compose --profile range up --build
```

Open `http://localhost:8000`.

Bundled targets:

- `http://juice-shop:3000`
- `http://dvwa`

Inspect active capabilities:

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
      "required_capabilities": ["browser"],
      "priority": 100
    }' | jq -r '.experiment.id'
)
```

Create a dependent experiment:

```bash
curl -sS "http://localhost:8000/api/campaigns/${CAMPAIGN_ID}/experiments" \
  -H 'content-type: application/json' \
  -d "{
    \"title\": \"Validate authorization hypotheses\",
    \"kind\": \"validation\",
    \"objective\": \"Test evidence-backed authorization hypotheses from route mapping.\",
    \"parent_ids\": [\"${ROOT_ID}\"],
    \"required_capabilities\": [\"browser\", \"http\"],
    \"priority\": 90
  }" | jq
```

Activate:

```bash
curl -sS -X POST \
  "http://localhost:8000/api/campaigns/${CAMPAIGN_ID}/activate" | jq
```

Lease work to a capability-specific worker:

```bash
curl -sS \
  "http://localhost:8000/api/campaigns/${CAMPAIGN_ID}/lease" \
  -H 'content-type: application/json' \
  -d '{
    "worker_id": "browser-worker-01",
    "capabilities": ["browser", "http"],
    "lease_seconds": 600
  }' | jq
```

Workers send checkpoints:

```bash
curl -sS \
  "http://localhost:8000/api/experiments/EXPERIMENT_ID/heartbeat" \
  -H 'content-type: application/json' \
  -d '{
    "worker_id": "browser-worker-01",
    "lease_seconds": 600,
    "checkpoint": {
      "pages_visited": 42,
      "artifact_index": "/workspace/browser/crawl.json"
    }
  }' | jq
```

Complete an experiment:

```bash
curl -sS \
  "http://localhost:8000/api/experiments/EXPERIMENT_ID/complete" \
  -H 'content-type: application/json' \
  -d '{
    "worker_id": "browser-worker-01",
    "result": {
      "evidence_artifacts": ["browser/crawl.json"],
      "summary": "Route and form map completed"
    }
  }' | jq
```

Inspect the experiment graph:

```bash
curl -sS \
  "http://localhost:8000/api/campaigns/${CAMPAIGN_ID}/graph" | jq
```

## Ground-truth scoring

```bash
curl -sS http://localhost:8000/api/evaluations/ground-truth \
  -H 'content-type: application/json' \
  --data @benchmarks/ground_truth_example.json | jq
```

The evaluator returns true positives, false positives, false negatives, precision, recall, F1, matched findings, missed vulnerabilities, and unmatched observations.

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

## Benchmark

```bash
python benchmarks/run_benchmark.py \
  --base-url http://localhost:8000 \
  --output benchmark-results.json
```

Operational completion is not sufficient evidence of vulnerability-discovery quality. Use the ground-truth endpoint to calculate detection precision and recall on targets with known vulnerabilities.

## Main endpoints

- `GET /api/capabilities`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/campaigns`
- `GET /api/campaigns/{campaign_id}`
- `GET /api/campaigns/{campaign_id}/graph`
- `POST /api/campaigns/{campaign_id}/experiments`
- `POST /api/campaigns/{campaign_id}/activate`
- `POST /api/campaigns/{campaign_id}/lease`
- `POST /api/experiments/{experiment_id}/heartbeat`
- `POST /api/experiments/{experiment_id}/complete`
- `POST /api/experiments/{experiment_id}/fail`
- `POST /api/evaluations/ground-truth`

## Boundary

SecPloit is for systems you own or are explicitly authorized to test. The default range topology has no public egress from research workspaces, no host path mounts, non-root execution, dropped capabilities, and bounded resources.

See [Long-Horizon Research](docs/LONG_HORIZON_RESEARCH.md), [Architecture](docs/ARCHITECTURE.md), and [Threat Model](docs/THREAT_MODEL.md).
