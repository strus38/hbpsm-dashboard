# Tableau de bord HBPSM

Suivi des poules 71 et 72 de la 2e division masculine P16 AURA : classements,
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
| `publie/historique.enc` | saisons passées collectées (rencontres, feuilles lues) | qui connaît la phrase |
| `publie/manifeste.json` | date et empreinte de la dernière mise à jour | tout le monde |
| `publie/seance-prochaine.hbt.json` | séance du prochain entraînement, sans nom de joueur | tout le monde |
| `publie/tableau-public.json` | résumé d'équipe sans nom de joueur (prochain match, classements, chances, repérage par numéro) | tout le monde |

Les deux fichiers publics en clair sont relus avant d'être écrits : si un nom de l'effectif ou
d'une feuille de match (saison passée comprise) y apparaît, la publication est refusée.

La même page sans donnée est aussi servie par GitHub Pages, à une adresse fixe
(https://strus38.github.io/hbpsm-dashboard/) : elle demande la phrase une fois par poste, comme
le fichier gardé sur le PC. Les captures brutes d'un lancement partent dans une archive
7z chiffrée avec la même phrase. La phrase n'existe que dans le secret `HBPSM_CLE` et chez les
entraîneurs : choisir au moins cinq mots tirés au hasard, car le fichier chiffré est public et
une phrase courte se devine par essais successifs.

## Mise en route

1. **Settings > Secrets and variables > Actions** : créer `HBPSM_CLE` (la phrase secrète) et,
   si souhaité, `HBPSM_EFFECTIF` (un joueur par ligne, « Prénom Nom,POSTE,disponibilité » :
   poste facultatif, « ARG/ARD » pour deux postes ; disponibilité « non » pour un joueur absent
   longtemps, « dépannage » pour un joueur qui ne joue que s'il manque du monde).
2. **Settings > Pages** : source « GitHub Actions » (une fois).
3. **Actions > Collecte quotidienne > Run workflow**. Les adresses des poules 71 et 72 sont
   dans `config.yml` ; vides, la collecte les retrouve sur la page de la compétition.

Ensuite la collecte tourne seule chaque jour du dimanche au vendredi à 05:00 UTC (7 h à
Paris l'été, 6 h l'hiver) : les feuilles arrivent dans le désordre, et une journée n'est close
que lorsque toutes ses feuilles sont lues. Dates et heures sont celles de Paris. Quand les données changent,
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
| Planification | les 4 prochains matchs : disponibilités (disponible, incertain, absent) et choix saisis par l'entraîneur, 12 joueurs dont 2 gardiens proposés par match, rotation guidée, force alignée et risque recalculés à chaque clic |
| Semaine | le prochain match : rang de l'adversaire, victoire estimée avec l'équipe retenue, enjeu pour la saison, recommandation de prise de risque, les 12 retenus, le sept possible |
| Convocation | après l'entraînement du vendredi : les 12, la date, le gymnase (lu sur ffhandball.fr), l'heure du rendez-vous, un message à copier pour le groupe et une version imprimable |
| Joueurs | fiches graphiques : note, buts ou arrêts par match, réussite au tir ou pourcentage d'arrêts face à la référence, sanctions, sélections à venir |
| Adversaires | toutes les équipes des deux poules, HBPSM compris : buts, mi-temps, discipline, gardiens, joueurs à surveiller (avec leurs chiffres de la saison passée s'ils étaient déjà là), repères communs, et les joueurs de la saison passée, ceux revus cette saison en tête |
| Saison | chances de finir premier, matchs à gagner, axes de travail, séance à importer, classements |

La proposition retient les 2 meilleurs gardiens et les 10 meilleurs joueurs de champ disponibles
(notes pondérées selon l'adversaire), en respectant les choix de l'entraîneur et les postes clefs
de `config.yml` : au moins 2 pivots et 4 arrières (ARG, DC ou ARD) sur chaque feuille ; un joueur
à deux postes (« 2e poste » dans sa fiche) compte pour l'un ou l'autre. Un joueur « en dépannage »
(effectif, ou case de sa fiche) n'est retenu que s'il manque des joueurs ou un poste clef, et
reste hors rotation. Puis la rotation,
sur les 4 matchs à la fois : chacun joue au moins 1 des 4 matchs (ou 2, ou rotation libre, au
choix de l'entraîneur). Elle se fait d'abord sur les matchs les plus abordables (victoire
estimée la plus haute), jamais sur un match clé, avec au plus 3 joueurs de champ et 1 gardien
changés par match (les 2 gardiens si le minimum l'exige, sur un match à la victoire estimée
d'au moins 65 %) ; laisse sa place celui qui a le plus joué sur la période (à égalité, le moins
bien noté), si bien que le repos tourne aussi chez les titulaires et les gardiens ; le
remplacement se fait poste pour poste quand c'est possible, et jamais au point de découvrir un
poste clef. Chaque note
dit sur combien de matchs elle repose (saison passée comptée pour moitié) : fragile sous 3,
indicative sous 6, solide au-delà ; tant que le club a moins de 5 feuilles lues ou des notes
fragiles, la planification le rappelle. Chaque note est ramenée vers la moyenne de l'effectif
(gardiens et joueurs de champ à part), comme si le joueur avait aussi joué 2 matchs moyens :
une note sur un ou deux matchs reste près de la moyenne, une note sur huit matchs bouge de
1 à 3 points ; la fiche garde la note brute. Chaque case
dit pourquoi au survol ; un minimum impossible à tenir est signalé en rouge. La force
alignée rapporte la valeur des 12 retenus à celle de l'équipe type ; la victoire estimée part
de celle calculée sur GitHub (équipe au complet) et baisse avec la force ; le risque multiplie
cette baisse par l'enjeu du match pour la saison.

Tout le calcul lourd (classements, notes, chances de victoire et de finir premier, matchs clés,
axes de travail) est fait par la collecte sur GitHub. La page ne fait que ces calculs légers,
parce que les disponibilités, les choix et les postes se saisissent sur l'ordinateur de
l'entraîneur et n'en sortent pas (un fichier « Sauvegarder mon planning » les emporte ailleurs).

Deux modes. Ouverte depuis HANDBALL-training, dont le lien se termine par `#entraineur`, la
page est en mode entraîneur : disponibilités, choix, rotation, rendez-vous, convocation et
postes se modifient. Ouverte directement (GitHub Pages ou fichier), elle se consulte seulement :
aucun contrôle de modification, une note rappelle qu'une feuille non validée par l'entraîneur
n'est qu'une suggestion, et toucher une case en donne la raison. Ce n'est pas un verrou : rien
de ce qu'on modifie ne quitte le navigateur, sauf la feuille que l'entraîneur valide (ci-dessous).

Sur téléphone, la page se resserre : menu sur une ligne, noms courts, tableaux sans les
colonnes secondaires, planification avec la colonne des noms fixe et des cases plus grandes. Le
survol n'existant pas au doigt, « Toucher une case : explique » affiche la raison d'une case
au lieu de la modifier.

Couleurs : celles du club, reprises du profil HBPSM de HANDBALL-training
(`clubs/hbpsm/profil.json`), avec les mêmes rôles : le bleu marine pour l'ossature, le jaune
pour ce qui est actif ou mis en avant, toujours avec un texte foncé.

La page lit `publie/hbpsm.enc` par `raw.githubusercontent.com` : les fichiers attachés à une
Release ne sont pas lisibles par une page web (GitHub n'y met pas d'en-tête CORS).

## Feuille validée par l'entraîneur

Tant que l'entraîneur n'a pas validé un match, tout le monde voit sur la page une
**suggestion** du tableau de bord (cases en pointillés chez les visiteurs). En mode entraîneur,
« Valider la feuille » (planification, semaine ou convocation) fige la feuille de ce match et
la publie : chacun voit alors « Choix de l'entraîneur, validé le… », et cette feuille sort de la
rotation automatique. Retoucher une feuille validée la repasse à valider ; les joueurs voient
la version publiée jusqu'à la nouvelle validation.

La page de l'entraîneur chiffre les feuilles validées avec la phrase du club et lance le
workflow « Choix de l'entraîneur » (`.github/workflows/choix.yml`). Il vérifie qu'elles sont
chiffrées avec la phrase du club, de la forme attendue, puis les écrit dans
`publie/choix.enc`, que toutes les pages relisent. Rien n'est déchiffré dans le journal.

Pour cela, la page a besoin d'un jeton GitHub, créé une fois par le propriétaire du dépôt :
1. GitHub > Settings > Developer settings > Personal access tokens > **Fine-grained tokens** >
   Generate new token ;
2. Repository access : **Only select repositories**, `hbpsm-dashboard` ;
3. Permissions > Repository permissions : **Actions : Read and write** (rien d'autre ; il peut
   lancer ce workflow, pas modifier le code) ;
4. une date d'expiration (la fin de la saison, par exemple), puis Generate token.

L'entraîneur colle ce jeton une fois, quand la page le lui demande à sa première validation ;
il reste dans son navigateur, jamais dans un fichier. « Oublier le jeton de publication », en
bas de la planification, l'efface.

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

L'onglet Saison estime les chances d'atteindre le rang visé (`objectif.rang`, 3 : se qualifier
pour la deuxième phase) en simulant les matchs restants de la poule, montre les chances de chaque
rang final, et donne pour chaque match du club l'écart de chances entre une victoire et un autre
résultat : les trois plus gros écarts sont les matchs clés. La force de chaque équipe reste
incertaine : chaque saison simulée la tire autour de son estimation (±8 % de buts au départ),
d'autant moins large que l'équipe a joué de matchs. Égalités départagées comme le
règlement (confrontations directes, puis différence de buts). Règlement AURA 2026-2027 : 2
montées par secteur (poules 71 et 72), au terme d'une deuxième phase dont la formule sera
publiée vers février ; le modèle ignore les pénalités.

## Saison passée

`historique` dans `config.yml` désigne les saisons passées au même niveau (2025-2026).
`python -m pipeline.history` les collecte une fois : les poules où jouaient le club et ses
adversaires d'aujourd'hui, puis les feuilles de leurs matchs. Le serveur des feuilles limite le
débit (HTTP 429) : elles arrivent par reprises successives, une toutes les 4 secondes, en
respectant le délai demandé, dans un budget de 15 minutes par passage (la collecte quotidienne
la relance jusqu'à ce qu'elle soit complète ; une feuille jamais déposée, HTTP 404, n'est plus
redemandée). Le résultat est publié chiffré dans `publie/historique.enc`, réécrit seulement
s'il change. Les anciennes feuilles disent qui entre et sort des buts : les buts pris y sont
attribués exactement au gardien en place, et à aucun quand il était sorti (jeu à 7). Les
mentions de commotion ne sont jamais conservées.

Ce qu'elle apporte :
- les notes des joueurs partent de la saison passée (un match de l'an dernier compte pour la
  moitié d'un match de cette saison) ; un joueur de l'effectif pas encore aligné reçoit une note
  provisoire ; un joueur parti n'est pas repris ;
- pour chaque adversaire déjà vu : bilan et classement, confrontations avec le club, joueurs de
  cette saison déjà là l'an dernier, devenir de ses meilleurs buteurs ;
- dans la simulation, la force de départ d'une équipe connue est celle de la saison passée,
  d'autant plus que son effectif est resté, au lieu de la moyenne de la poule.

## Lien avec l'application de préparation des entraînements

Le fichier chiffré contient une séance au format d'échange `.hbt.json` de HANDBALL-training :
datée du prochain entraînement, avec les axes de travail et le repérage de l'adversaire dans
l'objectif, sans exercice. Elle se télécharge depuis l'onglet Saison et s'importe par la
fonction Importer de l'application (vérifié avec l'importeur de la version 1.14.2).

L'exemplaire HBPSM de l'application a un écran « Tableau de bord HBPSM », sans phrase
secrète : il lit `publie/tableau-public.json` (prochain match, objectif et chances de chaque
rang, classements des deux poules, repérage de l'adversaire par numéro, axes de travail), crée
la séance de la semaine depuis `publie/seance-prochaine.hbt.json`, et ouvre d'un bouton le
tableau de bord complet sur GitHub Pages (planification, convocation, fiches des joueurs), qui
lui demande la phrase. C'est la seule partie de l'application qui passe par internet, et
seulement quand l'entraîneur ouvre cet écran.

Les deux projets restent indépendants, sans code partagé. Le seul lien est ce contrat, à ne
pas rompre d'un côté sans l'autre : les chemins `publie/tableau-public.json` (`format`
« hbpsm-public », `v` 1) et `publie/seance-prochaine.hbt.json` (`.hbt.json` v3) sur la branche
`main`, et l'adresse GitHub Pages. Ces adresses sont déclarées dans `clubs/hbpsm/profil.json`
de HANDBALL-training.

## Tests

`pip install -r requirements-dev.txt` puis `python -m pytest -q`. Les tests utilisent un faux
site local, de fausses feuilles et des joueurs inventés, construits sur la forme relevée sur le
vrai site ; ils couvrent la collecte, la lecture des feuilles, l'analyse, le chiffrement, la
reprise d'état et la page publiée ouverte en fichier local. Ce dernier test ouvre le Chrome
installé sur le poste (`HBPSM_NAVIGATEUR=chromium` pour le Chromium de Playwright, après
`playwright install chromium`). `python -m pipeline.demo_data` crée des données fictives pour un aperçu.
