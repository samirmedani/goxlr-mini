#!/usr/bin/env python3
"""Notes d'une version, tirees de CHANGELOG.md.

    python3 scripts/release_notes.py v4.1.0                  -> sortie standard
    python3 scripts/release_notes.py v4.1.0 --out notes.md   -> fichier UTF-8 (a utiliser sous Windows)
"""
import re
import sys
from pathlib import Path

args = sys.argv[1:]
out = None
if "--out" in args:
    i = args.index("--out")
    out = args[i + 1]
    del args[i:i + 2]
tag = args[0].lstrip("v")
text = Path(__file__).resolve().parent.parent.joinpath("CHANGELOG.md").read_text(encoding="utf-8")
m = re.search(r"^## \[?" + re.escape(tag) + r"\]?[^\n]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
if not m:
    sys.exit(f"Version {tag} absente de CHANGELOG.md")
notes = m.group(1).strip().replace("\r\n", "\n") + "\n"
if out:
    Path(out).write_text(notes, encoding="utf-8", newline="\n")
else:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(notes)
