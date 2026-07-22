# SecPloit

**SecPloit is a high-reasoning, evidence-driven security research platform for private cyber ranges.**

It is not a linear scanner wrapper. SecPloit combines a parallel specialist planning committee, a
lead planner, a hands-on operator, a critical step reviewer, a final evidence auditor, and a report
writer. Each engagement receives a persistent disposable Kali workspace where the agent can write
scripts, compile test cases, operate a bounded browser, run security tools, inspect results, revise
hypotheses, and continue until it has reproducible evidence.

## SecPloit v3

- Role-specific OpenAI reasoning effort, set to `high` by default
- Parallel specialist planning committee
- Lead-plan synthesis across web, network, code/binary, authentication, and skeptical-review views
- General shell inside a persistent per-engagement Kali workspace
- Headless Chromium evidence collection and bounded same-origin crawling
- Critical review after every command
- Duplicate-finding suppression
- Final evidence audit before report generation
- Persistent engagement state, transcript, findings, artifacts, and reports
- Docker-isolated workspaces with no host mounts and no public network by default
- Private range containing OWASP Juice Shop and DVWA
- Reproducible bundled benchmark runner
- Browser dashboard, JSON API, CLI, tests, and CI

## Reasoning architecture

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
```

The committee members run concurrently. Their assessments are hypotheses, not facts. The lead planner
resolves conflicts and creates a concrete research plan. The operator chooses one evidence-producing
action at a time. A separate critic reviews every command and result before a finding is stored. A
final audit can reject unsupported candidate findings before the report is written.

## Workspace capabilities

The runner image includes:

- Nmap, Nikto, ffuf, Gobuster, SQLMap
- Semgrep
- GDB, Radare2, Binwalk, Checksec, strace
- Chromium and Playwright
- curl, OpenSSL, DNS utilities, WHOIS, netcat
- Python, GCC, Git, jq and common Unix tooling

The workspace has broad command-line autonomy inside the range. The infrastructure boundary remains
hard: the workspace attaches only to the internal `secploit-range` network, receives no host
filesystem mounts, runs as a non-root user with all Linux capabilities dropped, and has CPU, memory,
PID, command-time, wall-time, and output limits.

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

Set at least:

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5.6
OPENAI_REASONING_EFFORT=high
OPENAI_OPERATOR_REASONING_EFFORT=high
OPENAI_CRITIC_REASONING_EFFORT=high
SECPLOIT_PLANNING_AGENTS=4
```

Then start the control plane, runner, and bundled range:

```bash
docker compose --profile range up --build
```

Open `http://localhost:8000`.

Bundled targets:

- `http://juice-shop:3000`
- `http://dvwa`

## Browser evidence helper

Capture a full-page screenshot, DOM, forms, links, scripts, response headers, and network-response
metadata:

```bash
secploit-browser snapshot http://juice-shop:3000 \
  --out /workspace/browser/juice-shop
```

Run a bounded same-origin crawl without submitting forms:

```bash
secploit-browser crawl http://juice-shop:3000 \
  --max-pages 20 \
  --max-depth 2 \
  --screenshots \
  --out /workspace/browser/crawl
```

All generated browser evidence remains in the engagement workspace and appears in the artifact list.

## CLI

```bash
secploit \
  --target http://juice-shop:3000 \
  --objective "Map the attack surface and validate high-confidence web findings" \
  --steps 24
```

## API

```bash
curl -sS http://localhost:8000/api/jobs \
  -H 'content-type: application/json' \
  -d '{
    "target": "http://juice-shop:3000",
    "objective": "Assess authentication and input-handling weaknesses",
    "max_steps": 24
  }'
```

Important endpoints:

- `POST /api/jobs`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/cancel`
- `GET /api/jobs/{job_id}/artifacts`
- `GET /health`

## Benchmark

Start the bundled range, then run:

```bash
python benchmarks/run_benchmark.py \
  --base-url http://localhost:8000 \
  --output benchmark-results.json
```

The benchmark runs the bundled Juice Shop and DVWA scenarios and records completion status, command
count, specialist count, review count, finding count, report presence, duration, and errors. It is an
operational benchmark, not proof that every finding is correct; report quality still requires human
review.

## Main configuration

| Variable | Default | Purpose |
|---|---:|---|
| `OPENAI_MODEL` | `gpt-5.6` | Planner, specialist, and operator model |
| `OPENAI_CRITIC_MODEL` | same as main model | Reviewer, auditor, and reporter model |
| `OPENAI_REASONING_EFFORT` | `high` | Specialist and planner reasoning effort |
| `OPENAI_OPERATOR_REASONING_EFFORT` | `high` | Operator reasoning effort |
| `OPENAI_CRITIC_REASONING_EFFORT` | `high` | Reviewer/auditor/report reasoning effort |
| `OPENAI_MAX_OUTPUT_TOKENS` | `24000` | Per-model-call output ceiling |
| `OPENAI_STORE_RESPONSES` | `false` | Whether OpenAI stores API responses |
| `SECPLOIT_PLANNING_AGENTS` | `4` | Concurrent planning specialists, 1-8 |
| `SECPLOIT_TARGET_ALLOWLIST` | bundled targets | Exact permitted target hostnames |
| `SECPLOIT_MAX_STEPS` | `30` | Maximum operator steps |
| `SECPLOIT_MAX_WALL_SECONDS` | `1800` | Engagement wall-clock limit |

## Operational boundary

SecPloit is built for systems you own or are explicitly authorized to test. The default Compose
topology has no public egress from workspaces. To attach another lab target, connect it to the
`secploit-range` Docker network and add its exact hostname to `SECPLOIT_TARGET_ALLOWLIST`.

Do not expose the runner API or Docker socket to an untrusted network. For serious deployment, place
the runner on a separate rootless-Docker host or replace the Docker backend with Firecracker,
Kubernetes Jobs, or another hardened sandbox.

SecPloit is not OpenAI's private internal cyber-evaluation harness and does not reproduce undisclosed
infrastructure, unreleased models, or private zero-days.

See [Architecture](docs/ARCHITECTURE.md) and [Threat Model](docs/THREAT_MODEL.md).
