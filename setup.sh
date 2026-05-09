#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

echo "Installing dependencies..."
pip install -r requirements.txt

if [ ! -d "migrations" ]; then
    echo "Initializing database..."
    aerich init-db
else
    echo "Running migrations..."
    aerich upgrade
fi

echo ""
echo "Done! To run the bot:"
echo "  source .venv/bin/activate"
echo "  python main.py"
