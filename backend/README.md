# Backend

FastAPI + LangGraph + MemoryPalace, in a single container.

## Layout

```
app/
  main.py            FastAPI app + lifespan (checkpointer, KB)
  config.py          pydantic-settings
  schemas.py         API request/response models
  api/               health, chat, threads, ingest
  agent/             LangGraph state graph, LLM factory, checkpointer
  kb/                KnowledgeBase interface, fake (tests), MemoryPalace adapter
  services/          ingestion pipeline
tests/
  unit/              isolated tests, no external services
  integration/       FastAPI TestClient with FakeKB + in-memory checkpointer
  e2e/               smoke tests against the running compose stack
```

## Run locally without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
export KB_BACKEND=fake LLM_PROVIDER=openai OPENAI_API_KEY=sk-...
uvicorn app.main:app --reload --port 8000
```

## Test

```bash
pytest -q                       # unit + integration with FakeKB
pytest -q -m integration        # marked integration tests (requires real services)
```
