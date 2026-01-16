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
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │  nginx (Static) │
                        │  Images/SVG     │
                        └─────────────────┘
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
| Static Files | nginx |

## Documentation

- [Backend Documentation](backend/README.md) - FastAPI, database models, background tasks, API reference
- [Frontend Documentation](frontend/README.md) - React app, components, hooks, state management

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
   - Static Files: http://localhost:8081/static/

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

## Real-time Updates

The app uses the **Ping-to-Refetch** pattern for real-time updates:

1. Backend worker processes an order
2. Worker publishes lightweight ping to Mercure
3. Frontend receives ping via SSE (EventSource)
4. Frontend invalidates TanStack Query cache
5. TanStack Query refetches fresh data from API

### Event Types

| Event Type | Purpose | Trigger |
|------------|---------|---------|
| `list_update` | Refetch order list | New order created |
| `order_update` | Refetch full order | Structural change (COMPLETED, ERROR, new version) |
| `image_status` | Refetch single image | Status-only change during processing |

The `image_status` events enable efficient updates during processing, fetching only ~1KB per status change instead of the full order payload.

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
