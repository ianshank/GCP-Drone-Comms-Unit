// eslint.config.js — ESLint v9 flat config
// Docs: https://eslint.org/docs/latest/use/configure/configuration-files
import js from "@eslint/js";
import tsParser from "@typescript-eslint/parser";
import tsPlugin from "@typescript-eslint/eslint-plugin";
import importPlugin from "eslint-plugin-import";
import globals from "globals";

/** @type {import("eslint").Linter.Config[]} */
export default [
  // ── Ignored paths ──────────────────────────────────────────────────────────
  {
    ignores: [
      "**/node_modules/**",
      "**/dist/**",
      "**/build/**",
      "**/.tsbuildinfo",
      "**/coverage/**",
      "**/.vitest-cache/**",
      "deliverables/**",          // Python deliverables — not linted by ESLint
      "scripts/hooks/**",         // Bash scripts
      "*.config.js",              // Vite / build configs (self-referential)
      "*.config.mjs",
      "artifacts/api-server/build.mjs",
    ],
  },

  // ── Base JS rules ─────────────────────────────────────────────────────────
  js.configs.recommended,

  // ── TypeScript source files ───────────────────────────────────────────────
  {
    files: ["**/*.ts", "**/*.tsx"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        // "true" means: find the nearest tsconfig.json for each linted file.
        // This is necessary in a monorepo where each package has its own tsconfig.
        project: true,
        tsconfigRootDir: import.meta.dirname,
        ecmaVersion: "latest",
        sourceType: "module",
      },
      globals: {
        ...globals.node,
        ...globals.es2022,
      },
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      "import": importPlugin,
    },
    rules: {
      // ── TypeScript strict ────────────────────────────────────────────────
      ...tsPlugin.configs["strict-type-checked"].rules,

      // ── No console — use structured logger (pino) ────────────────────────
      "no-console": "error",

      // ── No hardcoded env access via dot notation ─────────────────────────
      // Enforce process.env["KEY"] not process.env.KEY so keys are explicit
      // string literals and tooling can catch typos.
      "no-restricted-syntax": [
        "error",
        {
          selector: "MemberExpression[object.object.name='process'][object.property.name='env'][computed=false]",
          message: "Access env vars as process.env[\"KEY\"] not process.env.KEY",
        },
      ],

      // ── Imports ──────────────────────────────────────────────────────────
      "import/order": [
        "error",
        {
          groups: [
            "builtin",
            "external",
            "internal",
            "parent",
            "sibling",
            "index",
            "type",
          ],
          "newlines-between": "always",
          alphabetize: { order: "asc", caseInsensitive: true },
        },
      ],
      "import/no-duplicates": "error",
      "import/no-cycle": "error",

      // ── TypeScript specific ──────────────────────────────────────────────
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/explicit-function-return-type": [
        "error",
        { allowExpressions: true, allowTypedFunctionExpressions: true },
      ],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/consistent-type-imports": [
        "error",
        { prefer: "type-imports", fixStyle: "inline-type-imports" },
      ],
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/await-thenable": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/require-await": "error",

      // ── Relaxed in this codebase ─────────────────────────────────────────
      // Allow empty interfaces for extension patterns
      "@typescript-eslint/no-empty-interface": "off",
      // Router files often have many route handlers
      "@typescript-eslint/no-unsafe-call": "warn",
    },
  },

  // ── Test files (relaxed rules) ────────────────────────────────────────────
  {
    files: [
      "**/__tests__/**/*.ts",
      "**/*.test.ts",
      "**/*.spec.ts",
      "**/__tests__/**/*.tsx",
    ],
    rules: {
      // Tests may use any for mocks
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unsafe-call": "off",
      "@typescript-eslint/no-unsafe-member-access": "off",
      "@typescript-eslint/no-unsafe-assignment": "off",
      // Return types not required in test callbacks
      "@typescript-eslint/explicit-function-return-type": "off",
      // Void assertions in tests
      "@typescript-eslint/no-confusing-void-expression": "off",
    },
  },

  // ── Vite config files ─────────────────────────────────────────────────────
  {
    files: ["**/vite.config.ts", "**/vitest.config.ts"],
    languageOptions: {
      globals: { ...globals.node },
    },
    rules: {
      "@typescript-eslint/explicit-function-return-type": "off",
    },
  },
];
