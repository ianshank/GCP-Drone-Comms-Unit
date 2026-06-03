# Pelican 1400 / Jetson Orin Nano Super GCS — Printed Parts

Generated from the reviewed parts list. The geometry here **applies the peer-review
fixes**, so it differs from the original document in a few deliberate ways (below).

Regenerate any time with `generate_parts.py` after editing the parameter block.

---

## ⚠️ Read before printing Part 2

**The Jetson case dimensions are an UNVERIFIED estimate.** The crussella0129 repo
publishes no outer dimensions and ships STEP files, so `CASE_L/W/H = 118 × 97 × 46 mm`
is a guess (a fan-duct case is likely *taller* than 46 mm). Open the STEP in Fusion or
your slicer, read the bounding box, edit the three numbers at the top of
`generate_parts.py`, and re-run before committing the tray to filament.

**The tray no longer fits a "61 mm right column."** The original spec put a ~97 mm-wide
case into a 61 mm column — geometrically impossible. This tray is sized to the case
(~127 × 106 mm). Reconcile that against your actual Pelican 1400 internal layout; the
case footprint, not an arbitrary column, drives where it can sit.

**Thermal:** the crussella0129 case is *actively cooled* (fan duct + plenum exhausting
downward). This tray has an **open floor + perimeter rest ledge** so it can't cap that
exhaust, plus vented walls — but a sealed, foam-lined Pelican still recirculates hot air.
Plan to run the Jetson **lid-open**, not sealed.

---

## Files & material map

| STL | Part | Material | Qty | Notes |
|---|---|---|---|---|
| part1_riser_shell_LEFT/RIGHT | Keyboard riser | PETG | 1 set | Split halves; 3 mm ledge captures keyboard |
| part2_seating_tray | Jetson tray | PETG | 1 | Open floor; size to **measured** case |
| part3_display_bracket_LEFT/RIGHT | Lid display bracket | PETG | 1 set | Through-window, HDMI/USB notches, 4× M3 corners |
| part4_hinge_cable_guide_half | Hinge guide | **TPU 95A** | 4 | One half; 2 guides × 2 halves |
| part5_lr900_clip | LR900 clip | PETG/TPU | 1 | |
| part6_rm_pocket_cradle | RM Pocket cradle | PETG | 1 | Gimbal + antenna clearances |
| part7_power_bank_cradle | Power bank cradle | PETG | 1 | USB-C slot + thumb cutout |
| part8_usb_strain_relief_clip | USB clip | PETG/TPU | 4 | M2 mount |

**The Jetson case itself is NOT included here** — print it from the crussella0129 STEP
files in **ABS or PA-CF** (the author strongly recommends high-temp filament; PETG is
not suitable for that part), with ruthex M3 inserts in the *top half only*.

## Print settings

- Brackets/cradles (PETG): 3 walls, 15–20% gyroid, 0.2 mm. Tray and bracket print flat.
- TPU parts: 0.2 mm, slow, 3 walls, no support.
- All parts fit the Bambu A1 256 mm bed. Riser and bracket are pre-split.

## Joinery on split parts

Split faces have registration boss + a 3 mm dowel-pin hole. Insert a 3 mm rod (or
filament offcut), bond (PETG: CA or epoxy), or drill the boss out to M3 if you prefer
bolted halves. Alignment is built in either way.

## Still to verify before final fit

1. Measure the real case bounding box → update parameters.
2. Confirm where the case exhaust actually exits (keep tray center clear of it).
3. Pick the case version (V1.6 / V2.0 sleek / V2.0 GPIO / V2.1) — external envelope
   and any I/O passthroughs depend on it.
4. Validate display, LR900, RM Pocket, and power-bank body dimensions against your
   exact units; the cradle pockets assume the sizes in the parts list.
