#!/usr/bin/env bash
set -e

echo "==========================================================="
echo " Updating Options Tracker to the latest version..."
echo "==========================================================="

echo "1. Pulling latest code from GitHub..."
git pull origin master

echo ""
echo "2. Rebuilding and restarting containers..."
# Rebuild the backend and frontend images, and restart only what changed
docker compose up -d --build

echo ""
echo "==========================================================="
echo " Update complete! The new version is now running."
echo "==========================================================="
