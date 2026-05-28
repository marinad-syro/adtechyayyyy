#!/bin/bash
# Run from project root: ./start.sh
set -e
cd "$(dirname "$0")/backend"
echo "Starting BrainText at http://localhost:8000"
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
