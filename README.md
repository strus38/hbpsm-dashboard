# Tableau de bord HBPSM

Suivi hebdomadaire des poules 71 et 72 de la 2e division masculine P16 AURA : classements,
feuilles de match, équipe proposée pour le match suivant, matchs clés de la saison et axes de
travail pour l'entraînement.

## Principe : dépôt public, résultats chiffrés

Ce dépôt ne sert qu'à poser le code et à faire tourner la collecte. Tout ce qui porte un nom de
joueur est chiffré avant d'y entrer (AES-256-GCM, clé dérivée d'une phrase secrète) :

| Fichier | Contenu | Lisible par |
|---|---|---|
| `publie/HBPSM-tableau-de-bord.html` | la page, sans aucune donnée | tout le monde |
| `publie/hbpsm.enc` | données du tableau de bord et séance à importer | qui connaît la phrase |
| `publie/etat.enc` | état de la collecte (rencontres, feuilles lues) | qui connaît la phrase |
| `publie/manifeste.json` | date et empreinte de la dernière mise à jour | tout le monde |

Aucune page GitHub Pages n'est créée. Les captures brutes d'un lancement partent dans une archive
7z chiffrée avec la même phrase. La phrase n'existe que dans le secret `HBPSM_CLE` et chez les
entraîneurs : choisir au moins cinq mots tirés au hasard, car le fichier chiffré est public et
une phrase courte se devine par essais successifs.

## Mise en route

1. **Settings > Secrets and variables > Actions** : créer `HBPSM_CLE` (la phrase secrète) et,
   si souhaité, `HBPSM_EFFECTIF` (un joueur par ligne, « Prénom Nom »).
2. **Actions > Collecte hebdomadaire > Run workflow**. Les adresses des poules 71 et 72 sont
   dans `config.yml` ; vides, la collecte les retrouve sur la page de la compétition.

Ensuite la collecte tourne seule le lundi et le jeudi à 05:00 UTC. Quand les données changent,
une Release « Données du … » est créée.

## Pour les entraîneurs

Télécharger une fois `HBPSM-tableau-de-bord.html` depuis la dernière Release et le garder sur
son ordinateur. À chaque ouverture, la page récupère les dernières données, demande la phrase
secrète la première fois, puis s'en souvient. Tant qu'elle reste ouverte, elle revient voir le
dépôt toutes les dix minutes, et dès que la fenêtre revient au premier plan ou que la connexion
revient : elle ne lit que `manifeste.json` (quelques octets) et ne télécharge les données que si
elles ont changé, puis se redessine sans perdre l'onglet ni les réglages. Le bandeau du haut dit
« à jour » avec l'heure de la dernière vérification, ou « hors connexion ». Sans connexion, elle
affiche la dernière copie reçue. Quand la page elle-même évolue, un bandeau propose de
télécharger la nouvelle version.

La page suit la semaine de l'entraîneur :

| Onglet | Ce qu'il donne |
|---|---|
| Semaine | le prochain match : rang de l'adversaire, victoire estimée avec l'équipe retenue, enjeu pour la saison, recommandation de prise de risque, les 12 retenus, le sept possible |
| Planification | les 4 prochains matchs : disponibilités (disponible, incertain, absent) et choix saisis par l'entraîneur, 12 joueurs dont 2 gardiens proposés par match, rotation guidée, force alignée et risque recalculés à chaque clic |
| Convocation | après l'entraînement du vendredi : les 12, la date, le gymnase (lu sur ffhandball.fr), l'heure du rendez-vous, un message à copier pour le groupe et une version imprimable |
| Joueurs | fiches graphiques : note, buts ou arrêts par match, réussite au tir ou pourcentage d'arrêts face à la référence, sanctions, sélections à venir |
| Adversaires | repérage : buts, mi-temps, discipline, gardiens, joueurs à surveiller, repères communs |
| Saison | chances de finir premier, matchs à gagner, axes de travail, séance à importer, classements |

