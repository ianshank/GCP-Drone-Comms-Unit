# Hardware Asset Agent Guide

This guide applies under `hardware`. Also follow the root [../AGENTS.md](../AGENTS.md).

## Scope

- [gcs-stls](gcs-stls) contains Pelican 1400 GCS parts and generation code.
- [usernode-stls](usernode-stls) contains user-node enclosure assets.
- [vcase](vcase) contains the Jetson Orin Nano vertical case assets.

## Traps

- **Three assets are duplicated verbatim in `ops/pi5-node/`** and must move together:
  `pi5_node_base.stl`, `pi5_node_lid.stl`, `pi5_node_enclosure.png`. They are
  byte-identical copies, not a build output of one another, so regenerating here and
  stopping leaves the ops copy silently stale.
- Binary assets here are **regenerated, never edited**. A text-tool edit to an STL or
  PNG produces a file that still parses far enough to look committed and prints wrong.

## Rules

- Do not hand-edit binary STL, PNG, or ZIP files with text tools — why: they survive a
  text edit well enough to commit and fail only at print time — advisory: no checker
  inspects binary content; `check-added-large-files` bounds size only.
- Prefer changing generator scripts and README dimensions, then regenerate assets —
  why: the script is the reviewable artifact; a regenerated STL diff is unreadable.
- Keep generated filenames stable unless the physical part identity changes — why:
  the name is how the ops copy and the README dimension table are matched up.
- When touching CAD-generation scripts, document required dependencies and the
  regeneration command — why: the toolchain is not installed in CI, so the next
  person cannot rediscover it by running anything.
- Treat archived snapshots as historical records; do not update them during normal
  feature work — why: they record what shipped, so editing one destroys the record it
  exists to keep.

## Verification

- Confirm generated assets exist after regeneration.
- If geometry cannot be regenerated on this host, say so and keep the code/doc
  change reviewable.
