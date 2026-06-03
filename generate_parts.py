#!/usr/bin/env python3
"""
Pelican 1400 / Jetson Orin Nano Super GCS — printed parts generator.

Review fixes applied vs. the original parts list:
  * CASE_* dimensions are flagged UNVERIFIED and isolated here. The crussella0129
    repo publishes NO outer dimensions and ships STEP (not STL). Measure the STEP
    bounding box in Fusion / your slicer and update CASE_L/W/H, then re-run.
  * Part 2 (seating tray) is rebuilt: sized to the CASE footprint (not the
    contradictory 61 mm "right column"), with an OPEN floor + perimeter ledge so
    it cannot cap the case's downward plenum exhaust. Walls are vented.
  * Split parts use registration dowel bosses (3 mm pin + bond, or drill for M3).
"""

import numpy as np
import trimesh
from trimesh.creation import box as _box, cylinder as _cyl
import os, math

OUT = "/mnt/user-data/outputs"
os.makedirs(OUT, exist_ok=True)
BED = 256.0  # Bambu A1 bed (mm), square

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------
# !!! UNVERIFIED — measure the actual crussella0129 STEP bounding box and edit !!!
CASE_L, CASE_W, CASE_H = 118.0, 97.0, 46.0   # assembled Jetson case (estimate)
CASE_CLEAR = 2.0                              # per-side clearance in tray

# ----------------------------------------------------------------------------
# Mesh helpers (manifold boolean backend)
# ----------------------------------------------------------------------------
def box(l, w, h, x=0, y=0, z=0):
    """Axis-aligned box, min corner at (x,y,z)."""
    m = _box(extents=(l, w, h))
    m.apply_translation((l/2 + x, w/2 + y, h/2 + z))
    return m

def boxc(l, w, h, cx, cy, cz):
    """Axis-aligned box centered at (cx,cy,cz)."""
    m = _box(extents=(l, w, h))
    m.apply_translation((cx, cy, cz))
    return m

def cyl(r, h, cx=0, cy=0, cz=0, axis='z', n=72):
    m = _cyl(radius=r, height=h, sections=n)
    if axis == 'x':
        m.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2, (0, 1, 0)))
    elif axis == 'y':
        m.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2, (1, 0, 0)))
    m.apply_translation((cx, cy, cz))
    return m

def diff(a, b):
    return trimesh.boolean.difference([a, b])

def uni(*parts):
    return trimesh.boolean.union(list(parts))

def capsule_slot(length, dia, axis_len='x', cx=0, cy=0, cz=0, depth=10):
    """Rounded slot cutter (oval): length along axis_len, diameter dia, extruded 'depth' in the cut direction."""
    r = dia / 2
    body = boxc(length - dia, dia, depth, cx, cy, cz)
    c1 = cyl(r, depth, cx - (length - dia)/2, cy, cz, axis='z')
    c2 = cyl(r, depth, cx + (length - dia)/2, cy, cz, axis='z')
    return uni(body, c1, c2)

def add_dowel_joint(full, xc, anchors, boss=(28, 18, 14), pin_r=1.6, pin_len=70):
    """Add registration bosses straddling plane x=xc and drill a dowel pin hole through each."""
    for (y, z) in anchors:
        full = uni(full, boxc(boss[0], boss[1], boss[2], xc, y, z))
    for (y, z) in anchors:
        full = diff(full, cyl(pin_r, pin_len, xc, y, z, axis='x'))
    return full

def split_x(full, xc, total_len):
    a = trimesh.boolean.intersection([full, box(xc + 0.001, 1e4, 1e4, -1, -5000, -5000)])
    b = trimesh.boolean.intersection([full, box(total_len - xc + 1, 1e4, 1e4, xc, -5000, -5000)])
    return a, b

def save(mesh, name):
    path = os.path.join(OUT, name)
    mesh.export(path)
    bb = mesh.bounds
    dims = bb[1] - bb[0]
    wt = mesh.is_watertight
    fit = "OK" if (dims[0] <= BED and dims[1] <= BED) else "TOO BIG"
    print(f"  {name:38s}  {dims[0]:6.1f} x {dims[1]:6.1f} x {dims[2]:6.1f} mm  "
          f"watertight={str(wt):5s}  bed={fit}")
    return path

saved = []

# ----------------------------------------------------------------------------
# PART 1 — Keyboard Elevation Riser Shell  (split into 2 halves)
# ----------------------------------------------------------------------------
print("PART 1 - Keyboard riser shell")
L, W, H = 229.9, 160.0, 78.7
wall, lip, recess_d = 2.5, 3.0, 12.0
full = box(L, W, H)
# lower cavity (narrow) leaves the 3 mm support ledge
full = diff(full, box(L - 2*(wall+lip), W - 2*(wall+lip), H, wall+lip, wall+lip, wall))
# top keyboard recess (wide), 12 mm deep
full = diff(full, box(L - 2*wall, W - 2*wall, recess_d + 2, wall, wall, H - recess_d))
# rear USB-A pass-through slot 15 x 8, centered on rear (+Y) wall
full = diff(full, box(15, wall + 2, 8, L/2 - 7.5, W - wall - 1, H - 30))
# split with dowel registration
xc = L / 2
full = add_dowel_joint(full, xc, [(40, H/2), (120, H/2)])
a, b = split_x(full, xc, L)
saved.append(save(a, "part1_riser_shell_LEFT.stl"))
saved.append(save(b, "part1_riser_shell_RIGHT.stl"))

