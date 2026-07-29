// Root vitest workspace config — delegates to package-level configs.
// Run all tests:   pnpm -r run test
// Run one package: pnpm --filter @workspace/api-server run test
import { defineWorkspace } from "vitest/config";

export default defineWorkspace([
  "artifacts/api-server/vitest.config.ts",
  // Add more packages here as tests are introduced:
  // "lib/api-zod/vitest.config.ts",
  // "lib/db/vitest.config.ts",
]);
