# Backend

FastAPI backend for Fotomalovánky Admin.

## Project Structure

```
backend/
├── app/
│   ├── api/v1/              # API endpoints
│   │   ├── health.py        # Health check endpoint
│   │   ├── orders.py        # Order management endpoints
│   │   └── webhooks.py      # Shopify webhook handlers
│   ├── graphql/queries/     # Shopify GraphQL queries
│   ├── models/              # SQLModel database models
│   │   ├── coloring.py      # ColoringVersion, SvgVersion
│   │   ├── enums.py         # Status enums
│   │   └── order.py         # Order, LineItem, Image
│   ├── services/            # Business logic
│   │   ├── mercure.py       # Mercure SSE publishing
│   │   ├── runpod.py        # RunPod API client
│   │   ├── shopify.py       # Shopify API client
│   │   ├── shopify_client/  # Generated GraphQL client
│   │   └── vectorizer.py    # Vectorizer.ai client
│   ├── tasks/               # Dramatiq background tasks
│   │   ├── image_download.py
│   │   ├── order_ingestion.py
│   │   └── process/
│   │       ├── generate_coloring.py
│   │       └── vectorize_image.py
│   ├── utils/               # Utility functions
│   ├── config.py            # Pydantic settings
│   ├── db.py                # Database session management
│   └── main.py              # FastAPI app
├── migrations/              # Alembic migrations
└── pyproject.toml           # Dependencies
```

## Database Models

### Order

Main order entity from Shopify.

| Field | Type | Description |
|-------|------|-------------|
| `shopify_id` | int | Shopify order ID |
| `shopify_order_number` | str | Display number (e.g., "#1270") |
| `status` | OrderStatus | Processing status |
| `customer_name` | str | Customer name |
| `customer_email` | str | Customer email |

### ColoringVersion

Generated coloring book version for an image.

| Field | Type | Description |
|-------|------|-------------|
| `image_id` | int | Parent image |
| `version` | int | Version number |
| `file_path` | str | Local storage path |
| `status` | ColoringProcessingStatus | Processing status |
| `megapixels` | float | Generation setting |
| `steps` | int | Generation setting |

### SvgVersion

Vectorized SVG from a coloring version.

| Field | Type | Description |
|-------|------|-------------|
| `coloring_version_id` | int | Source coloring |
| `version` | int | Version number |
| `file_path` | str | Local storage path |
| `status` | SvgProcessingStatus | Processing status |
| `shape_stacking` | str | Vectorizer setting |
| `group_by` | str | Vectorizer setting |

## Processing Status Enums

### ColoringProcessingStatus

Status flow for coloring generation (RunPod):

| Status | Czech Label | Description |
|--------|-------------|-------------|
| `pending` | Čeká na odeslání | Not yet queued |
| `queued` | Čeká ve frontě | In Dramatiq queue |
| `processing` | Zpracovává se... | Dramatiq task started |
| `runpod_submitting` | Runpod: odesílání na server | Submitting to RunPod |
| `runpod_submitted` | Runpod: úloha přijata | RunPod accepted job |
| `runpod_queued` | Runpod: čeká ve frontě | RunPod: IN_QUEUE |
| `runpod_processing` | Runpod: Probíhá zpracování | RunPod: IN_PROGRESS |
| `completed` | Dokončeno | Successfully completed |
| `error` | Chyba | Processing failed |

### SvgProcessingStatus

Status flow for SVG vectorization (Vectorizer.ai):

| Status | Czech Label | Description |
|--------|-------------|-------------|
| `pending` | Čeká na odeslání | Not yet queued |
| `queued` | Čeká ve frontě | In Dramatiq queue |
| `processing` | Zpracovává se... | Dramatiq task started |
| `vectorizer_processing` | Vectorizer: Probíhá zpracování | HTTP request in progress |
| `completed` | Dokončeno | Successfully completed |
| `error` | Chyba | Processing failed |

## API Endpoints

### Orders

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/orders` | List orders |
| GET | `/api/v1/orders/{order_number}` | Get order detail |
| GET | `/api/v1/orders/{order_number}/images/{image_id}` | Get single image |
| POST | `/api/v1/orders/{order_number}/sync` | Re-sync from Shopify |
| POST | `/api/v1/orders/fetch-from-shopify` | Import recent orders |

### Coloring Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/orders/{order_number}/generate-coloring` | Generate for all images |
| POST | `/api/v1/images/{image_id}/generate-coloring` | Generate for single image |
| GET | `/api/v1/images/{image_id}/coloring-versions` | List versions |
| POST | `/api/v1/coloring-versions/{version_id}/retry` | Retry failed |

### SVG Generation

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/orders/{order_number}/generate-svg` | Generate for all images |
| POST | `/api/v1/images/{image_id}/generate-svg` | Generate for single image |
| GET | `/api/v1/images/{image_id}/svg-versions` | List versions |
| POST | `/api/v1/svg-versions/{version_id}/retry` | Retry failed |

### Version Selection

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/images/{image_id}/select-coloring/{version_id}` | Select coloring |
| POST | `/api/v1/images/{image_id}/select-svg/{version_id}` | Select SVG |

## Mercure Events

Events published to the Mercure hub for real-time updates:

### `list_update`

Sent when order list changes. Triggers full list refetch.

```json
{"type": "list_update"}
```

### `order_update`

Sent for structural changes (COMPLETED, ERROR, new version).

```json
{"type": "order_update", "order_number": "1270"}
```

### `image_status`

Sent during processing for granular status updates.

```json
{
  "type": "image_status",
  "order_number": "1270",
  "image_id": 123,
  "status_type": "coloring",
  "version_id": 456,
  "status": "runpod_processing"
}
```

## Available Scripts

```bash
# Run development server
uv run uvicorn app.main:app --reload

# Run Dramatiq worker
uv run dramatiq app.tasks --watch app

# Regenerate Shopify GraphQL client
uv run codegen

# Run database migrations
uv run alembic upgrade head

# Create new migration
uv run alembic revision --autogenerate -m "description"

# Run linter
uv run ruff check app/

# Run type checker
uv run mypy app/
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | Required |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `MERCURE_URL` | Mercure hub URL | Required |
| `MERCURE_PUBLISHER_JWT_KEY` | JWT key for publishing | Required |
| `SHOPIFY_STORE_URL` | Shopify store URL | Required |
| `SHOPIFY_ACCESS_TOKEN` | Shopify API token | Required |
| `SHOPIFY_WEBHOOK_SECRET` | Webhook HMAC secret | Required |
| `STORAGE_PATH` | Local file storage path | `/data/images` |
| `STATIC_URL` | Public URL for static files | `http://localhost:8081/static` |
| `RUNPOD_API_KEY` | RunPod API key | Required |
| `RUNPOD_ENDPOINT_ID` | RunPod endpoint ID | Required |
| `VECTORIZER_API_KEY` | Vectorizer.ai API key | Required |
| `VECTORIZER_API_SECRET` | Vectorizer.ai API secret | Required |

## File Storage Layout

Files are stored using the following directory structure:

```
/data/images/{order_id}/{line_item_id}/
├── image_{position}.jpg           # Source image
├── coloring/
│   ├── v1/
│   │   └── image_{position}.png   # Coloring version 1
│   └── v2/
│       └── image_{position}.png   # Coloring version 2
└── svg/
    └── v1/
        └── image_{position}.svg   # SVG version 1
```

URLs are generated by nginx at `http://localhost:8081/static/images/...`
