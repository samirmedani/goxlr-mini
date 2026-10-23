# Sécurité

Pour signaler une faille, **n'ouvre pas d'issue publique**. Utilise « Report a vulnerability » dans l'onglet
Security du dépôt (signalement privé). Décris le problème, comment le reproduire et son impact.

Points sensibles de GoXLR Mini :

- **Moteur sous le compte système** : il écoute seulement sur `127.0.0.1:14565`. Les actions (`POST`) exigent
  l'en-tête `X-GoXLR: 1` et un hôte `127.0.0.1` ou `localhost`, ce qui bloque les requêtes venues d'une page web.
- **Mises à jour** : seule source acceptée, les releases GitHub de ce dépôt
  (`https://github.com/samirmedani/goxlr-mini/releases/download/`, redirections vers les serveurs de fichiers de
  GitHub uniquement). Taille et empreinte SHA-256 comparées à celles annoncées par GitHub ; archive vérifiée
  (aucun chemin hors du dossier, aucun lien) ; jamais de retour à une version plus ancienne ; retour arrière
  automatique si la nouvelle version ne répond pas.
- **Aucune télémétrie** : le seul contact extérieur est `GET https://api.github.com/repos/samirmedani/goxlr-mini/releases/latest`
  (5 s après le démarrage, puis toutes les 6 heures), et le téléchargement d'une mise à jour que tu as acceptée.

*To report a vulnerability, use "Report a vulnerability" in the Security tab. Please do not open a public issue.*