# ----------------------------------------------------------------------------
# PART 2 — Jetson Case Seating Tray  (REDESIGNED: open floor + perimeter ledge)
# ----------------------------------------------------------------------------
print("PART 2 - Jetson seating tray (open-floor, thermal-safe)")
wall = 2.5
ledge = 6.0          # width of perimeter rest ledge the case sits on
base = 2.0           # base/ledge thickness
cap = 10.0           # how far walls capture the case bottom
pocket_l = CASE_L + 2*CASE_CLEAR     # 122
pocket_w = CASE_W + 2*CASE_CLEAR     # 101
OL = pocket_l + 2*wall
OW = pocket_w + 2*wall
OH = cap + base
tray = box(OL, OW, OH)
# capture pocket (open top)
tray = diff(tray, box(pocket_l, pocket_w, cap + 1, wall, wall, base))
# big central floor opening for plenum exhaust -> leaves a 'ledge'-wide rest rim
tray = diff(tray, box(pocket_l - 2*ledge, pocket_w - 2*ledge, base + 2,
                      wall + ledge, wall + ledge, -1))
# wall vents: slots on all four walls
for i in range(4):
    yv = wall + 12 + i * ((pocket_w - 24) / 3)
    tray = diff(tray, box(wall + 2, 3, 6, -1, yv, base + 1))           # -X wall
    tray = diff(tray, box(wall + 2, 3, 6, OL - wall - 1, yv, base + 1)) # +X wall
for i in range(4):
    xv = wall + 14 + i * ((pocket_l - 28) / 3)
    tray = diff(tray, box(3, wall + 2, 6, xv, -1, base + 1))           # -Y wall
    tray = diff(tray, box(3, wall + 2, 6, xv, OW - wall - 1, base + 1)) # +Y wall
saved.append(save(tray, "part2_seating_tray.stl"))

# ----------------------------------------------------------------------------
# PART 3 — Lid Display Bracket  (split into 2 halves)
# ----------------------------------------------------------------------------
print("PART 3 - Lid display bracket")
OLb, OWb, OHb = 300.0, 225.0, 20.0
disp_l, disp_w = 171.0, 110.0
frame_lip = 8.0
pl_x = (OLb - disp_l) / 2
pl_y = (OWb - disp_w) / 2
full = box(OLb, OWb, OHb)
# display pocket on top face (depth 8)
full = diff(full, box(disp_l, disp_w, frame_lip + 1, pl_x, pl_y, OHb - frame_lip))
# through window (leaves 8 mm capture lip all round, opens the back for weight/airflow)
full = diff(full, box(disp_l - 2*frame_lip, disp_w - 2*frame_lip, OHb + 2,
                      pl_x + frame_lip, pl_y + frame_lip, -1))
# HDMI-mini notch (right pocket wall) and USB-A notch
full = diff(full, box(frame_lip + 2, 25, 12, pl_x + disp_l - frame_lip - 1, pl_y + 30, OHb - 12))
full = diff(full, box(frame_lip + 2, 12, 8,  pl_x + disp_l - frame_lip - 1, pl_y + 65, OHb - 8))
# cable trough along -Y long edge routing to hinge side
full = diff(full, box(OLb - 40, 8, 8, 20, 4, OHb - 8))
# 4 corner M3 mounting holes
for (hx, hy) in [(12, 12), (OLb-12, 12), (12, OWb-12), (OLb-12, OWb-12)]:
    full = diff(full, cyl(1.75, OHb + 2, hx, hy, OHb/2, axis='z'))
# split at x=150 with 3 dowel registrations along centerline
xc = OLb / 2
full = add_dowel_joint(full, xc, [(40, OHb/2), (OWb/2, OHb/2), (OWb-40, OHb/2)],
                       boss=(28, 16, 12), pin_len=80)
a, b = split_x(full, xc, OLb)
saved.append(save(a, "part3_display_bracket_LEFT.stl"))
saved.append(save(b, "part3_display_bracket_RIGHT.stl"))

