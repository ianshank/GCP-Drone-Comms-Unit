# Running base_node.py as a service on the base node

Target: Linux with systemd (the Jetson or a Pi base node). Assumes a T-Beam on USB
and a reachable FreeTAKServer.

## 1. Lay down the code + venv
```bash
sudo useradd -r -s /usr/sbin/nologin -G dialout meshsa   # service account, serial access
sudo mkdir -p /opt/meshsa && sudo chown meshsa:meshsa /opt/meshsa

# copy the framework + example into place (from this repo's packages/meshsa/)
sudo -u meshsa cp -r packages/meshsa /opt/meshsa/meshsa

# venv with the framework and the radio libs
sudo -u meshsa python3 -m venv /opt/meshsa/venv
sudo -u meshsa /opt/meshsa/venv/bin/pip install -e "/opt/meshsa/meshsa[meshtastic]"
# the install creates a `meshsa-base` console script in /opt/meshsa/venv/bin/
```

## 2. Configuration
```bash
sudo mkdir -p /etc/meshsa
sudo cp base.env.example /etc/meshsa/base.env
sudo nano /etc/meshsa/base.env        # set port, FTS host, callsign, lat/lon
sudo chmod 640 /etc/meshsa/base.env && sudo chown root:meshsa /etc/meshsa/base.env
```
Confirm the serial device: `ls -l /dev/ttyUSB*` (the `meshsa` user is in `dialout`,
so it can open it). If your distro uses a different group (e.g. `uucp`), adjust the
unit's `Group=` and the useradd `-G`.

## 3. Install + start the service
```bash
sudo cp meshsa-base.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now meshsa-base.service
```

## 4. Operate
```bash
systemctl status meshsa-base.service          # health
journalctl -u meshsa-base.service -f          # live logs (structlog lines)
sudo systemctl restart meshsa-base.service    # after editing base.env
```

## Notes
- The TAK link auto-reconnects with backoff, so a FreeTAKServer restart does **not**
  require restarting this service.
- `base_node.py` traps SIGTERM, so `systemctl stop` shuts the node down cleanly.
- If FreeTAKServer runs on this same host as a unit, uncomment the `After=` line in
  the service so the bridge starts after it.
- This bridges the **base** node only; user nodes (phones + Meshtastic ATAK plugin)
  connect over the mesh and do not run this service.
