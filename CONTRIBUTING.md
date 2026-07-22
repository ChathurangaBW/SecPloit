# Contributing to SecPloit

## Scope

Contributions must preserve SecPloit's default boundary: explicitly authorized private cyber ranges, isolated workspaces, bounded resources, and evidence-based reporting.

Changes that enable arbitrary public-target operation, destructive actions, persistence, credential reuse outside the range, denial of service, or host escape are not accepted.

## Development setup

```bash
git clone https://github.com/ChathurangaBW/SecPloit.git
cd SecPloit
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
```

## Required local checks

```bash
ruff check .
pytest --cov=app --cov=runner --cov-report=term-missing
python -m compileall -q app runner scripts scanner.py
python -m build
```

Validate the Compose configuration:

```bash
cp .env.example .env
docker compose config --quiet
docker compose --profile range config --quiet
```

Run the full Docker QA path:

```bash
docker compose build --pull control runner
docker compose --profile range up -d --no-build
python scripts/qa_smoke.py --base-url http://127.0.0.1:8000
docker compose --profile range down --volumes --remove-orphans
```

## Pull requests

A pull request should include:

- the problem and intended behavior;
- implementation summary;
- tests covering the change;
- security-boundary impact;
- operational or migration notes;
- evidence that lint, tests, package validation, and relevant Docker checks pass.

Never include API keys, private target information, credentials, proprietary artifacts, or vulnerability details that are not ready for public disclosure.
