#!/bin/sh
# Start the scheduler in the background, then run uvicorn in the foreground.
# If uvicorn exits, the container exits (Fly.io will restart it).

set -e

mkdir -p /data /app/logs

echo "Starting TAF scheduler..."
python3 /app/scheduler.py --workers 3 &

echo "Starting API server..."
exec uvicorn main:app --host 0.0.0.0 --port 8080
