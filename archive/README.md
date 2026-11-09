# Archive

Read-only history. Nothing here is a pnpm workspace member, is type-checked, linted or
tested, or is reachable from a console script. Edit nothing; if something is wanted back,
restore it to its original path in a deliberate PR.

| Entry | What it is | Retired |
| ----- | ---------- | ------- |
| `mockup-sandbox/` | The Replit-era React 19 / Vite 7 UI component preview (`@workspace/mockup-sandbox`, formerly `artifacts/mockup-sandbox`). Its all-interfaces Vite dev server is audit row #25 in `../docs/AUDIT_M2_AUTH.md`. | plan P3-4 / T-2.3b, 2026-11-09 |
| `api-client-react/` | The orval-generated React Query client (`@workspace/api-client-react`, formerly `lib/api-client-react`) and its hand-written `custom-fetch.ts` mutator; the sandbox was its only consumer. The spec it was generated from stays live at `../lib/api-spec/openapi.yaml`, with `lib/api-zod` as the one remaining target. | plan P3-4 / T-2.3b, 2026-11-09 |
| `*.zip` | Snapshots of the Python framework, the base-node service, the Pi 5 node kit and the 3D-print assets as they shipped. | earlier |
