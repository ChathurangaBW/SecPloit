# Autonomous Security Research Agent

A FastAPI application that uses an OpenAI reasoning model to plan and execute evidence-driven security assessment steps against explicitly configured lab or owned targets.

The agent is autonomous inside its container: it can choose tools, run commands, inspect results, revise its hypothesis, and produce a report without per-command approval. The container and target allowlist remain the hard execution boundary.

## Features

- Persistent multi-step agent loop using the OpenAI Responses API
- Browser dashboard for starting jobs and reviewing live evidence
- CLI entry point for terminal workflows
- SQLite job and event history
- Per-job workspaces
- Read-only reconnaissance tool profile
- Exact or wildcard target allowlisting
- Command timeouts and output limits
- Non-root Docker image with dropped Linux capabilities
- CI tests for scope and command policy

## Architecture

```text
Web UI / CLI
     |
FastAPI API
     |
Security agent loop ---- OpenAI Responses API
     |
Policy validator
     |
Subprocess runner inside a disposable, non-root container
     |
Configured lab or owned target
```

## Quick start with Docker

```bash
git clone https://github.com/ChathurangaBW/Automated-Penetration-Testing-Script.git
cd Automated-Penetration-Testing-Script
cp .env.example .env
```

Edit `.env`:

```dotenv
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-5
TARGET_ALLOWLIST=localhost,127.0.0.1,*.lab.internal
```

Start the application:

```bash
docker compose up --build
```

Open `http://localhost:8000`.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.api:app --reload
```

The host must have the command-line tools listed in `COMMAND_ALLOWLIST`. Docker installs the default tool set automatically.

## CLI

```bash
python scanner.py \
  --target https://app.lab.internal \
  --objective "Map the exposed HTTP surface and identify defensible security findings" \
  --max-steps 12
```

## API

### Create a job

```bash
curl -s http://localhost:8000/api/jobs \
  -H 'content-type: application/json' \
  -d '{
    "target": "https://app.lab.internal",
    "objective": "Assess HTTP, TLS, and exposed services",
    "max_steps": 12
  }'
```

### Read a job

```bash
curl -s http://localhost:8000/api/jobs/JOB_ID
```

### List jobs

```bash
curl -s http://localhost:8000/api/jobs
```

## Target allowlist

`TARGET_ALLOWLIST` accepts comma-separated exact hosts and wildcard suffixes:

```dotenv
TARGET_ALLOWLIST=127.0.0.1,localhost,app.lab.internal,*.range.local
```

A job is rejected before execution when its host does not match the allowlist. Network commands must also reference the job target literally.

## Default tool profile

The default Docker image includes:

- `curl`
- `nmap`
- `dig` and `nslookup`
- `whois`
- `openssl`
- `jq`
- standard read-only text and filesystem utilities

The default policy blocks shell chaining, command substitution, write-oriented HTTP methods, intrusive Nmap script categories, arbitrary interpreters, persistence tooling, credential attacks, and destructive operations.

`COMMAND_ALLOWLIST` is configurable, but expanding it changes the security properties of the runner.

## Tests

```bash
pytest -q
```

## Operational scope

Use this software only for systems you own or are explicitly authorized to assess. Run the application in a dedicated cyber range or isolated assessment environment. Do not mount the Docker socket, host root filesystem, cloud credentials, or production secrets into the container.
