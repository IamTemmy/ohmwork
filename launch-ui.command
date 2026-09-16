#!/bin/bash
# Double-click this file (from Finder, or keep it in your Dock) to start
# Ohmwork's local web UI and open it in your browser. Runs from wherever
# this file itself lives, so it works no matter where you double-click it
# from (this folder, your Desktop, a Dock shortcut, ...).

cd "$(dirname "$0")" || exit 1

if [ ! -x "./.venv/bin/ohmwork" ]; then
    echo "Ohmwork's virtual environment isn't set up yet in this folder."
    echo "Run this once from a terminal, inside the ohmwork project folder:"
    echo ""
    echo "  python3 -m venv .venv"
    echo "  ./.venv/bin/pip install -e \".[dev]\""
    echo ""
    read -r -p "Press Return to close this window..."
    exit 1
fi

./.venv/bin/ohmwork ui
echo ""
read -r -p "Server stopped. Press Return to close this window..."
