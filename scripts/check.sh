#!/bin/sh
# Verification locale avant une pull request : tests sur simulateur et recherche de donnees personnelles.
set -e
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -p 'test_*.py'
python3 scripts/leakscan.py
