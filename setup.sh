#!/bin/bash
# One-time setup — install TribeV2 and backend deps
set -e
echo "Installing TribeV2 from GitHub..."
pip install "tribev2[plotting] @ git+https://github.com/facebookresearch/tribev2.git"

echo "Installing backend extras..."
pip install -r backend/requirements.txt

echo "Pre-downloading Llama-3.2-3B weights..."
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 - "$SCRIPT_DIR" <<'EOF'
import os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(sys.argv[1]) / "backend/.env")
from huggingface_hub import login
token = os.environ.get("HF_API_KEY")
if token:
    login(token=token, add_to_git_credential=False)
from transformers import AutoTokenizer, AutoModel
AutoTokenizer.from_pretrained("meta-llama/Llama-3.2-3B", truncation_side="left")
AutoModel.from_pretrained("meta-llama/Llama-3.2-3B")
print("Llama-3.2-3B cached.")
EOF

echo ""
echo "Setup complete! Run: ./start.sh"
