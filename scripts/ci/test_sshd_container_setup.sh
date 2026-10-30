#!/usr/bin/env bash
# Runs INSIDE the throwaway sshd container started by scripts/ci/start_test_sshd.sh
# (mounted read-only at /setup). Expects the keys at /keys: host_ed25519{,.pub} and
# authorized_keys. Installs openssh-server, adds user `phi` that accepts only the
# test key, and execs sshd in the foreground.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends openssh-server >/dev/null

install -m 600 /keys/host_ed25519 /etc/ssh/ssh_host_ed25519_key
install -m 644 /keys/host_ed25519.pub /etc/ssh/ssh_host_ed25519_key.pub

useradd -m -s /bin/bash phi
usermod -p '*' phi  # no password, but not locked: key auth still works
install -d -m 700 -o phi -g phi /home/phi/.ssh
install -m 600 -o phi -g phi /keys/authorized_keys /home/phi/.ssh/authorized_keys

# AcceptEnv lets the SendEnv passthrough test reach the remote shell.
cat > /etc/ssh/sshd_config.d/phi-test.conf <<'EOF'
HostKey /etc/ssh/ssh_host_ed25519_key
PasswordAuthentication no
AcceptEnv PHI_RB_*
EOF

mkdir -p /run/sshd
exec /usr/sbin/sshd -D -e
