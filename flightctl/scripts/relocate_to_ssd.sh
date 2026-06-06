#!/usr/bin/env bash
# =============================================================================
# relocate_to_ssd.sh — Phase 1: free the 97%-full eMMC by relocating deps/caches
# to the NVMe SSD at /mnt/ssd (Jetson Orin Nano, JetPack 6.2 / L4T R36.4.7).
#
# CONSERVATIVE by design: it does NOT move system partitions, /home, /opt, /tmp,
# or purge runtime CUDA/JetPack packages. It moves Docker's data-root (currently
# empty → near-zero risk), redirects pip/npm/HF/apt/uv caches, hardens the mount,
# and runs safe cleanup.
#
#   !!! REVIEW BEFORE RUNNING. Run with sudo:  sudo bash relocate_to_ssd.sh
#   Flags:  --yes  skip confirmations   --samples  also purge CUDA sample/doc pkgs
# Re-runnable (idempotent). Every step prints what it does; destructive steps ask.
# =============================================================================
set -euo pipefail

SSD=/mnt/ssd
SSD_UUID="07421890-e541-4a79-9515-2cd5fbf2250e"   # verify with: blkid /dev/nvme0n1p1
ASSUME_YES=0
DO_SAMPLES=0
for a in "$@"; do
  case "$a" in
    --yes) ASSUME_YES=1 ;;
    --samples) DO_SAMPLES=1 ;;
    *) echo "unknown arg: $a" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then echo "must run as root (sudo)" >&2; exit 1; fi
TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"

confirm() { [ "$ASSUME_YES" -eq 1 ] && return 0; read -rp "$1 [y/N] " r; [ "$r" = y ] || [ "$r" = Y ]; }
say()     { printf '\n=== %s ===\n' "$*"; }

# --- precondition: SSD mounted -----------------------------------------------
say "Preconditions"
if ! mountpoint -q "$SSD"; then echo "ERROR: $SSD is not mounted; aborting." >&2; exit 1; fi
df -h / "$SSD"

# --- 1. safe cleanup ---------------------------------------------------------
say "1. Safe cleanup (apt cache, journal, user cache)"
apt-get clean
journalctl --vacuum-size=100M || true
rm -rf "/home/${TARGET_USER}/.cache/pip" "/home/${TARGET_USER}/.cache/huggingface" 2>/dev/null || true

# --- 2. harden mount + dirs --------------------------------------------------
say "2. Harden $SSD mount (noatime) + create dirs"
if grep -qE "^[^#].*\s${SSD}\s" /etc/fstab; then
  if ! grep -qE "^[^#].*\s${SSD}\s.*noatime" /etc/fstab; then
    cp /etc/fstab "/etc/fstab.bak.$(date +%s 2>/dev/null || echo bak)"
    sed -i -E "s#(^[^#].*\s${SSD}\s+ext4\s+)defaults#\1defaults,noatime#" /etc/fstab
    systemctl daemon-reload
    mount -o remount "$SSD"
  fi
fi
mount | grep "$SSD" || true
install -d -o "$TARGET_USER" -g "$TARGET_USER" \
  "$SSD"/docker "$SSD"/venvs "$SSD"/projects "$SSD"/data "$SSD"/models \
  "$SSD"/caches/{pip,npm,hf,apt-archives,uv}
install -d -o _apt -g root "$SSD"/caches/apt-archives/partial

# --- 3. caches -> SSD --------------------------------------------------------
say "3. Redirect caches to SSD (durable)"
add_env() { grep -qxF "$1" /etc/environment || echo "$1" >> /etc/environment; }
add_env "XDG_CACHE_HOME=${SSD}/caches"
add_env "PIP_CACHE_DIR=${SSD}/caches/pip"
add_env "HF_HOME=${SSD}/caches/hf"
add_env "HF_HUB_CACHE=${SSD}/caches/hf/hub"
add_env "UV_CACHE_DIR=${SSD}/caches/uv"
add_env "npm_config_cache=${SSD}/caches/npm"
cat > /etc/profile.d/ssd-caches.sh <<EOF
export XDG_CACHE_HOME=${SSD}/caches
export PIP_CACHE_DIR="\$XDG_CACHE_HOME/pip"
export HF_HOME="\$XDG_CACHE_HOME/hf"
export HF_HUB_CACHE="\$HF_HOME/hub"
export UV_CACHE_DIR="\$XDG_CACHE_HOME/uv"
export npm_config_cache="\$XDG_CACHE_HOME/npm"
EOF
echo "Dir::Cache::Archives \"${SSD}/caches/apt-archives/\";" > /etc/apt/apt.conf.d/01-ssd-cache

# --- 4. docker data-root -> SSD ---------------------------------------------
say "4. Move Docker data-root to ${SSD}/docker"
if command -v docker >/dev/null 2>&1; then
  if [ "$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo)" != "${SSD}/docker" ]; then
    if confirm "Stop Docker and migrate data-root to ${SSD}/docker?"; then
      systemctl stop docker docker.socket || true
      rsync -axPS /var/lib/docker/ "${SSD}/docker/" 2>/dev/null || true
      python3 - "$SSD" <<'PY'
import json, os, sys
ssd = sys.argv[1]; path = "/etc/docker/daemon.json"
cfg = {}
if os.path.exists(path):
    try: cfg = json.load(open(path))
    except Exception: cfg = {}
cfg.setdefault("runtimes", {}).setdefault("nvidia", {"args": [], "path": "nvidia-container-runtime"})
cfg["default-runtime"] = "nvidia"
cfg["data-root"] = f"{ssd}/docker"
json.dump(cfg, open(path, "w"), indent=4)
print("wrote", path)
PY
      mkdir -p /etc/systemd/system/docker.service.d
      printf '[Unit]\nRequiresMountsFor=%s\n' "$SSD" > /etc/systemd/system/docker.service.d/ssd-mount.conf
      systemctl daemon-reload
      systemctl start docker
      echo "Docker root dir is now: $(docker info --format '{{.DockerRootDir}}')"
      echo "NOTE: old /var/lib/docker left in place; remove after a day: sudo rm -rf /var/lib/docker"
    fi
  else
    echo "Docker data-root already on SSD."
  fi
else
  echo "docker not installed; skipping."
fi

# --- 5. optional: purge ONLY genuinely-leaf sample packages ------------------
# DANGER (learned the hard way): NVIDIA meta-packages `cuda-toolkit-12-6` and
# `tensorrt` *Depend on* their -samples/-documentation sub-packages. Purging
# cuda-documentation-12-6 / libcudnn9-samples / libnvinfer-samples therefore
# removes the meta, and a follow-up `autoremove --purge` then cascades to the
# ENTIRE CUDA toolkit (nvcc, cuBLAS, cuFFT, ...) and TensorRT. So:
#   * do NOT purge any cuda-*/cudnn/nvinfer sample/doc package, and
#   * do NOT run autoremove here.
# Only these standalone sample packages are safe (verified to not pull metas):
if [ "$DO_SAMPLES" -eq 1 ]; then
  say "5. Purge standalone sample packages only (safe; ~0.3 GB)"
  apt-get remove --purge -y \
    libopencv-samples opencv-samples-data vpi3-samples nvidia-l4t-vulkan-sc-samples || true
  echo "Skipped cuda/cudnn/nvinfer samples on purpose (purging them removes the whole CUDA+TensorRT toolkit)."
fi

say "Done. Recovered space:"
df -h / "$SSD"
echo "Re-login (or reboot) so /etc/environment cache vars take effect for all sessions."
