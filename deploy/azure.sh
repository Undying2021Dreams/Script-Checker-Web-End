#!/usr/bin/env bash
#
# Provision (or tear down) the whole deployment on Azure.
#
# This exists because the deployment is not permanent: it goes up for a
# review, comes down to protect a fixed student credit, and goes up
# again for the final demo. Anything done by hand once is a thing that
# has to be remembered correctly weeks later, so it lives here instead.
#
#   ./deploy/azure.sh up        provision everything and deploy
#   ./deploy/azure.sh deploy    push a new image revision only
#   ./deploy/azure.sh stop      stop the database (stops compute billing)
#   ./deploy/azure.sh start     start it again
#   ./deploy/azure.sh down      delete every resource in the group
#   ./deploy/azure.sh status    what exists right now, and the URL
#
set -euo pipefail

RG="${RG:-webend-rg}"

# Two regions, not one, and not by preference.
#
# This subscription carries an "Allowed resource deployment regions"
# policy limiting it to indonesiacentral, malaysiawest, austriaeast,
# koreacentral and centralindia. Of those, Central India refuses to
# create a Container Apps environment at all —
# MaxNumberOfEnvironmentsInSubExceeded, a capacity cap on the student
# offering rather than a quota that can be raised on request. So the app
# runs in Korea Central.
#
# The database stays in Central India because it is the closest allowed
# region to the users. The cross-region hop costs a few tens of
# milliseconds per query; moving it to Korea Central instead is a
# one-line change here if that ever matters more than proximity.
APP_LOC="${APP_LOC:-koreacentral}"
DB_LOC="${DB_LOC:-centralindia}"

ENV_NAME="${ENV_NAME:-webend-env}"
APP_NAME="${APP_NAME:-webend}"

# Built and published by .github/workflows/image.yml. Public package, so
# the container app pulls it without registry credentials.
IMAGE="${IMAGE:-ghcr.io/undying2021dreams/script-checker-web-end:latest}"

# Entra app registration. A public SPA client id is not a secret.
AZURE_CLIENT_ID="${AZURE_CLIENT_ID:-08409bfc-af77-447a-9389-3466a29ea9dd}"
AZURE_TENANT_ID="${AZURE_TENANT_ID:-common}"
TEACHER_EMAILS="${TEACHER_EMAILS:-2105025@ugrad.cse.buet.ac.bd}"

# The self-hosted model runs in a Kaggle notebook behind an ngrok tunnel,
# and the tunnel takes a fresh address every time that notebook restarts.
# So this is passed in rather than pinned:
#   SELF_HOSTED_LLM_URL=https://xxxx.ngrok-free.dev ./deploy/azure.sh deploy
SELF_HOSTED_LLM_URL="${SELF_HOSTED_LLM_URL:-}"

# Generated on first `up` and read back on every later run. Kept out of
# git (see .gitignore) — it holds the database password.
SECRETS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.azure-secrets"
PG_ENV="$SECRETS_DIR/pg.env"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

require_az() {
  command -v az >/dev/null || { echo "az CLI not found"; exit 1; }
  az account show >/dev/null 2>&1 || { echo "Run 'az login' first"; exit 1; }
}

load_secrets() {
  [ -f "$PG_ENV" ] || { echo "Missing $PG_ENV — run '$0 up' first"; exit 1; }
  # shellcheck disable=SC1090
  set -a; . "$PG_ENV"; set +a
}

# ── provisioning ────────────────────────────────────────────────────
cmd_up() {
  require_az

  log "Registering resource providers"
  # Not registered by default on a fresh subscription; without these the
  # creates below fail with MissingSubscriptionRegistration.
  for p in Microsoft.App Microsoft.ContainerRegistry Microsoft.DBforPostgreSQL Microsoft.OperationalInsights; do
    az provider register --namespace "$p" --wait -o none
  done

  log "Resource group $RG"
  az group create -n "$RG" -l "$DB_LOC" -o none

  mkdir -p "$SECRETS_DIR"; chmod 700 "$SECRETS_DIR"
  if [ ! -f "$PG_ENV" ]; then
    PG_NAME="webend-pg-$(openssl rand -hex 3)"
    PG_PASS="$(openssl rand -hex 16)"
    cat > "$PG_ENV" <<EOF
PG_NAME=$PG_NAME
PG_USER=webend
PG_PASS=$PG_PASS
EOF
    chmod 600 "$PG_ENV"
  fi
  load_secrets

  log "Postgres flexible server $PG_NAME ($DB_LOC)"
  if ! az postgres flexible-server show -g "$RG" -n "$PG_NAME" -o none 2>/dev/null; then
    # B1ms is the cheapest burstable tier and is what dominates the
    # monthly cost here; the container app itself scales to zero.
    az postgres flexible-server create \
      -g "$RG" -n "$PG_NAME" -l "$DB_LOC" \
      --tier Burstable --sku-name Standard_B1ms \
      --storage-size 32 --version 16 \
      --admin-user "$PG_USER" --admin-password "$PG_PASS" \
      --public-access 0.0.0.0 --yes -o none
  fi

  # Container Apps egresses from shared addresses that aren't knowable in
  # advance, so the database accepts connections from Azure services and
  # relies on credentials + TLS rather than on an IP allowlist.
  az postgres flexible-server firewall-rule create \
    -g "$RG" -n "$PG_NAME" --rule-name allow-azure \
    --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0 -o none 2>/dev/null || true

  # -n is the *database* name here and -s the server; there is no -d.
  # Getting that wrong fails the argument parser rather than the API, so
  # with stderr discarded it looked exactly like the idempotent
  # "already exists" case — the database was silently never created and
  # the app crash-looped on "database webend does not exist".
  az postgres flexible-server db create \
    -g "$RG" -s "$PG_NAME" -n webend -o none 2>&1 | grep -v "already exists" || true

  log "Container Apps environment $ENV_NAME ($APP_LOC)"
  if ! az containerapp env show -g "$RG" -n "$ENV_NAME" -o none 2>/dev/null; then
    # No Log Analytics workspace: it is a separate billed resource, and
    # live log streaming from a running replica works without one.
    az containerapp env create \
      -g "$RG" -n "$ENV_NAME" -l "$APP_LOC" --logs-destination none -o none
  fi

  cmd_deploy
}

