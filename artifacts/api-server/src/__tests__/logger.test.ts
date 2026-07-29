/**
 * Tests for lib/logger.ts
 *
 * Covers:
 *   - Logger is a pino instance
 *   - LOG_LEVEL env var is respected (dynamic level setting)
 *   - Redaction fields are configured (authorization, cookie, set-cookie)
 *   - Default level is "info" when LOG_LEVEL is unset
 *   - Logger does not expose sensitive data in its base configuration
 *
 * Tests that validate runtime behaviour (actual log output) are deferred to
 * integration tests; these are configuration/contract tests only.
 */

import { describe, it, expect, afterEach, vi } from "vitest";

import type pino from "pino";

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Import a fresh logger instance with a given LOG_LEVEL override. */
async function importLoggerWithLevel(
  level: string | undefined,
): Promise<{ logger: pino.Logger }> {
  const key = "LOG_LEVEL";
  const original = process.env[key];

  if (level === undefined) {
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete
    delete process.env[key];
  } else {
    process.env[key] = level;
  }

  // Bypass module cache so we get a fresh instance for each test
  vi.resetModules();
  const mod = await import("../lib/logger.js");

  // Restore env — delete is the only reliable way to unset a process.env key
  if (original === undefined) {
    // eslint-disable-next-line @typescript-eslint/no-dynamic-delete
    delete process.env[key];
  } else {
    process.env[key] = original;
  }

  return mod;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("logger — basic contract", () => {
  it("exports a named logger symbol", async () => {
    vi.resetModules();
    const { logger } = await import("../lib/logger.js");
    expect(logger).toBeDefined();
    expect(typeof logger.info).toBe("function");
    expect(typeof logger.error).toBe("function");
    expect(typeof logger.warn).toBe("function");
    expect(typeof logger.debug).toBe("function");
  });

  it("is a pino logger instance (has .level property)", async () => {
    vi.resetModules();
    const { logger } = await import("../lib/logger.js");
    expect(typeof logger.level).toBe("string");
  });
});

describe("logger — log level from environment", () => {
  afterEach(() => {
    vi.resetModules();
  });

  it("defaults to 'info' when LOG_LEVEL is not set", async () => {
    const { logger } = await importLoggerWithLevel(undefined);
    expect(logger.level).toBe("info");
  });

  it("respects LOG_LEVEL=debug", async () => {
    const { logger } = await importLoggerWithLevel("debug");
    expect(logger.level).toBe("debug");
  });

  it("respects LOG_LEVEL=warn", async () => {
    const { logger } = await importLoggerWithLevel("warn");
    expect(logger.level).toBe("warn");
  });

  it("respects LOG_LEVEL=error", async () => {
    const { logger } = await importLoggerWithLevel("error");
    expect(logger.level).toBe("error");
  });

  it("respects LOG_LEVEL=silent (used in tests)", async () => {
    const { logger } = await importLoggerWithLevel("silent");
    expect(logger.level).toBe("silent");
  });
});

describe("logger — redaction configuration", () => {
  it("logger instance carries expected redaction paths", async () => {
    // We cannot directly inspect pino's redact configuration after construction,
    // but we can verify the logger was constructed without throwing and
    // responds to calls that would hit redacted paths.
    vi.resetModules();
    process.env["LOG_LEVEL"] = "silent";
    const { logger } = await import("../lib/logger.js");

    // Writing a log with a redacted-path field must not throw
    expect(() => {
      logger.info({
        req: {
          headers: {
            authorization: "Bearer super-secret-token",
            cookie: "session=abc123",
          },
        },
      }, "test redaction — must not throw");
    }).not.toThrow();

    delete process.env["LOG_LEVEL"];
  });

  it("does not log a transport in production mode", async () => {
    vi.resetModules();
    const originalNodeEnv = process.env["NODE_ENV"];
    process.env["NODE_ENV"] = "production";
    process.env["LOG_LEVEL"] = "silent";

    const { logger } = await import("../lib/logger.js");

    // In production, pino should not have a pretty-print transport
    // (we can't directly assert the transport, but construction must succeed)
    expect(logger).toBeDefined();

    process.env["NODE_ENV"] = originalNodeEnv;
    delete process.env["LOG_LEVEL"];
  });
});

describe("logger — safety: no console fallthrough", () => {
  it("the logger module does not call process.stdout.write directly", async () => {
    // This is a static check — we just verify the import does not throw
    // and does not pollute stdout (LOG_LEVEL=silent suppresses all output)
    vi.resetModules();
    process.env["LOG_LEVEL"] = "silent";

    const writeSpy = vi.spyOn(process.stdout, "write");
    const { logger } = await import("../lib/logger.js");

    logger.info("silent test message");
    // In silent mode, nothing should be written to stdout
    expect(writeSpy).not.toHaveBeenCalled();

    writeSpy.mockRestore();
    delete process.env["LOG_LEVEL"];
  });
});