# ----------------------------------------------------------------------------
# PART 4 — Hinge Cable Guide / Strain Relief (TPU)  -- one clamp half, print x4
# ----------------------------------------------------------------------------
print("PART 4 - Hinge cable guide half (TPU, qty 4)")
gl, gw, gh = 50.0, 26.0, 13.0
half = box(gl, gw, gh)
half = diff(half, cyl(6.0, gl + 2, gl/2, gw/2, gh, axis='x'))      # semicircular hinge groove on top
half = diff(half, box(gl + 2, 22, 6, -1, gw/2 - 11, -1))           # cable channel underside (22 x 6)
# M2 ears
for ey in (3.0, gw - 3.0):
    half = diff(half, cyl(1.1, gh + 2, 8, ey, gh/2, axis='z'))
    half = diff(half, cyl(1.1, gh + 2, gl - 8, ey, gh/2, axis='z'))
saved.append(save(half, "part4_hinge_cable_guide_half.stl"))

# ----------------------------------------------------------------------------
# PART 5 — LR900 Radio Retention Clip
# ----------------------------------------------------------------------------
print("PART 5 - LR900 retention clip")
ci, ch, depth, w = 65.0, 16.0, 15.0, 2.0
clip = box(depth, ci + 2*w, ch + w, 0, 0, 0)
clip = diff(clip, box(depth + 2, ci, ch + 2, -1, w, w))            # U channel, open top
clip = diff(clip, cyl(5.0, depth + 2, depth/2, (ci + 2*w)/2, w + ch/2, axis='x'))  # antenna notch end... 
# retention nibs at top inner edges
clip = uni(clip, boxc(depth, 2, 2, depth/2, w + 1, ch + w - 1))
clip = uni(clip, boxc(depth, 2, 2, depth/2, ci + w - 1, ch + w - 1))
saved.append(save(clip, "part5_lr900_clip.stl"))

# ----------------------------------------------------------------------------
# PART 6 — RadioMaster Pocket ELRS Cradle
# ----------------------------------------------------------------------------
print("PART 6 - RM Pocket cradle")
il, iw, dp = 130.0, 88.0, 15.0
floor = 2.0
OLc, OWc = 140.0, 95.0
cr = box(OLc, OWc, dp + floor)
cr = diff(cr, box(il, iw, dp + 1, (OLc-il)/2, (OWc-iw)/2, floor))   # pocket
# gimbal clearance holes (2 x 35x35 through floor)
cr = diff(cr, boxc(35, 35, floor + 2, OLc/2 - 35, OWc/2, floor/2))
cr = diff(cr, boxc(35, 35, floor + 2, OLc/2 + 35, OWc/2, floor/2))
# antenna pass-throughs on +Y top edge
cr = diff(cr, cyl(4.0, 20, OLc/2 - 30, OWc - 1, dp, axis='y'))
cr = diff(cr, cyl(4.0, 20, OLc/2 + 30, OWc - 1, dp, axis='y'))
saved.append(save(cr, "part6_rm_pocket_cradle.stl"))

# ----------------------------------------------------------------------------
# PART 7 — Power Bank Cradle
# ----------------------------------------------------------------------------
print("PART 7 - Power bank cradle")
il, iw, dp = 167.0, 77.0, 18.0
floor, w = 2.0, 2.0
OLp, OWp = il + 2*w, iw + 2*w
cr = box(OLp, OWp, dp + floor)
cr = diff(cr, box(il, iw, dp + 1, w, w, floor))                    # pocket
cr = diff(cr, box(w + 2, 14, 8, -1, OWp/2 - 7, floor + 3))         # USB-C access slot (short -X wall)
# thumb-out cutout: rounded 40 (along X) x 20 (tall, Z) slot through the +Y long wall
r = 10.0
thumb_cx, thumb_cz = OLp/2, dp/2 + floor
tb = boxc(40 - 2*r, 20, w + 4, thumb_cx, OWp - w/2, thumb_cz)
tc1 = cyl(r, w + 4, thumb_cx - (40 - 2*r)/2, OWp - w/2, thumb_cz, axis='y')
tc2 = cyl(r, w + 4, thumb_cx + (40 - 2*r)/2, OWp - w/2, thumb_cz, axis='y')
cr = diff(cr, uni(tb, tc1, tc2))
saved.append(save(cr, "part7_power_bank_cradle.stl"))

# ----------------------------------------------------------------------------
# PART 8 — USB Cable Strain Relief Clip (print x4)
# ----------------------------------------------------------------------------
print("PART 8 - USB strain relief clip (qty 4)")
b = box(12, 12, 8)
b = diff(b, cyl(3.0, 14, 6, 6, 8, axis='x'))                       # 6 mm cable channel from top
b = diff(b, box(3, 14, 4, 4.5, -1, 6))                             # snap mouth
b = uni(b, box(12, 6, 3, 0, 12, 0))                                # mounting tab
b = diff(b, cyl(1.5, 5, 6, 15, 1.5, axis='z'))                     # M2 mount hole
saved.append(save(b, "part8_usb_strain_relief_clip.stl"))

print("\nTotal STL files:", len(saved))
print("\n".join(os.path.basename(s) for s in saved))
