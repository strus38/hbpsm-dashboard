# HBPSM : ce que les joueurs envoient depuis le tableau de bord

Ce dépôt reçoit ce que n'importe quel joueur envoie depuis le tableau de bord HBPSM
(https://strus38.github.io/hbpsm-dashboard/) : propositions d'amendes de la caisse noire
(`propositions.enc`), réponses de présence aux entraînements et aux matchs, « Vous êtes » et votes
de l'homme du match (`presences.enc`). Il ne contient que du code et des journaux chiffrés : aucun
nom n'y apparaît en clair.

- La page chiffre l'envoi avec la phrase du club et lance le workflow « Envoi d'un joueur »
  (`proposer.yml`) avec un jeton limité à ce dépôt (droit « Actions » seulement).
- `propositions.py` vérifie le coffre (phrase du club, forme, taille) et ajoute chaque envoi à son
  journal, sans doublon, avec l'heure de réception.
- Les pages relisent ces journaux quelques minutes après. Seuls les trésoriers valident ou refusent
  une amende, dans le registre du tableau de bord ; seul l'entraîneur voit les réponses de présence
  des autres sur la page.

Le jeton de la page ne peut lancer que ce workflow : même s'il était extrait, il ne permettrait que
d'ajouter un envoi (chiffré avec la phrase du club), jamais de valider une amende ni de toucher au
tableau de bord.

Secret attendu : `HBPSM_CLE`, la phrase du club (la même que celle du tableau de bord).

Ce dépôt est tenu depuis le dossier `cn/` de strus38/hbpsm-dashboard, où le code est testé.
