# construction-analyzer

A modular, test-driven hackathon scaffold pairing an IDE-style Next.js shell with a LangGraph-powered FastAPI backend. Uploaded documents flow through a registry-backed ingestion pipeline into [MemoryPalace](https://github.com/jeffpierce/memory-palace) (PostgreSQL + pgvector + Ollama), while SQLite-backed registry and checkpoint state keep uploads and conversations durable.

```
┌──────────────────────────────── construction-analyzer ──────────────────────────────┐
│ Frontend shell → FastAPI backend → MemoryPalace + SQLite state                     │
│ onboarding · file tree · graph · preview · chat · profile · settings               │
│ /api/chat · /api/chat/sync · /api/ingest · /api/threads · /health · /ready         │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

## Service Architecture

These diagrams reflect the code in the repository today: the browser shell sends
uploads and chat messages to FastAPI; the ingest pipeline turns documents into
typed elements and stores them in MemoryPalace; chat runs through LangGraph and
checkpoints thread history in SQLite.

### Current Architecture

```text
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Frontend shell                                                                       │
│ onboarding · file tree · graph · preview · chat · profile · settings                 │
├───────────────────────────────┬──────────────────────────────────────────────────────┤
│ FastAPI backend               │ Persistence and services                             │
│ /api/chat                     │ document registry (SQLite)                           │
│ /api/chat/sync                │ thread checkpointer (SQLite)                         │
│ /api/ingest                   │ MemoryPalace KB (PostgreSQL + pgvector + Ollama)     │
│ /api/threads                  │ raw uploads                                           │
│ /health · /ready              │ optional visual analysis for figure-like elements    │
│ LangGraph agent + KB tools    │                                                       │
│ ingestion pipeline            │                                                       │
└───────────────────────────────┴──────────────────────────────────────────────────────┘
```

### Ingestion Flow

```text
User uploads a PDF, Markdown file, or plain text
        |
        v
Upload validation, hashing, and registry deduplication
        |
        v
Document parser turns files into typed elements
        |
        v
Optional visual-only enrichment for chart, diagram, drawing, and image elements
        |
        v
Elements are chunked with provenance and stored in MemoryPalace
        |
        v
Registry status is updated to indexed or failed
```

### Chat and Thread Flow

```text
User sends a message
        |
        v
Frontend calls /api/chat or /api/chat/sync
        |
        v
LangGraph injects the system prompt and invokes kb_recall / kb_remember
        |
        v
Streaming tokens and tool events return to the browser
        |
        v
Thread state is checkpointed in SQLite and histories are replayed through /api/threads/{id}/history
```

### Report Generation Pipeline

The "Build Report" button kicks off a multi-stage workflow whose progress is
streamed back to the browser over Server-Sent Events. Two human-in-the-loop
gates (template confirmation and validation) can pause the pipeline until the
user answers; the final PDF is produced by ReportLab and downloaded directly
from the export endpoint.

```text
        ┌──────────────────────────────────────────────────────────────┐
        │  User clicks "Build Report"  (ChatPanel.tsx)                 │
        └───────────────┬──────────────────────────────────────────────┘
                        │
          ┌─────────────┴──────────────┐
          v                            v
 ┌──────────────────────┐    ┌────────────────────────────────────┐
 │ POST /api/reports    │    │ GET  /api/reports/{id}/stream  SSE │
 │ launch_report_session│    │ stream_report_session              │
 └──────────┬───────────┘    └──────────────┬─────────────────────┘
            │                               ^
            v                               │ ReportCard / ReportGate
 ┌──────────────────────────────────────────┴─────────────────────┐
 │  ReportPipeline   (backend/app/services/report_pipeline.py)    │
 │                                                                │
 │   start() ──► [ Gate: template confirmation ]                  │
 │                       │ answer_gate                            │
 │                       v                                        │
 │   ┌──────────────────────────────────────────────────────────┐ │
 │   │ 1. Inventory   build_source_inventory()                  │ │
 │   │ 2. Plan        build_general_project_dossier_section_…() │ │
 │   │ 3. Retrieval   retrieve_section_evidence()               │ │
 │   │ 4. Draft       draft_report_sections()                   │ │
 │   │ 5. Validation  validate_report_projection()              │ │
 │   └──────────────────────┬───────────────────────────────────┘ │
 │                          │                                     │
 │              blockers?   │   no blockers                       │
 │              ┌───────────┴──────────┐                          │
 │              v                      │                          │
 │              | [ Gate: validation ] │                          │
 │              │ answer_gate          │                          │
 │              └──────────┬───────────┘                          │
 │                         v                                      │
 │   6. Export   report_exporter.export_report_pdf()              │
 │                 │  (ReportLab → A4 PDF, atomic move)           │
 │                 v                                              │
 │   /app/data/exports/{session_id}-report.pdf                    │
 │                 │                                              │
 │                 v                                              │
 │   export.status = ready  •  session = complete  ── done ──┐    │
 └───────────────────────────────────────────────────────────┼────┘
                                                             │
                                                             v
                                       ┌────────────────────────────────┐
                                       │ ReportView.tsx                 │
                                       │   • stages / artifacts         │
                                       │   • validation findings        │
                                       │   • gate prompts               │
                                       │   • download link              │
                                       └──────────────┬─────────────────┘
                                                      │  click download
                                                      v
                       GET /api/reports/{id}/exports/{ex}/download
                          → FileResponse(application/pdf)
```

Key files:

- Frontend trigger: [`frontend/src/components/chat/ChatPanel.tsx`](frontend/src/components/chat/ChatPanel.tsx) · API client: [`frontend/src/lib/api.ts`](frontend/src/lib/api.ts) · UI: [`frontend/src/components/report/ReportView.tsx`](frontend/src/components/report/ReportView.tsx)
- Backend routes: [`backend/app/api/reports.py`](backend/app/api/reports.py)
- Orchestration: [`backend/app/services/report_pipeline.py`](backend/app/services/report_pipeline.py)
- PDF export: [`backend/app/services/report_exporter.py`](backend/app/services/report_exporter.py)

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router) · TypeScript · Tailwind · Framer Motion · Zustand · `react-markdown` |
| Backend | FastAPI · LangGraph · LangChain · pydantic-settings · sse-starlette |
| Knowledge base | MemoryPalace (in-process Python library) backed by **PostgreSQL 16 + pgvector** and **Ollama** for embeddings |
| Thread persistence | LangGraph `AsyncSqliteSaver` (SQLite) |
| Orchestration | Docker Compose (4 services, named volumes, healthchecks, dependency-ordered startup) |
| Tests | pytest + httpx + respx (backend) · Vitest + RTL + MSW (frontend) · Playwright (e2e) · bash smoke script |

---

## Prerequisites

### macOS

```bash
# Docker Desktop (recommended) OR colima
brew install --cask docker            # Docker Desktop, then launch it once
# OR
brew install colima docker docker-compose && colima start

# (Optional) for the host-side helpers
brew install make curl python@3.12 node@20
```

### Linux (Ubuntu / Debian)

```bash
# Docker Engine + Compose plugin
sudo apt install -y docker.io docker-compose-plugin make curl python3 nodejs npm
sudo usermod -aG docker "$USER"   # log out / back in for this to take effect
```

Both platforms also need:

| Tool | Why | Install |
|---|---|---|
| `docker` 24+ and `docker compose` v2 | Run all four containers | see above |
| `make` | Convenience targets in the root `Makefile` | `xcode-select --install` (Mac) or `apt install make` (Linux) |
| `curl` | Used by `make smoke` | preinstalled on both |
| `python3` | JSON parsing inside `make smoke` | preinstalled on both |
| `node` 20+ (optional) | Run frontend tests on the host | see above |

> No host-side install of Postgres, pgvector, or Ollama is required — they ship in containers. The `pgvector/pgvector:pg16` image bundles the extension; the `ollama/ollama` image bundles the inference engine.

---

## First-time setup

```bash
git clone <this repo> construction-analyzer
cd construction-analyzer

cp .env.example .env
# Edit .env:
#   - LLM_PROVIDER=openai     and set OPENAI_API_KEY=sk-...
#     OR
#   - LLM_PROVIDER=ollama     (no key needed; slower)
#   - KB_BACKEND=memorypalace (default; uses Postgres + Ollama)
#     OR
#   - KB_BACKEND=fake         (no Ollama/Postgres; in-memory only — handy for the very first boot)
```

### Bring everything up

```bash
make up                # build images and start frontend + backend + postgres + ollama
make pull-models       # one-time: pull the Ollama models MemoryPalace needs
make smoke             # end-to-end pipeline check
```

Open http://localhost:3000.

The first `make up` typically takes 5–10 minutes because the backend image clones and installs MemoryPalace from GitHub. Subsequent builds are cached.

### Verifying the wiring quickly

If you don't yet have an `OPENAI_API_KEY` and Ollama hasn't pulled its models, run:

```bash
SKIP_CHAT=1 make smoke    # checks /health, /ready, frontend reachability — proves the wiring
```

Once you've set `OPENAI_API_KEY=sk-...` (recommended for hackathon speed) **or** pulled an Ollama model that supports tool calling (`make pull-models`), run the full thing:

```bash
make smoke                # full round-trip including a real chat reply on a fresh thread,
                          # then a second turn on the same thread that hits the checkpointer
```

---

## Document ingestion (secure)

The `backend/data/documents/` folder is **gitignored** and **cursorignored** (see [.gitignore](.gitignore) and [.cursorignore](.cursorignore)). Anything you drop in there stays on your machine.

### Two ingestion paths

1. **Drop files into the host folder** (auto-mounted into the backend container):
   ```bash
   cp ~/Downloads/spec-sheet.pdf backend/data/documents/
   curl -X POST http://localhost:8000/api/ingest \
        -F "files=@backend/data/documents/spec-sheet.pdf"
   ```

2. **Upload via the API** from the frontend or curl:
   ```bash
   curl -X POST http://localhost:8000/api/ingest \
        -F "files=@./contract.pdf" \
        -F "files=@./notes.md"
   ```

Supported extensions: `.pdf`, `.md`, `.markdown`, `.txt`. Files are chunked, embedded by Ollama (`nomic-embed-text` by default), and stored in MemoryPalace's Postgres + pgvector tables.

### Ask about your documents

```bash
curl -X POST http://localhost:8000/api/chat/sync \
  -H "Content-Type: application/json" \
  -d '{"message":"summarise the spec sheet","thread_id":"demo-1"}'
```

Or just chat in the UI — the agent calls `kb_recall` automatically.

---

## Running tests

### Backend (pytest, in-container)

```bash
make test-backend      # 64 unit + integration tests, fully hermetic
```

Or run on the host with a Python 3.12 venv:

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

The MemoryPalace integration test (`tests/integration/test_memorypalace_kb.py`) is automatically **skipped** unless Postgres + Ollama are reachable and the `memory_palace` package is importable. Inside the running compose stack:

```bash
docker compose exec backend pytest -q -m integration
```

### Frontend (Vitest + RTL + MSW, in-container)

```bash
make test-frontend     # 26 unit tests
```

Or on the host:

```bash
cd frontend
npm install
npm test
```

### End-to-end pipeline

```bash
make up                # full stack
make smoke             # 6-step curl-based round-trip
```

`make smoke` proves the entire wiring:
1. `/health` is reachable
2. `/ready` reports component status
3. First chat turn returns an assistant message on a fresh `thread_id`
4. Second chat turn on the same `thread_id` succeeds
5. `/api/threads/{id}/history` returns ≥ 4 messages — the LangGraph checkpointer is persisting
6. Frontend `/api/health` (or `/`) responds

### Browser e2e (Playwright)

```bash
cd frontend
npm run e2e:install    # one-time: download Chromium
cd ..
make e2e               # send a chat, reload the page, assert history rehydrates
```

---

## Common operations

| Command | What it does |
|---|---|
| `make up` | Build and start all containers |
| `make down` | Stop everything (data preserved in named volumes) |
| `make logs` | Tail logs from all services |
| `make ps` | Show service status |
| `make rebuild` | Force a full rebuild |
| `make pull-models` | Pull `nomic-embed-text` + `qwen3:1.7b` into the Ollama container |
| `make pg-shell` | Open `psql` against the MemoryPalace database |
| `make pg-index` | Add an HNSW index on the `memories.embedding` column for faster recall |
| `make backend-shell` | `bash` inside the backend container |
| `make frontend-shell` | `sh` inside the frontend container |
| `make clean` | Stop and remove containers **and named volumes** (destructive) |
| `make clean-data` | Wipe local `backend/data/` (documents + checkpointer) |

---

## Troubleshooting

### "Port 3000 / 8000 / 5432 / 11434 already in use"

Something else on your host is listening. Either stop that process or override the port mapping in [docker-compose.yml](docker-compose.yml). Mac's AirPlay Receiver hijacks 5000 by default but does not touch any of our ports.

### Backend `/ready` shows `degraded`

Read the `detail` field. Most common causes:

- `ollama` — models not pulled yet → `make pull-models`
- `postgres` — Postgres still booting on first run → wait 10s and retry
- `kb` — `KB_BACKEND=memorypalace` but `memory_palace` failed to import (check `docker compose logs backend` for the install-time error and re-run `make rebuild`). As a temporary workaround, set `KB_BACKEND=fake` in `.env` and `make restart`.

### The first chat reply is very slow (or times out)

Ollama on CPU only is slow. **First inference for a new model can take several minutes** — the model is loaded into memory from disk, and on machines without GPU passthrough every token is computed on the CPU. Symptoms: `make smoke` hangs at step 3, browser shows the typing indicator forever, `docker stats` shows the `ollama` container at 1000%+ CPU.

Workarounds, in order of recommendation:

1. **Use OpenAI for the chat LLM** — fastest path:
   ```bash
   # in .env
   LLM_PROVIDER=openai
   OPENAI_API_KEY=sk-...
   ```
   MemoryPalace still uses Ollama for its embeddings, but those are tiny (~150ms per call after warmup).

2. **Pull a smaller tool-capable model** for Ollama:
   ```bash
   docker compose exec ollama ollama pull qwen3:1.7b   # ~1GB, decent quality
   # or, even smaller:
   docker compose exec ollama ollama pull qwen3:0.6b   # ~500MB, very lean
   ```
   Update `OLLAMA_MODEL` and `MEMORY_PALACE_LLM_MODEL` in `.env`, then `docker compose up -d backend` to reload.

3. **Run Ollama natively on the host** (Mac/Linux) so it can use the GPU:
   ```bash
   brew install ollama && ollama serve   # macOS
   # or apt-style on Linux
   ```
   Then in `.env` set `OLLAMA_HOST=http://host.docker.internal:11434` and remove the `ollama` service from `docker-compose.yml`.

4. **Use `SKIP_CHAT=1 make smoke`** to confirm the rest of the wiring while you sort the LLM out.

If `KB_BACKEND=memorypalace` and you haven't pulled `nomic-embed-text` yet, every ingest call will also hang. Run `make pull-models` first.

### Apple Silicon: which Ollama model?

The defaults (`nomic-embed-text` + `qwen3:1.7b`) run comfortably on M1/M2/M3 with 8–16 GB. If you have ≥ 24 GB and want better answers:

```bash
docker compose exec ollama ollama pull qwen3:8b
# Then in .env:
OLLAMA_MODEL=qwen3:8b
MEMORY_PALACE_LLM_MODEL=qwen3:8b
```

### SSE responses appear "all at once"

You are likely viewing the response through a proxy that buffers. Use `curl --no-buffer` and ensure no nginx / Cloudflare in between.

### "memory_palace not installed" warnings on container startup

The backend Dockerfile installs MemoryPalace from `git+https://github.com/jeffpierce/memory-palace.git@main`. Network hiccups during build can fail this step (the Dockerfile is tolerant and continues so you still get a working image). If you see the warning at runtime, run `make rebuild` on a healthy network. As a fallback, the backend gracefully falls back to `KB_BACKEND=fake` if the package is missing.

### "permission denied" writing to `backend/data/`

```bash
mkdir -p backend/data/documents
chmod -R u+rw backend/data/
```

### Wipe everything and start fresh

```bash
make clean         # removes containers + volumes (postgres, ollama, checkpointer)
make clean-data    # removes local documents and checkpointer file
make up
make pull-models
```

---

## Repository layout

```
construction-analyzer/
├── README.md                       (this file)
├── docker-compose.yml              4 services + named volumes + healthchecks
├── Makefile                        Mac + Linux compatible
├── .env.example
├── .gitignore                      includes backend/data/, *.pdf, *.docx, ...
├── .cursorignore                   identical scope as .gitignore
├── scripts/
│   └── smoke.sh                    bash, no GNU-isms — runs on Mac and Linux
├── backend/                        see backend/README.md
│   ├── Dockerfile                  python:3.12-slim + memory_palace via pip
│   ├── pyproject.toml
│   ├── app/                        FastAPI + LangGraph + KB interface
│   ├── tests/                      unit + integration + gated e2e
│   └── data/                       GITIGNORED runtime state
└── frontend/                       see frontend/README.md
    ├── Dockerfile                  multi-stage Node 20 alpine, output: standalone
    ├── package.json
    ├── src/                        Next.js App Router
    └── tests/                      Vitest + RTL + MSW + Playwright
```

## Architecture choices

- **MemoryPalace as a library, not an MCP sidecar.** Single backend container, faster startup, cleaner debugging. The `KnowledgeBase` interface in [backend/app/kb/base.py](backend/app/kb/base.py) abstracts the implementation, so swapping to an external MCP server is a one-file change.
- **Pluggable LLM provider.** [backend/app/agent/llm.py](backend/app/agent/llm.py) selects OpenAI or Ollama from `LLM_PROVIDER`. The agent code never imports a concrete provider.
- **`AsyncSqliteSaver` checkpointer.** [backend/app/agent/checkpointer.py](backend/app/agent/checkpointer.py) persists thread state across backend restarts. The frontend's `localStorage` thread id and the backend's checkpointer together guarantee history rehydrates after a reload.
- **All-fake test mode.** Every test runs against `FakeKB` + `ScriptedChatModel` + `AsyncSqliteSaver(":memory:")`. No network, no Postgres, no Ollama. The MemoryPalace integration test runs only when those services are actually present.
- **Health vs readiness split.** `/health` never depends on external services and is what container orchestrators poll. `/ready` actively probes Postgres + Ollama + KB and is what the frontend connection badge surfaces.

## License

MIT.
