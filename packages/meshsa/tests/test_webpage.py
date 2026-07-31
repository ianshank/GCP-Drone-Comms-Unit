"""Tests for meshsa._webpage — the SRI-pinned MapLibre tags and safe-literal helper
shared by meshsa.ui._html and meshsa.scout.station._html (code-hygiene-modularity T-1.2).
"""

from __future__ import annotations

from meshsa._webpage import MAPLIBRE_CSS_TAG, MAPLIBRE_JS_TAG, MAPLIBRE_VERSION, js_literal


def test_maplibre_tags_pin_the_exact_version_with_integrity() -> None:
    for tag in (MAPLIBRE_CSS_TAG, MAPLIBRE_JS_TAG):
        assert f"maplibre-gl@{MAPLIBRE_VERSION}/" in tag  # exact version, not a floating major
        assert 'integrity="sha384-' in tag
        assert 'crossorigin="anonymous"' in tag


def test_maplibre_version_is_not_a_floating_major() -> None:
    # A bare major (e.g. "4") would let the CDN silently swap the served bytes without an
    # integrity mismatch catching it — the exact gap this module closes.
    assert MAPLIBRE_VERSION.count(".") >= 1


def test_js_literal_escapes_script_close() -> None:
    literal = js_literal("</script><script>alert(1)</script>")
    assert "</script>" not in literal
    assert "\\u003c/script\\u003e" in literal


def test_js_literal_decodes_to_the_original_value() -> None:
    import json

    # The \uXXXX escapes are valid JSON, so json.loads recovers the exact original value —
    # the escaping changes the JS-source-safe encoding, not the decoded value.
    payload = {"a": 1, "b": [True, None, "<x>&"]}
    assert json.loads(js_literal(payload)) == payload


def test_js_literal_plain_values_unchanged() -> None:
    assert js_literal(None) == "null"
    assert js_literal(["tracks", "chat"]) == '["tracks", "chat"]'
