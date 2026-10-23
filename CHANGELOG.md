# Nouveautés

## 4.1.3

**Corrigé**
- Après une mise à jour, l'appli se relance d'elle-même sur la nouvelle version. Elle lisait la version de son
  exe dans la mémoire du programme déjà ouvert et croyait n'avoir rien de nouveau. Les applis 4.1.0 à 4.1.2 encore
  ouvertes sont fermées puis rouvertes par l'installation.
- Le message « GoXLR Mini … est installé » s'affiche bien après la mise à jour.
- Les fichiers de la mise à jour (environ 200 Mo) sont supprimés dans la minute, et non plus 6 heures plus tard.

## 4.1.2

**Corrigé**
- La mise à jour intégrée restait sur « Installation en cours » sans rien installer : la tâche d'installation
  cherchait ses instructions au mauvais endroit. Elle installe maintenant la nouvelle version.
- Si l'installation ne démarre pas, GoXLR Mini le dit au bout de 90 secondes (rien n'est modifié) et propose
  de réessayer, au lieu d'attendre sans fin.
- Resté bloqué sur « Installation en cours » en 4.1.0 ou 4.1.1 ? Redémarre Windows une fois, puis lance la
  mise à jour : la 4.1.2 s'installe normalement.

## 4.1.1

**Corrigé**
- Les notes de version gardent leurs accents dans la fenêtre de mise à jour et sur GitHub.

## 4.1.0

Première version publique.

**Nouveau**
- Mise à jour intégrée : GoXLR Mini cherche les nouvelles versions sur GitHub, les annonce une fois et les
  installe en un clic (empreinte vérifiée, retour arrière automatique si besoin).
- Installeur : `Installer.cmd`, moteur lancé au démarrage de Windows, désinstallation propre.
- Couper une voie d'une seule sortie (stream, Discord, casque, enceintes) ; appui long = couper partout.
- Bouton micro : bascule, maintenir pour couper, appuyer pour parler.
- VOD sans musique, scènes automatiques selon l'appli ouverte, incrustation OBS, diagnostic en direct.
- Appli Windows : icône d'état, bulle à l'écran quand le micro change, relance du moteur s'il ne répond plus.

**Corrigé**
- Le logiciel se figeait au bout d'une heure environ (index de commande USB sur 16 bits jamais remis à zéro) :
  plus rien ne répondait et les voyants des boutons ne bougeaient plus.