# ── the app itself ──────────────────────────────────────────────────
cmd_deploy() {
  require_az; load_secrets

  local host="$PG_NAME.postgres.database.azure.com"
  # sslmode=require: Azure's Postgres refuses plaintext, and psycopg2
  # does not negotiate TLS on its own.
  local db_url="postgresql+psycopg2://$PG_USER:$PG_PASS@$host:5432/webend?sslmode=require"

  if az containerapp show -g "$RG" -n "$APP_NAME" -o none 2>/dev/null; then
    log "Updating $APP_NAME to $IMAGE"
    az containerapp update -g "$RG" -n "$APP_NAME" --image "$IMAGE" -o none
  else
    log "Creating container app $APP_NAME"
    # min-replicas 0 is the single most important cost setting here: an
    # idle app bills nothing. The trade is a cold start on the first
    # request after a quiet period, which for a demo deployment is the
    # right way round.
    az containerapp create \
      -g "$RG" -n "$APP_NAME" --environment "$ENV_NAME" \
      --image "$IMAGE" \
      --target-port 8000 --ingress external \
      --cpu 1.0 --memory 2.0Gi \
      --min-replicas 0 --max-replicas 1 \
      --secrets "db-url=$db_url" \
      --env-vars \
        "DATABASE_URL=secretref:db-url" \
        "AZURE_CLIENT_ID=$AZURE_CLIENT_ID" \
        "AZURE_TENANT_ID=$AZURE_TENANT_ID" \
        "TEACHER_EMAILS=$TEACHER_EMAILS" \
      -o none
  fi

  # The app's own public address is only knowable after ingress exists,
  # and it is needed both as a setting and as an Entra redirect URI.
  local fqdn
  fqdn="$(az containerapp show -g "$RG" -n "$APP_NAME" --query properties.configuration.ingress.fqdn -o tsv)"
  az containerapp update -g "$RG" -n "$APP_NAME" \
    --set-env-vars "PUBLIC_BASE_URL=https://$fqdn" "FRONTEND_ORIGINS=https://$fqdn" -o none

  # Left untouched when empty, so a plain redeploy does not wipe an
  # address that was set by an earlier run.
  if [ -n "$SELF_HOSTED_LLM_URL" ]; then
    az containerapp update -g "$RG" -n "$APP_NAME" \
      --set-env-vars "SELF_HOSTED_LLM_URL=$SELF_HOSTED_LLM_URL" -o none
  fi

  log "Deployed: https://$fqdn"
  cat <<EOF

One manual step remains, and sign-in fails without it:

  Entra portal -> App registrations -> Web-End -> Authentication
  add this Single-page application redirect URI:

      https://$fqdn/

  The trailing slash matters, and the path is the site root rather than
  a dedicated callback route: MSAL is configured with redirectUri '/'
  (frontend/src/lib/msal.ts) and main.tsx detects the popup landing
  there and hands the response back over a BroadcastChannel instead of
  mounting the app a second time.

EOF
}

# ── cost control ────────────────────────────────────────────────────
# The database bills for compute whether or not anyone is using it, and
# it is the only thing here that does. Between the review and the final
# demo it should simply be off.
cmd_stop()  { require_az; load_secrets; az postgres flexible-server stop  -g "$RG" -n "$PG_NAME" -o none && echo "stopped"; }
cmd_start() { require_az; load_secrets; az postgres flexible-server start -g "$RG" -n "$PG_NAME" -o none && echo "started"; }

cmd_down() {
  require_az
  read -rp "Delete resource group '$RG' and everything in it? [y/N] " a
  [ "$a" = y ] || { echo "aborted"; exit 1; }
  az group delete -n "$RG" --yes --no-wait
  echo "Deletion started. '$0 up' rebuilds it."
}

cmd_status() {
  require_az
  az resource list -g "$RG" --query "[].{name:name,type:type,location:location}" -o table 2>/dev/null || echo "no resource group"
  local fqdn
  fqdn="$(az containerapp show -g "$RG" -n "$APP_NAME" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)"
  [ -n "$fqdn" ] && echo && echo "URL: https://$fqdn"
}

case "${1:-}" in
  up) cmd_up ;; deploy) cmd_deploy ;; stop) cmd_stop ;; start) cmd_start ;;
  down) cmd_down ;; status) cmd_status ;;
  *) sed -n '3,16p' "$0"; exit 1 ;;
esac
