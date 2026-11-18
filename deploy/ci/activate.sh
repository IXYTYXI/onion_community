#!/usr/bin/env bash
# Verify a release in the inactive API slot, then switch the unchanged domain.
set -Eeuo pipefail
umask 027

root=/opt/ows-community
inbox=/var/spool/ows-community-release
validator=/usr/local/libexec/ows-community/package_release.py
template=/usr/local/libexec/ows-community/ows-community-slot.service
venv_reuse=/usr/local/libexec/ows-community/release_venv_reuse.py
site=/etc/nginx/sites-available/ows-community-new
worker_unit=/etc/systemd/system/ows-deployment.service
domain=owscommunity.awesome.guanghexinzhi.cn
commit=${1:-}
digest=${2:-}

[[ $EUID -eq 0 ]] || { echo 'release must run as root' >&2; exit 2; }
[[ $commit =~ ^[0-9a-f]{40}$ && $digest =~ ^[0-9a-f]{64}$ ]] || {
  echo 'invalid release identity' >&2; exit 2;
}
for path in "$validator" "$template" "$venv_reuse" "$site" "$worker_unit" "$root/.venv/bin/uv"; do
  test -f "$path"
done

exec 9>/run/lock/ows-community-release.lock
flock -n 9 || { echo 'another release is active' >&2; exit 3; }

