# GoXLR Mini — consignes pour contribuer (humains et agents)

Logiciel libre qui pilote une GoXLR Mini sous Windows avec le pilote officiel. Lire [README.md](README.md)
avant de toucher au moteur.

## Règles du moteur (`engine/goxlrctl.py`)

- `TUSBAUDIO_EnumerateDevices()` invalide **tous** les handles ouverts : seulement handle fermé. Le port HTTP
  est pris avant l'USB, pour qu'un second moteur s'arrête sans toucher au pilote.
- Index de commande sur 16 bits : remise à zéro (commande 0) avant 65 535. La Mini répond avec son propre
  compteur ; un décalage se rattrape par une resynchronisation.
- Un seul fil parle à l'USB. L'API ne touche jamais l'appareil : elle modifie l'état et marque ce qui doit partir.
- Toute erreur pendant un échange USB ferme le handle et relance une connexion propre qui réapplique l'état.
- Mises à jour : uniquement depuis les releases GitHub du dépôt, taille et SHA-256 vérifiées, retour arrière
  si la nouvelle version ne répond pas. Ne jamais affaiblir ces contrôles.

## Développement

- Python 3.11, bibliothèque standard seulement. Appli C# .NET 10 (`app/`).
- Tester avec le simulateur (`tests/`, `--simulate`) ; `scripts/check.sh` avant une pull request.
- Ne jamais lancer GoXLR Utility pendant un test sur une vraie GoXLR.
- Aucune donnée personnelle dans le dépôt (voir [CONTRIBUTING.md](CONTRIBUTING.md)) ; `scripts/leakscan.py`
  doit passer.
- Mettre à jour [CHANGELOG.md](CHANGELOG.md) avec tout changement visible. Une release = un tag `vX.Y.Z`
  identique à `VERSION` (moteur) et `<Version>` (appli) : GitHub fabrique et publie le paquet.
