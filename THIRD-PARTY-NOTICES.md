# Composants tiers

GoXLR Mini est distribué sous licence MIT (voir [LICENSE](LICENSE)). Il s'appuie sur :

| Composant | Utilisation | Licence |
| --- | --- | --- |
| [goxlr-utility](https://github.com/GoXLR-on-Linux/goxlr-utility) | Identifiants et formats des commandes USB de la GoXLR, repris comme référence (aucun code copié tel quel) | MIT |
| [Python 3.11 embarqué](https://www.python.org/downloads/windows/) | Exécute le moteur, livré dans la release | PSF License |
| [.NET](https://github.com/dotnet/runtime) | Appli Windows, livrée autonome dans la release | MIT |
| [Microsoft Edge WebView2](https://developer.microsoft.com/microsoft-edge/webview2/) | Affiche l'interface dans l'appli (SDK NuGet, runtime de Windows) | Licence du SDK WebView2 (BSD) |
| [NAudio](https://github.com/naudio/NAudio) | Outil de test audio du dépôt (`tools/audiotest`), absent de la release | MIT |
| [Lucide](https://lucide.dev) | Icônes de l'interface | ISC |
| [Inter](https://rsms.me/inter) | Police de l'interface, intégrée à `ui.html` | SIL Open Font License 1.1 |

Le **pilote officiel GoXLR** (TC-Helicon / Music Tribe) n'est pas distribué avec GoXLR Mini : il s'installe à part.
GoXLR est une marque de Music Tribe. Ce projet indépendant n'est ni affilié, ni soutenu par TC-Helicon ou Music Tribe.

## Lucide (icônes)

Icônes de l'interface (`engine/ui.html`), version 1.61.0, https://lucide.dev — licence ISC.

Copyright (c) 2026 Lucide Icons and Contributors. Permission to use, copy, modify, and/or distribute this software
for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission
notice appear in all copies. THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD
TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS.

## Inter (police)

Police de l'interface, intégrée à `engine/ui.html` (sous-ensemble latin, @fontsource-variable/inter 5.3.0),
https://rsms.me/inter — Copyright (c) 2016 The Inter Project Authors, SIL Open Font License 1.1
(https://openfontlicense.org).
