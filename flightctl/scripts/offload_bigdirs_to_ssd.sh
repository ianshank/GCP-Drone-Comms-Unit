#!/usr/bin/env bash
# =============================================================================
# offload_bigdirs_to_ssd.sh — relieve the eMMC root by relocating large static
# directories onto the NVMe SSD and bind-mounting them back (path-transparent).
# Frees REAL eMMC space (unlike caches/data-root relocation, which only helps
# future growth). Run with sudo after reviewing.  Reverse with --revert <dir>.
#
# Safe by construction: rsync -> keep a same-fs backup -> bind-mount -> verify ->
# reclaim, with automatic rollback if verification fails. Each dir is in
# /etc/fstab as `bind,nofail` so a missing SSD never blocks boot (systemd orders
# the bind after mnt-ssd.mount automatically because the source is under /mnt/ssd).
#
# Verified on this box: /usr/local/cuda-12.6 (~4.4G) and /opt (~1.4G) -> eMMC 97%->75%.
#
# /home is intentionally NOT relocated by default: do it only from a console with
# NO active desktop/login session (stop gdm3 first), since moving a live $HOME can
# corrupt the running session. See --home below.
# =============================================================================
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
mountpoint -q /mnt/ssd || { echo "/mnt/ssd not mounted"; exit 1; }

relocate() {  # <src> [verify-cmd]
  local SRC="$1" VERIFY="${2:-}" DST="/mnt/ssd/sysroot$1"
  [ -d "$SRC" ] || { echo "skip: $SRC missing"; return 0; }
  mountpoint -q "$SRC" && { echo "skip: $SRC already a mountpoint"; return 0; }
  echo ">>> $SRC -> $DST"
  mkdir -p "$(dirname "$DST")"
  rsync -aAXH --numeric-ids "$SRC/" "$DST/"
  mv "$SRC" "${SRC}.relbak"; mkdir "$SRC"; mount --bind "$DST" "$SRC"
  grep -qF " $SRC none bind" /etc/fstab || echo "$DST $SRC none bind,nofail 0 0" >> /etc/fstab
  if [ -n "$VERIFY" ] && ! eval "$VERIFY"; then
    echo "!!! verify failed; rolling back"; umount "$SRC"; rmdir "$SRC"
    mv "${SRC}.relbak" "$SRC"; sed -i "\#${DST} ${SRC} none bind#d" /etc/fstab; return 1
  fi
  rm -rf "${SRC}.relbak"; echo ">>> OK $SRC"
}

revert() {  # <src>
  local SRC="$1" DST="/mnt/ssd/sysroot$1"
  mountpoint -q "$SRC" && umount "$SRC"
  rmdir "$SRC" 2>/dev/null || true
  rsync -aAXH --numeric-ids "$DST/" "$SRC/"
  sed -i "\#${DST} ${SRC} none bind#d" /etc/fstab
  echo ">>> reverted $SRC back onto eMMC"
}

case "${1:-}" in
  --revert) shift; revert "$1" ;;
  --home)
    # Only safe with NO active session. Caller must have stopped gdm3.
    if loginctl list-sessions --no-legend 2>/dev/null | grep -q .; then
      echo "ERROR: active login session present; stop it first (sudo systemctl stop gdm3)"; exit 1
    fi
    relocate /home 'test -d /home'
    ;;
  *)
    relocate /usr/local/cuda-12.6 '/usr/local/cuda/bin/nvcc --version >/dev/null'
    relocate /opt 'test -d /opt/nvidia'
    echo; df -h / /mnt/ssd
    ;;
esac
