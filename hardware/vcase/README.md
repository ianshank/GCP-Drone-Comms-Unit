# Vertical Jetson Orin Nano Super Case — purpose-built for the Pelican 1400 GCS

Created (not sourced) because no existing case is edge-standing or sized for the
70 mm strip left beside the keyboard. This one is.

## Why vertical
The dev kit board is **100 × 79 mm** (NVIDIA: 100 × 79 × 21 mm overall). Laid flat,
any case is ≥ ~83 mm on its short edge — wider than the 70 mm side strip and 65 mm
back strip, so no flat case fits beside the full keyboard. Standing the board on its
100 mm edge drops the across-strip dimension to the stack thickness instead.

## Envelope & fit
| | mm | constraint | result |
|---|---|---|---|
| Length (X) | 107 | along 225 mm strip | OK |
| Thickness (Y) | 49 | < 70 mm side strip | OK (21 mm margin) |
| Height (Z) | 86 | < 102 mm bottom depth | OK (16 mm margin) |

## Files
- `vcase_front_fan.stl` — fan-intake grille face + top/bottom vent slots
- `vcase_back_standoffs.stl` — M2.5 carrier standoff bosses + NVMe-side wall

Two shells split on the PCB plane; 4 corner posts join with M3 (insert one shell,
bolt from the other). Board sits on 4 standoffs per NVIDIA's design guide
(M2.5 standoffs, M2.5 × 3.7 mm screws).

## Print
- **ABS / PA-CF / PC** (high-temp — same reasoning as the crussella0129 case). Not PETG.
- 3 walls, ~15% gyroid, 0.2 mm. Each shell ~107 × 86 mm — fits the A1 easily.
- Print shells open-face-up; vents bridge fine, no support needed.

## ⚠️ Verify before final print
1. **Standoff pattern** is placed on an approximate 92 × 71 mm rectangle. Confirm
   against the carrier mechanical drawing (or the NVIDIA STEP) and nudge the four
   bosses to the real hole centers.
2. **I/O window** is a single generous opening on the +X end. Match it to whichever
   board edge carries your port cluster (USB / DP / RJ45 / DC jack); rotate the board
   in the case if the ports are on a different edge.
3. **Cooling orientation.** Vertical mounting changes convection vs. the horizontal
   plenum design. Mount so the fan intake (grille face) is unobstructed and the top
   slots are the exhaust (heat rises). Don't seat it fan-down in the tray.
4. Re-confirm the stack thickness (44 mm cavity) against your actual heatsink/fan; if
   you run a taller cooler, increase `cavY` and re-check the 70 mm strip.
