<p align="center">
  <img src="app/icon.svg" width="96" alt="">
</p>

<h1 align="center">GoXLR Mini</h1>

<p align="center">
  <b>Pilote ta GoXLR Mini sous Windows, sans GoXLR Utility, avec le seul pilote officiel.</b><br>
  Mixeur, micro, routage, éclairage, scènes automatiques, incrustation OBS… et des mises à jour en un clic.
</p>

<p align="center">
  <a href="https://github.com/samirmedani/goxlr-mini/releases/latest"><img src="https://img.shields.io/github/v/release/samirmedani/goxlr-mini?label=version&color=0A84FF" alt="Dernière version"></a>
  <a href="https://github.com/samirmedani/goxlr-mini/actions/workflows/ci.yml"><img src="https://github.com/samirmedani/goxlr-mini/actions/workflows/ci.yml/badge.svg" alt="Vérification"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-MIT-30D158" alt="Licence MIT"></a>
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-64D2FF" alt="Windows 10 et 11">
</p>

> [!IMPORTANT]
> **GoXLR Mini devient [Rustudio](https://github.com/samirmedani/rustudio)**, réécrit en Rust.
> Depuis GoXLR Mini 4.x, clique « Mettre à jour » en bas à gauche : Rustudio s'installe à sa place et reprend
> tes réglages. GoXLR Mini n'est retiré qu'une fois ta GoXLR reprise par Rustudio ; sinon, il revient tout seul.
> Nouvelle installation : [Rustudio-Setup.exe](https://github.com/samirmedani/rustudio/releases/latest).
> Ce dépôt ne reçoit plus que le passage vers Rustudio.

<p align="center">
  <img src="docs/captures/mixer.jpg" width="880" alt="Mixeur de GoXLR Mini : quatre faders, musique coupée du stream seulement">
</p>

*Open-source controller for the TC-Helicon GoXLR Mini on Windows, using only the official driver: mixer, mic
processing, routing, lighting, automatic scenes, OBS overlay and one-click updates. French interface.*

## Pourquoi

La GoXLR se pilote depuis l'ordinateur : sans logiciel, ses boutons ne coupent rien et ses couleurs restent
figées. GoXLR Mini est un petit moteur qui parle directement au pilote officiel de TC-Helicon, et une appli
claire pour tout régler. Il tourne en arrière-plan dès le démarrage de Windows, se relance seul s'il a un souci,
et reprend la GoXLR dès qu'elle est rebranchée.

## Ce qu'il sait faire

<table>
<tr>
<td width="50%"><img src="docs/captures/mic.jpg" alt="Page Micro"></td>
<td width="50%"><img src="docs/captures/routing.jpg" alt="Page Routage"></td>
</tr>
<tr>
<td><b>Micro</b> : ta voix naturelle par défaut. Égaliseur, noise gate, compresseur et de-esser ont chacun leur interrupteur ; <b>« Régler ma voix »</b> trouve ton micro (48 V compris), cale le gain et prépare des réglages doux sans les allumer ; « M'écouter » enregistre ta voix et te la fait réécouter ; retour micro dans le casque au choix. Bouton micro en bascule, <i>maintenir pour couper</i> ou <i>appuyer pour parler</i>.</td>
<td><b>Routage</b> : qui entend quoi (toi, ton stream, Discord, la VOD, les enceintes). <b>VOD sans musique</b> : la VOD reçoit le stream sans la musique, anti-DMCA.</td>
</tr>
<tr>
<td><img src="docs/captures/scenes.jpg" alt="Page Scènes"></td>
<td><img src="docs/captures/light.jpg" alt="Page Éclairage"></td>
</tr>
<tr>
<td><b>Scènes</b> : Streaming, Gaming, Soirée Discord, Podcast… en un clic, et <b>scènes automatiques</b> : « OBS s'ouvre → Streaming », « Spotify → Écoute ».</td>
<td><b>Éclairage</b> : thèmes (les barres prennent la couleur de la voie), couleurs par bouton, styles des barres, animations.</td>
</tr>
</table>

- **Couper d'une seule sortie** : chaque bouton mute a son mode (partout, stream, Discord, casque, enceintes).
  Appui long = coupé partout, le bouton clignote. Orange dans l'appli = coupé d'une sortie, rouge = partout.
- **Égaliseur du casque** : correction de ton casque (AutoEq, cible Harman), styles et profils sur 10 bandes, appliqués
  par Equalizer APO aux voies GoXLR choisies ; coupé tout seul pendant le live.
- **Anti-écho Windows** : l'appli vérifie en continu les périphériques son par défaut de Windows. Si Discord ou tes
  jeux enregistrent « Broadcast Stream Mix » au lieu de ton micro, ou si le son du PC contourne la GoXLR, un clic
  remet tout sur les bonnes voies.
- **Faders physiques** suivis en direct ; un trait pointillé montre l'écart avec le volume réglé dans l'appli.
- **Appli Windows** : interface claire qui suit la taille de la fenêtre, icône d'état (rouge = micro coupé), bulle
  à l'écran quand le micro change (jamais de focus, même en jeu), menu rapide dans la zone de notification.
- **Incrustation OBS** : « Micro coupé » à l'écran du stream quand il ne t'entend plus
  (`http://127.0.0.1:14565/overlay`).
- **Diagnostic** en direct : état de la connexion, commandes, reconnexions, journal ; bouton « Reconnecter ».

<p align="center">
  <img src="docs/captures/casque.jpg" width="720" alt="Page Casque : égaliseur, correction du casque et styles">
</p>

<p align="center">
  <img src="docs/captures/overlay.jpg" width="380" alt="Incrustation OBS : micro coupé">
</p>

## Une voix propre, sans écho

<p align="center">
  <img src="docs/captures/voice.jpg" width="720" alt="Régler ma voix : micro statique trouvé, gain, noise gate et compresseur calés sur la voix et la pièce">
</p>

1. Page **Micro › Régler ma voix** : parle une dizaine de secondes, puis tais-toi quelques secondes. Le gain se
   cale sur ta voix ; aucun traitement ne s'allume. Allume ensuite, un par un, ceux qui t'aident (noise gate si le
   bruit de fond gêne, compresseur pour une voix plus régulière) et vérifie avec **M'écouter**.
2. **Windows** : micro par défaut « Chat Mic », sortie « System ». L'appli le vérifie et le corrige en un clic
   (conseil dans Scènes).
3. **Discord** : micro « Chat Mic », sortie « Chat ». Coupe l'annulation d'écho et le réglage automatique du
   gain de Discord. Pour le bruit de fond, choisis : noise gate de la GoXLR ou suppression de bruit de Discord.
4. **OBS** : une seule source audio, « Broadcast Stream Mix » ; « Audio du bureau » désactivé. Ce qui part en
   live se choisit dans la page Routage.
5. Branche la GoXLR **toujours sur le même port USB** : sur un autre port, Windows crée de nouveaux périphériques
   audio, et Discord ou OBS ne retrouvent plus les leurs.
6. Casque ouvert et micro statique : garde le retour micro bas, et pas d'enceintes pendant les vocaux.

## Installer

1. Installe le **pilote officiel GoXLR** de TC-Helicon (il fournit les voies audio System, Game, Chat, Music…).
2. Ferme **GoXLR Utility** s'il est installé : deux logiciels ne peuvent pas piloter la GoXLR en même temps.
3. Télécharge **[GoXLR-Mini-Setup.exe](https://github.com/samirmedani/goxlr-mini/releases/latest/download/GoXLR-Mini-Setup.exe)**
   et ouvre-le : un clic sur **Installer**, Windows demande l'autorisation, c'est prêt.

<p align="center">
  <img src="docs/captures/setup.png" width="560" alt="Installeur de GoXLR Mini">
</p>

C'est tout : le moteur démarre avec Windows, l'appli se lance avec ta session et l'icône apparaît en bas à droite.
Tes réglages vivent dans `C:\ProgramData\GoXLR Mini` et survivent aux mises à jour. Pour désinstaller :
*Paramètres › Applications › GoXLR Mini*.

Tu préfères sans installeur ? **[GoXLR-Mini.zip](https://github.com/samirmedani/goxlr-mini/releases/latest/download/GoXLR-Mini.zip)**
contient les mêmes fichiers : décompresse-le, puis double-clique `Installer.cmd` (et `Desinstaller.cmd` pour
retirer). Pour un déploiement sans fenêtre : `GoXLR-Mini-Setup.exe /quiet` (options `/nodesktop`, `/nostartup`).

> Les exécutables ne sont pas signés : Windows SmartScreen peut afficher « Windows a protégé votre ordinateur ».
> Choisis *Informations complémentaires › Exécuter quand même*, ou vérifie d'abord l'empreinte SHA-256 affichée par
> GitHub à côté de chaque fichier de la release (aussi dans `GoXLR-Mini.sha256`).

## Mises à jour

<p align="center">
  <img src="docs/captures/update.jpg" width="720" alt="Fenêtre de mise à jour">
</p>

GoXLR Mini regarde s'il existe une nouvelle version 5 secondes après le démarrage, puis toutes les 6 heures. Une
version nouvelle est annoncée **une seule fois** ; la fenêtre montre ses notes. « Mettre à jour » :

1. télécharge `GoXLR-Mini.zip` **uniquement** depuis les releases de ce dépôt ;
2. compare sa taille et son empreinte **SHA-256** à celles annoncées par GitHub, et vérifie l'archive ;
3. garde la version en place de côté, installe la nouvelle et la redémarre ;
4. si la nouvelle version ne répond pas, **remet l'ancienne** toute seule.

Le seul échange avec Internet : `GET api.github.com/repos/samirmedani/goxlr-mini/releases/latest` (sans compte
ni identifiant), puis le téléchargement que tu as accepté. Aucune télémétrie.

## Comment ça marche

```mermaid
flowchart LR
  A["Appli GoXLR Mini<br/>(WebView2, icône, bulle)"] -- "HTTP 127.0.0.1:14565" --> C
  O["OBS<br/>source navigateur"] -- HTTP --> C
  S["Superviseur<br/>tâche « GoXLR Mini »"] -- "lance, surveille, relance" --> C["Moteur Python<br/>un seul fil USB"]
  C -- "pilote officiel<br/>(API Thesycon)" --> D["GoXLR Mini"]
  C --- E["Réglages<br/>ProgramData"]
  C -. "mises à jour" .-> G["Releases GitHub"]
```

- Le moteur (`engine/goxlrctl.py`, Python 3.11, bibliothèque standard seulement) envoie les commandes USB de la
  GoXLR à travers le pilote officiel. Un seul fil parle à l'appareil ; l'interface ne l'attend jamais.
- Toute erreur USB ferme la connexion et en rouvre une propre qui réapplique tous tes réglages. Un superviseur
  relance le moteur s'il s'arrête ou se fige.
- L'interface (`engine/ui.html`) est une page web locale ; l'appli (`app/`, C# .NET 10) l'affiche dans une
  fenêtre WebView2 et gère l'icône, la bulle et le démarrage.

## Développer

Tout se code et se teste **sans GoXLR**, grâce à une fausse GoXLR qui imite le pilote, y compris ses pièges
(débranchement, pilote bloqué, compteur de commandes).

```bash
python3 -m unittest discover -s tests -v                              # tests du moteur et des mises à jour
python3 engine/goxlrctl.py daemon --child --simulate --port 14566     # puis http://127.0.0.1:14566/
```

Le diagnostic propose alors des boutons pour appuyer sur les touches, débrancher, rebrancher ou bloquer l'USB.
Une release se publie en poussant un tag `vX.Y.Z` : GitHub fabrique `GoXLR-Mini.zip` (Python embarqué officiel,
appli autonome) et `GoXLR-Mini-Setup.exe` (le même paquet dans un installeur), puis les publie avec leurs notes
tirées de [CHANGELOG.md](CHANGELOG.md). Voir
[CONTRIBUTING.md](CONTRIBUTING.md).

## Compatibilité

- **GoXLR Mini** (firmware 1.2.x testé ; 1.3 pris en charge avec Stream Mix 2). La GoXLR « Full » n'est pas gérée.
- Windows 10 ou 11, 64 bits, pilote officiel GoXLR installé.
- Captures faites avec l'appareil simulé.

## Remerciements et licence

Les identifiants et formats des commandes USB s'appuient sur le travail du projet
[goxlr-utility](https://github.com/GoXLR-on-Linux/goxlr-utility) (MIT). Composants tiers :
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

GoXLR Mini est distribué sous licence [MIT](LICENSE). Projet indépendant, ni affilié ni soutenu par TC-Helicon ou
Music Tribe ; GoXLR est une marque de Music Tribe.
