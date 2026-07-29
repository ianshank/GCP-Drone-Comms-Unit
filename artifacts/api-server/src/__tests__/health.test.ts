/**
 * Tests for GET /api/healthz
 *
 * Covers:
 *   - Happy path: 200 response with correct body shape
 *   - Response schema matches HealthCheckResponse Zod schema
 *   - Content-Type is application/json
 *   - Method restriction: POST /api/healthz → 404 or 405
 *
 * Uses supertest against the Express app directly (no live network port).
 * The pino-http logger is suppressed in tests via LOG_LEVEL=silent.
 */

import supertest from "supertest";
import { describe, it, expect } from "vitest";

import app from "../app.js";

// Silence pino output during tests
process.env["LOG_LEVEL"] = "silent";

const request = supertest(app);

describe("GET /api/healthz", () => {
  it("returns HTTP 200", async () => {
    const res = await request.get("/api/healthz");
    expect(res.status).toBe(200);
  });

  it("responds with Content-Type application/json", async () => {
    const res = await request.get("/api/healthz");
    expect(res.headers["content-type"]).toMatch(/application\/json/);
  });

  it("body has status: ok", async () => {
    const res = await request.get("/api/healthz");
    expect(res.body).toEqual({ status: "ok" });
  });

  it("body shape matches HealthCheckResponse Zod schema", async () => {
    const { HealthCheckResponse } = await import("@workspace/api-zod");
    const res = await request.get("/api/healthz");
    // Parse will throw if the shape is wrong — Zod validates for us
    const parsed = HealthCheckResponse.safeParse(res.body);
    expect(parsed.success).toBe(true);
    if (parsed.success) {
      expect(parsed.data.status).toBe("ok");
    }
  });

  it("returns consistent response on repeated calls", async () => {
    const [res1, res2, res3] = await Promise.all([
      request.get("/api/healthz"),
      request.get("/api/healthz"),
      request.get("/api/healthz"),
    ]);
    expect(res1.body).toEqual(res2.body);
    expect(res2.body).toEqual(res3.body);
  });
});

describe("GET /api/healthz — routing edge cases", () => {
  it("POST /api/healthz returns 404 (route not defined for POST)", async () => {
    const res = await request.post("/api/healthz");
    // Express returns 404 for undefined routes, not 405
    expect(res.status).toBeGreaterThanOrEqual(400);
  });

  it("GET /api/healthz/ (trailing slash) returns 200 or 301", async () => {
    // Express 5 handles trailing slashes strictly — either redirect or same response
    const res = await request.get("/api/healthz/");
    expect([200, 301, 308]).toContain(res.status);
  });

  it("unknown route returns 404", async () => {
    const res = await request.get("/api/unknown-endpoint-xyz");
    expect(res.status).toBe(404);
  });

  it("/healthz without /api prefix returns 404", async () => {
    // Routes are mounted under /api — bare /healthz must not leak
    const res = await request.get("/healthz");
    expect(res.status).toBe(404);
  });
});

describe("GET /api/healthz — response headers", () => {
  it("does not expose X-Powered-By: Express (information disclosure)", async () => {
    const res = await request.get("/api/healthz");
    // Express disables this by default in Express 5 or via app.disable("x-powered-by")
    // We assert it is absent as a security check
    expect(res.headers["x-powered-by"]).toBeUndefined();
  });
});
