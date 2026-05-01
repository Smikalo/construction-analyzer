# Frontend

Next.js 15 (App Router) + TypeScript + Tailwind + Framer Motion + Zustand.
An immersive ChatGPT-style UI for the construction-analyzer backend.

## Layout

```
src/
  app/
    layout.tsx, page.tsx, globals.css
    api/health/route.ts
  components/
    ChatShell.tsx        full app shell
    Composer.tsx         message input
    Message.tsx          single message bubble
    MessageList.tsx
    ConnectionBadge.tsx  polls /health every 5s
    ThreadList.tsx       sidebar of recent threads
    TypingIndicator.tsx
  lib/
    api.ts               REST + SSE client
    store.ts             Zustand store with localStorage thread persistence
    animations.ts
  types/
tests/
  setup.ts
  unit/                  Vitest + RTL + MSW
  e2e/                   Playwright vs the running compose stack
```

## Run locally without Docker

```bash
npm install
cp .env.example .env.local
npm run dev
```

The frontend expects the backend on `NEXT_PUBLIC_BACKEND_URL`
(default `http://localhost:8000`).

## Test

```bash
npm test                # unit
npm run e2e:install     # one-time: download Chromium for Playwright
npm run e2e             # against a running stack on :3000 + :8000
```
