#!/usr/bin/env bash
# setup.sh — one-time setup for AI Podcast Pipeline
set -e

echo "=== AI Podcast Pipeline Setup ==="
echo ""

# ── Python virtual environment ────────────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "[1/4] Creating Python virtual environment..."
  python3 -m venv .venv
else
  echo "[1/4] Virtual environment already exists, skipping."
fi

source .venv/bin/activate
echo "      Activated: $(which python3)"

# ── Python dependencies ───────────────────────────────────────────────────────
echo "[2/4] Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "      Python packages installed."

# ── .env file ─────────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo "[3/4] Creating .env from .env.example..."
  cp env.example .env
  echo "      .env created. Fill in your API keys before running."
else
  echo "[3/4] .env already exists, skipping."
fi

# ── Frontend build ────────────────────────────────────────────────────────────
echo "[4/4] Building React frontend..."
if command -v npm &> /dev/null; then
  cd frontend
  npm install --silent
  npm run build --silent
  cd ..
  echo "      Frontend built to ./static/"
else
  echo "      WARN: npm not found. Install Node.js 18+ then run:"
  echo "        cd frontend && npm install && npm run build"
fi

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║              Setup Complete! Next Steps:             ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║                                                      ║"
echo "║  1. Fill in .env (open it now):                      ║"
echo "║       GEMINI_API_KEY=...  (aistudio.google.com)      ║"
echo "║                                                      ║"
echo "║  2. Authenticate NotebookLM (one-time browser login):║"
echo "║       source .venv/bin/activate                      ║"
echo "║       python3 -m notebooklm login                    ║"
echo "║                                                      ║"
echo "║  3. Run the server:                                  ║"
echo "║       source .venv/bin/activate                      ║"
echo "║       python3 main.py                                ║"
echo "║       → Dashboard: http://localhost:8000             ║"
echo "║       → API docs:  http://localhost:8000/docs        ║"
echo "║                                                      ║"
echo "║  4. Or test the pipeline once:                       ║"
echo "║       python3 main.py --run-now                      ║"
echo "║                                                      ║"
echo "╚══════════════════════════════════════════════════════╝"
