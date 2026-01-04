# Fotomalovánky Admin

Internal admin dashboard for **Fotomalovanky.cz** (Shopify) order processing.

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   React App     │────▶│    FastAPI      │────▶│   PostgreSQL    │
│   (Vite + TS)   │     │    Backend      │     │   Database      │
└────────┬────────┘     └────────┬────────┘     └─────────────────┘
         │                       │
         │ SSE                   │ Enqueue
         ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Mercure Hub   │◀────│ Dramatiq Worker │────▶│   Shopify API   │
│   (Real-time)   │     │ (Background)    │     │   (GraphQL)     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + TypeScript + Vite |
| UI | Tailwind CSS + shadcn/ui |
| State | TanStack Query |
| Real-time | Mercure (SSE) |
| Backend | FastAPI (Python 3.14+) |
| ORM | SQLModel |
| Database | PostgreSQL |
| Task Queue | Dramatiq + Redis |
| HTTP Client | httpx |

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.14+ with `uv`
- Node.js 22+

### Development

1. Copy environment variables:

```bash
cp .env.example .env
# Edit .env with your Shopify credentials
```

2. Start all services with Docker Compose:

```bash
docker compose up -d
```

3. Access the application:
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:8000
   - API Docs: http://localhost:8000/docs
   - Mercure Hub: http://localhost:3000

### Local Development (without Docker)

**Backend:**

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

**Dramatiq Worker:**

```bash
cd backend
uv run dramatiq app.tasks --watch app
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

## Project Structure

```
├── backend/                 # FastAPI backend
│   ├── app/
│   │   ├── api/v1/         # API endpoints
│   │   ├── models/         # SQLModel database models
│   │   ├── services/       # Business logic (Shopify, Mercure, etc.)
│   │   ├── tasks.py        # Dramatiq background tasks
│   │   └── main.py         # FastAPI app
│   ├── migrations/         # Alembic migrations
│   └── pyproject.toml
│
├── frontend/               # React frontend
│   ├── src/
│   │   ├── components/     # React components
│   │   ├── hooks/          # Custom hooks (Mercure SSE)
│   │   ├── lib/            # API client, utilities
│   │   ├── pages/          # Page components
│   │   └── types/          # TypeScript types
│   └── package.json
│
└── docker-compose.yml      # Development orchestration
```

## Real-time Updates

The app uses the **Ping-to-Refetch** pattern for real-time updates:

1. Backend worker processes an order
2. Worker publishes lightweight ping to Mercure: `{"type": "order_update", "id": 123}`
3. Frontend receives ping via SSE (EventSource)
4. Frontend invalidates TanStack Query cache
5. TanStack Query refetches fresh data from API

This pattern keeps the API as the single source of truth and simplifies security.

## Order Status Flow

| Status | Description |
|--------|-------------|
| `pending` | Webhook received, waiting for processing |
| `downloading` | Downloading images from Shopify |
| `processing` | Images downloaded, processing |
| `ready_for_review` | Ready for admin review |
| `error` | Something failed (show Retry button) |

## License

Private - Fotomalovánky.cz
