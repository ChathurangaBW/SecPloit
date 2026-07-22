.PHONY: dev test lint up down range logs

dev:
	uvicorn app.api:app --reload --host 127.0.0.1 --port 8000

test:
	pytest

lint:
	ruff check .

up:
	docker compose up --build

range:
	docker compose --profile range up --build

down:
	docker compose --profile range down --remove-orphans

logs:
	docker compose logs -f control runner
