# Hardware Asset Agent Guide

This guide applies under `hardware`. Also follow the root [../AGENTS.md](../AGENTS.md).

## Scope

- [gcs-stls](gcs-stls) contains Pelican 1400 GCS parts and generation code.
- [usernode-stls](usernode-stls) contains user-node enclosure assets.
- [vcase](vcase) contains the Jetson Orin Nano vertical case assets.

## Rules

- Do not hand-edit binary STL, PNG, or ZIP files with text tools.
- Prefer changing generator scripts and README dimensions, then regenerate assets.
- Keep generated filenames stable unless the physical part identity changes.
- When touching CAD-generation scripts, document required dependencies and the
  regeneration command.
- Treat archived snapshots as historical records; do not update them during normal
  feature work.

## Verification

- Confirm generated assets exist after regeneration.
- If geometry cannot be regenerated on this host, say so and keep the code/doc
  change reviewable.