# The proxy is the source of truth. The old API and its connections remain alive.
upstreams=$(grep -oE 'proxy_pass http://127\.0\.0\.1:800[01]' "$site" | sort -u)
[[ $upstreams == 'proxy_pass http://127.0.0.1:8000' ||
   $upstreams == 'proxy_pass http://127.0.0.1:8001' ]] || {
  echo 'ambiguous OWS proxy target' >&2; exit 4;
}
active_port=${upstreams##*:}
if [[ $active_port == 8000 ]]; then
  active_unit=ows-community.service
  candidate_port=8001
  candidate_unit=ows-community-blue.service
else
  active_unit=ows-community-blue.service
  candidate_port=8000
  candidate_unit=ows-community.service
fi
active_source=$(systemctl show -P WorkingDirectory "$active_unit")
[[ $active_source == "$root" || $active_source == "$root"/.releases/*/source ]] || {
  echo 'unexpected active source' >&2; exit 4;
}
systemctl is-active --quiet "$active_unit"
systemctl is-active --quiet ows-deployment.service

if [[ -f $root/.release-commit && $(cat "$root/.release-commit") == "$commit" ]]; then
  echo "already-active: $commit"
  exit 0
fi

archive="$inbox/$commit.tar.gz"
test -f "$archive"
install -d -m 0711 "$root/.releases"
stage=$(mktemp -d "$root/.releases/ci-$commit.XXXXXX")
chmod 0711 "$stage"
python3 "$validator" extract --archive "$archive" --digest "$digest" \
  --commit "$commit" --destination "$stage"
source="$stage/source"
test -f "$source/frontend/dist/.vite/manifest.json"
test -f "$source/frontend/dist/connect.html"
if python3 "$venv_reuse" "$active_source" "$source"; then
  ln -s "$(realpath "$active_source/.venv")" "$source/.venv"
  echo 'release-dependencies: reused active virtualenv'
else
  "$root/.venv/bin/uv" sync --project "$source" --frozen --no-dev --no-editable \
    --python /usr/bin/python3
  echo 'release-dependencies: installed changed dependencies'
fi
find "$source" -type d -exec chmod 0755 {} +
# uv creates pyvenv.cfg and installed modules under the root umask. The API
# and Worker run as separate unprivileged users and must read these files.
find "$source/.venv" -type f -exec chmod a+r {} +
rsync -a --ignore-existing "$active_source/frontend/dist/assets/" \
  "$source/frontend/dist/assets/"

cd "$source"
runuser -u ows-community -- env OWS_COMMUNITY_SETTINGS_FILE=/etc/ows-community/community.env \
  "$source/.venv/bin/python" -m scripts.check_server
runuser -u awesome -- env OWS_COMMUNITY_SETTINGS_FILE=/etc/ows-community/worker.env \
  "$source/.venv/bin/python" -m scripts.check_server --executor

cp -p "$site" "$stage/previous-site"
cp -p "$worker_unit" "$stage/previous-worker-unit"
worker_old_source=$(sed -n 's/^WorkingDirectory=//p' "$worker_unit" | head -1)
[[ $worker_old_source == "$root" || $worker_old_source == "$root"/.releases/*/source ]] || {
  echo 'unexpected Worker source' >&2; exit 4;
}

switched=0
worker_changed=0
rollback() {
  status=$?
  trap - ERR INT TERM HUP
  if (( switched )); then
    cp -p "$stage/previous-site" "$site"
    nginx -t && systemctl reload nginx || true
  fi
  if (( worker_changed )); then
    systemctl stop ows-deployment.service || true
    cp -p "$stage/previous-worker-unit" "$worker_unit"
    systemctl daemon-reload
    systemctl start ows-deployment.service || true
  fi
  systemctl stop "$candidate_unit" || true
  echo "release-failed: kept $active_unit on port $active_port (exit $status)" >&2
  exit "$status"
}
trap rollback ERR INT TERM HUP

# Reuse only the inactive slot. The currently routed API is never stopped.
systemctl stop "$candidate_unit" || true
sed -e "s|@SOURCE@|$source|g" -e "s|@PORT@|$candidate_port|g" \
  "$template" > "/etc/systemd/system/$candidate_unit"
systemctl daemon-reload
systemctl enable "$candidate_unit"
systemctl start "$candidate_unit"
for attempt in {1..15}; do
  if curl --noproxy '*' -fsS --max-time 3 -H "Host: $domain" \
    "http://127.0.0.1:$candidate_port/health/ready" >/dev/null; then break; fi
  sleep 2
done
curl --noproxy '*' -fsS --max-time 3 -H "Host: $domain" \
  "http://127.0.0.1:$candidate_port/health/ready" >/dev/null
test "$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 3 \
  -H "Host: $domain" "http://127.0.0.1:$candidate_port/connect.html")" = 303

switched=1
python3 - "$site" "$active_port" "$candidate_port" <<'PY'
from pathlib import Path
import sys
path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
content = path.read_text()
needle = f'127.0.0.1:{old}'
assert content.count(needle) == 2
path.write_text(content.replace(needle, f'127.0.0.1:{new}'))
PY
nginx -t
systemctl reload nginx
for attempt in {1..10}; do
  code=$(curl --noproxy '*' -sS -o /dev/null -w '%{http_code}' --max-time 3 \
    --resolve "$domain:443:127.0.0.1" "https://$domain/connect.html") || code=000
  [[ $code == 303 ]] && break
  sleep 1
done
[[ $code == 303 ]]
curl --noproxy '*' -fsS --max-time 3 --resolve "$domain:443:127.0.0.1" \
  "https://$domain/health/ready" >/dev/null

# One deployment Worker, moved only after B serves the domain. Its state paths
# and credentials stay in /etc and /var, shared with the previous release.
worker_changed=1
systemctl stop ows-deployment.service
python3 - "$worker_unit" "$worker_old_source" "$source" <<'PY'
from pathlib import Path
import sys
path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
content = path.read_text()
assert content.count(old) >= 3
path.write_text(content.replace(old, new))
PY
systemctl daemon-reload
systemctl start ows-deployment.service
sleep 5
systemctl is-active --quiet ows-deployment.service
systemctl is-active --quiet "$candidate_unit"
test "$(systemctl show -P WorkingDirectory "$candidate_unit")" = "$source"
printf '%s\n' "$commit" > "$root/.release-commit"
rm -f "$archive"
trap - ERR INT TERM HUP
echo "release-active: $commit on port $candidate_port; previous API retained on port $active_port"
