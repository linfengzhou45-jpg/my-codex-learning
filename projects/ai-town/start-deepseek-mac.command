#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
echo "Starting AI Town with DeepSeek. Keep this terminal open."
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    echo "Python 3.10 or newer is required: https://www.python.org/downloads/"
    read -r -p "Press Return to close... "
    exit 1
fi
python3 server.py --mode deepseek --prompt-key --port 0 --open-browser
read -r -p "Press Return to close... "
