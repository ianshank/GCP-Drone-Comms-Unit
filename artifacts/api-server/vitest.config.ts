import { defineConfig } from "vitest/config";
import path from "node:path";

process.env["LOG_LEVEL"] = process.env["LOG_LEVEL"] || "silent";

export default defineConfig({
  test: {
    // Use the Node.js environment (not jsdom) — this is a server-side package
    environment: "node",

    // Test file patterns
    include: ["src/**/__tests__/**/*.test.ts", "src/**/*.test.ts"],
    exclude: ["**/node_modules/**", "**/dist/**"],

    // Global test setup
    globals: false,    // use explicit imports from "vitest" — no magic globals

    // Coverage configuration
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "html", "lcov"],
      reportsDirectory: "coverage",
      include: ["src/**/*.ts"],
      exclude: [
        "src/**/__tests__/**",
        "src/**/*.test.ts",
        "src/**/index.ts",    // entry-point wiring — tested via integration
      ],
      thresholds: {
        lines: 80,
        functions: 80,
        branches: 75,
        statements: 80,
      },
      // Fail CI if coverage drops below threshold
      thresholdAutoUpdate: false,
    },

    // Resolve workspace packages (pnpm links)
    resolve: {
      alias: {
        "@workspace/api-zod": path.resolve(__dirname, "../../lib/api-zod/src"),
        "@workspace/db": path.resolve(__dirname, "../../lib/db/src"),
      },
    },

    // Timeout for integration tests hitting the app
    testTimeout: 10_000,
    hookTimeout: 10_000,

    // Reporter
    reporter: process.env["CI"] ? "verbose" : "default",
  },
});
