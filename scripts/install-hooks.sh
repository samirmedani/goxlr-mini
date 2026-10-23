#!/bin/sh
# Active les garde-fous Git du projet (.githooks). A lancer une fois apres le clonage.
set -e
cd "$(dirname "$0")/.."
git config core.hooksPath .githooks
chmod +x .githooks/*
echo "Garde-fous Git actifs (.githooks)."
