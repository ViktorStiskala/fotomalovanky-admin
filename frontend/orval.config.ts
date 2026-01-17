import { defineConfig } from "orval";

// Support both local development and Docker environments
const apiUrl =
    process.env.ORVAL_API_URL || "http://localhost:8000/openapi.json";

export default defineConfig({
    api: {
        input: {
            target: apiUrl,
        },
        output: {
            target: "./src/api/generated/endpoints.ts",
            schemas: "./src/api/generated/schemas",
            client: "react-query",
            mode: "tags-split", // Split by API tags (orders, images, coloring, svg, events)
            override: {
                mutator: {
                    path: "./src/api/fetcher.ts",
                    name: "customFetch",
                },
                query: {
                    useQuery: true,
                    useMutation: true,
                    signal: true,
                },
            },
        },
    },
});
