#!/bin/sh
# Host-scoped GIT_ASKPASS helper for internal GitLab (gitlab.yc345.tv).
# Never echoes credentials for github.com or any other external Git host.
set -eu

PROMPT="${1-}"
LOWER_PROMPT="$(printf '%s' "$PROMPT" | tr '[:upper:]' '[:lower:]')"

case "$LOWER_PROMPT" in
  *"https://gitlab.yc345.tv"*|*"@gitlab.yc345.tv"*) ;;
  *) exit 1 ;;
esac

TOKEN_FILE=""
for CANDIDATE in /etc/awesome-deploy/gitlab-git-token /etc/ows-community/gitlab-git-token; do
  if [ -f "$CANDIDATE" ] && [ -r "$CANDIDATE" ]; then
    TOKEN_FILE="$CANDIDATE"
    break
  fi
done

[ -n "$TOKEN_FILE" ] || exit 1

RAW_LINE="$(tr -d '\r\n' < "$TOKEN_FILE")"
[ -n "$RAW_LINE" ] || exit 1

case "$RAW_LINE" in
  *:*)
    GIT_USER="${RAW_LINE%%:*}"
    GIT_PASS="${RAW_LINE#*:}"
    ;;
  *)
    GIT_USER="oauth2"
    GIT_PASS="$RAW_LINE"
    ;;
esac

[ -n "$GIT_USER" ] && [ -n "$GIT_PASS" ] || exit 1

case "$LOWER_PROMPT" in
  username*)
    printf '%s\n' "$GIT_USER"
    ;;
  password*)
    printf '%s\n' "$GIT_PASS"
    ;;
  *)
    exit 1
    ;;
esac
