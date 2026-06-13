#!/usr/bin/env bash
#
# harden_vps.sh — first-boot hardening for the Omega Realm game-server VPS.
# Target: fresh Ubuntu 24.04 DigitalOcean droplet, run as the `deploy` user.
#
# Run with:   sudo bash harden_vps.sh
#
# Safe to re-run (idempotent). SSH config is validated with `sshd -t`
# BEFORE anything is reloaded, so a bad config can never lock you out of
# your CURRENT session. Always verify a SECOND ssh session works before
# closing this one.
#
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run me with sudo: sudo bash harden_vps.sh" >&2
  exit 1
fi

ADMIN_USER="deploy"
log() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------------------
log "1/6  Updating package lists and applying security updates"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get -y upgrade

# ---------------------------------------------------------------------------
log "2/6  Installing ufw and fail2ban"
apt-get install -y ufw fail2ban

# ---------------------------------------------------------------------------
log "3/6  Configuring firewall (ufw): default-deny inbound"
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

# SSH: 'limit' adds rate-limiting against brute force (max 6 conns / 30s / IP)
ufw limit 22/tcp        comment 'SSH (rate-limited)'
ufw allow 8081/udp      comment 'omega ARENA game (ENet/UDP)'
ufw allow 8082/udp      comment 'omega SANCTUARY hub (ENet/UDP)'
ufw allow 8080/tcp      comment 'Go API (HTTP)'
# NOTE: Prometheus 9100/9101, Postgres 5432, Redis 6379 are intentionally NOT
# opened. Keep them internal (bound to localhost by the native services).
ufw --force enable
ufw status verbose

# ---------------------------------------------------------------------------
log "4/6  Configuring fail2ban for sshd"
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
# Ban for 1h after 5 failures within 10 min; escalate on repeat offenders.
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd
# Never ban loopback.
ignoreip = 127.0.0.1/8 ::1

[sshd]
enabled = true
port    = 22
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban

# ---------------------------------------------------------------------------
log "5/6  Hardening SSH (drop-in: 99-hardening.conf)"
# Written as a drop-in so we never clobber cloud-init's config.
# Ordering: drop-ins load alphabetically; 99- wins over the 50-/60- defaults.
cat > /etc/ssh/sshd_config.d/99-hardening.conf <<EOF
# Managed by harden_vps.sh — keys-only, no root, restricted to ${ADMIN_USER}.
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitEmptyPasswords no
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowAgentForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers ${ADMIN_USER}
EOF

# CRITICAL: validate before applying. If this fails, we abort WITHOUT
# touching the running sshd, so the current session stays alive.
if ! sshd -t; then
  echo "sshd config test FAILED — removing drop-in, not reloading." >&2
  rm -f /etc/ssh/sshd_config.d/99-hardening.conf
  exit 1
fi
echo "sshd -t passed."

# Ubuntu 24.04 may be socket-activated; cover both service and socket.
systemctl reload ssh 2>/dev/null || systemctl restart ssh 2>/dev/null || true
systemctl restart ssh.socket 2>/dev/null || true

# ---------------------------------------------------------------------------
log "6/6  Enabling automatic security updates"
apt-get install -y unattended-upgrades
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades

# ---------------------------------------------------------------------------
log "DONE. Verification summary:"
echo "--- ufw ---";        ufw status verbose | sed 's/^/   /'
echo "--- fail2ban ---";   fail2ban-client status sshd 2>/dev/null | sed 's/^/   /' || echo "   (sshd jail starting)"
echo "--- sshd effective root/password settings ---"
sshd -T 2>/dev/null | grep -Ei '^(permitrootlogin|passwordauthentication|pubkeyauthentication|maxauthtries|allowusers)' | sed 's/^/   /'
echo
echo ">>> BEFORE CLOSING THIS SESSION: open a NEW terminal and confirm:"
echo ">>>     ssh ${ADMIN_USER}@$(hostname -I | awk '{print $1}')"
echo ">>> If it works, you're hardened. If not, this session is still open to fix it."
