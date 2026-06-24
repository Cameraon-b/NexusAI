#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/home/noratheredeemer/nexusai"
LOG_DIR="$APP_DIR/logs"
BACKUP_DIR="$APP_DIR/backups"
DB_FILE="$APP_DIR/data/nexusai.db"
TIMESTAMP="$(date +%F-%H%M%S)"

mkdir -p "$LOG_DIR" "$BACKUP_DIR"

exec > >(tee -a "$LOG_DIR/deploy-$TIMESTAMP.log") 2>&1

echo "=== NexusAI deploy started: $(date) ==="
echo "App directory: $APP_DIR"

cd "$APP_DIR"

echo
echo "Current git commit:"
git rev-parse --short HEAD || true

echo
echo "Backing up SQLite database if present..."
if [ -f "$DB_FILE" ]; then
    cp "$DB_FILE" "$BACKUP_DIR/nexusai-$TIMESTAMP.db"
    echo "Database backed up to $BACKUP_DIR/nexusai-$TIMESTAMP.db"
else
    echo "No database found at $DB_FILE"
fi

echo
echo "Pulling latest code..."
git pull

echo
NEW_COMMIT="$(git rev-parse --short HEAD || true)"
echo "New git commit:"
echo "$NEW_COMMIT"
if [ -n "$NEW_COMMIT" ]; then
    printf '%s\n' "$NEW_COMMIT" > .nexusai_commit
    echo "Wrote build commit to $APP_DIR/.nexusai_commit"
else
    echo "WARNING: could not determine git commit; version endpoint will report unknown commit"
fi

cat > .env <<EOF
NEXUSAI_COMMIT=$NEW_COMMIT
NEXUSAI_ENVIRONMENT=AETHER
NEXUSAI_HOST=Nora
EOF
echo "Wrote runtime version environment to $APP_DIR/.env"

echo
echo "Rebuilding and restarting NexusAI..."
sudo docker compose up --build -d

echo
echo "Current container status:"
sudo docker compose ps

echo
echo "Recent logs:"
sudo docker compose logs --tail=50 nexusai || sudo docker compose logs --tail=50

echo
echo "=== NexusAI deploy finished: $(date) ==="