La proposition retient les 2 meilleurs gardiens et les 10 meilleurs joueurs de champ disponibles
(notes pondérées selon l'adversaire), en respectant les choix de l'entraîneur. En rotation
guidée, hors match clé, elle fait entrer jusqu'à 3 joueurs de champ et 1 gardien qui attendent
depuis le plus longtemps, pour que chacun joue au moins 1 match sur 3 (ou 1 sur 2). La force
alignée rapporte la valeur des 12 retenus à celle de l'équipe type ; la victoire estimée part
de celle calculée sur GitHub (équipe au complet) et baisse avec la force ; le risque multiplie
cette baisse par l'enjeu du match pour la saison.

Tout le calcul lourd (classements, notes, chances de victoire et de finir premier, matchs clés,
axes de travail) est fait par la collecte sur GitHub. La page ne fait que ces calculs légers,
parce que les disponibilités, les choix et les postes se saisissent sur l'ordinateur de
l'entraîneur et n'en sortent pas (un fichier « Sauvegarder mon planning » les emporte ailleurs).

Couleurs : celles du club, reprises du profil HBPSM de HANDBALL-training
(`clubs/hbpsm/profil.json`), avec les mêmes rôles : le bleu marine pour l'ossature, le jaune
pour ce qui est actif ou mis en avant, toujours avec un texte foncé.

La page lit `publie/hbpsm.enc` par `raw.githubusercontent.com` : les fichiers attachés à une
Release ne sont pas lisibles par une page web (GitHub n'y met pas d'en-tête CORS).

## Chaîne de traitement

| Étape | Commande | Produit |
|---|---|---|
| Reprise | `python -m pipeline.publish restore` | `data/` depuis `publie/etat.enc` |
| Effectif | `python -m pipeline.publish roster` | `roster.csv` depuis le secret |
| Collecte | `python -m pipeline.collect` | `data/fixtures.json`, `raw/fdme/*.pdf` |
| Feuilles | `python -m pipeline.parse_fdme` | `data/matches/<id>.json` |
| Publication | `python -m pipeline.publish seal` | `publie/` |

`data/`, `raw/`, `docs/` et `roster.csv` ne sont jamais versionnés. Pour un aperçu en clair sur
sa propre machine : `python -m pipeline.build_dashboard` écrit `docs/index.html`.

La collecte n'a pas besoin de navigateur : chaque page de ffhandball.fr porte ses données en
JSON dans le HTML servi (`<smartfire-component name="competitions---rencontre-list"
attributes="…">`). Elle lit la page de la poule, puis chaque journée pas encore close (une
journée est close quand toutes ses feuilles sont lues), soit une quinzaine de pages par poule
en début de saison et de moins en moins ensuite, avec une pause d'une seconde entre deux.
La feuille se télécharge à l'adresse tirée de son code (`fdm.fdme.ffhandball.fr/W/A/G/W/WAGWUHC.pdf`),
sans ouvrir la page de la rencontre. Les pages passent par un cache d'une à deux heures : un
score absent de la page est pris sur la feuille, et un classement fédéral qui compte moins de
matchs joués est signalé « pas encore à jour » plutôt que comme une pénalité.

## Réglages

- `config.yml` : URL des poules, motifs de reconnaissance du club, taille de la feuille, rang
  visé, équipe et jours d'entraînement.
- Effectif : le nom s'écrit « Prénom Nom » ; il est rapproché de celui de la feuille de match
  sans tenir compte de l'ordre, des accents ni de la casse. On peut ajouter `,POSTE`
  (GB, ALG, ARG, DC, ARD, ALD, PIV). Un joueur jamais aligné apparaît dans « Pas encore alignés ».
  Postes et absences se saisissent aussi dans la page, où ils restent sur l'ordinateur.

## Comment la note est calculée

Note sur 100 par joueur, à partir des feuilles du club : buts récents (les derniers matchs
pèsent plus), efficacité si les tirs sont saisis, discipline, écart de l'équipe avec et sans le
joueur, buts en fin de match serré, assiduité. Trois pondérations (équilibré, attaque, rigueur) ;
celle conseillée dépend du profil de l'adversaire. Gardiens : d'abord le pourcentage d'arrêts
(arrêts sur tirs cadrés subis, c'est-à-dire arrêts + buts pris), puis les arrêts par match,
l'impact et l'assiduité. Joueurs de champ : les buts face aux tirs (réussite au tir).

La feuille donne les arrêts de chaque gardien, pas ses buts pris. Quand un seul gardien a fait
des arrêts, il prend tous les buts du match. Quand deux gardiens se partagent le match, chaque but
encaissé va au gardien du dernier arrêt de la même mi-temps (à défaut, du prochain) : c'est une
estimation, marquée comme telle dans la page. Le même calcul donne le pourcentage d'arrêts des
gardiens adverses dans le repérage.

L'équipe proposée compte 12 joueurs dont 2 gardiens (`effectif_feuille` et `gardiens_feuille`
dans `config.yml`), les mieux notés parmi les disponibles ; s'il manque du monde, un joueur de
l'effectif pas encore aligné complète la feuille.

Discipline : les trois sanctions de la feuille restent distinctes partout (joueurs, journal des
matchs, repérage de l'adversaire) : l'avertissement (carton jaune, un au plus par joueur et par
match), l'exclusion de 2 minutes, et la disqualification (carton rouge, que le carton bleu
complète d'un rapport). Dans la note, un 2 minutes compte 1, un carton rouge 3, un carton jaune 0,3.

Limites : la feuille ne dit ni le temps de jeu, ni les postes, ni qui était sur le terrain en
même temps. Le tableau de bord donne les matchs disputés, le temps passé sur le banc à 2 minutes
et un indice de présence (tranches de dix minutes avec une action relevée). Avec peu de matchs,
les notes sont des tendances.

## Objectif de saison et matchs clés

L'onglet Saison estime les chances d'atteindre le rang visé (`objectif.rang`) en simulant les
matchs restants de la poule, et donne pour chaque match du club l'écart de chances entre une
victoire et un autre résultat : les trois plus gros écarts sont les matchs clés. Le modèle ignore
les pénalités et le règlement de la phase suivante.

## Lien avec l'application de préparation des entraînements

Le fichier chiffré contient une séance au format d'échange `.hbt.json` de HANDBALL-training :
datée du prochain entraînement, avec les axes de travail et le repérage de l'adversaire dans
l'objectif, sans exercice. Elle se télécharge depuis l'onglet Saison et s'importe par la
fonction Importer de l'application (vérifié avec l'importeur de la version 1.14.2).

L'exemplaire HBPSM de l'application a aussi un bouton « Tableau de bord HBPSM », à côté
d'Importer : il télécharge `publie/hbpsm.enc`, le déchiffre avec la même phrase secrète et
ajoute la séance du champ `seance_hbt`, comme une séance reçue. C'est la seule partie de
l'application qui passe par internet, et seulement au clic.

Les deux projets restent indépendants, sans code partagé. Le seul lien est ce contrat, à ne
pas rompre d'un côté sans l'autre : le chemin `publie/hbpsm.enc` sur la branche `main`, le
format de l'enveloppe (en tête de `pipeline/vault.py`) et le champ `seance_hbt` au format
`.hbt.json`. L'adresse est déclarée dans `clubs/hbpsm/profil.json` de HANDBALL-training.

## Tests

`pip install -r requirements-dev.txt` puis `python -m pytest -q`. Les tests utilisent un faux
site local, de fausses feuilles et des joueurs inventés, construits sur la forme relevée sur le
vrai site ; ils couvrent la collecte, la lecture des feuilles, l'analyse, le chiffrement, la
reprise d'état et la page publiée ouverte en fichier local. Ce dernier test ouvre le Chrome
installé sur le poste (`HBPSM_NAVIGATEUR=chromium` pour le Chromium de Playwright, après
`playwright install chromium`). `python -m pipeline.demo_data` crée des données fictives pour un aperçu.
