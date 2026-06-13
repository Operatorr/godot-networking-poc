#!/usr/bin/env bash
#
# update_os.sh — OS maintenance for the Omega Realm VPS (Ubuntu).
# Applies package security + feature updates, cleans up, and (optionally) does a
# distribution release upgrade. Run ON the server:  sudo bash deployment/update_os.sh
#
# NOTE: harden_vps.sh already enables `unattended-upgrades`, which installs
# SECURITY patches daily on its own. This script is for the periodic FULL upgrade
# (all packages, kernel) and for Ubuntu version bumps — things that want a human
# and usually a reboot.
#
# Flags:
#   --reboot            reboot at the end IF the system reports one is required
#   --release-upgrade   also run an Ubuntu release upgrade (e.g. 24.04 -> 24.10/next LTS)
#                       — interactive, slower, higher-risk; snapshot/backup first.
#   -y, --yes           assume yes (non-interactive apt)
#
set -euo pipefail

DO_REBOOT=false
DO_RELEASE=false
ASSUME_YES=false
for a in "$@"; do
  case "$a" in
    --reboot)          DO_REBOOT=true ;;
    --release-upgrade) DO_RELEASE=true ;;
    -y|--yes)          ASSUME_YES=true ;;
    -h|--help)         sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown flag: $a" >&2; exit 1 ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo bash deployment/update_os.sh" >&2
  exit 1
fi

log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
export DEBIAN_FRONTEND=noninteractive
APT_YES=(); $ASSUME_YES && APT_YES=(-y)

log "1/5  Refreshing package lists"
apt-get update -y

log "2/5  Full upgrade (packages + kernel)"
# full-upgrade (a.k.a. dist-upgrade) handles deps that plain upgrade holds back.
apt-get ${APT_YES[@]+"${APT_YES[@]}"} full-upgrade

log "3/5  Removing orphaned packages + cleaning cache"
apt-get -y autoremove --purge
apt-get -y autoclean

if $DO_RELEASE; then
  log "4/5  Ubuntu release upgrade (do-release-upgrade)"
  echo "WARNING: this changes your Ubuntu version. Make sure you have a droplet"
  echo "snapshot / backup. The game services will be down during the upgrade."
  apt-get install -y update-manager-core
  # -d would target a not-yet-released devel version; omit it for stable upgrades.
  do-release-upgrade ${ASSUME_YES:+-f DistUpgradeViewNonInteractive}
else
  log "4/5  Skipping release upgrade (pass --release-upgrade to enable)"
fi

log "5/5  Reboot check"
if [[ -f /var/run/reboot-required ]]; then
  echo "A reboot IS required (kernel/library update):"
  cat /var/run/reboot-required 2>/dev/null || true
  if $DO_REBOOT; then
    echo "Rebooting now — systemd will bring all services back up on boot."
    sleep 2
    reboot
  else
    echo "Run 'sudo reboot' when ready (or re-run with --reboot)."
    echo "After reboot, verify: systemctl is-active omega-api omega-arena omega-sanctuary"
  fi
else
  echo "No reboot required."
fi
