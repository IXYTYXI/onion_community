#!/usr/bin/env bash
# Run once as root on the production server with the CI deploy public key path.
set -Eeuo pipefail
umask 027

public_key=${1:-}
[[ $EUID -eq 0 && -f $public_key ]] || {
  echo 'usage: provision.sh /path/to/ci-deploy.pub (as root)' >&2
  exit 2
}

if ! id ows-release >/dev/null 2>&1; then
  useradd --system --create-home --home-dir /var/lib/ows-release \
    --shell /bin/bash ows-release
fi
install -d -o ows-release -g ows-release -m 0700 /var/lib/ows-release/.ssh
install -d -o ows-release -g ows-release -m 0700 /var/spool/ows-community-release
printf 'restrict %s\n' "$(cat "$public_key")" > /var/lib/ows-release/.ssh/authorized_keys
chown ows-release:ows-release /var/lib/ows-release/.ssh/authorized_keys
chmod 0600 /var/lib/ows-release/.ssh/authorized_keys

install -d -o root -g root -m 0755 /usr/local/libexec/ows-community
install -o root -g root -m 0755 activate.sh /usr/local/libexec/ows-community/activate.sh
install -o root -g root -m 0644 package_release.py /usr/local/libexec/ows-community/package_release.py

cat > /etc/sudoers.d/ows-community-ci <<'EOF'
ows-release ALL=(root) NOPASSWD: /usr/local/libexec/ows-community/activate.sh *
EOF
chmod 0440 /etc/sudoers.d/ows-community-ci
visudo -c -f /etc/sudoers.d/ows-community-ci
