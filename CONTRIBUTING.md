# Contribuer à GoXLR Mini

Merci ! Quelques règles pour que le projet reste fiable et sans données personnelles.

1. Lis [README.md](README.md) et [AGENTS.md](AGENTS.md) (règles du moteur).
2. Active les garde-fous Git une fois : `scripts/install-hooks.sh`.
3. Code et teste **sans GoXLR** grâce au simulateur :
   ```bash
   python3 -m unittest discover -s tests -v
   python3 engine/goxlrctl.py daemon --child --simulate --port 14566   # puis http://127.0.0.1:14566/
   ```
4. Avant une pull request : `scripts/check.sh` (tests + recherche de données personnelles). Le Python reste
   compatible 3.11 et n'utilise que la bibliothèque standard.
5. Un comportement d'appareil nouveau = un test sur simulateur ; un constat fait sur une vraie GoXLR = le
   simulateur mis à jour pour le reproduire.
6. Une branche par sujet, une pull request relue. Commits signés `git commit -s`, première ligne courte.

**Jamais dans le dépôt** : nom, e-mail, chemin de machine (`C:\Users\…`, `/Users/…`), nom de PC, adresse IP du
réseau local, numéro de série d'appareil, `state.json`, journaux, enregistrements audio, binaires
(`.exe`, `.dll`, `.zip`). La vérification GitHub refuse ces fichiers et motifs.

Les textes de l'interface sont en français, avec le tutoiement.
