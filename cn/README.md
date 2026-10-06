# Caisse noire HBPSM : propositions d'amendes

Ce dépôt reçoit les propositions d'amendes que n'importe quel joueur envoie depuis le tableau de
bord HBPSM (https://strus38.github.io/hbpsm-dashboard/). Il ne contient que du code et un journal
chiffré : aucun nom n'y apparaît en clair.

- La page chiffre la proposition avec la phrase du club et lance le workflow « Proposition
  d'amende » avec un jeton limité à ce dépôt (droit « Actions » seulement).
- `propositions.py` vérifie le coffre (phrase du club, forme, taille) et l'ajoute à
  `propositions.enc`, sans doublon.
- Les pages relisent ce journal : la proposition est visible par tous quelques minutes après.
  Seuls les trésoriers la valident ou la refusent, dans le registre du tableau de bord.

Le jeton de la page ne peut lancer que ce workflow : même s'il était extrait, il ne permettrait que
d'ajouter une proposition (chiffrée avec la phrase du club), jamais de valider une amende ni de
toucher au tableau de bord.

Secret attendu : `HBPSM_CLE`, la phrase du club (la même que celle du tableau de bord).

Ce dépôt est tenu depuis le dossier `cn/` de strus38/hbpsm-dashboard, où le code est testé.
