#!/usr/bin/env bash
# Run full stack locally with Docker (same as cloud: Go + Redis + Python brain).
# Prerequisites: Docker Desktop running, .env in project root with APCA_API_KEY_ID and APCA_API_SECRET_KEY.
set -e
cd "$(dirname "$0")"
docker compose up --build
