#!/usr/bin/env bash
# Install one verified release. Provision this root-owned script once; CI may only invoke it via sudo.
set -Eeuo pipefail
umask 027

root=/opt/ows-community
inbox=/var/spool/ows-community-release
validator=/usr/local/libexec/ows-community/package_release.py
commit=${1:-}
digest=${2:-}

[[ $EUID -eq 0 ]] || { echo 'release must run as root' >&2; exit 2; }
[[ $commit =~ ^[0-9a-f]{40}$ && $digest =~ ^[0-9a-f]{64}$ ]] || {
  echo 'invalid release identity' >&2; exit 2;
}

exec 9>/run/lock/ows-community-release.lock
flock -n 9 || { echo 'another release is active' >&2; exit 3; }

if [[ -f $root/.release-commit && $(cat "$root/.release-commit") == "$commit" ]]; then
  echo "already-active: $commit"
  exit 0
fi

archive="$inbox/$commit.tar.gz"
test -f "$archive"
test -f "$validator"
install -d -m 0700 "$root/.releases"
stage=$(mktemp -d "$root/.releases/ci-$commit.XXXXXX")
previous="$stage/previous"
install -m 0600 "$archive" "$stage/release.tar.gz"
python3 "$validator" extract --archive "$stage/release.tar.gz" \
  --digest "$digest" --commit "$commit" --destination "$stage"
source="$stage/source"
test -f "$source/frontend/dist/.vite/manifest.json"
test -f "$source/pyproject.toml"
test -f "$root/.venv/bin/uv"

# Build the next Python environment beside the live one, before stopping either service.
"$root/.venv/bin/uv" sync --project "$source" --frozen --no-dev --no-editable \
  --python /usr/bin/python3
install -m 0755 "$root/.venv/bin/uv" "$source/.venv/bin/uv"

# Old browser tabs can still request their hashed JS/CSS files after activation.
if [[ -d $root/frontend/dist/assets ]]; then
  rsync -a --ignore-existing "$root/frontend/dist/assets/" "$source/frontend/dist/assets/"
fi

mkdir -p "$previous/source"
exclude=(
  --exclude='/.releases/' --exclude='/.venv/' --exclude='/var/'
  --exclude='/.env' --exclude='/.env.server' --exclude='/frontend/node_modules/'
)
rsync -a "${exclude[@]}" "$root/" "$previous/source/"

activated=0
rollback() {
  status=$?
  trap - ERR INT TERM HUP
  if (( activated )); then
    systemctl stop ows-community.service ows-deployment.service || true
    rm -rf "$root/.venv"
    if [[ -d $previous/venv ]]; then mv "$previous/venv" "$root/.venv"; fi
    rsync -a --delete "${exclude[@]}" "$previous/source/" "$root/"
    systemctl start ows-community.service ows-deployment.service || true
    echo "release-failed: restored prior code (exit $status)" >&2
  fi
  exit "$status"
}
trap rollback ERR INT TERM HUP

# The Worker waits for any in-flight deployment before its service stops.
activated=1
systemctl stop ows-deployment.service
systemctl stop ows-community.service
mv "$root/.venv" "$previous/venv"
rsync -a --delete "${exclude[@]}" "$source/" "$root/"
mv "$source/.venv" "$root/.venv"

systemctl start ows-community.service
systemctl start ows-deployment.service
runuser -u ows-community -- env OWS_COMMUNITY_SETTINGS_FILE=/etc/ows-community/community.env \
  "$root/.venv/bin/python" -m scripts.check_server
systemctl is-active --quiet ows-community.service
systemctl is-active --quiet ows-deployment.service
for attempt in {1..15}; do
  if curl -fsS --max-time 3 http://127.0.0.1:8000/health/ready >/dev/null; then break; fi
  sleep 2
done
curl -fsS --max-time 3 http://127.0.0.1:8000/health/ready >/dev/null
test "$(cat "$root/.release-commit")" = "$commit"

printf '%s\n' "$commit" > "$stage/deployed-commit"
rm -f "$archive"
trap - ERR INT TERM HUP
rm -rf "$stage"
echo "release-active: $commit"
