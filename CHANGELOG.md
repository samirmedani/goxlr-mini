# Nouveautés

## 4.7.0

**Nouveau**
- Anti-écho Windows : l'appli surveille les périphériques son par défaut de Windows. Si Discord et tes jeux
  enregistrent « Broadcast Stream Mix » (le mix du stream, qui contient déjà le son de tout le monde) au lieu de
  ton micro, une alerte s'affiche avec « Corriger » : Windows reprend « Chat Mic » en un clic.
- Même vérification pour la sortie : si le son du PC part ailleurs que sur la GoXLR, faders, mute et égaliseur
  du casque ne s'y appliquent pas ; « Passer par la GoXLR » le remet sur « System » (et « Chat » pour les
  communications). Un choix déjà fait sur une voie GoXLR (Jeu, Musique…) est gardé.
- Le diagnostic affiche la sortie et le micro utilisés par Windows, et les ajoute au rapport copié.

## 4.6.0

**Nouveau**
- Page **Casque** : un égaliseur pour tout le son du PC qui passe par la GoXLR. Choisis ton casque pour le
  ramener à la courbe de référence Harman (corrections AutoEq de 21 casques courants), ajoute un style (Basses +,
  Jeu, Voix claire, Film, Musique, Doux), règle finement sur 10 bandes et enregistre tes profils.
- Un clic installe Equalizer APO (logiciel libre, téléchargé depuis sa page officielle, empreinte vérifiée) et le
  branche sur les voies GoXLR choisies ; GoXLR Mini le rebranche tout seul si la GoXLR change de port USB.
- Filtres sans latence, volume baissé juste ce qu'il faut pour ne jamais saturer. Le stream recevant aussi ce son,
  l'égaliseur se coupe tout seul quand OBS est ouvert (réglable).

## 4.5.0

**Nouveau**
- « M'écouter » : enregistre-toi 8 secondes puis réécoute ta voix telle que l'entendent Discord et ton stream,
  ou écoute-toi en direct dans le casque avec un réglage de volume.

**Corrigé**
- Le moteur envoie maintenant le réglage des sous-mixages (casque et sorties sur le mix A) sur les firmwares
  Mini 1.2.0.46 et plus récents, comme goxlr-utility. Il manquait pour le retour micro dans le casque.
- Une position de fader lue une seule fois ne change plus le volume d'une voie, et l'appli n'affiche plus
  « Fader physique à 0 % » quand la GoXLR ne remonte pas la position de ses faders.
- Les scènes intégrées ne remplacent plus le préréglage de ta voix une fois qu'elle a été mesurée.
- Le diagnostic USB ne reste plus sur « appareil en échec » quand la GoXLR revient juste à ce moment-là.

## 4.4.0

**Nouveau**
- « Régler ma voix », sur la page Micro : en vingt secondes, l'appli trouve ton micro (elle essaie le 48 V pour
  un micro statique), écoute ta voix puis le silence de ta pièce, et cale le gain, le noise gate et le
  compresseur sur ces mesures. Elle signale aussi ce qui fait de l'écho (Discord renvoyé vers Discord, enceintes,
  retour micro trop fort) avec une correction en un clic.
- Préréglage « Studio » pour les micros statiques : voix nette et posée, graves allégés, présence, de-esser. Une
  fois ta voix mesurée, chaque préréglage place ses seuils par rapport à elle, et ils suivent le gain.
- « M'écouter » : ta voix traitée dans le casque pendant 15 secondes, puis tout revient comme avant.
- Quand la GoXLR n'apparaît pas, l'appli dit ce que Windows voit sur l'USB : rien (câble qui ne fait que
  charger, port non relié), un appareil qui n'arrive pas à se présenter, ou une GoXLR complète.

**Corrigé**
- Le moteur répond tout de suite même quand le pilote USB tarde à se charger (au réveil du PC par exemple), et
  le diagnostic indique l'étape où il bloque.

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
