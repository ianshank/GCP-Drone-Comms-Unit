# Pi 5 Consolidated Comms/TAK Node — build kit (OpenMANET Route A)

A Raspberry Pi 5 running **Raspberry Pi OS** (not OpenWrt) as the comms/TAK plane:
HaLow 802.11s + batman-adv mesh gate, FreeTAKServer, TAK Meshtastic Gateway, and
ADS-B→CoT. The Jetson stays the AI/compute plane and rides the mesh as an IP host.

## Files
| File | What it does |
|---|---|
| `setup_pi5_node.sh` | Provisions everything; writes systemd units + dnsmasq/hostapd/FTS configs |
| `mesh-up.sh` | Brings up HaLow 802.11s + batman-adv, addresses `bat0`, NATs to uplink |
| `pi5_node_base.stl` | Enclosure base — Pi 5 standoffs (58×49 M2.5), I/O cutouts, vents, lid posts |
| `pi5_node_lid.stl` | Vented lid — fan grille over the cooler + 2× SMA antenna holes |

## Software install
```bash
chmod +x setup_pi5_node.sh mesh-up.sh
# EDIT the CONFIG block at the top of setup_pi5_node.sh first, then:
./setup_pi5_node.sh
sudo systemctl start mesh-up tak-gateway adsbcot
```
Order on boot: `mesh-up` → `dnsmasq`/`hostapd` → `tak-gateway` + `adsbcot`; FTS runs
under Docker with `restart: unless-stopped`. FTS UI at `http://<node-ip>:5000`.

### Must do by hand (not scripted)
1. **HaLow driver** — install the Morse Micro driver per Seeed's wiki and confirm the
   interface (`iw dev`) builds against your Pi 5 kernel. This is the #1 risk on Pi 5.
2. **Mesh mode** — `mesh-up.sh` assumes 802.11s mesh-point; if the driver lacks it,
   uncomment the IBSS fallback block.
3. **HaLow frequency/bandwidth** — set `HALOW_FREQ` for your region (US 902–928).
4. **TX power** — stock Morse BCF ≈ 21 dBm; OpenMANET's tuned BCF reaches ≈ 27 dBm.
   Source/apply a higher-TX BCF only within FCC limits.

## Enclosure
- **Standoffs** use the verified Pi 58 × 49 mm M2.5 pattern (Ø2.1 holes; self-tap or inserts).
- **Lid** screws to four M3 corner posts (heat-set inserts); fan grille sits over the
  Pi 5 active cooler; two Ø6.5 SMA bulkhead holes for the HaLow + SDR antennas.
- **Print:** PETG or ABS (this node runs warm), 3 walls, 20–25%, 0.2 mm. Both halves
  print flat on a 256 mm bed. The base is open-top as oriented (no support).

### Verify before final print
- **I/O cutouts are generous and approximate.** The base assumes the USB/Ethernet
  cluster on one long edge and USB-C-power + micro-HDMI on the adjacent short edge —
  confirm against your Pi 5 and widen/shift if needed.
- Internal height (≈44 mm above the board) targets the official active cooler + a
  HaLow HAT on a stacking header; check clearance for your specific cooler/HAT.

## Layered comms recap
- **HaLow (this node)** — medium-range, high-bandwidth IP mesh → full TAK, video, voice
- **LoRa / Meshtastic** — long-range, low-power fallback → recovery beacons, PLI/chat
- **ELRS / LR900** — real-time control link

⚠️ Three sub-GHz radios share ~900 MHz (HaLow + 915 LoRa + LR900). Plan channels and
separate the antennas; expect mutual desense if they transmit hard together.
