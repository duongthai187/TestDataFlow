#!/bin/sh
set -eu

TEMPLATE=/etc/alertmanager/alertmanager.yml.tmpl
RENDERED=/tmp/alertmanager.yml
RENDER_ONLY="${ALERTMANAGER_RENDER_ONLY:-0}"

DEFAULT_SLACK="https://hooks.slack.com/services/REPLACE/ME"
DEFAULT_EMAIL_FROM="alertmanager@example.com"
DEFAULT_EMAIL_TO="alerts@example.com"
DEFAULT_SMTP_SMARTHOST="smtp.example.com:587"
DEFAULT_TEAMS="https://outlook.office.com/webhook/REPLACE/ME"

escape_for_sed() {
  # Escape characters that are special to sed replacement.
  printf '%s' "$1" | sed 's/[&/]/\\&/g'
}

render_config() {
  slack_url="${ALERTMANAGER_SLACK_WEBHOOK_URL:-$DEFAULT_SLACK}"
  email_from="${ALERTMANAGER_EMAIL_FROM:-$DEFAULT_EMAIL_FROM}"
  email_to="${ALERTMANAGER_EMAIL_TO:-$DEFAULT_EMAIL_TO}"
  smtp_smarthost="${ALERTMANAGER_SMTP_SMARTHOST:-$DEFAULT_SMTP_SMARTHOST}"
  smtp_username="${ALERTMANAGER_SMTP_USERNAME:-}"
  smtp_password="${ALERTMANAGER_SMTP_PASSWORD:-}"
  teams_url="${ALERTMANAGER_TEAMS_WEBHOOK_URL:-$DEFAULT_TEAMS}"

  # Emit a warning when defaults are in use to prevent missed routing.
  if [ "${slack_url}" = "$DEFAULT_SLACK" ]; then
    echo "[alertmanager-entrypoint] WARNING: ALERTMANAGER_SLACK_WEBHOOK_URL not set; using placeholder." >&2
  fi
  if [ "${teams_url}" = "$DEFAULT_TEAMS" ]; then
    echo "[alertmanager-entrypoint] WARNING: ALERTMANAGER_TEAMS_WEBHOOK_URL not set; using placeholder." >&2
  fi
  if [ "${smtp_smarthost}" = "$DEFAULT_SMTP_SMARTHOST" ] || [ -z "${smtp_username}" ] || [ -z "${smtp_password}" ]; then
    echo "[alertmanager-entrypoint] WARNING: Email SMTP credentials incomplete; email routing will likely fail." >&2
  fi

  sed \
    -e "s#__ALERTMANAGER_SLACK_WEBHOOK_URL__#$(escape_for_sed "${slack_url}")#g" \
    -e "s#__ALERTMANAGER_EMAIL_FROM__#$(escape_for_sed "${email_from}")#g" \
    -e "s#__ALERTMANAGER_EMAIL_TO__#$(escape_for_sed "${email_to}")#g" \
    -e "s#__ALERTMANAGER_SMTP_SMARTHOST__#$(escape_for_sed "${smtp_smarthost}")#g" \
    -e "s#__ALERTMANAGER_SMTP_USERNAME__#$(escape_for_sed "${smtp_username}")#g" \
    -e "s#__ALERTMANAGER_SMTP_PASSWORD__#$(escape_for_sed "${smtp_password}")#g" \
    -e "s#__ALERTMANAGER_TEAMS_WEBHOOK_URL__#$(escape_for_sed "${teams_url}")#g" \
    "$TEMPLATE" > "$RENDERED"
}

render_config

if [ "$RENDER_ONLY" = "1" ]; then
  cat "$RENDERED"
  exit 0
fi

exec /bin/alertmanager --config.file="$RENDERED" "$@"
