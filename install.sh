#!/usr/bin/env bash
# Install Seed Code from source.
set -e

python -m pip install --upgrade pip
python -m pip install .

echo "Seed Code installed. Run 'seedcode' to start."
