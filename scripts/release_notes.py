#!/usr/bin/env python3
"""Notes d'une version, tirees de CHANGELOG.md : python3 scripts/release_notes.py v4.1.0"""
import re
import sys
from pathlib import Path

tag = sys.argv[1].lstrip("v")
text = Path(__file__).resolve().parent.parent.joinpath("CHANGELOG.md").read_text(encoding="utf-8")
m = re.search(r"^## \[?" + re.escape(tag) + r"\]?[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
if not m:
    sys.exit(f"Version {tag} absente de CHANGELOG.md")
print(m.group(1).strip())
