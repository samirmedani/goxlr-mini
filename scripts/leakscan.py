#!/usr/bin/env python3
"""
Recherche de donnees personnelles avant publication : chemins de machine, IP privees, e-mails, noms de PC,
adresses MAC, fichiers interdits. Termes propres au mainteneur : --deny fichier (une expression par ligne),
garde hors du depot.
  python3 scripts/leakscan.py                 fichiers suivis par Git
  python3 scripts/leakscan.py --staged        fichiers indexes (hook pre-commit)
  python3 scripts/leakscan.py --root DOSSIER  tout un dossier
Code de sortie 1 si quelque chose est trouve.
"""
import argparse
import os
import re
import subprocess
import sys

RULES = [
    ("chemin de machine", re.compile(r"/(?:Users|home)/(?!runner/|user/|me/|vous/|toi/)[A-Za-z0-9._-]+/")),
    ("chemin de machine", re.compile(r"[A-Za-z]:\\+Users\\+(?!Public\\|Default\\|<|%|\{|\$|toi\\|vous\\|user\\)[A-Za-z0-9._-]+", re.I)),
    ("IP privee", re.compile(r"\b(?:192\.168|10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7]))\.\d{1,3}\.\d{1,3}\b")),
    ("e-mail", re.compile(r"\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com\b|example\.(?:com|org)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("nom de PC", re.compile(r"\bDESKTOP-[A-Z0-9]{7}\b")),
    ("adresse MAC", re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)),
    ("cle ou jeton", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b")),
]
FORBIDDEN = re.compile(r"\.(?:wav|mp3|m4a|flac|db|sqlite|pem|key|p12|pfx|zip|exe|dll|msi)$|(^|/)(?:review|INTERNE)\.md$|(^|/)\.env|(^|/)state\.json$", re.I)
SKIP_DIRS = {".git", "private", "dist", "bin", "obj", "__pycache__", "node_modules"}
TEXT_EXT = {".py", ".md", ".html", ".cs", ".csproj", ".ps1", ".cmd", ".sh", ".yml", ".yaml", ".json", ".txt", ".svg", ".gitignore", ""}


def files_from_git(staged):
    args = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"] if staged else ["git", "ls-files"]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f and not f.startswith("private/")]


def files_from_dir(root):
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for n in names:
            yield os.path.relpath(os.path.join(d, n), root).replace(os.sep, "/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--root")
    ap.add_argument("--deny", action="append", default=[])
    a = ap.parse_args()
    base = a.root or "."
    files = list(files_from_dir(base)) if a.root else files_from_git(a.staged)
    deny = []
    for path in a.deny:
        if os.path.exists(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#"):
                    deny.append(("terme prive", re.compile(line, re.I)))
    found = 0
    for rel in files:
        if FORBIDDEN.search(rel):
            print(f"{rel}: fichier interdit dans le depot public")
            found += 1
            continue
        path = os.path.join(base, rel)
        if os.path.splitext(rel)[1].lower() not in TEXT_EXT or not os.path.isfile(path):
            continue
        try:
            text = open(path, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        if rel == "scripts/leakscan.py":
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for label, rx in RULES + deny:
                m = rx.search(line)
                if m:
                    shown = m.group(0) if label not in ("terme prive", "cle ou jeton") else "***"
                    print(f"{rel}:{n}: {label} : {shown}")
                    found += 1
    if found:
        print(f"\n{found} probleme(s) : rien n'est publie tant qu'il en reste.", file=sys.stderr)
        sys.exit(1)
    print(f"Aucune donnee personnelle trouvee ({len(files)} fichiers).")


if __name__ == "__main__":
    main()
