# Frontend

React frontend for Fotomalovánky Admin.

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   └── ui/              # shadcn/ui components
│   │       ├── button.tsx
│   │       └── dialog.tsx
│   ├── hooks/               # Custom React hooks
│   │   ├── useMercure.ts    # Mercure SSE subscription
│   │   ├── useOrderEvents.ts    # Order detail updates
│   │   └── useOrderListEvents.ts # Order list updates
│   ├── lib/                 # Utilities and API
│   │   ├── api.ts           # API client functions
│   │   ├── config.ts        # Environment configuration
│   │   ├── queryClient.ts   # TanStack Query client
│   │   └── utils.ts         # Utility functions
│   ├── pages/               # Page components
│   │   ├── OrderDetail.tsx  # Order detail view
│   │   └── OrderList.tsx    # Order list view
│   ├── types/               # TypeScript types
│   │   └── index.ts         # Type definitions and status displays
│   ├── App.tsx              # Main app with routing
│   ├── index.css            # Global styles
│   └── main.tsx             # Entry point
├── index.html
├── package.json
├── tailwind.config.js
├── tsconfig.json
└── vite.config.ts
```

## Key Components

### OrderList

Main page displaying all orders with pagination. Subscribes to `list_update` Mercure events for real-time updates.

### OrderDetail

Detailed order view with:
- Order information (customer, payment status, shipping)
- Line items with images
- Coloring/SVG generation controls
- Version switching and selection
- Real-time status updates via `image_status` events

### ImageCard

Individual image card with:
- Original image preview
- Coloring generation settings and button
- SVG generation settings and button
- Version tabs (Coloring/SVG)
- Status badges with real-time updates

## Custom Hooks

### useMercure

Low-level hook for Mercure SSE subscriptions.

```typescript
useMercure(topic: string, onMessage: (data: unknown) => void, enabled?: boolean)
```

### useOrderEvents

Subscribes to order-specific Mercure events. Handles both `order_update` (full refetch) and `image_status` (efficient single-image update).

```typescript
useOrderEvents(orderNumber: string)
```

### useOrderListEvents

Subscribes to order list events (`list_update`, `order_update`).

```typescript
useOrderListEvents()
```

## API Client

The `lib/api.ts` module provides typed API functions:

### Orders

```typescript
fetchOrders(skip?: number, limit?: number): Promise<OrderListResponse>
fetchOrder(orderNumber: string): Promise<OrderDetail>
fetchImage(orderNumber: string, imageId: number): Promise<OrderImage>
syncOrder(orderNumber: string): Promise<{status, message}>
fetchFromShopify(limit?: number): Promise<FetchFromShopifyResponse>
```

### Coloring Generation

```typescript
generateOrderColoring(orderNumber: string, settings?: ColoringSettings): Promise<GenerateColoringResponse>
generateImageColoring(imageId: number, settings?: ColoringSettings): Promise<ColoringVersion>
listColoringVersions(imageId: number): Promise<ColoringVersion[]>
retryColoringVersion(versionId: number): Promise<ColoringVersion>
```

### SVG Generation

```typescript
generateOrderSvg(orderNumber: string, settings?: SvgSettings): Promise<GenerateSvgResponse>
generateImageSvg(imageId: number, settings?: SvgSettings): Promise<SvgVersion>
listSvgVersions(imageId: number): Promise<SvgVersion[]>
retrySvgVersion(versionId: number): Promise<SvgVersion>
```

### Version Selection

```typescript
selectColoringVersion(imageId: number, versionId: number): Promise<{status, message}>
selectSvgVersion(imageId: number, versionId: number): Promise<{status, message}>
```

## TypeScript Types

### API Response Types

```typescript
interface OrderImage {
  id: number;
  position: number;
  url: string | null;  // Served by nginx
  downloaded_at: string | null;
  selected_version_ids: {
    coloring: number | null;
    svg: number | null;
  };
  versions: {
    coloring: ColoringVersion[];
    svg: SvgVersion[];
  };
}

interface ColoringVersion {
  id: number;
  version: number;
  url: string | null;
  status: ColoringProcessingStatus;
  options: {
    megapixels: number;
    steps: number;
  };
  created_at: string;
}

interface SvgVersion {
  id: number;
  version: number;
  url: string | null;
  status: SvgProcessingStatus;
  coloring_version_id: number;
  options: {
    shape_stacking: string;
    group_by: string;
  };
  created_at: string;
}
```

## Status Display Mappings

### COLORING_STATUS_DISPLAY

Czech labels for coloring processing statuses:

| Status | Label |
|--------|-------|
| `pending` | Čeká na odeslání |
| `queued` | Čeká ve frontě |
| `processing` | Zpracovává se... |
| `runpod_submitting` | Runpod: odesílání na server |
| `runpod_submitted` | Runpod: úloha přijata |
| `runpod_queued` | Runpod: čeká ve frontě |
| `runpod_processing` | Runpod: Probíhá zpracování |
| `completed` | Dokončeno |
| `error` | Chyba |

### SVG_STATUS_DISPLAY

Czech labels for SVG processing statuses:

| Status | Label |
|--------|-------|
| `pending` | Čeká na odeslání |
| `queued` | Čeká ve frontě |
| `processing` | Zpracovává se... |
| `vectorizer_processing` | Vectorizer: Probíhá zpracování |
| `completed` | Dokončeno |
| `error` | Chyba |

## Available Scripts

```bash
# Start development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Run linter
npm run lint

# Fix linter issues
npm run lint:fix

# Run type checker
npm run typecheck

# Format code
npm run format

# Check formatting
npm run format:check

# Run all checks
npm run check
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `VITE_API_URL` | Backend API base URL | `http://localhost:8000` |
| `VITE_MERCURE_URL` | Mercure hub URL | `http://localhost:3000/.well-known/mercure` |
| `VITE_SHOPIFY_STORE_HANDLE` | Shopify admin URL handle | - |
| `VITE_STATIC_URL` | Static files base URL | `http://localhost:8081/static` |
