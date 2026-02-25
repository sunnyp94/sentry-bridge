#!/usr/bin/env bash
# One-time fetch: copy relevant logs/data from GCP VM to local for analysis.
# Run from repo root: ./fetch_vm_logs.sh

set -e

# Your VM (same as deploy)
SSH_KEY="${SSH_KEY:-$HOME/deploy_key}"
VM_USER="${VM_USER:-sunnyakpatel}"
VM_HOST="${VM_HOST:-34.145.173.89}"
REMOTE_REPO="${REMOTE_REPO:-~/sentry-bridge}"
REMOTE_DATA="$REMOTE_REPO/data"

# Local destination (timestamped so you can run again without overwriting)
DEST_DIR="${DEST_DIR:-./vm-logs/$(date +%Y%m%d_%H%M%S)}"
mkdir -p "$DEST_DIR"
echo "Fetching VM logs into $DEST_DIR ..."

scp -i "$SSH_KEY" -o ConnectTimeout=10 \
  "$VM_USER@$VM_HOST:$REMOTE_DATA/app.log" \
  "$DEST_DIR/app.log"

scp -i "$SSH_KEY" -o ConnectTimeout=10 \
  "$VM_USER@$VM_HOST:$REMOTE_DATA/experience_buffer.jsonl" \
  "$DEST_DIR/experience_buffer.jsonl" 2>/dev/null || echo "  (no experience_buffer.jsonl)"

scp -i "$SSH_KEY" -o ConnectTimeout=10 \
  "$VM_USER@$VM_HOST:$REMOTE_DATA/generated_filter_rules.json" \
  "$DEST_DIR/generated_filter_rules.json" 2>/dev/null || echo "  (no generated_filter_rules.json)"

scp -i "$SSH_KEY" -o ConnectTimeout=10 \
  "$VM_USER@$VM_HOST:$REMOTE_DATA/generated_filter_rules_proposed.json" \
  "$DEST_DIR/generated_filter_rules_proposed.json" 2>/dev/null || echo "  (no generated_filter_rules_proposed.json)"

scp -i "$SSH_KEY" -o ConnectTimeout=10 \
  "$VM_USER@$VM_HOST:$REMOTE_DATA/active_symbols.txt" \
  "$DEST_DIR/active_symbols.txt" 2>/dev/null || echo "  (no active_symbols.txt)"

echo "Done. Files in $DEST_DIR:"
ls -la "$DEST_DIR"
