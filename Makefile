SHELL := /bin/bash

COMPOSE ?= docker compose
BACKEND_URL ?= http://localhost:8000
FRONTEND_URL ?= http://localhost:3000

.DEFAULT_GOAL := help

.PHONY: help up down restart rebuild logs ps \
        pull-models pg-shell pg-index \
        test test-backend test-frontend smoke e2e \
        backend-shell frontend-shell clean clean-data

help:
	@echo "construction-analyzer - common commands"
	@echo ""
	@echo "  make up             Build and start all containers (frontend, backend, ollama, postgres)"
	@echo "  make down           Stop all containers"
	@echo "  make restart        Restart all containers"
	@echo "  make rebuild        Rebuild images and start"
	@echo "  make logs           Tail logs from all services"
	@echo "  make ps             Show running services"
	@echo ""
	@echo "  make pull-models    Pull required Ollama models (nomic-embed-text + qwen3:1.7b)"
	@echo "  make pg-shell       Open psql shell on the postgres container"
	@echo "  make pg-index       Create HNSW vector index on memorypalace memories table"
	@echo ""
	@echo "  make test           Run backend + frontend test suites in containers"
	@echo "  make test-backend   Run backend pytest suite"
	@echo "  make test-frontend  Run frontend vitest suite"
	@echo "  make smoke          End-to-end pipeline smoke test (curl-based)"
	@echo "  make e2e            Playwright e2e against the running stack"
	@echo ""
	@echo "  make backend-shell  Shell inside the backend container"
	@echo "  make frontend-shell Shell inside the frontend container"
	@echo "  make clean          Stop and remove containers + named volumes"
	@echo "  make clean-data     Wipe local backend/data/ folder (DESTRUCTIVE)"

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

rebuild:
	$(COMPOSE) up -d --build --force-recreate

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

pull-models:
	$(COMPOSE) exec ollama ollama pull nomic-embed-text
	$(COMPOSE) exec ollama ollama pull qwen3:1.7b

pg-shell:
	$(COMPOSE) exec postgres psql -U construction -d memory_palace

pg-index:
	$(COMPOSE) exec postgres psql -U construction -d memory_palace -c \
		"CREATE INDEX IF NOT EXISTS memories_embedding_hnsw_idx ON memories USING hnsw (embedding vector_cosine_ops);"

test: test-backend test-frontend

test-backend:
	$(COMPOSE) run --rm --no-deps backend pytest -q

test-frontend:
	$(COMPOSE) run --rm --no-deps frontend npm test --silent

smoke:
	@bash scripts/smoke.sh

e2e:
	$(COMPOSE) run --rm --no-deps frontend npm run e2e

backend-shell:
	$(COMPOSE) exec backend /bin/bash

frontend-shell:
	$(COMPOSE) exec frontend /bin/sh

clean:
	$(COMPOSE) down -v --remove-orphans

clean-data:
	rm -rf backend/data/documents/* backend/data/checkpoints.sqlite*
