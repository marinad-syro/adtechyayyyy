#!/bin/bash
# Vercel-demo setup — no TribeV2 / Llama weights
set -e
echo "Installing backend deps (embedding demo)..."
pip install -r backend/requirements.txt
echo ""
echo "Setup complete! Run: ./start.sh"
echo "Deploy: push branch vercel-demo and import on Vercel (see DEPLOY_VERCEL.md)"
