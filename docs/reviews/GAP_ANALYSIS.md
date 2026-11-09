# Testing Gap Analysis — meshsa framework

Date: 2026-06-20
Baseline State: 101 tests, 100% line coverage, 100% branch coverage.

Although line and branch coverage is at 100%, coverage does not guarantee robustness across all testing disciplines. The project's global rules require 80% test coverage with unit, integration, functional, e2e, user journey, security, and sanity tests. This document identifies the gaps to reach that standard.

## Category Assessment

| Test Category | Current Status | Identified Gaps | Remediation Plan |
|---|---|---|---|
| **Unit Tests** | High | Most components tested in isolation using fakes. | Maintain 100% unit coverage for the new `inference` module. |
| **Integration** | Medium | `test_bridge_e2e.py` bridges loopback codecs. | Add integration tests for `InferenceService` subscribing to `Router` and queueing tasks without blocking. |
| **Functional** | Low | Missing edge-case boundaries (cache eviction, inbox full). | Add `test_gap_fills.py` covering dedupe LRU exact boundaries and backpressure / queue full behavior. |
| **End-to-End (E2E)** | Low | No E2E test covers the entire bridge + external API pathway. | Add `test_inference_e2e.py` simulating radio inbound → inference analysis → radio outbound broadcast. |
| **User Journey** | Absent | No tests model the complete user interaction flow with the node. | Add a lifecycle user journey test: CLI config load → node start → simulated operations → graceful shutdown. |
| **Security** | Absent | No validation for sensitive configurations or malformed data. | Add tests for missing API keys, enforce HTTPS `base_url` for inference, and ensure API keys aren't leaked in logs. |
| **Sanity** | Absent | No checks for architectural/config constants consistency. | Add checks ensuring `SCHEMA_VERSION` matches documentation and registry imports are completely isolated. |
| **Property-Based** | Absent | Hardcoded data used for codec tests. | Add Hypothesis tests to fuzz `JsonCodec`, `CompactCodec`, and `CotCodec` roundtrips to ensure no exceptions on edge-case data. |

## Conclusion

To meet the 80% rule across all categories, we need to introduce ~40 new tests across 3 new files (`test_inference.py`, `test_inference_e2e.py`, `test_gap_fills.py`). The line coverage is a sufficient proxy for unit tests, but the remaining categories require explicit structural representation.
