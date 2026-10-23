# Nouveautés

## 4.3.0

**Nouveau**
- Nouvelle interface claire, dans l'esprit d'Apple : barre latérale en verre, grands titres, police Inter,
  icônes Lucide, fond lumineux. Le mixeur montre quatre faders en capsule, un bouton rond pour couper chaque
  voie (orange quand elle est coupée d'une seule sortie) et les autres voies dans une liste groupée.
- La fenêtre se redimensionne et l'interface suit : sur une petite fenêtre, la barre latérale devient une
  colonne d'icônes et les panneaux passent les uns sous les autres.
- Le menu ⋯ est dans l'en-tête, à côté de l'état du micro. Le menu de l'icône de notification passe aussi en clair.

**Corrigé**
- Fenêtre de mise à jour : un point des notes écrit sur plusieurs lignes s'affiche d'un seul tenant, comme sur
  GitHub, au lieu d'être coupé en morceaux.

## 4.2.0

**Nouveau**
- Installeur en un seul fichier, `GoXLR-Mini-Setup.exe` : un clic sur « Installer », Windows demande
  l'autorisation, puis « Ouvrir GoXLR Mini ». Il suit le thème clair ou sombre de Windows, prévient si le pilote
  GoXLR manque ou si GoXLR Utility est ouvert, et sait mettre à jour une version déjà installée. Le ZIP reste
  proposé à côté.
- Installation sans fenêtre : `GoXLR-Mini-Setup.exe /quiet` (options `/nodesktop` et `/nostartup`).

**Corrigé**
- `install.ps1` rend un code de sortie fiable et garde l'option `-Quiet` quand il redemande les droits
  administrateur.

## 4.1.5

**Corrigé**
- Installeur : le raccourci arrive sur le vrai Bureau du compte, même s'il est redirigé (OneDrive par exemple).
- Désinstallation depuis « Programmes et fonctionnalités » : retire aussi le démarrage avec la session et le
  raccourci du compte choisi à l'installation, même lancée depuis un autre compte administrateur.

## 4.1.4

**Corrigé**
- Les fichiers téléchargés pour une mise à jour sont supprimés dans la minute qui suit, même quand le message
  « installé » a déjà été lu.

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
