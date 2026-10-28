# requirements/

`ci-constraints.txt` is the CI lock (plan P1-6): the fully resolved, cross-platform pin set
for both packages' `[dev]` extras (plus meshsa `[inference]`), compiled once and applied
with `pip install -c` in the `test` and `perception` CI jobs. It never changes what a
package *requires* — those ranges stay in each `pyproject.toml` — only which version CI
installs, so an upstream release becomes a dependabot PR instead of a red build.

Regenerate (from the repo root; `uv` is the resolver, pip is still the installer in CI):

```bash
uv pip compile --universal -p 3.10 --extra dev --extra inference \
  packages/meshsa/pyproject.toml packages/jetson_yolo_gcs/pyproject.toml \
  -o requirements/ci-constraints.txt
```

The ruff/mypy lines here must agree with the pyproject pins; `tools/check_tool_pins.py`
does not read this file, so the `python-tooling` dependabot group carries it instead.

Dependabot bumps one line at a time without re-resolving, so a bump that moves a package
away from a co-pinned partner (`pydantic` without `pydantic-core`, `aiohttp` without
`aiosignal`) can make that PR's install fail with a resolution error. That is the PR being
honest, not the lock being wrong: regenerate with the command above and push the result.
Only the `test` and `perception` jobs are constrained; `nightly.yml` and `fts-e2e.yml`
install unconstrained on purpose, because their job is to catch optional-dependency drift.
