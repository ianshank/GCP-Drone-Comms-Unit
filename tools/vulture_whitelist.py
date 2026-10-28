# ruff: noqa
# mypy: ignore-errors
"""vulture whitelist — names vulture reports as unused that are live by construction.

Read by the advisory dead-code step in the CI governance job
(docs/CODE_QUALITY_TECH_DEBT_PLAN.md P1-2): ``vulture <paths> tools/vulture_whitelist.py``
treats every name referenced here as used. One entry per line, each with the reason it
is a false positive; a name with no reason is itself a finding for a reviewer.

Regenerate candidates with ``vulture <paths> --min-confidence 80 --make-whitelist``; never
paste the output in wholesale — each line is a claim that the code is live.
"""

# packages/meshsa/src/meshsa/transports/meshtastic_radio.py — the ``interface`` parameter
# of the ``meshtastic.receive`` pypubsub callback. pypubsub matches callback arguments by
# name, so the parameter must exist even though the handler never reads it.
interface
