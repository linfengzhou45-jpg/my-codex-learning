#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
echo "Starting AI Town. Keep this window open while using the town."
echo "Your browser will open automatically. No API key is needed."
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "Python 3.10 or newer was not found."
    echo "Install Python from https://www.python.org/downloads/ and try again."
    read -r -p "Press Return to close... "
    exit 1
fi
python3 server.py --port 0 --open-browser
read -r -p "Press Return to close... "
