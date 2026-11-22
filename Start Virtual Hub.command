#!/bin/zsh
# Double-click to start the virtual hub. Terminal needs Bluetooth permission the first time.
cd "$(dirname "$0")"
exec .venv/bin/python -u run.py "$@"
