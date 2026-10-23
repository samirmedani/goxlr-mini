# Composants tiers

GoXLR Mini est distribué sous licence MIT (voir [LICENSE](LICENSE)). Il s'appuie sur :

| Composant | Utilisation | Licence |
| --- | --- | --- |
| [goxlr-utility](https://github.com/GoXLR-on-Linux/goxlr-utility) | Identifiants et formats des commandes USB de la GoXLR, repris comme référence (aucun code copié tel quel) | MIT |
| [Python 3.11 embarqué](https://www.python.org/downloads/windows/) | Exécute le moteur, livré dans la release | PSF License |
| [.NET](https://github.com/dotnet/runtime) | Appli Windows, livrée autonome dans la release | MIT |
| [Microsoft Edge WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) | Affiche l'interface dans l'appli (SDK NuGet, runtime de Windows) | Licence du SDK WebView2 (BSD) |
| [NAudio](https://github.com/naudio/NAudio) | Outil de test audio du dépôt (`tools/audiotest`), absent de la release | MIT |

Le **pilote officiel GoXLR** (TC-Helicon / Music Tribe) n'est pas distribué avec GoXLR Mini : il s'installe à part.
GoXLR est une marque de Music Tribe. Ce projet indépendant n'est ni affilié, ni soutenu par TC-Helicon ou Music Tribe.
